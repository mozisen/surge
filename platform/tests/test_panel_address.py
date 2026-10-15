"""面板地址：辅助程序（Nginx 配置、证书、面板地址、失败回滚、关闭旧地址）、面板接口与节点迁移、节点程序 HTTP 开关与切换地址、升级时补装辅助服务。"""
import importlib.util
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from agent.__main__ import Agent, valid_url
from vaio.common import validate_set_url_task
from vaio.server import create_app

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


def load(name, prefix=None):
    if prefix:
        os.environ['VAIO_ADDRESS_PREFIX'] = str(prefix)
    spec = importlib.util.spec_from_file_location(name.replace('-', '_') + str(time.time_ns()), SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.environ.pop('VAIO_ADDRESS_PREFIX', None)
    return module


class Helper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ('etc/vaio-panel', 'var/lib/vaio-panel', 'etc/nginx/sites-available', 'etc/nginx/sites-enabled', 'etc/letsencrypt/live'):
            (self.root / d).mkdir(parents=True)
        (self.root / 'etc/vaio-panel/panel.env').write_text('VAIO_DATABASE=/var/lib/vaio-panel/panel.sqlite\nPYTHONDONTWRITEBYTECODE=1\n')
        self.h = load('panel-address', self.root)
        self.calls = []
        self.fail = None

        def run(*command, **kwargs):
            self.calls.append(command)
            if command[0] == 'certbot':
                (self.root / 'etc/letsencrypt/live' / command[command.index('-d') + 1]).mkdir(parents=True, exist_ok=True)
                (self.root / 'etc/letsencrypt/live' / command[command.index('-d') + 1] / 'fullchain.pem').write_text('cert')
            if self.fail and self.fail == command[0]:
                raise subprocess.CalledProcessError(1, list(command), stderr=b'boom: certificate refused')
        self.patches = [patch.object(self.h, 'run', side_effect=run), patch.object(self.h, 'port_busy', return_value=False)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def env(self):
        return (self.root / 'etc/vaio-panel/panel.env').read_text()

    def site(self):
        return (self.root / 'etc/nginx/sites-available/vaio-panel').read_text()

    def test_ip_install_then_bind_domain_then_close_legacy(self):
        self.h.install(type('A', (), {'domain': None, 'ip': '1.2.3.4', 'port': 8080})())
        self.assertIn('VAIO_PUBLIC_URL=http://1.2.3.4:8080', self.env())
        self.assertIn('VAIO_ALLOW_HTTP=1', self.env())
        self.assertIn('VAIO_DATABASE=/var/lib/vaio-panel/panel.sqlite', self.env())
        self.assertIn('listen 8080;', self.site())
        self.assertNotIn('ssl', self.site())
        self.assertTrue((self.root / 'etc/nginx/sites-enabled/vaio-panel').is_symlink())
        self.assertNotIn(('systemctl', 'restart', 'vaio-panel'), self.calls)           # install does not start the panel
        # Bind a domain from the panel: certificate, HTTPS on 8443, old HTTP kept until closed.
        (self.root / 'var/lib/vaio-panel/address-request.json').write_text(json.dumps({"action": "set_domain", "domain": "Panel.Example.com", "port": 8443}))
        self.h.apply()
        status = json.loads((self.root / 'var/lib/vaio-panel/address-status.json').read_text())
        self.assertEqual((status['state'], status['url']), ('succeeded', 'https://panel.example.com:8443'))
        self.assertFalse((self.root / 'var/lib/vaio-panel/address-request.json').exists())
        self.assertIn('VAIO_PUBLIC_URL=https://panel.example.com:8443', self.env())
        self.assertIn('VAIO_ALLOW_HTTP=1', self.env())
        site = self.site()
        self.assertIn('listen 8443 ssl;', site)
        self.assertIn('listen 8080;', site)
        self.assertIn('return 301 https://panel.example.com:8443$request_uri', site)
        self.assertIn('/etc/letsencrypt/live/panel.example.com/fullchain.pem', site)
        self.assertTrue(any(c[0] == 'certbot' for c in self.calls))
        self.assertIn(('systemctl', 'restart', 'vaio-panel'), self.calls)
        # Close the old address: HTTP block and VAIO_ALLOW_HTTP go away.
        self.h.close_legacy()
        self.assertNotIn('listen 8080;', self.site())
        self.assertNotIn('VAIO_ALLOW_HTTP', self.env())
        self.assertEqual(json.loads((self.root / 'etc/vaio-panel/address.json').read_text())['legacy'], None)

    def test_domain_change_keeps_previous_until_closed_and_failure_restores(self):
        self.h.install(type('A', (), {'domain': 'old.example.com', 'ip': None, 'port': 443})())
        self.assertIn('VAIO_PUBLIC_URL=https://old.example.com', self.env())
        self.assertNotIn('VAIO_ALLOW_HTTP', self.env())
        before = (self.site(), self.env())
        self.fail = 'certbot'
        (self.root / 'var/lib/vaio-panel/address-request.json').write_text(json.dumps({"action": "set_domain", "domain": "new.example.com", "port": 443}))
        self.h.apply()
        status = json.loads((self.root / 'var/lib/vaio-panel/address-status.json').read_text())
        self.assertEqual(status['state'], 'failed')
        self.assertIn('certificate refused', status['message'])
        self.assertEqual((self.site(), self.env()), before)                             # restored
        self.fail = None
        self.h.set_domain('new.example.com', 443)
        self.assertIn('server_name old.example.com;', self.site())                      # previous domain still served
        self.assertIn('server_name new.example.com;', self.site())
        self.assertIn('VAIO_PUBLIC_URL=https://new.example.com', self.env())
        self.h.close_legacy()
        self.assertNotIn('old.example.com', self.site())
        with self.assertRaisesRegex(ValueError, '域名格式'):
            self.h.set_domain('https://x', 443)
        with self.assertRaisesRegex(ValueError, '端口'):
            self.h.set_domain('a.example.com', 70000)

    def test_state_from_older_install_and_unknown_requests(self):
        (self.root / 'etc/vaio-panel/panel.env').write_text('VAIO_PUBLIC_URL=https://io.example.com\n')
        self.assertEqual(self.h.load_state(), {"legacy": None, "previous": None, "domain": {"name": "io.example.com", "port": 443}})
        (self.root / 'var/lib/vaio-panel/address-request.json').write_text('{"action":"rm -rf"}')
        self.h.apply()
        self.assertEqual(json.loads((self.root / 'var/lib/vaio-panel/address-status.json').read_text())['state'], 'failed')
        self.h.close_legacy()                                                          # nothing to close: no change
        with self.assertRaisesRegex(ValueError, 'IPv4'):
            self.h.check_ip('2001:db8::1')


class PanelAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = self.tmp.name + '/panel.sqlite'

    def tearDown(self):
        self.tmp.cleanup()

    def app(self, url, **extra):
        app = create_app({'TESTING': True, 'DATABASE': self.db, 'PUBLIC_URL': url, 'ADDRESS_HELPER': True, **extra})
        store = app.extensions['store']
        with store.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('password',?)", (generate_password_hash('a-long-test-password', method='pbkdf2:sha256:1000'),))
        client = app.test_client()
        headers = {'X-CSRF-Token': client.post('/api/login', json={'username': 'admin', 'password': 'a-long-test-password'}).json['csrf']}
        return app, client, headers

    def test_http_only_when_allowed_and_enrollment_marks_it(self):
        with self.assertRaisesRegex(ValueError, 'HTTPS'):
            create_app({'TESTING': True, 'DATABASE': self.db, 'PUBLIC_URL': 'http://1.2.3.4:8080'})
        app, client, h = self.app('http://1.2.3.4:8080', ALLOW_HTTP=True)
        r = client.post('/api/nodes', json={'name': 'n'}, headers=h).json
        enrollment = json.loads(r['script'].split("<<'VAIO_ENROLLMENT'\n")[1].split('\nVAIO_ENROLLMENT')[0])
        self.assertIs(enrollment['allow_http'], True)
        login = app.test_client().post('/api/login', json={'username': 'admin', 'password': 'a-long-test-password'})
        self.assertNotIn('Secure', login.headers.get('Set-Cookie', ''))
        data = client.get('/api/panel-address').json
        self.assertEqual((data['url'], data['secure'], data['migration']), ('http://1.2.3.4:8080', False, None))

    def test_requests_and_node_migration(self):
        app, client, h = self.app('http://1.2.3.4:8080', ALLOW_HTTP=True)
        store = app.extensions['store']
        with store.connect() as db:
            for i, name in enumerate(('A', 'B')):
                db.execute("INSERT INTO nodes(id,name,created,adopted,snapshot) VALUES(?,?,0,1,'{}')", ('n%d' % i, name))
        for bad in ({'domain': 'bad'}, {'domain': 'a.example.com', 'port': 18080}, {'domain': 'a.example.com', 'port': '443'}, {'domain': 'a.example.com', 'x': 1}):
            self.assertEqual(client.post('/api/panel-address', json=bad, headers=h).status_code, 400, bad)
        self.assertEqual(client.post('/api/panel-address', json={'domain': 'Panel.Example.com', 'port': 8443}, headers=h).status_code, 200)
        request = json.loads((Path(self.tmp.name) / 'address-request.json').read_text())
        self.assertEqual(request, {'action': 'set_domain', 'domain': 'panel.example.com', 'port': 8443})
        self.assertEqual(client.post('/api/panel-address', json={'domain': 'x.example.com'}, headers=h).status_code, 400)  # one at a time
        self.assertTrue(client.get('/api/panel-address').json['pending'])
        self.assertEqual(client.post('/api/panel-address/close-legacy', json={}, headers=h).status_code, 400)          # still HTTP
        # The helper switched the panel: it restarts on the HTTPS address and notifies every node once.
        (Path(self.tmp.name) / 'address-request.json').unlink()
        app, client, h = self.app('https://panel.example.com:8443', ALLOW_HTTP=True)
        store = app.extensions['store']
        with store.connect() as db:
            tasks = db.execute("SELECT node_id, request FROM tasks WHERE action='agent_set_url' ORDER BY node_id").fetchall()
        self.assertEqual([t['node_id'] for t in tasks], ['n0', 'n1'])
        self.assertEqual(json.loads(tasks[0]['request'])['params']['url'], 'https://panel.example.com:8443')
        self.app('https://panel.example.com:8443', ALLOW_HTTP=True)                    # same address again: nothing new
        with store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tasks WHERE action='agent_set_url'").fetchone()[0], 2)
            db.execute("UPDATE tasks SET status='succeeded' WHERE node_id='n0'")
            db.execute("UPDATE tasks SET status='failed', message='任务字段无效' WHERE node_id='n1'")
        data = client.get('/api/panel-address').json
        self.assertEqual((data['legacy_open'], data['migration']['done'], data['migration']['total']), (True, 1, 2))
        r = client.post('/api/panel-address/close-legacy', json={}, headers=h)
        self.assertEqual((r.status_code, r.json['waiting']), (409, ['B']))
        self.assertEqual(client.post('/api/panel-address/retry', json={}, headers=h).json['queued'], 1)
        self.assertEqual(client.post('/api/panel-address/close-legacy', json={'force': True}, headers=h).status_code, 200)
        self.assertEqual(json.loads((Path(self.tmp.name) / 'address-request.json').read_text()), {'action': 'close_legacy'})

    def test_first_start_on_https_records_without_notifying(self):
        app, client, h = self.app('https://io.example.com')
        with app.extensions['store'].connect() as db:
            db.execute("INSERT INTO nodes(id,name,created,adopted,snapshot) VALUES('n','A',0,1,'{}')")
        self.app('https://io.example.com')
        with app.extensions['store'].connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tasks").fetchone()[0], 0)


class AgentSide(unittest.TestCase):
    def test_valid_url_and_set_url(self):
        with self.assertRaises(ValueError):
            valid_url('http://1.2.3.4:8080')
        self.assertEqual(valid_url('http://1.2.3.4:8080/', allow_http=True), 'http://1.2.3.4:8080')
        with self.assertRaises(ValueError):
            validate_set_url_task({'action': 'agent_set_url', 'params': {'url': 'http://x.example.com'}})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            config = {'url': 'http://1.2.3.4:8080', 'node_id': 'n', 'token': 't', 'allow_http': True}
            path.write_text(json.dumps(config))
            agent = Agent(config, Path(tmp) / 'state', cfg=Path(tmp), config_path=path)
            task = {'id': '1', 'action': 'agent_set_url', 'params': {'url': 'https://panel.example.com:8443'}}
            with patch('agent.__main__.urllib.request.OpenerDirector.open', side_effect=OSError('certificate verify failed')):
                result = agent.run_task(task)
            self.assertEqual((result['status'], agent.url), ('failed', 'http://1.2.3.4:8080'))
            class Ok:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *a): return False
            with patch('agent.__main__.urllib.request.OpenerDirector.open', return_value=Ok()):
                result = agent.run_task(task)
            self.assertEqual((result['status'], agent.url), ('succeeded', 'https://panel.example.com:8443'))
            saved = json.loads(path.read_text())
            self.assertEqual((saved['url'], 'allow_http' in saved, saved['token']), ('https://panel.example.com:8443', False, 't'))


class StatusFiles(unittest.TestCase):
    """The root helpers write status into the panel-owned data folder: never follow a link planted there."""

    def check(self, write, path):
        victim = path.parent.parent / 'victim'
        victim.write_text('keep')
        path.symlink_to(victim)
        write()
        self.assertEqual(victim.read_text(), 'keep')
        self.assertFalse(path.is_symlink())
        self.assertEqual(oct(path.stat().st_mode & 0o777), '0o644')
        self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])   # no temp file left behind
        return json.loads(path.read_text())

    def test_address_status_replaces_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'var/lib/vaio-panel').mkdir(parents=True)
            h = load('panel-address', root)
            saved = self.check(lambda: h.status('failed', 'domain', 'x'), root / 'var/lib/vaio-panel/address-status.json')
            self.assertEqual(saved['state'], 'failed')

    def test_update_status_replaces_symlink(self):
        module = load('update-panel')
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / 'data'
            data.mkdir()
            saved = self.check(lambda: module.update_status(data / 'panel-update-status.json', 'running', 'x', ref='v1'), data / 'panel-update-status.json')
            self.assertEqual((saved['state'], saved['ref']), ('running', 'v1'))


class UpgradeHelper(unittest.TestCase):
    def test_upgrade_installs_address_units_once(self):
        module = load('update-panel')
        with tempfile.TemporaryDirectory() as tmp, patch.object(module.subprocess, 'run') as run:
            units = Path(tmp)
            self.assertTrue(module.ensure_address_helper(units))
            self.assertIn('panel-address.py apply', (units / 'vaio-panel-address.service').read_text())
            self.assertIn('PathExists=/var/lib/vaio-panel/address-request.json', (units / 'vaio-panel-address.path').read_text())
            self.assertFalse(module.ensure_address_helper(units))
            self.assertIn(['systemctl', 'enable', '--now', 'vaio-panel-address.path'], [c.args[0] for c in run.call_args_list])


if __name__ == '__main__':
    unittest.main()
