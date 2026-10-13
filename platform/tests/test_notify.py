"""通知配置：TG 设置迁移与校验、发送队列不留记录、平台用户提醒、每日报告、用户机器人与绑定码。"""
import datetime
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from vaio import backups, monitor, platform_users
from vaio.common import digest
from vaio.server import create_app
from vaio.store import Store

GIB = 1073741824
TOKEN = '123456:' + 'a' * 30


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name + '/panel.sqlite')

    def tearDown(self):
        self.tmp.cleanup()

    def user(self, name='alice', **fields):
        with self.store.connect() as db:
            return platform_users.create_user(db, {'name': name, **fields}, now=1760000000)

    def link(self, user_id, used, node='n1', name='香港', seen=None):
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM nodes WHERE id=?', (node,)).fetchone():
                db.execute("INSERT INTO nodes(id,name,created,last_seen,snapshot) VALUES(?,?,0,?,'{}')", (node, name, seen))
            db.execute("INSERT INTO platform_links(id,user_id,node_id,account_id,origin,cycle_used,state,created) VALUES(?,?,?,?,?,?,?,0)",
                       (user_id + node, user_id, node, 'acc-' + node, 'panel', used, 'synced'))

    def queue(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM notifications ORDER BY id')]

    def configure(self, **extra):
        monitor.save_settings(self.store, dict(enabled=True, bot_token=TOKEN, chat_id='1234', **extra))


class SettingsTest(Base):
    def test_legacy_settings_migrate_and_webhook_is_dropped(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO settings VALUES('notifications',?)", (json.dumps(dict(enabled=True, telegram_token=TOKEN, telegram_chat='42', webhook='https://x')),))
        config = monitor.settings(self.store, True)
        self.assertEqual((config['bot_token'], config['chat_id'], config['enabled'], config['quota_percent']), (TOKEN, '42', True, 80))
        self.assertNotIn('webhook', monitor.settings(self.store))
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('notifications',?)", (json.dumps(dict(enabled=True, webhook='https://x')),))
        self.assertFalse(monitor.settings(self.store, True)['enabled'])  # webhook-only: unconfigured, off

    def test_validation_redaction_and_rollback_keys(self):
        for bad in (dict(enabled=True), dict(enabled='yes'), dict(enabled=False, bot_token='bad'), dict(enabled=False, chat_id='x y'),
                    dict(enabled=False, quota_percent=49), dict(enabled=False, quota_percent=True), dict(enabled=False, daily_time='24:00'),
                    dict(enabled=False, webhook='https://x')):
            with self.assertRaises(ValueError, msg=bad):
                monitor.save_settings(self.store, bad)
        self.configure(quota_percent=90, daily_enabled=True, daily_time='08:30')
        public = monitor.settings(self.store)
        self.assertNotIn(TOKEN, json.dumps(public))
        self.assertTrue(public['token_configured'])
        self.assertEqual((public['quota_percent'], public['daily_time']), (90, '08:30'))
        raw = json.loads(self.store.setting('notifications'))
        self.assertEqual((raw['telegram_token'], raw['telegram_chat']), (TOKEN, '1234'))
        monitor.save_settings(self.store, dict(enabled=True, chat_id='1234'))  # empty token keeps the stored one
        self.assertEqual(monitor.settings(self.store, True)['bot_token'], TOKEN)

    def test_token_change_or_clear_disables_the_bot(self):
        self.configure()
        monitor.update(self.store, bot_enabled=True, bot_offset=9)
        monitor.save_settings(self.store, dict(enabled=True, bot_token=TOKEN, chat_id='1234'))
        self.assertTrue(monitor.settings(self.store, True)['bot_enabled'])  # same token: unchanged
        monitor.save_settings(self.store, dict(enabled=True, bot_token='654321:' + 'b' * 30, chat_id='1234'))
        config = monitor.settings(self.store, True)
        self.assertEqual((config['bot_enabled'], config['bot_offset']), (False, 0))
        with self.assertRaisesRegex(ValueError, 'Bot Token'):
            monitor.save_settings(self.store, dict(enabled=True, clear_token=True, chat_id='1234'))
        monitor.save_settings(self.store, dict(enabled=False, clear_token=True))
        self.assertEqual(monitor.settings(self.store, True)['bot_token'], '')


class AlertTest(Base):
    def test_threshold_user_alerts_and_queue_without_history(self):
        self.configure(quota_percent=60)
        bound, plain = self.user('alice', quota_gb=10), self.user('bob', quota_gb=10)
        self.link(bound, 7 * GIB)
        self.link(plain, 7 * GIB, node='n2')
        with self.store.connect() as db:
            db.execute("INSERT INTO platform_tg(user_id,chat_id,username,bound_at) VALUES(?,?,?,1)", (bound, '777', 'al'))
        monitor.scan(self.store, 1760000000)
        titles = [r['title'] for r in self.queue() if not r['chat_id']]
        self.assertIn('平台用户 alice · 总流量已达配额的 60%', titles)
        self.assertEqual([r for r in self.queue() if r['chat_id']], [])  # bot disabled: nothing for users
        with self.store.connect() as db:
            db.execute('DELETE FROM incidents')
        monitor.update(self.store, bot_enabled=True)
        monitor.scan(self.store, 1760000000)
        personal = [r for r in self.queue() if r['chat_id']]
        self.assertEqual(len(personal), 1)
        self.assertEqual(personal[0]['chat_id'], '777')
        self.assertIn('使用率已达 70%', personal[0]['title'])
        sent = []
        with patch('vaio.monitor.deliver', side_effect=lambda token, chat, text: sent.append(chat) or True):
            monitor.send_pending(self.store)
        self.assertIn('777', sent)
        self.assertIn('1234', sent)
        self.assertEqual(self.queue(), [])

    def test_disabled_admin_alerts_are_not_recorded_and_queued_rows_are_dropped(self):
        self.user('alice', quota_gb=1)
        monitor.scan(self.store, 1760000000)
        self.assertEqual(self.queue(), [])
        self.configure()
        with self.store.connect() as db:
            monitor.queue(db, 1, 'x')
        monitor.save_settings(self.store, dict(enabled=False))
        with patch('vaio.monitor.deliver') as deliver:
            monitor.send_pending(self.store)
            deliver.assert_not_called()
        self.assertEqual(self.queue(), [])

    def test_daily_report_once_within_the_hour(self):
        self.configure(daily_enabled=True, daily_time='09:00')
        alice = self.user('alice', quota_gb=10)
        self.link(alice, 2 * GIB, seen=time.time())
        nine = datetime.datetime(2026, 10, 13, 9, 20).timestamp()
        monitor.scan(self.store, datetime.datetime(2026, 10, 13, 8, 59).timestamp())
        self.assertFalse(any('每日流量报告' in r['title'] for r in self.queue()))
        monitor.scan(self.store, nine)
        monitor.scan(self.store, nine + 60)
        reports = [r['title'] for r in self.queue() if '每日流量报告' in r['title']]
        self.assertEqual(len(reports), 1)
        self.assertIn('平台用户：1 个，总用量 2.0 GiB', reports[0])
        self.assertIn('alice  2.0 GiB / 10.0 GiB（20%）', reports[0])
        monitor.scan(self.store, datetime.datetime(2026, 10, 14, 11, 0).timestamp())  # outside the window: skipped that day
        self.assertEqual(len([r for r in self.queue() if '每日流量报告' in r['title']]), 1)

    def test_test_message_rate_limit(self):
        with self.assertRaisesRegex(ValueError, '启用'):
            monitor.test_message(self.store)
        self.configure()
        monitor.test_message(self.store, 100)
        with self.assertRaisesRegex(ValueError, '一分钟'):
            monitor.test_message(self.store, 130)
        monitor.test_message(self.store, 170)
        self.assertEqual(len(self.queue()), 2)

    def test_restore_drops_the_queue(self):
        self.configure()
        with self.store.connect() as db:
            monitor.queue(db, 1, 'pending')
        name = backups.create(self.store)
        backups.restore(self.store, name)
        self.assertEqual(self.queue(), [])


class BotTest(Base):
    def msg(self, text, chat=555, kind='private', username='tg_alice'):
        return {'update_id': 1, 'message': {'chat': {'id': chat, 'type': kind}, 'from': {'username': username}, 'text': text}}

    def test_bind_query_unbind_and_guards(self):
        alice = self.user('alice', quota_gb=10, expire_date='2099-01-01')
        self.link(alice, 4 * GIB, name='香港')
        with self.store.connect() as db:
            code, expires = monitor.new_code(db, alice, now=1000)
        self.assertRegex(code, r'^[A-F0-9]{12}$')
        self.assertEqual(expires, 1000 + 86400)
        with self.store.connect() as db:
            row = db.execute('SELECT code_hash FROM platform_tg').fetchone()
        self.assertNotIn(code, row['code_hash'])
        h = monitor.handle_update
        self.assertIsNone(h(self.store, self.msg('/bind ' + code, kind='group'), 1001))
        self.assertIsNone(h(self.store, self.msg('hello'), 1001))
        self.assertIn('用法', h(self.store, self.msg('/bind'), 1001))
        self.assertIn('格式无效', h(self.store, self.msg('/bind xyz'), 1001))
        self.assertIn('尚未绑定', h(self.store, self.msg('/traffic'), 1001))
        self.assertIn('无效或已过期', h(self.store, self.msg('/bind ' + code), 1000 + 86401))
        self.assertIn('无效或已过期', h(self.store, self.msg('/bind ABCDEFABCDEF'), 1001))
        self.assertIn('绑定成功：alice', h(self.store, self.msg('/bind ' + code.lower()), 1001))
        self.assertIn('无效或已过期', h(self.store, self.msg('/bind ' + code, chat=556), 1002))  # one-time code
        self.assertIn('已绑定账号', h(self.store, self.msg('/bind ' + code), 1002))
        report = h(self.store, self.msg('/traffic@vaio_bot'), 1002)
        for text in ('用户：alice', '已使用：4.0 GiB', '总配额：10.0 GiB', '剩余流量：6.0 GiB', '使用率：40%', '到期时间：2099-01-01', '账号状态：正常', '· 香港：4.0 GiB'):
            self.assertIn(text, report)
        self.assertEqual(h(self.store, self.msg('/status'), 1002), report)
        self.assertIn('/bind', h(self.store, self.msg('/start'), 1002))
        self.assertIn('未知命令', h(self.store, self.msg('/nope'), 1002))
        with self.store.connect() as db:
            listing = monitor.bindings(db, 1002)
        self.assertEqual((listing[0]['bound'], listing[0]['username'], listing[0]['code_pending']), (True, 'tg_alice', False))
        self.assertIn('已解除账号 alice', h(self.store, self.msg('/unbind'), 1003))
        self.assertIn('尚未绑定', h(self.store, self.msg('/unbind'), 1003))
        with self.store.connect() as db:
            self.assertFalse(monitor.bindings(db, 1003)[0]['bound'])

    def test_rebind_moves_to_the_new_chat_and_deleting_the_user_removes_it(self):
        alice = self.user('alice')
        for chat in (555, 556):
            with self.store.connect() as db:
                code, _ = monitor.new_code(db, alice, now=1000)
            self.assertIn('绑定成功', monitor.handle_update(self.store, self.msg('/bind ' + code, chat=chat), 1001))
        with self.store.connect() as db:
            self.assertEqual([r[0] for r in db.execute('SELECT chat_id FROM platform_tg')], ['556'])
            platform_users.delete_user(db, alice, 'detach')
            self.assertEqual(db.execute('SELECT count(*) FROM platform_tg').fetchone()[0], 0)
            with self.assertRaises(ValueError):
                monitor.new_code(db, 'missing')

    def test_poll_advances_offset_and_replies(self):
        self.configure()
        calls = []

        def fake(token, method, params, timeout=10):
            calls.append((method, params))
            if method == 'getUpdates':
                return [{'update_id': 41, 'message': {'chat': {'id': 9, 'type': 'private'}, 'text': '/help'}}, {'bad': True}]
            return {}
        with patch('vaio.monitor.tg_call', side_effect=fake):
            self.assertEqual(monitor.poll_bot(self.store), 0)  # bot disabled
            monitor.update(self.store, bot_enabled=True)
            self.assertEqual(monitor.poll_bot(self.store), 1)
        self.assertEqual(calls[0][1]['offset'], 0)
        self.assertEqual(calls[1][0], 'sendMessage')
        self.assertEqual(calls[1][1]['chat_id'], 9)
        self.assertEqual(monitor.settings(self.store, True)['bot_offset'], 42)

    def test_enable_bot(self):
        with self.assertRaisesRegex(ValueError, 'Bot Token'):
            monitor.enable_bot(self.store, True)
        self.configure()
        methods = []
        with patch('vaio.monitor.tg_call', side_effect=lambda t, m, p, timeout=10: methods.append(m) or {'username': 'vaio_bot'}):
            self.assertEqual(monitor.enable_bot(self.store, True), {'username': 'vaio_bot'})
        self.assertEqual(methods, ['getMe', 'deleteWebhook', 'setMyCommands'])
        self.assertTrue(monitor.settings(self.store, True)['bot_enabled'])
        monitor.enable_bot(self.store, False)
        self.assertFalse(monitor.settings(self.store, True)['bot_enabled'])
        with patch('vaio.monitor.tg_call', side_effect=RuntimeError('x')):
            with self.assertRaisesRegex(ValueError, '未启用'):
                monitor.enable_bot(self.store, True)
        self.assertFalse(monitor.settings(self.store, True)['bot_enabled'])


class APITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'DATABASE': self.tmp.name + '/panel.sqlite'})
        self.client = self.app.test_client()
        self.store = self.app.extensions['store']
        with self.store.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest('session'), 'csrf', time.time() + 1000))
            self.uid = platform_users.create_user(db, {'name': 'alice'})
        self.client.set_cookie('vaio_session', 'session')
        self.h = {'X-CSRF-Token': 'csrf'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_endpoints(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.post('/api/users/%s/tg-code' % self.uid, json={}).status_code, 401)
        self.assertEqual(self.client.post('/api/users/%s/tg-code' % self.uid, json={}).status_code, 403)
        r = self.client.post('/api/users/%s/tg-code' % self.uid, json={}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        code = r.json['code']
        data = self.client.get('/api/monitor').json
        self.assertEqual(data['users'][0]['name'], 'alice')
        self.assertTrue(data['users'][0]['code_pending'])
        self.assertNotIn(code, json.dumps(data))
        with self.store.connect() as db:
            audit = ' '.join(r[0] for r in db.execute('SELECT detail FROM audit'))
        self.assertNotIn(code, audit)
        self.assertEqual(self.client.post('/api/users/missing/tg-code', json={}, headers=self.h).status_code, 400)
        self.assertEqual(self.client.post('/api/users/%s/tg-unbind' % self.uid, json={}, headers=self.h).status_code, 200)
        self.assertEqual(self.client.post('/api/monitor/bot', json={'enabled': 'yes'}, headers=self.h).status_code, 400)
        self.assertEqual(self.client.post('/api/monitor/bot', json={'enabled': True}, headers=self.h).status_code, 400)
        self.assertEqual(self.client.post('/api/monitor/bot', json={'enabled': False}, headers=self.h).status_code, 200)
        self.assertEqual(self.client.post('/api/monitor/test', json={}, headers=self.h).status_code, 400)


if __name__ == '__main__':
    unittest.main()
