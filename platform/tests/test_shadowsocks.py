import base64
import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import unquote
from agent.runtime import render_inbound
from agent.bridge import Bridge
from agent.inventory import read_db, mutable
from vaio.common import validate_task
from vaio.install_options import SS_METHODS
import test_protocol_extensions as extensions


class ShadowsocksTest(unittest.TestCase):
    setUp = extensions.ProtocolExtensions.setUp
    tearDown = extensions.ProtocolExtensions.tearDown
    task = extensions.ProtocolExtensions.task
    def test_traffic_state_follows_how_the_instance_is_counted(self):
        from agent.billing import traffic_state
        for proto in ('ss-legacy', 'ss2022'):
            # One password on the inbound: the single user's own sample time.
            row = {'users': [{'uuid': 'K', 'traffic_observed_at': 999}]}
            self.assertEqual(traffic_state({}, 'singbox', proto, row, 1000), 'ready')
            self.assertEqual(traffic_state({}, 'singbox', proto, row, 2000), 'unavailable')
            self.assertEqual(traffic_state({}, 'singbox', proto, {'users':[{}]}, 2000), 'unavailable')
            # Named users: the Sing-box per-user sample time.
            multi = {'users': [{'name': 'a', 'uuid': 'A'}, {'name': 'b', 'uuid': 'B'}]}
            self.assertEqual(traffic_state({'meta': {'traffic_observed_singbox': 1990}}, 'singbox', proto, multi, 2000), 'ready')
            self.assertEqual(traffic_state({'meta': {'traffic_observed_singbox': 100}}, 'singbox', proto, multi, 2000), 'unavailable')
        # SS2022 with one user whose key differs from the instance key is rendered with a named user too.
        self.assertEqual(traffic_state({'meta': {'traffic_observed_singbox': 1990}}, 'singbox', 'ss2022',
                                       {'password': 'S', 'users': [{'name': 'a', 'uuid': 'A'}]}, 2000), 'ready')

    def test_keys_methods_render_and_rejection(self):
        for proto, methods in SS_METHODS.items():
            for method in methods:
                with self.subTest(method=method), patch.object(Bridge,'check_port'):
                    self.bridge.write({'xray':{},'singbox':{},'meta':{}})
                    task=self.task('singbox',proto,'install',name='alice',method=method)
                    self.bridge.execute(task)
                    row=read_db(self.cfg)['singbox'][proto][0]
                    credential=row['users'][0]['uuid']
                    if proto=='ss2022':
                        self.assertEqual(len(base64.b64decode(credential)),16 if '128' in method else 32)
                    inbound=render_inbound(proto,row,core='singbox')
                    self.assertEqual(inbound['type'],'shadowsocks')
                    self.assertEqual(inbound['password'],credential)
                    self.assertEqual(inbound['method'],method)
                    self.assertNotIn('tls',inbound)
                    link=Bridge.share(proto,row,{'name':'alice','host':'::1'})
                    self.assertTrue(link.startswith('ss://'))
                    self.assertIn('@[::1]:30001',link)
                    if proto=='ss2022': self.assertIn(method+':'+credential,unquote(link))
                    stopped=copy.deepcopy(row);stopped['users'][0]['enabled']=False
                    disabled=render_inbound(proto,stopped,core='singbox')
                    self.assertNotEqual(disabled['password'],credential)
                    if proto=='ss2022':self.assertEqual(len(base64.b64decode(disabled['password'])),16 if '128' in method else 32)
                    # A second user turns the instance multi-user; existing users stay valid.
                    self.bridge.execute(self.task('singbox',proto,'user_add',name='second'))
                    multi=read_db(self.cfg)['singbox'][proto][0]
                    self.assertEqual([u['name'] for u in multi['users']],['alice','second'])
                    second=multi['users'][1]['uuid']
                    inbound=render_inbound(proto,multi,core='singbox')
                    self.assertEqual(sorted(u['name'] for u in inbound['users']),[proto+'-alice',proto+'-second'])
                    if proto=='ss2022':
                        self.assertEqual(multi['password'],credential)                    # instance key kept
                        self.assertEqual(len(base64.b64decode(second)),16 if '128' in method else 32)
                        self.assertEqual(inbound['password'],credential)
                        self.assertIn(method+':'+credential+':'+second,unquote(Bridge.share(proto,multi,{'name':'second','host':'1.2.3.4'})))
                    else:
                        self.assertNotIn('password',inbound)
                        decoded=base64.urlsafe_b64decode(Bridge.share(proto,multi,{'name':'second','host':'1.2.3.4'})[5:].split('@')[0]+'==').decode()
                        self.assertEqual(decoded,method+':'+second)
                    # Port change, stop and start of a multi-user instance.
                    self.assertTrue(mutable('singbox',proto,multi))
                    self.assertTrue(mutable('singbox',proto,{**multi,'panel_managed':False}))
                    move=self.task('singbox',proto,'update');move['params']={'port':30002}
                    self.bridge.execute(move)
                    self.assertEqual(read_db(self.cfg)['singbox'][proto][0]['port'],30002)
                    self.bridge.execute(self.task('singbox',proto,'user_delete',name='second',port=30002))
                    left=read_db(self.cfg)['singbox'][proto][0]
                    self.assertEqual([u['name'] for u in left['users']],['alice'])
                    if proto=='ss2022':
                        # Back to one user whose key is the instance key: the original single-password form.
                        self.assertEqual(render_inbound(proto,left,core='singbox')['password'],credential)
        for params in ({'method':'none'},{'credential':'not-a-base64-key'}, {'method':'2022-blake3-aes-128-gcm','credential':base64.b64encode(b'x'*32).decode()}, {'sni':'example.com'}):
            with self.assertRaises(ValueError):validate_task({k:v for k,v in self.task('singbox','ss2022','install',**params).items() if k!='id'})

    @unittest.skipUnless(os.environ.get('VAIO_TEST_SINGBOX'), '未指定真实 Sing-box 校验工具')
    def test_real_core_accepts_active_and_disabled_configurations(self):
        binary = os.environ['VAIO_TEST_SINGBOX']
        with tempfile.TemporaryDirectory() as d:
            for proto, methods in SS_METHODS.items():
                for method in methods:
                    password = base64.b64encode(b'x' * (16 if '128' in method else 32)).decode()
                    other = base64.b64encode(b'y' * (16 if '128' in method else 32)).decode()
                    multi = [dict(name='test',uuid=password,enabled=True), dict(name='second',uuid=other,enabled=True)]
                    for enabled in (True, False, 'multi'):
                        row = dict(port=32001, method=method, users=multi) if enabled == 'multi' else \
                            dict(port=32001, method=method, users=[dict(name='test',uuid=password,enabled=enabled)])
                        inbound = render_inbound(proto,row,core='singbox')
                        inbound['listen']='127.0.0.1'
                        config=Path(d)/'config.json'
                        config.write_text(json.dumps(dict(inbounds=[inbound],outbounds=[dict(type='direct',tag='direct')])))
                        result=subprocess.run([binary,'check','-c',str(config)],capture_output=True,text=True,timeout=15)
                        self.assertEqual(result.returncode,0,method+' '+str(enabled)+': '+result.stderr)
