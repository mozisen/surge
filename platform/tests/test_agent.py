import concurrent.futures
import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent.__main__ import Agent, valid_url
from agent.bridge import Bridge
from agent.inventory import inventory, read_db, sanitize_snapshot
from agent.runtime import Runtime, atomic_write, render_inbound
from vaio.common import config_revision, validate_task


def fixture():
    return {"version":"4.0.0","xray":{"vless":[
        {"port":24443,"uuid":"uuid1","private_key":"PRIVATE","public_key":"PUBLIC","short_id":"abcd","sni":"example.com","users":[{"name":"default","uuid":"uuid1","enabled":True,"used":12,"telegram_chat_id":"secret-chat"}]},
        {"port":24444,"uuid":"uuid2","users":[{"name":"second","uuid":"uuid2","enabled":True,"used":99}]}]},"singbox":{},"meta":{}}


class FakeRuntime:
    def __init__(self,path,fail=False):self.path=Path(path);self.fail=fail;self.calls=[];self.running=True
    def paths(self,*args):return [self.path]
    def is_running(self,name):return self.running
    def is_enabled(self,name):return self.running
    def service(self,name,action):
        if action=='stop':self.running=False
        if action in ('start','restart'):self.running=True
    def install(self,proto):pass
    def keys(self):return 'private','public'
    def certificate(self,row):row.update(panel_cert='/cert',panel_key='/key')
    def apply(self,*args):
        self.calls.append(args)
        self.path.write_text('changed')
        if self.fail:raise RuntimeError('failure')
    def restore(self,name,files,running,enabled):
        for p,content in files.items():
            if content is None:Path(p).unlink(missing_ok=True)
            else:Path(p).write_bytes(content)


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cfg=Path(self.tmp.name)/'cfg';self.cfg.mkdir()
        self.state=Path(self.tmp.name)/'state';self.db=fixture()
        atomic_write(self.cfg/'db.json',json.dumps(self.db))
        self.runtime=FakeRuntime(self.cfg/'config.json');self.runtime.path.write_text('original')
        self.bridge=Bridge(self.cfg,self.state,self.runtime)

    def tearDown(self):self.tmp.cleanup()

    def task(self,action,params=None):
        return {"id":str(uuid.uuid4()),"action":action,"protocol":"vless","core":"xray","port":24443,"params":params or {},"revision":config_revision(read_db(self.cfg))}

    def test_scoped_delete_preserves_other_ports_and_users(self):
        self.bridge.execute(self.task('delete'))
        db=read_db(self.cfg)
        self.assertEqual(db['xray']['vless'],[self.db['xray']['vless'][1]])
        self.assertEqual(len(list((self.state/'backups').iterdir())),1)

    def test_transaction_replay_and_conflicting_request_id(self):
        task = self.task('delete')
        result = self.bridge.execute(task)
        self.assertEqual(self.bridge.execute(task), result)
        self.assertEqual(len(self.runtime.calls), 1)
        task['port'] = 24444
        with self.assertRaisesRegex(ValueError, '不同请求'):
            self.bridge.execute(task)

    def test_interrupted_transaction_never_replayed(self):
        from agent.bridge import TransactionUnknown
        task = self.task('delete')
        with patch.object(self.bridge, '_execute', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.bridge.execute(task)
        with self.assertRaises(TransactionUnknown):
            self.bridge.execute(task)
        self.assertEqual(self.runtime.calls, [])

    def test_rollback_restores_db_and_runtime(self):
        self.runtime.fail=True
        with self.assertRaisesRegex(RuntimeError,'已回滚'):
            self.bridge.execute(self.task('delete'))
        self.assertEqual(read_db(self.cfg),self.db)
        self.assertEqual(self.runtime.path.read_text(),'original')

    def test_stale_revision_rejected_without_mutation(self):
        task=self.task('delete');task['revision']='0'*64
        with self.assertRaisesRegex(ValueError,'过期任务'):self.bridge.execute(task)
        self.assertEqual(read_db(self.cfg),self.db)
        self.assertFalse(self.runtime.calls)

    def test_user_changes_scoped_and_preserve_counters(self):
        self.bridge.execute(self.task('user_update',{'name':'default','enabled':False}))
        db=read_db(self.cfg)
        self.assertFalse(db['xray']['vless'][0]['users'][0]['enabled'])
        self.assertEqual(db['xray']['vless'][0]['users'][0]['used'],12)
        self.assertEqual(db['xray']['vless'][0]['users'][0]['telegram_chat_id'],'secret-chat')
        self.assertEqual(db['xray']['vless'][1],self.db['xray']['vless'][1])

    def test_user_names_unique_across_ports(self):
        with self.assertRaisesRegex(ValueError,'已存在'):self.bridge.execute(self.task('user_add',{'name':'second'}))

    def test_default_user_cannot_be_deleted(self):
        with self.assertRaisesRegex(ValueError,'默认用户'):self.bridge.execute(self.task('user_delete',{'name':'default'}))

    def test_inventory_never_uploads_credentials(self):
        data=sanitize_snapshot(inventory(self.cfg,status=lambda _: 'running'))
        text=json.dumps(data)
        for secret in ('PRIVATE','uuid1','secret-chat','PUBLIC'):
            self.assertNotIn(secret,text)
        self.assertEqual(len(data['instances']),2)

    def test_traffic_does_not_invalidate_config(self):
        changed=copy.deepcopy(self.db);changed['xray']['vless'][0]['users'][0]['used']=999
        self.assertEqual(config_revision(changed),config_revision(self.db))

    def test_render_all_disabled_does_not_restore_default(self):
        row=self.db['xray']['vless'][0];row['users'][0]['enabled']=False
        self.assertEqual(render_inbound('vless',row)['settings']['clients'],[])
        row.update(panel_cert='/cert',panel_key='/key')
        generated=render_inbound('hy2',row)['users']
        self.assertEqual(generated[0]['name'],'vaio-disabled')
        self.assertNotEqual(generated[0]['password'],row['users'][0]['uuid'])

    def test_share_uses_selected_user_not_default(self):
        row=self.db['xray']['vless'][0]
        row['users'].append({'name':'custom','uuid':'other-credential'})
        connection=Bridge.share('vless',row,{'name':'custom','host':'2001:db8::1'})
        self.assertIn('other-credential@[2001:db8::1]',connection)

    def test_malicious_requests_rejected(self):
        for override in ({'action':'shell'},{'protocol':'../../etc'},{'port':True},{'params':{'port':'1;id'}},{'params':{'port':0}}):
            task=self.task('update',{'port':30000});task.pop('id');task.update(override)
            with self.assertRaises(ValueError):validate_task(task)

    def test_runtime_preserves_unrelated_inbounds_and_routing(self):
        runtime=Runtime(self.cfg,self.state)
        runtime.command=lambda *a,**k: ''
        runtime.ensure_unit=lambda *a:None
        runtime.service=lambda *a:None
        runtime.is_running=lambda *a:True
        first=render_inbound('vless',self.db['xray']['vless'][0]);first['streamSettings']['sockopt']={'tcpFastOpen':True}
        sibling={'protocol':'trojan','port':33333,'settings':{'clients':[{'password':'keep'}]}}
        original={'inbounds':[first,sibling],'outbounds':[{'tag':'chain','protocol':'socks'}],'routing':{'rules':[{'outboundTag':'chain','domain':['example.com']}]}}
        atomic_write(self.cfg/'config.json',json.dumps(original))
        changed=copy.deepcopy(self.db['xray']['vless'][0]);changed['port']=25555
        with patch('agent.runtime.time.sleep'):
            runtime.apply('xray','vless',self.db['xray']['vless'][0],changed,self.db)
        actual=json.loads((self.cfg/'config.json').read_text())
        self.assertEqual(actual['routing'],original['routing'])
        self.assertEqual(actual['inbounds'][1],sibling)
        self.assertEqual(actual['inbounds'][0]['streamSettings'],first['streamSettings'])
        self.assertEqual(actual['inbounds'][0]['port'],25555)

    def test_install_three_protocol_families_without_replacing_existing(self):
        for proto,port in [('vless',30001),('hy2',30002),('snell',30003)]:
            task=self.task('install',{'name':'new_snell'} if proto=='snell' else {'sni':'example.com'})
            task.update(protocol=proto,core='singbox' if proto=='hy2' else 'xray',port=port)
            with patch.object(Bridge,'check_port'):
                self.bridge.execute(task)
        db=read_db(self.cfg)
        self.assertEqual(db['xray']['vless'][:2],self.db['xray']['vless'])
        self.assertEqual(db['singbox']['hy2'][0]['port'],30002)
        self.assertEqual(db['xray']['snell'][0]['port'],30003)

    def test_stop_shared_service_is_persistent_and_reconcile_skips_it(self):
        self.bridge.execute(self.task('stop'))
        self.assertIn('vless-reality',read_db(self.cfg)['meta']['panel_paused_services'])
        self.bridge.reconcile()
        self.assertFalse(self.runtime.calls)
        with self.assertRaisesRegex(ValueError,'暂停'):
            self.bridge.execute(self.task('user_add',{'name':'newuser'}))

    def test_snell_single_port_delete_preserves_sibling(self):
        db={'xray':{'snell':[{'port':10001,'snell_id':'a'*24,'psk':'one','users':[{'name':'a','uuid':'one','id':'a'*24,'enabled':True}]},
                              {'port':10002,'snell_id':'b'*24,'psk':'two','users':[{'name':'b','uuid':'two','id':'b'*24,'enabled':True,'used':999}]}]},'singbox':{},'meta':{'snell_users':{'snell':True}}}
        atomic_write(self.cfg/'db.json',json.dumps(db))
        task=self.task('delete');task.update(protocol='snell',port=10001)
        self.bridge.execute(task)
        self.assertEqual(read_db(self.cfg)['xray']['snell'],[db['xray']['snell'][1]])

    def test_snell_legacy_multiport_refused(self):
        db={'xray':{'snell':[{'port':10001,'psk':'one'},{'port':10002,'psk':'two'}]},'singbox':{},'meta':{}}
        atomic_write(self.cfg/'db.json',json.dumps(db))
        task=self.task('delete');task.update(protocol='snell',port=10001)
        with self.assertRaisesRegex(ValueError,'旧版多端口'):
            self.bridge.execute(task)


class JournalTest(unittest.TestCase):
    def test_restart_marks_running_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            atomic_write(Path(tmp)/'journal.json',json.dumps({'task':{'status':'running','sent':False}}))
            a=Agent({'url':'http://127.0.0.1:8080','node_id':'node','token':'secret'},tmp,cfg=tmp)
            self.assertEqual(a.journal['task']['status'],'unknown')

    def test_completed_task_survives_result_network_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Agent({'url':'http://127.0.0.1:8080','node_id':'node','token':'secret'},tmp,cfg=tmp)
            a.journal={'task':{'status':'running','sent':False}}
            future=concurrent.futures.Future();future.set_result({'status':'succeeded','message':'ok','result':{}})
            a.api=lambda *args: (_ for _ in ()).throw(OSError('network'))
            with self.assertRaises(OSError):a.cycle(None,future)
            self.assertEqual(a.journal['task']['status'],'succeeded')
            sent=[]
            a.api=lambda suffix,payload:sent.append(suffix) or {'task':None}
            self.assertIsNone(a.cycle(None,future))
            self.assertTrue(a.journal['task']['sent'])
            self.assertIn('/tasks/task/result',sent)

    def test_plain_http_rejected_for_remote(self):
        with self.assertRaises(ValueError):valid_url('http://node.example.com')


if __name__=='__main__':unittest.main()
