"""面板更新与一键更新节点程序：GitHub 版本标签检查（缓存、静默失败）、面板更新接口、root 辅助程序按请求更新、全部节点一键升级与跳过原因。"""
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from vaio import __version__, updates
from vaio.server import create_app

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def bump(version, step=1):
    major, minor, patch_ = updates.version_key(version)
    return 'v%d.%d.%d' % (major, minor + step, 0)


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app = create_app({'TESTING': True, 'DATABASE': self.tmp.name + '/panel.sqlite', 'PUBLIC_URL': 'https://p.example.com'})
        self.store = app.extensions['store']

    def tearDown(self):
        self.tmp.cleanup()

    def test_tags_pick_largest_release_only(self):
        class Response:
            def __init__(self, data):
                self.data = json.dumps(data).encode()
            def read(self, n):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        tags = [{'name': 'v1.2.0'}, {'name': 'v1.10.0'}, {'name': 'v1.9.3'}, {'name': 'v2.0.0-preview.1'}, {'name': 'v1.0.0：'}, {'name': 'main'}, 'junk']
        with patch.object(updates.urllib.request, 'urlopen', return_value=Response(tags)):
            self.assertEqual(updates.fetch_latest(), 'v1.10.0')
        with patch.object(updates.urllib.request, 'urlopen', return_value=Response([])):
            self.assertIsNone(updates.fetch_latest())
        self.assertGreater(updates.version_key('1.10.0'), updates.version_key('v1.9.9'))
        self.assertIsNone(updates.version_key('1.2.0-preview.1'))

    def test_cache_and_silent_failure(self):
        calls = []
        def fetch():
            calls.append(1)
            return 'v9.0.0'
        def broken():
            raise OSError('offline')
        with self.store.connect() as db:
            r = updates.check(db, '1.1.0', now=1000, fetch=fetch)
            self.assertEqual((r['latest'], r['newer'], r['reachable']), ('v9.0.0', True, True))
            updates.check(db, '1.1.0', now=1000 + updates.CACHE - 1, fetch=fetch)
            self.assertEqual(len(calls), 1)                                      # cached
            r = updates.check(db, '1.1.0', now=1000 + updates.CACHE + 1, fetch=broken)
            self.assertEqual((r['latest'], r['newer'], r['reachable']), ('v9.0.0', True, False))   # last answer kept
            updates.check(db, '1.1.0', now=1000 + updates.CACHE + 2, fetch=fetch)
            self.assertEqual(len(calls), 1)                                      # failure retried after RETRY, not at once
            updates.check(db, '1.1.0', now=1000 + updates.CACHE + updates.RETRY + 2, fetch=fetch)
            self.assertEqual(len(calls), 2)
            self.assertFalse(updates.check(db, '9.0.0', now=1000 + updates.CACHE + updates.RETRY + 3, fetch=fetch)['newer'])
            self.assertFalse(updates.check(db, '9.1.0', now=1000 + updates.CACHE + updates.RETRY + 3, fetch=fetch)['newer'])


class API(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app = create_app({'TESTING': True, 'DATABASE': str(self.dir / 'panel.sqlite'), 'PUBLIC_URL': 'https://p.example.com', 'UPDATE_HELPER': True})
        self.store = self.app.extensions['store']
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('password',?)", (generate_password_hash('a-long-test-password', method='pbkdf2:sha256:1000'),))
        self.client = self.app.test_client()
        self.h = {'X-CSRF-Token': self.client.post('/api/login', json={'username': 'admin', 'password': 'a-long-test-password'}).json['csrf']}
        self.latest = bump(__version__)

    def tearDown(self):
        self.tmp.cleanup()

    def cache(self, latest):
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('update_check',?)", (json.dumps({'at': time.time(), 'ok': True, 'latest': latest}),))

    def test_status_and_request(self):
        self.cache(self.latest)
        r = self.client.get('/api/panel-update').json
        self.assertEqual((r['current'], r['latest'], r['newer'], r['pending'], r['helper'], r['status']), (__version__, self.latest, True, False, True, None))
        self.assertEqual(r['repository'], 'mozisen/vaio-panel')
        for body in ({'version': 'v0.0.1'}, {'version': self.latest, 'x': 1}, {}):
            self.assertEqual(self.client.post('/api/panel-update', json=body, headers=self.h).status_code, 400)
        with self.store.connect() as db:
            db.execute("INSERT INTO nodes(id,name,created,adopted,snapshot) VALUES('n','A',0,1,'{}')")
            db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES('t','n','agent_upgrade','{}','running',0,'k')")
        busy = self.client.post('/api/panel-update', json={'version': self.latest}, headers=self.h)
        self.assertIn('节点任务', busy.json['error'])
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET status='succeeded'")
        self.assertEqual(self.client.post('/api/panel-update', json={'version': self.latest}, headers=self.h).status_code, 200)
        self.assertEqual(json.loads((self.dir / 'panel-update-request.json').read_text()), {'ref': self.latest})
        self.assertTrue(self.client.get('/api/panel-update').json['pending'])
        again = self.client.post('/api/panel-update', json={'version': self.latest}, headers=self.h)
        self.assertIn('进行中', again.json['error'])
        (self.dir / 'panel-update-status.json').write_text(json.dumps({'state': 'running', 'message': 'x'}))
        self.assertEqual(self.client.get('/api/panel-update').json['status']['state'], 'running')
        with self.store.connect() as db:
            self.assertTrue(db.execute("SELECT 1 FROM audit WHERE event='panel.update_requested'").fetchone())

    def test_no_update_when_current(self):
        self.cache('v' + __version__ if updates.version_key(__version__) else None)
        self.assertFalse(self.client.get('/api/panel-update').json['newer'])
        self.assertEqual(self.client.post('/api/panel-update', json={'version': 'v' + __version__}, headers=self.h).status_code, 400)
        self.assertFalse((self.dir / 'panel-update-request.json').exists())

    def test_missing_update_helper_is_installed_through_address_helper(self):
        app = create_app({'TESTING': True, 'DATABASE': str(self.dir / 'panel.sqlite'), 'PUBLIC_URL': 'https://p.example.com', 'ADDRESS_HELPER': True})
        client = app.test_client()
        client.post('/api/login', json={'username': 'admin', 'password': 'a-long-test-password'})
        self.cache(self.latest)
        r = client.get('/api/panel-update').json
        self.assertEqual((r['helper'], r['installing']), (False, True))
        self.assertEqual(json.loads((self.dir / 'address-request.json').read_text()), {'action': 'install_update_helper'})
        (self.dir / 'address-request.json').write_text('{"action": "set_domain"}')     # never overwrites a pending address change
        client.get('/api/panel-update')
        self.assertIn('set_domain', (self.dir / 'address-request.json').read_text())
        self.assertFalse(self.client.get('/api/panel-update').json['installing'])     # helper present

    def test_needs_admin(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/api/panel-update').status_code, 401)
        self.assertEqual(anonymous.post('/api/nodes/upgrade-all', json={}).status_code, 401)

    def test_upgrade_all_queues_and_explains_skips(self):
        now = time.time()
        def node(nid, name, version, upgrade=1, seen=now, maintenance=0, adopted=1):
            snapshot = {'agent_version': version, 'upgrade_version': upgrade}
            with self.store.connect() as db:
                db.execute("INSERT INTO nodes(id,name,created,adopted,last_seen,maintenance,snapshot) VALUES(?,?,?,?,?,?,?)",
                           (nid, name, now, adopted, seen, maintenance, json.dumps(snapshot)))
        node('a', 'ok', '1.0.0')
        node('b', 'current', __version__)
        node('c', 'offline', '1.0.0', seen=now - 600)
        node('d', 'maint', '1.0.0', maintenance=1)
        node('e', 'old', '0.3.0-preview.10', upgrade=0)
        node('f', 'busy', '1.0.0')
        node('g', 'notadopted', '1.0.0', adopted=0)
        with self.store.connect() as db:
            db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES('t','f','install','{}','unknown',0,'k')")
        self.assertEqual(self.client.post('/api/nodes/upgrade-all', json={'x': 1}, headers=self.h).status_code, 400)
        r = self.client.post('/api/nodes/upgrade-all', json={}, headers=self.h).json
        self.assertEqual(r['queued'], ['ok'])
        self.assertEqual({s['name']: s['reason'] for s in r['skipped']}, {
            'offline': '节点离线', 'maint': '节点正在维护', 'old': '节点程序不支持一键升级，请先用命令升级一次', 'busy': '有未完成或待核对的任务'})
        with self.store.connect() as db:
            self.assertEqual([tuple(t) for t in db.execute("SELECT node_id, action, status FROM tasks WHERE id!='t'")], [('a', 'agent_upgrade', 'queued')])
        # A second click does not queue the same node twice.
        again = self.client.post('/api/nodes/upgrade-all', json={}, headers=self.h).json
        self.assertEqual(again['queued'], [])
        self.assertIn({'name': 'ok', 'reason': '有未完成或待核对的任务'}, again['skipped'])
        listed = {n['name']: n for n in self.client.get('/api/nodes').json['nodes']}
        self.assertEqual((listed['ok']['upgrade_available'], listed['current']['upgrade_available'], listed['ok']['panel_version']), (True, False, __version__))


class Helper(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location('update_panel_%d' % time.time_ns(), SCRIPTS / 'update-panel.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_units_installed_once(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp, patch.object(module.subprocess, 'run') as run:
            units = Path(tmp)
            self.assertTrue(module.ensure_address_helper(units))
            self.assertIn('update-panel.py --from-request /var/lib/vaio-panel/panel-update-request.json', (units / 'vaio-panel-update.service').read_text())
            self.assertIn('PathExists=/var/lib/vaio-panel/panel-update-request.json', (units / 'vaio-panel-update.path').read_text())
            self.assertFalse(module.ensure_address_helper(units))
            self.assertIn(['systemctl', 'enable', '--now', 'vaio-panel-update.path'], [c.args[0] for c in run.call_args_list])
        # The installer writes the same units.
        installer = (SCRIPTS / 'install-panel.sh').read_text()
        self.assertIn(module.HELPER_UNITS['vaio-panel-update.service'].strip().splitlines()[-1], installer)
        self.assertIn('vaio-panel-update.path', installer)

    def test_address_helper_installs_update_units(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['VAIO_ADDRESS_PREFIX'] = tmp
            try:
                spec = importlib.util.spec_from_file_location('panel_address_%d' % time.time_ns(), SCRIPTS / 'panel-address.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            finally:
                os.environ.pop('VAIO_ADDRESS_PREFIX', None)
            module.DATA.mkdir(parents=True)
            module.REQUEST.write_text(json.dumps({'action': 'install_update_helper'}))
            with patch.object(module.subprocess, 'run') as run:
                module.apply()
            command = run.call_args.args[0]
            self.assertEqual((Path(command[1]).name, command[2]), ('update-panel.py', '--install-helpers'))
            self.assertFalse(module.REQUEST.exists())
            self.assertFalse(module.STATUS.exists())                                # the address dialog shows nothing

    def test_install_helpers_flag(self):
        module = self.load()
        with patch.object(module, 'ensure_address_helper') as ensure, patch.object(module.os, 'geteuid', return_value=0), \
                patch('sys.argv', ['update-panel.py', '--install-helpers']), patch.object(module, 'run_update') as run:
            module.main()
        ensure.assert_called_once_with()
        run.assert_not_called()

    def test_from_request_reports_outcome(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / 'panel-update-request.json'
            status = Path(tmp) / 'panel-update-status.json'
            seen = []
            with patch.object(module, 'run_update', side_effect=lambda repo, ref, archive: seen.append((repo, ref, archive))):
                request.write_text(json.dumps({'ref': 'v1.2.0'}))
                self.assertEqual(module.from_request(request), 0)
            self.assertEqual(seen, [('mozisen/vaio-panel', 'v1.2.0', None)])
            self.assertFalse(request.exists())
            self.assertEqual(json.loads(status.read_text())['state'], 'succeeded')
            with patch.object(module, 'run_update', side_effect=SystemExit('健康检查失败')):
                request.write_text(json.dumps({'ref': 'v1.2.0'}))
                self.assertEqual(module.from_request(request), 1)
            saved = json.loads(status.read_text())
            self.assertEqual(saved['state'], 'failed')
            self.assertIn('健康检查失败', saved['message'])
            with patch.object(module, 'run_update') as run:
                request.write_text(json.dumps({'ref': 'main; rm -rf /'}))
                self.assertEqual(module.from_request(request), 1)
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
