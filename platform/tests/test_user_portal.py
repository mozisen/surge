"""平台用户登录与自助页面：登录分流、管理接口一律拒绝用户会话、只看自己的数据、导出只含连接、TG 绑定码、改密码与会话失效。"""
import json
import re
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from vaio import monitor, platform_users
from vaio.server import create_app

ADMIN_PASSWORD = 'a-long-test-password'
G = 1073741824


class Portal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'DATABASE': self.tmp.name + '/panel.sqlite', 'PUBLIC_URL': 'https://p.example.com'})
        self.store = self.app.extensions['store']
        now = time.time()
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('password',?)", (generate_password_hash(ADMIN_PASSWORD, method='pbkdf2:sha256:1000'),))
            self.alice = platform_users.create_user(db, {'name': 'alice', 'quota_gb': 10, 'reset_day': 1, 'note': '内部备注'})
            self.bob = platform_users.create_user(db, {'name': 'bob'})
            for node_id, name, account, user, member in (('n1', 'hk', 'acc-a', self.alice, 'alice'), ('n2', 'jp', 'acc-b', self.bob, 'bob')):
                snapshot = {'config_details_version': 2, 'addresses': {'ipv4': '9.9.9.%d' % len(name)},
                            'accounts': {account: {'members': [{'core': 'xray', 'protocol': 'vless', 'port': 443, 'name': member, 'enabled': True, 'used': 5},
                                                               {'core': 'singbox', 'protocol': 'hy2', 'port': 8443, 'name': member, 'enabled': False}]}}}
                db.execute("INSERT INTO nodes(id,name,created,adopted,last_seen,snapshot) VALUES(?,?,?,?,?,?)", (node_id, name, now, 1, now, json.dumps(snapshot)))
                db.execute("INSERT INTO platform_links(id,user_id,node_id,account_id,origin,members,state,cycle_used,created) VALUES(?,?,?,?,?,?,?,?,?)",
                           ('link-' + node_id, user, node_id, account, 'created', '[]', 'synced', 3 * G, now))
            hop = {'node_id': 'n2', 'rule': {'backend': 'realm', 'remark': '', 'transport': 'tcp', 'listen_host': '0.0.0.0', 'listen_port': 30001,
                                             'remote_host': '9.9.9.2', 'remote_port': 443, 'enabled': True}, 'forward_id': 'f1', 'task_id': None, 'status': 'active'}
            db.execute("INSERT INTO relay_lines VALUES(?,?,?,?,?,?,?,?,0,?,?)", ('line-a', self.alice, 'n1', 'xray', 'vless', 443, '9.9.9.2', json.dumps([hop]), now, now))
            db.execute("INSERT INTO relay_lines VALUES(?,?,?,?,?,?,?,?,0,?,?)", ('line-b', self.bob, 'n2', 'xray', 'vless', 443, '9.9.9.2', json.dumps([hop]), now, now))

    def tearDown(self):
        self.tmp.cleanup()

    def admin(self):
        client = self.app.test_client()
        csrf = client.post('/api/login', json={'username': 'admin', 'password': ADMIN_PASSWORD}).json['csrf']
        return client, {'X-CSRF-Token': csrf}

    def enable(self, user_id, password='user-password-1'):
        """Set the user's password through 编辑用户 (as the admin does)."""
        client, h = self.admin()
        r = client.post('/api/users/%s' % user_id, json={'password': password}, headers=h)
        self.assertEqual(r.status_code, 200, r.json)

    def user(self, name='alice', password='user-password-1'):
        client = self.app.test_client()
        r = client.post('/api/login', json={'username': name, 'password': password})
        self.assertEqual((r.status_code, r.json.get('role')), (200, 'user'), r.json)
        return client, {'X-CSRF-Token': r.json['csrf']}

    def test_login_roles_and_password_reset(self):
        client = self.app.test_client()
        # Users from before 1.3.1 got a random password at upgrade: nobody can sign in until the admin sets one.
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM platform_users WHERE password_hash IS NULL").fetchone()[0], 0)
        self.assertEqual(client.post('/api/login', json={'username': 'alice', 'password': 'user-password-1'}).status_code, 401)
        self.enable(self.alice)
        self.assertEqual(self.app.test_client().post('/api/login', json={'username': 'admin', 'password': ADMIN_PASSWORD}).json['role'], 'admin')
        self.assertEqual(client.post('/api/login', json={'username': 'alice', 'password': 'wrong-password'}).status_code, 401)
        user, h = self.user()
        self.assertEqual(user.get('/api/me').json['name'], 'alice')
        self.assertEqual(user.get('/api/session').status_code, 401)            # not an admin session
        admin, ah = self.admin()
        # Editing other fields keeps the password and the session; a new password ends the sessions.
        self.assertEqual(admin.post('/api/users/%s' % self.alice, json={'note': 'x'}, headers=ah).status_code, 200)
        self.assertEqual(user.get('/api/me').status_code, 200)
        r = admin.post('/api/users/%s' % self.alice, json={'password': 'reset-password-9'}, headers=ah)
        self.assertEqual(r.json['changed'], ['password'])
        self.assertEqual(user.get('/api/me').status_code, 401)
        self.user(password='reset-password-9')
        for bad in ({'password': 'short'}, {'password': 'x' * 129}, {'password': 5}):
            self.assertEqual(admin.post('/api/users/%s' % self.alice, json=bad, headers=ah).status_code, 400)
        self.assertEqual(admin.post('/api/users/%s/login' % self.alice, json={'enabled': False}, headers=ah).status_code, 404)  # removed

    def test_create_with_password(self):
        admin, h = self.admin()
        self.assertIn('密码', admin.post('/api/users', json={'name': 'carol', 'password': 'short'}, headers=h).json['error'])
        dave = admin.post('/api/users', json={'name': 'dave'}, headers=h)            # no password: random, cannot sign in
        self.assertEqual(dave.status_code, 201)
        self.assertEqual(self.app.test_client().post('/api/login', json={'username': 'dave', 'password': ''}).status_code, 401)
        r = admin.post('/api/users', json={'name': 'carol', 'quota_gb': 1, 'password': 'carol-password'}, headers=h)
        self.assertEqual(r.status_code, 201, r.json)
        self.user('carol', 'carol-password')

    def test_admin_name_cannot_be_a_user(self):
        admin, h = self.admin()
        self.assertIn('管理员', admin.post('/api/users', json={'name': 'Admin', 'password': 'user-password-1'}, headers=h).json['error'])
        self.assertIn('管理员', admin.post('/api/users/%s' % self.alice, json={'name': 'admin'}, headers=h).json['error'])
        r = admin.post('/api/account', json={'username': 'alice', 'current_password': ADMIN_PASSWORD, 'new_password': '', 'confirm_password': ''}, headers=h)
        self.assertIn('平台用户', r.json['error'])

    def test_every_admin_endpoint_rejects_a_user_session(self):
        self.enable(self.alice)
        user, h = self.user()
        checked = 0
        for rule in self.app.url_map.iter_rules():
            path = rule.rule
            if not path.startswith('/api/') or path.startswith(('/api/me', '/api/agent/', '/api/enroll')) or path in ('/api/login', '/api/logout'):
                continue
            url = re.sub(r'<[^>]+>', 'x', path)
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                r = user.open(url, method=method, json={}, headers=h)
                self.assertEqual(r.status_code, 401, (method, path, r.status_code))
                checked += 1
        self.assertGreater(checked, 50)

    def test_view_is_only_the_users_own_data(self):
        self.enable(self.alice)
        user, h = self.user()
        me = user.get('/api/me').json
        self.assertEqual((me['name'], me['used'], me['quota'], me['state']), ('alice', 3 * G, 10 * G, ''))
        self.assertEqual([l['node_name'] for l in me['links']], ['hk'])
        self.assertEqual(me['links'][0]['members'][0], {'core': 'xray', 'protocol': 'vless', 'port': 443, 'enabled': True})
        self.assertEqual([r['id'] for r in me['relays']], ['line-a'])
        self.assertEqual(me['relays'][0]['chain'], ['jp', 'hk'])
        text = json.dumps(me, ensure_ascii=False)
        for secret in ('内部备注', 'acc-a', '"n1"', 'bob', '9.9.9.2:443', 'line-b', 'link-n2'):
            self.assertNotIn(secret, text)
        self.assertEqual(me['telegram'], {'bound': False, 'username': '', 'bound_at': None, 'code_pending': False, 'bot': {'enabled': False, 'username': ''}})

    def finish(self, task_id, result):
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET status='succeeded',finished=?,result=? WHERE id=?", (time.time(), json.dumps(result), task_id))

    def test_share_own_protocol_and_relay_only(self):
        self.enable(self.alice)
        user, h = self.user()
        r = user.post('/api/me/share', json={'link_id': 'link-n2', 'core': 'xray', 'protocol': 'vless', 'port': 443}, headers=h)
        self.assertEqual(r.status_code, 404)                                     # bob's
        r = user.post('/api/me/share', json={'link_id': 'link-n1', 'core': 'singbox', 'protocol': 'hy2', 'port': 8443}, headers=h)
        self.assertIn('停用', r.json['error'])
        self.assertEqual(user.post('/api/me/share', json={'relay_id': 'line-b'}, headers=h).status_code, 404)
        r = user.post('/api/me/share', json={'link_id': 'link-n1', 'core': 'xray', 'protocol': 'vless', 'port': 443}, headers=h)
        self.assertEqual(r.status_code, 201, r.json)
        task_id = r.json['id']
        with self.store.connect() as db:
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        self.assertEqual((task['node_id'], json.loads(task['request'])['params']), ('n1', {'name': 'alice'}))
        self.assertIn('进行中', user.post('/api/me/share', json={'relay_id': 'line-a'}, headers=h).json['error'])
        with self.store.connect() as db:                                         # never picked up: stops blocking
            db.execute("UPDATE tasks SET created=created-121 WHERE id=?", (task_id,))
        stale = user.post('/api/me/share', json={'relay_id': 'line-a'}, headers=h)
        self.assertEqual(stale.status_code, 201)
        with self.store.connect() as db:
            db.execute("DELETE FROM tasks WHERE id=?", (stale.json['id'],))
        self.assertEqual(user.get('/api/me/tasks/' + task_id).json['status'], 'queued')
        self.finish(task_id, {'connection': 'vless://alice@hk', 'config_details': 'PRIVATE KEY'})
        view = user.get('/api/me/tasks/' + task_id).json
        self.assertEqual(view, {'status': 'succeeded', 'message': '', 'connection': 'vless://alice@hk'})
        self.assertEqual(user.get('/api/me/tasks/%s/qr' % task_id).mimetype, 'image/svg+xml')
        r = user.post('/api/me/share', json={'relay_id': 'line-a'}, headers=h)
        self.assertEqual(r.status_code, 201, r.json)
        with self.store.connect() as db:
            relay_task = db.execute("SELECT * FROM tasks WHERE id=?", (r.json['id'],)).fetchone()
        self.assertEqual(json.loads(relay_task['request'])['params'], {'name': 'alice', 'host': '9.9.9.2', 'port': 30001})
        # Someone else's export, or an admin's, is not visible.
        self.enable(self.bob)
        other, oh = self.user('bob')
        self.assertEqual(other.get('/api/me/tasks/' + task_id).status_code, 404)
        self.assertEqual(other.get('/api/me/tasks/%s/qr' % task_id).status_code, 404)
        with self.store.connect() as db:
            db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key,result,finished) VALUES('adm','n1','share','{}','succeeded',0,'k','{}',?)", (time.time(),))
        self.assertEqual(user.get('/api/me/tasks/adm').status_code, 404)

    def test_offline_node_and_bad_input(self):
        self.enable(self.alice)
        user, h = self.user()
        with self.store.connect() as db:
            db.execute("UPDATE nodes SET last_seen=0 WHERE id='n1'")
        self.assertIn('离线', user.post('/api/me/share', json={'link_id': 'link-n1', 'core': 'xray', 'protocol': 'vless', 'port': 443}, headers=h).json['error'])
        for bad in ({'link_id': 'link-n1'}, {'link_id': 1, 'core': 'x', 'protocol': 'y', 'port': 1}, {'relay_id': 5}):
            self.assertIn(user.post('/api/me/share', json=bad, headers=h).status_code, (400, 404))
        self.assertEqual(user.post('/api/me/share', json={'relay_id': 'line-a'}).status_code, 403)       # CSRF

    def test_telegram_code_and_bot(self):
        self.enable(self.alice)
        user, h = self.user()
        self.assertIn('尚未启用', user.post('/api/me/tg-code', json={}, headers=h).json['error'])
        monitor.update(self.store, bot_token='123456:' + 'a' * 30, bot_enabled=True)
        with patch.object(monitor, 'tg_call', return_value={'username': 'vaio_bot'}) as call:
            self.assertEqual(user.get('/api/me').json['telegram']['bot'], {'enabled': True, 'username': 'vaio_bot'})
            user.get('/api/me')
            self.assertEqual(call.call_count, 1)                                 # looked up once, then saved
        r = user.post('/api/me/tg-code', json={}, headers=h).json
        self.assertRegex(r['code'], r'^[A-F0-9]{12}$')
        self.assertTrue(user.get('/api/me').json['telegram']['code_pending'])
        with self.store.connect() as db:
            db.execute("UPDATE platform_tg SET chat_id='42',username='alice_tg',bound_at=1 WHERE user_id=?", (self.alice,))
        tg = user.get('/api/me').json['telegram']
        self.assertEqual((tg['bound'], tg['username']), (True, 'alice_tg'))
        self.assertEqual(user.post('/api/me/tg-unbind', json={}, headers=h).status_code, 200)
        self.assertFalse(user.get('/api/me').json['telegram']['bound'])
        self.assertEqual(monitor.settings(self.store)['bot_username'], 'vaio_bot')
        monitor.save_settings(self.store, {'enabled': False, 'bot_token': '654321:' + 'b' * 30})
        self.assertEqual(monitor.settings(self.store)['bot_username'], '')       # a new bot is enabled again

    def test_password_change_and_logout(self):
        self.enable(self.alice)
        user, h = self.user()
        second, _ = self.user()
        bad = user.post('/api/me/password', json={'current_password': 'nope', 'new_password': 'new-password-2', 'confirm_password': 'new-password-2'}, headers=h)
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(user.post('/api/me/password', json={'current_password': 'user-password-1', 'new_password': 'new-password-2',
                                                               'confirm_password': 'other-password'}, headers=h).status_code, 400)
        ok = user.post('/api/me/password', json={'current_password': 'user-password-1', 'new_password': 'new-password-2', 'confirm_password': 'new-password-2'}, headers=h)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(second.get('/api/me').status_code, 401)
        third, th = self.user(password='new-password-2')
        self.assertEqual(third.post('/api/logout', json={}).status_code, 403)    # CSRF
        self.assertEqual(third.post('/api/logout', json={}, headers=th).status_code, 200)
        self.assertEqual(third.get('/api/me').status_code, 401)
        admin, ah = self.admin()
        self.assertEqual(admin.post('/api/logout', json={}, headers=ah).status_code, 200)
        self.assertEqual(admin.get('/api/session').status_code, 401)

    def test_deleting_user_ends_sessions(self):
        self.enable(self.alice)
        user, h = self.user()
        admin, ah = self.admin()
        self.assertEqual(admin.post('/api/users/%s/delete' % self.alice, json={'mode': 'release'}, headers=ah).status_code, 200)
        self.assertEqual(user.get('/api/me').status_code, 401)


if __name__ == '__main__':
    unittest.main()
