import datetime
import json
import sqlite3
import tempfile
import time
import unittest
import uuid

from werkzeug.security import generate_password_hash
from vaio import backups, monitor, platform_users
from vaio.server import create_app
from vaio.store import Store

GIB = 1073741824


class SimNode:
    """A node that executes platform_apply like the script's account_apply."""

    def __init__(self, test, name, version=1):
        self.test, self.version, self.accounts, self.clock = test, version, {}, 1760000000
        self.protocol_users = {('xray', 'vless', 443): {}, ('singbox', 'hy2', 8443): {}}
        result = test.client.post('/api/nodes', json={"name": name}, headers=test.headers)
        self.id = result.json['node_id']
        script = result.json['script']
        enrollment = json.loads(script.split("<<'VAIO_ENROLLMENT'\n")[1].split('\nVAIO_ENROLLMENT')[0])
        token = test.client.post('/api/enroll', json=enrollment).json['token']
        self.auth = {"Authorization": "Bearer " + token}
        self.poll()
        test.client.post('/api/nodes/' + self.id + '/adopt', json={"revision": "a" * 64}, headers=test.headers)
        self.tasks = []

    def snapshot(self):
        instances = [{"core": c, "protocol": p, "port": port, "service": "s", "status": "running", "traffic_state": "ready",
                      "users": [{"name": n, "enabled": u.get("enabled", True), "used": u["used"], "account_id": u.get("account_id", "")}
                                for n, u in users.items()]} for (c, p, port), users in self.protocol_users.items()]
        accounts = {}
        for identity, a in self.accounts.items():
            members = []
            for m in a["members"]:
                u = self.protocol_users[(m["core"], m["protocol"], m["port"])].get(m["name"])
                members.append({**m, "used": u["used"] if u else None, "enabled": u.get("enabled", True) if u else None, "disable_reason": ""})
            accounts[identity] = {**{k: a[k] for k in ("name", "note", "enabled", "expire_date", "quota", "reset_day", "rev", "mtime")},
                                  "cycle": "", "cycle_used": 0, "platform_user_id": a.get("platform_user_id"),
                                  "platform_block": a.get("platform_block", ""), "state": "", "members": members}
        return {"revision": "a" * 64, "instances": instances, "metrics": {}, "accounts_version": self.version, "accounts": accounts}

    def poll(self, run=True):
        reply = self.test.client.post('/api/agent/' + self.id + '/poll', json={"snapshot": self.snapshot(), "ready": True}, headers=self.auth).json
        task = reply.get('task') if reply else None
        if task and run:
            self.tasks.append(task)
            status, message = self.execute(task)
            self.test.client.post('/api/agent/' + self.id + '/tasks/' + task['id'] + '/result',
                                  json={"status": status, "message": message, "result": {}}, headers=self.auth)
        return task

    def settle(self, rounds=4):
        for _ in range(rounds):
            self.poll()

    def touch(self, account, field):
        self.clock += 10
        account["rev"] += 1
        account["mtime"][field] = self.clock

    def execute(self, task):
        if getattr(self, 'outcome', None):
            outcome, self.outcome = self.outcome, None
            return outcome
        for op in task["params"]["ops"]:
            account = self.accounts.get(op["account_id"])
            if op["op"] == "update" and account["rev"] != op["base_rev"]:
                return "failed", "统一用户已在节点上修改，未写入；面板将按最新数据重新合并（节点版本 %d）" % account["rev"]
        for op in task["params"]["ops"]:
            identity, kind = op["account_id"], op["op"]
            account = self.accounts.get(identity)
            if kind == "create":
                fields = {"note": "", "enabled": True, "expire_date": "", "quota": 0, "reset_day": 0, **op["fields"]}
                self.accounts[identity] = account = {**fields, "rev": 1, "mtime": {k: self.clock for k in fields}, "members": [],
                                                     "platform_user_id": op.get("platform_user_id")}
                for member in op.get("members", []):
                    t = member["target"]
                    self.protocol_users[(t["core"], t["protocol"], t["port"])][member["name"]] = {"used": 0, "account_id": identity}
                    account["members"].append({**t, "name": member["name"]})
            elif kind == "update":
                for key, value in op["fields"].items():
                    account[key] = value
                    self.touch(account, key)
            elif kind == "link":
                account["platform_user_id"] = op["platform_user_id"]
            elif kind == "unlink":
                account.pop("platform_user_id", None)
                account["platform_block"] = ""
            elif kind == "block":
                account["platform_block"] = op["platform_block"]
            elif kind == "member_claim":
                t = op["target"]
                self.protocol_users[(t["core"], t["protocol"], t["port"])][op["name"]]["account_id"] = identity
                account["members"].append({**t, "name": op["name"]})
            elif kind == "delete":
                del self.accounts[identity]
            elif kind in ("reset_credentials", "member_add", "member_remove", "reset_usage"):
                pass
        return "succeeded", "操作完成"

    def use(self, identity, amount):
        m = self.accounts[identity]["members"][0]
        self.protocol_users[(m["core"], m["protocol"], m["port"])][m["name"]]["used"] += amount


class PlatformUsersPanel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE": self.tmp.name + "/panel.sqlite"})
        self.store = self.app.extensions["store"]
        with self.store.connect() as db:
            db.execute("INSERT INTO settings VALUES('password',?)", (generate_password_hash("a-long-test-password", method="pbkdf2:sha256:1000"),))
        self.client = self.app.test_client()
        self.headers = {"X-CSRF-Token": self.client.post('/api/login', json={"username": "admin", "password": "a-long-test-password"}).json['csrf']}

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, path, data, status=200):
        response = self.client.post('/api' + path, json=data, headers=self.headers)
        self.assertEqual(response.status_code, status, response.json)
        return response.json

    def user(self, identity):
        return self.client.get('/api/users/' + identity).json['user']

    def linked_pair(self, quota_gb=0):
        a, b = SimNode(self, 'A'), SimNode(self, 'B')
        user = self.post('/users', {"name": "alice", "quota_gb": quota_gb, "reset_day": 1, "expire_date": "2099-01-01"}, 201)['id']
        self.post('/users/' + user + '/links', {"node_id": a.id, "members": [{"core": "xray", "protocol": "vless", "port": 443}]})
        self.post('/users/' + user + '/links', {"node_id": b.id, "members": [{"core": "singbox", "protocol": "hy2", "port": 8443}]})
        a.settle(); b.settle()
        return user, a, b

    def account(self, node):
        self.assertEqual(len(node.accounts), 1)
        return next(iter(node.accounts.items()))

    def test_create_links_on_two_nodes_and_push_panel_edits(self):
        user, a, b = self.linked_pair()
        for node in (a, b):
            identity, account = self.account(node)
            self.assertEqual((account["name"], account["platform_user_id"], account["expire_date"]), ("alice", user, "2099-01-01"))
        self.assertEqual({l["sync"] for l in self.user(user)["links"]}, {"synced"})
        self.post('/users/' + user, {"expire_date": "2099-06-30", "note": "vip"})
        a.settle(); b.settle()
        for node in (a, b):
            self.assertEqual((self.account(node)[1]["expire_date"], self.account(node)[1]["note"]), ("2099-06-30", "vip"))
        self.assertEqual([op["op"] for op in a.tasks[-1]["params"]["ops"]], ["update"])

    def test_node_change_propagates_and_later_change_wins(self):
        user, a, b = self.linked_pair()
        identity, account = self.account(a)
        account["expire_date"] = "2099-03-01"; a.touch(account, "expire_date")
        a.settle(); b.settle()
        self.assertEqual(self.user(user)["expire_date"], "2099-03-01")
        self.assertEqual(self.account(b)[1]["expire_date"], "2099-03-01")
        # Both changed: the node's change is older than the panel's, so the panel wins.
        account["note"] = "node"; a.clock = 1000; a.touch(account, "note")
        self.post('/users/' + user, {"note": "panel"})
        a.settle(); b.settle()
        self.assertEqual((self.user(user)["note"], account["note"], self.account(b)[1]["note"]), ("panel", "panel", "panel"))
        self.assertIn("已按后改的一方合并", [l for l in self.user(user)["links"] if l["node_id"] == a.id][0]["notice"])
        # Both changed again, the node later this time: the node wins everywhere.
        self.post('/users/' + user, {"note": "panel2"})
        account["note"] = "node2"; a.clock = int(time.time()) + 1000; a.touch(account, "note")
        a.settle(); b.settle()
        self.assertEqual((self.user(user)["note"], self.account(b)[1]["note"]), ("node2", "node2"))

    def test_cross_node_quota_blocks_everywhere_and_cycle_restores(self):
        user, a, b = self.linked_pair(quota_gb=1)
        a.use(self.account(a)[0], 600 * 1048576); b.use(self.account(b)[0], 500 * 1048576)
        a.settle(); b.settle(); a.settle(); b.settle()
        self.assertEqual(self.user(user)["state"], "quota")
        self.assertEqual((self.account(a)[1].get("platform_block"), self.account(b)[1].get("platform_block")), ("quota", "quota"))
        future = time.mktime((datetime.date.today().replace(day=1) + datetime.timedelta(days=40)).replace(day=2).timetuple())
        with self.store.connect() as db:
            platform_users.rollover(db, future)
        a.settle(); b.settle()
        self.assertEqual(self.user(user)["used"], 0)
        self.assertEqual((self.account(a)[1]["platform_block"], self.account(b)[1]["platform_block"]), ("", ""))
        # A counter that drops (core restart) is counted once from the new value.
        a.protocol_users[('xray', 'vless', 443)]['alice']['used'] = 10
        a.settle()
        self.assertEqual(self.user(user)["used"], 10)

    def test_claim_existing_account_keeps_usage_and_preferred_side(self):
        node = SimNode(self, 'N')
        identity = str(uuid.uuid4())
        node.protocol_users[('xray', 'vless', 443)]['bob'] = {"used": 5 * GIB, "account_id": identity}
        node.accounts[identity] = {"name": "bob", "note": "", "enabled": True, "expire_date": "2098-01-01", "quota": 0, "reset_day": 0,
                                   "rev": 3, "mtime": {}, "members": [{"core": "xray", "protocol": "vless", "port": 443, "name": "bob"}]}
        node.poll()
        listing = self.client.get('/api/users').json
        self.assertEqual([u["account_id"] for u in listing["unlinked"]], [identity])
        user = self.post('/users', {"name": "bob", "expire_date": "2099-01-01"}, 201)['id']
        self.post('/users/' + user + '/links', {"node_id": node.id, "account_id": identity, "prefer": "node"})
        node.settle()
        detail = self.user(user)
        self.assertEqual((detail["expire_date"], detail["used"]), ("2098-01-01", 5 * GIB))
        self.assertEqual(node.accounts[identity]["platform_user_id"], user)
        self.assertEqual(self.client.get('/api/users').json["unlinked"], [])

    def test_offline_and_old_nodes(self):
        old = SimNode(self, 'old', version=0)
        user = self.post('/users', {"name": "carol"}, 201)['id']
        self.post('/users/' + user + '/links', {"node_id": old.id, "members": []}, 400)
        node = SimNode(self, 'N')
        with self.store.connect() as db:
            db.execute("UPDATE nodes SET last_seen=? WHERE id=?", (time.time() - 600, node.id))
        self.post('/users/' + user + '/links', {"node_id": node.id, "members": [{"core": "xray", "protocol": "vless", "port": 443}]})
        with self.store.connect() as db:
            platform_users.schedule(db)
            self.assertIsNone(db.execute("SELECT 1 FROM tasks WHERE node_id=?", (node.id,)).fetchone())
        self.assertEqual(self.user(user)["links"][0]["sync"], "offline")
        node.settle()
        self.assertEqual(len(node.accounts), 1)

    def test_identical_plan_queued_once_and_single_user_protocols_refused(self):
        user, a, b = self.linked_pair()
        self.post('/users/' + user, {"note": "x"})
        with self.store.connect() as db:
            platform_users.schedule(db); platform_users.schedule(db)
            count = db.execute("SELECT count(*) FROM tasks WHERE node_id=? AND status='queued'", (a.id,)).fetchone()[0]
        self.assertEqual(count, 1)
        link = self.user(user)["links"][0]["id"]
        self.post('/links/' + link + '/members', {"action": "add", "target": {"core": "singbox", "protocol": "ss2022", "port": 9}}, 400)
        self.post('/users/' + user + '/links', {"node_id": SimNode(self, 'C').id, "members": [{"core": "xray", "protocol": "snell-v5", "port": 9}]}, 400)

    def test_failed_and_unknown_outcomes(self):
        user, a, b = self.linked_pair()
        self.post('/users/' + user + '/reset-credentials', {})
        a.outcome = ("failed", "统一用户应用失败，节点已回滚")
        a.poll()
        link = [l for l in self.user(user)["links"] if l["node_id"] == a.id][0]
        self.assertEqual(link["sync"], "failed")
        self.assertIn("同步失败", link["notice"])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM platform_pending WHERE link_id=?", (link["id"],)).fetchone()[0], 0)
        self.post('/users/' + user, {"note": "after"})
        b.outcome = ("unknown", "结果未确认")
        b.poll()
        before = len(b.tasks)
        b.settle()
        self.assertEqual(len(b.tasks), before)
        task = b.tasks[-1]["id"]
        self.post('/tasks/' + task + '/resolve', {"note": "已在节点核对"})
        b.settle()
        self.assertEqual(self.account(b)[1]["note"], "after")

    def test_version_conflict_is_remerged(self):
        user, a, b = self.linked_pair()
        identity, account = self.account(a)
        self.post('/users/' + user, {"note": "panel"})
        account["expire_date"] = "2099-09-09"; a.touch(account, "expire_date")
        with self.store.connect() as db:
            platform_users.schedule(db)
        a.poll()   # executes the stale update -> rev_conflict, retried on the next poll
        self.assertIn("节点版本", [t for t in self.client.get('/api/tasks').json['tasks'] if t['id'] == a.tasks[-1]['id']][0]['message'])
        a.settle(); b.settle()
        self.assertEqual((account["note"], self.user(user)["expire_date"], self.account(b)[1]["expire_date"]), ("panel", "2099-09-09", "2099-09-09"))

    def test_remove_links_then_delete_user(self):
        user, a, b = self.linked_pair()
        self.post('/users/' + user + '/delete', {"mode": "release"})
        a.settle(); b.settle()
        self.assertEqual(self.client.get('/api/users/' + user).status_code, 404)
        self.assertNotIn("platform_user_id", self.account(a)[1])
        user2 = self.post('/users', {"name": "dave"}, 201)['id']
        self.assertTrue(self.post('/users/' + user2 + '/delete', {"mode": "release"})["deleted"])

    def test_alerts_follow_platform_users(self):
        user, a, b = self.linked_pair(quota_gb=1)
        a.use(self.account(a)[0], 2 * GIB)
        a.settle()
        monitor.scan(self.store)
        with self.store.connect() as db:
            keys = {r["key"] for r in db.execute("SELECT key FROM incidents WHERE active=1")}
        self.assertIn("puser-over:" + user, keys)
        self.assertFalse([k for k in keys if k.startswith("overquota:")])

    def test_auth_validation_and_migration(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/api/users').status_code, 401)
        self.assertEqual(self.client.post('/api/users', json={"name": "x"}).status_code, 403)
        for bad in ({"name": "bad name"}, {"name": "x", "quota_gb": -1}, {"name": "x", "reset_day": 29}, {"name": "x", "expire_date": "2099-13-01"}, {"name": "x", "password": "y"}):
            self.post('/users', bad, 400)
        self.post('/users', {"name": "Erin"}, 201)
        self.post('/users', {"name": "erin"}, 400)
        path = self.tmp.name + "/old.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("PRAGMA user_version=1")
        Store(path)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name='platform_links'").fetchone())
        backups.verify(backups.directory(self.store) / backups.create(self.store))


if __name__ == '__main__':
    unittest.main()
