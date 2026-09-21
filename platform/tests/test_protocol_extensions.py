"""Isolated contract/transaction tests; these do not install production cores."""
import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent.bridge import Bridge, TransactionUnknown
from agent.inventory import inventory, read_db, sanitize_snapshot
from agent.runtime import Runtime, atomic_write, render_inbound
from vaio.common import config_revision, write_capabilities
from test_agent import FakeRuntime


class ExtendedRuntime(FakeRuntime):
    def install(self, proto, core=None):
        pass

    def keys(self, core=None):
        return 'private', 'public'


class ProtocolExtensions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / 'cfg'
        self.state = Path(self.tmp.name) / 'state'
        self.cfg.mkdir()
        self.runtime = ExtendedRuntime(self.cfg / 'runtime.json')
        self.runtime.path.write_text('original')
        self.bridge = Bridge(self.cfg, self.state, self.runtime)
        self.bridge.write({'xray': {}, 'singbox': {}, 'meta': {}})

    def tearDown(self):
        self.tmp.cleanup()

    def task(self, core, proto, action, port=30001, **params):
        return dict(id=str(uuid.uuid4()), action=action, core=core, protocol=proto,
                    port=port, params=params, revision=config_revision(read_db(self.cfg)))

    def test_every_declared_combination_scopes_install_users_update_delete(self):
        for item in write_capabilities():
            core, proto = item['core'], item['protocol']
            with self.subTest(core=core, protocol=proto), patch.object(Bridge, 'check_port'):
                self.bridge.write({'xray': {}, 'singbox': {}, 'meta': {}})
                for port in (30001, 30002):
                    self.bridge.execute(self.task(core, proto, 'install', port, **(
                        {'name': 'u' + str(port)} if proto.startswith('snell') else {'sni': 'example.com'})))
                db = read_db(self.cfg)
                sibling = copy.deepcopy(db[core][proto][1])
                first = db[core][proto][0]
                identity = first['instance_id']
                user = first['users'][0]
                user.update(used=765, telegram_chat_id='binding', quota=123456789)
                self.bridge.write(db)
                old_secret = user['uuid']
                self.bridge.execute(self.task(core, proto, 'user_update', name=user['name'], reset_credentials=True))
                changed = read_db(self.cfg)[core][proto][0]['users'][0]
                self.assertNotEqual(changed['uuid'], old_secret)
                self.assertEqual((changed['used'], changed['telegram_chat_id'], changed['quota']), (765, 'binding', 123456789))
                if not proto.startswith('snell'):
                    self.bridge.execute(self.task(core, proto, 'user_add', name='additional'))
                    self.bridge.execute(self.task(core, proto, 'user_delete', name='additional'))
                task = self.task(core, proto, 'update')
                task['params'] = {'port': 31001}
                self.bridge.execute(task)
                self.assertEqual(read_db(self.cfg)[core][proto][0]['instance_id'], identity)
                self.bridge.execute(self.task(core, proto, 'delete', 31001))
                self.assertEqual(read_db(self.cfg)[core][proto], [sibling])

    def test_new_protocols_render_only_selected_inbound_and_keep_stats(self):
        for core, proto in [('xray', 'trojan'), ('singbox', 'trojan'), ('singbox', 'anytls'), ('singbox', 'vless')]:
            with self.subTest(core=core, protocol=proto):
                row = dict(port=30001, panel_cert='/cert', panel_key='/key', users=[dict(name='alice', uuid='secret', enabled=True)])
                row.update(sni='example.com', private_key='private', short_id='abcd')
                sibling = {'tag': 'untouched', 'port' if core == 'xray' else 'listen_port': 30002, 'custom': ['keep']}
                before = {'inbounds': [render_inbound(proto, row, core=core), sibling], 'outbounds': [{'tag': 'custom'}],
                          'experimental': {'v2ray_api': {'stats': {'enabled': True, 'users': ['keep-existing']}}}}
                path = self.cfg / ('config.json' if core == 'xray' else 'singbox.json')
                atomic_write(path, json.dumps(before))
                runtime = Runtime(self.cfg, self.state)
                runtime.command = lambda *a, **k: ''
                runtime.ensure_unit = lambda *a: None
                runtime.service = lambda *a: None
                runtime.is_running = lambda *a: True
                changed = copy.deepcopy(row)
                changed['port'] = 31001
                with patch('agent.runtime.time.sleep'):
                    runtime.apply(core, proto, row, changed, {})
                actual = json.loads(path.read_text())
                self.assertEqual(actual['inbounds'][1], sibling)
                self.assertEqual(actual['outbounds'], before['outbounds'])
                if core == 'singbox':
                    self.assertEqual(actual['experimental']['v2ray_api']['stats']['users'], ['keep-existing', proto + '-alice'])
                for user in changed['users']:
                    user['enabled'] = False
                inbound = render_inbound(proto, changed, actual['inbounds'][0], core)
                self.assertNotIn('secret', json.dumps(inbound))

    def test_invalid_candidate_never_replaces_live_configuration(self):
        runtime = Runtime(self.cfg, self.state)
        row = dict(port=30001, panel_cert='/cert', panel_key='/key', users=[])
        path = self.cfg / 'singbox.json'
        atomic_write(path, json.dumps({'inbounds': [render_inbound('anytls', row, core='singbox')]}))
        original = path.read_bytes()
        def reject(argv, **kwargs):
            self.assertEqual(path.read_bytes(), original)
            self.assertNotEqual(argv[-1], str(path))
            self.assertTrue(Path(argv[-1]).exists())
            raise RuntimeError('invalid candidate')
        runtime.command = reject
        with self.assertRaisesRegex(RuntimeError, 'invalid candidate'):
            runtime.apply('singbox', 'anytls', row, {**row, 'port': 31001}, {})
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.cfg.glob('.vaio-check-*')))

    def test_each_new_combination_rolls_back_and_failed_restore_is_unknown(self):
        for core, proto in [('xray', 'trojan'), ('singbox', 'trojan'), ('singbox', 'anytls'), ('singbox', 'vless')]:
            with self.subTest(core=core, protocol=proto), patch.object(Bridge, 'check_port'):
                original = read_db(self.cfg)
                self.runtime.fail = True
                self.runtime.path.write_text('original')
                with self.assertRaisesRegex(RuntimeError, '已回滚'):
                    self.bridge.execute(self.task(core, proto, 'install', sni='example.com'))
                self.assertEqual(read_db(self.cfg), original)
                self.assertEqual(self.runtime.path.read_text(), 'original')
        with patch.object(Bridge, 'check_port'), patch.object(self.runtime, 'restore', side_effect=RuntimeError('restore failed')):
            task = self.task('singbox', 'anytls', 'install', sni='example.com')
            with self.assertRaises(TransactionUnknown):
                self.bridge.execute(task)
            with self.assertRaises(TransactionUnknown):
                self.bridge.execute(task)

    def test_capabilities_round_trip_and_selected_user_share(self):
        snap = sanitize_snapshot(inventory(self.cfg, status=lambda _: 'running'))
        self.assertEqual(snap['task_api_version'], 2)
        self.assertEqual(snap['write_capabilities'], write_capabilities())
        self.assertEqual(sanitize_snapshot({})['task_api_version'], 1)
        for proto in ('trojan', 'anytls'):
            link = Bridge.share(proto, {'port': 30001, 'sni': 'example.com', 'panel_cert': '/cert', 'users': [
                {'name': 'default', 'uuid': 'default-secret'}, {'name': 'chosen', 'uuid': 'selected-secret'}]},
                {'name': 'chosen', 'host': '2001:db8::1'})
            self.assertIn('selected-secret@[2001:db8::1]:30001', link)
            self.assertNotIn('default-secret', link)


if __name__ == '__main__':
    unittest.main()
