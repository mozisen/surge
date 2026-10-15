"""总览流量：按天累计各服务器网卡收发（计数回落按新值计）、今日与本月合计、升级时用分钟采样补算、汇总接口。"""
import datetime
import json
import tempfile
import time
import unittest

from werkzeug.security import generate_password_hash

from vaio import daily, platform_users
from vaio.server import create_app
from vaio.store import Store

G = 1073741824


def at(day, hour=12):
    return time.mktime(datetime.datetime.strptime(day, "%Y-%m-%d").replace(hour=hour).timetuple())


class Daily(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name + "/panel.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def test_deltas_reboot_days_and_month(self):
        with self.store.connect() as db:
            daily.record(db, "a", {"network_rx": 100 * G, "network_tx": 10 * G}, at("2026-10-14"))   # first sample: baseline only
            daily.record(db, "a", {"network_rx": 101 * G, "network_tx": 12 * G}, at("2026-10-14", 13))
            daily.record(db, "a", {"network_rx": 1 * G, "network_tx": 1 * G}, at("2026-10-15", 1))   # reboot: counts the new value
            daily.record(db, "a", {"network_rx": 3 * G, "network_tx": 1 * G}, at("2026-10-15", 2))
            daily.record(db, "b", {"network_rx": 5 * G, "network_tx": 5 * G}, at("2026-10-15", 2))
            daily.record(db, "b", {"network_rx": 6 * G, "network_tx": 7 * G}, at("2026-10-15", 3))
            daily.record(db, "a", {"network_rx": 9 * G, "network_tx": 9 * G}, at("2026-09-30", 3))  # other month, ignored below
            daily.record(db, "a", {"network_rx": "x"}, at("2026-10-15", 4))                          # bad metrics ignored
            totals = daily.totals(db, at("2026-10-15", 20))
            self.assertEqual(totals["today"], {"rx": 3 * G + 1 * G, "tx": 1 * G + 2 * G})
            self.assertEqual(totals["month"], {"rx": 1 * G + 3 * G + 1 * G, "tx": 2 * G + 1 * G + 2 * G})
            daily.prune(db, at("2027-12-01"))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM traffic_daily").fetchone()[0], 0)

    def test_backfill_from_samples_once(self):
        path = self.tmp.name + "/old.sqlite"
        Store(path)
        store = Store(path)
        with store.connect() as db:
            db.execute("DELETE FROM settings WHERE key='traffic_daily_backfilled'")
            db.execute("DELETE FROM traffic_last")
            now = int(time.time() // 60)
            for i, rx in enumerate((10 * G, 11 * G, 13 * G)):
                db.execute("INSERT INTO samples VALUES(?,?,?)", ("n", now - 2 + i, json.dumps({"network_rx": rx, "network_tx": 0})))
        Store(path)                                   # startup backfills
        Store(path)                                   # and only once
        with store.connect() as db:
            self.assertEqual(db.execute("SELECT SUM(rx) FROM traffic_daily").fetchone()[0], 3 * G)


class SummaryAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'DATABASE': self.tmp.name + '/panel.sqlite', 'PUBLIC_URL': 'https://p.example.com'})
        self.store = self.app.extensions['store']
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('password',?)", (generate_password_hash('a-long-test-password', method='pbkdf2:sha256:1000'),))
            platform_users.create_user(db, {'name': 'alice'})
            platform_users.create_user(db, {'name': 'bob'})
            daily.record(db, "n", {"network_rx": 0, "network_tx": 0})
            daily.record(db, "n", {"network_rx": 2 * G, "network_tx": G})
        self.client = self.app.test_client()
        self.client.post('/api/login', json={'username': 'admin', 'password': 'a-long-test-password'})

    def tearDown(self):
        self.tmp.cleanup()

    def test_summary(self):
        r = self.client.get('/api/summary').json
        self.assertEqual((r['users'], r['relays'], r['today'], r['month']), (2, 0, {'rx': 2 * G, 'tx': G}, {'rx': 2 * G, 'tx': G}))
        self.assertEqual(self.app.test_client().get('/api/summary').status_code, 401)


if __name__ == '__main__':
    unittest.main()
