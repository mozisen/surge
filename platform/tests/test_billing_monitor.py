import datetime
import json
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent.billing import advance, configure, cycle_key, traffic_state
from agent.bridge import Bridge
from agent.inventory import read_db
from agent.runtime import active_users, atomic_write, render_inbound
from vaio.common import config_revision, validate_task
from vaio.store import Store
from vaio import backups, monitor
from test_agent import fixture, FakeRuntime


class BillingTest(unittest.TestCase):
    def test_month_boundary_restart_manual_disable_and_counter_reset(self):
        user = {'used': 100, 'enabled': False}
        configure(user, {'quota_gb': 1, 'reset_day': 15}, datetime.date(2026, 9, 20))
        self.assertEqual(user['panel_used'], 100)
        user['used'] = 120
        advance(user, datetime.date(2026, 10, 14))
        self.assertEqual(user['panel_used'], 120)
        user = json.loads(json.dumps(user))
        user['used'] = 130
        advance(user, datetime.date(2026, 10, 15))
        self.assertEqual(user['panel_used'], 10)
        advance(user, datetime.date(2026, 10, 15))
        self.assertEqual(user['panel_used'], 10)
        user['used'] = 4
        advance(user, datetime.date(2026, 10, 15))
        self.assertEqual(user['panel_used'], 14)
        self.assertFalse(user['enabled'])
        self.assertEqual(cycle_key(28, datetime.date(2026, 1, 1)), '2025-12-28')

    def test_shared_renderer_enforces_quota_and_expiry(self):
        row = fixture()['xray']['vless'][0]
        user = row['users'][0]
        configure(user, {'quota_gb': 1})
        user['panel_used'] = 1073741824
        self.assertEqual(active_users(row), [])
        inbound = render_inbound('vless', row, core='xray')
        self.assertEqual(inbound['settings']['clients'], [])
        user['panel_used'] = 0
        user['expire_date'] = '2020-01-01'
        self.assertEqual(active_users(row), [])
        self.assertEqual(render_inbound('vless', row, core='xray')['settings']['clients'], [])

    def test_freshness_and_validation(self):
        data = fixture(); row=data['xray']['vless'][0]
        self.assertEqual(traffic_state(data, 'xray', 'vless', row, 1000), 'unavailable')
        data['meta']['traffic_observed_xray']=950
        self.assertEqual(traffic_state(data, 'xray', 'vless', row, 1000), 'ready')
        self.assertEqual(traffic_state(data, 'xray', 'vless', row, 2000), 'unavailable')
        self.assertEqual(traffic_state(data, 'xray', 'ss2022', row, 1000), 'unsupported')
        self.assertEqual(traffic_state(data, 'xray', 'snell-v5', row, 1000), 'unavailable')
        for bad in (-1, 29, True, '1'):
            with self.assertRaises(ValueError):
                validate_task(dict(action='user_update',protocol='vless',core='xray',port=24443,params={'name':'default','reset_day':bad},revision='a'*64))

    def test_scoped_billing_transaction_and_failure_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/'cfg';cfg.mkdir();state=Path(d)/'state'
            data=fixture(); data['meta']['traffic_observed_xray']=time.time()
            atomic_write(cfg/'db.json', json.dumps(data))
            runtime=FakeRuntime(cfg/'config.json');runtime.path.write_text('original')
            bridge=Bridge(cfg,state,runtime)
            task=dict(id=str(uuid.uuid4()),action='user_update',protocol='vless',core='xray',port=24443,params={'name':'default','quota_gb':1,'reset_day':1},revision=config_revision(data))
            bridge.execute(task)
            updated=read_db(cfg)
            self.assertEqual(updated['xray']['vless'][1],data['xray']['vless'][1])
            user=updated['xray']['vless'][0]['users'][0]
            self.assertEqual(user['panel_quota'],1073741824)
            self.assertEqual(user['used'],12)
            revision=config_revision(updated)
            user['used']+=100
            user['panel_cycle']='2000-01-01'
            self.assertEqual(config_revision(updated),revision)
            atomic_write(cfg/'db.json',json.dumps(updated))
            runtime.fail=True
            with self.assertRaises(RuntimeError):bridge.reconcile()
            self.assertEqual(read_db(cfg),updated)
            self.assertEqual(runtime.path.read_text(),'changed') # state before failed reconcile
            runtime.fail=False
            bridge.reconcile()
            reset=read_db(cfg)['xray']['vless'][0]['users'][0]
            self.assertEqual(reset['panel_used'],100)


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name+'/panel.sqlite')
    def tearDown(self):self.tmp.cleanup()
    def node(self, seen=1000):
        with self.store.connect() as db:
            db.execute("INSERT INTO nodes(id,name,created,last_seen,snapshot) VALUES('one','测试节点',0,?,'{}')",(seen,))
    def events(self):
        with self.store.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM notifications')]
    def test_offline_dedup_recovery_and_maintenance(self):
        self.node()
        monitor.scan(self.store, 1130);monitor.scan(self.store,1140)
        self.assertEqual(len(self.events()),1)
        with self.store.connect() as db:db.execute("UPDATE nodes SET last_seen=1140")
        monitor.scan(self.store,1150)
        self.assertEqual(len(self.events()),2)
        self.assertTrue(self.events()[-1]['title'].startswith('已恢复'))
        with self.store.connect() as db:db.execute('UPDATE nodes SET maintenance=1')
        monitor.scan(self.store,2000)
        self.assertEqual(len(self.events()),2)
    def test_credentials_redacted_and_delivery_not_replayed(self):
        token='123456:'+'a'*30
        monitor.save_settings(self.store,dict(enabled=True,telegram_token=token,telegram_chat='1234',webhook=''))
        self.assertNotIn(token,json.dumps(monitor.settings(self.store)))
        self.node();monitor.scan(self.store,1130)
        with patch('vaio.monitor.deliver',return_value='failed') as deliver:
            monitor.send_pending(self.store);monitor.send_pending(self.store)
            self.assertEqual(deliver.call_count,1)
        with self.store.connect() as db:db.execute("INSERT INTO notifications(at,title,status) VALUES(0,'test','sending')")
        monitor.send_pending(self.store)
        self.assertEqual(self.events()[-1]['status'],'unknown')
    def test_backup_restore_does_not_replay_tasks_or_sessions(self):
        self.node()
        with self.store.connect() as db:
            db.execute("INSERT INTO sessions VALUES('token','csrf',1000)")
            for i,status in enumerate(('running','queued')):
                db.execute('INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)',(str(i),'one','user_update','{}',status,0,str(i)))
        name=backups.create(self.store)
        self.assertEqual(os.stat(backups.resolve(self.store,name)).st_mode & 0o777,0o600)
        self.assertEqual(backups.drill(self.store,name),dict(nodes=1,tasks=2))
        backups.restore(self.store,name)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
            self.assertEqual([r[0] for r in db.execute('SELECT status FROM tasks ORDER BY id')],['unknown','cancelled'])
        with self.assertRaises(ValueError):backups.drill(self.store,'../panel.sqlite')
        with self.assertRaises(ValueError):monitor.save_settings(self.store,dict(enabled=True,webhook='http://example.com'))

class MonitorAPITest(unittest.TestCase):
    def setUp(self):
        from vaio.server import create_app
        from vaio.common import digest
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app({'TESTING':True,'DATABASE':self.tmp.name+'/panel.sqlite'})
        self.client=self.app.test_client();self.store=self.app.extensions['store']
        with self.store.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(digest('session'),'csrf',time.time()+1000))
        self.client.set_cookie('vaio_session','session')
        self.headers={'X-CSRF-Token':'csrf'}
    def tearDown(self):self.tmp.cleanup()
    def test_new_endpoints_auth_csrf_redaction_and_restore_drill(self):
        anonymous=self.app.test_client()
        for path in ('/api/monitor','/api/backups','/api/nodes/no/history'):
            self.assertEqual(anonymous.get(path).status_code,401)
        for path in ('/api/monitor','/api/monitor/test','/api/backups','/api/backups/verify'):
            self.assertEqual(self.client.post(path,json={}).status_code,403)
        r=self.client.post('/api/backups',headers=self.headers,json={})
        self.assertEqual(r.status_code,200)
        self.assertEqual(self.client.post('/api/backups/verify',json={'name':r.json['name']},headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/monitor',json={'enabled':True,'webhook':'http://bad'},headers=self.headers).status_code,400)
        config=dict(enabled=True,telegram_token='123456:'+('a'*30),telegram_chat='12345')
        self.assertEqual(self.client.post('/api/monitor',json=config,headers=self.headers).status_code,200)
        self.assertNotIn(config['telegram_token'],self.client.get('/api/monitor').get_data(as_text=True))
        self.assertEqual(self.client.post('/api/monitor/test',json={},headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/monitor/test',json={},headers=self.headers).status_code,400)
