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

    def __init__(self, test, name, version=1, authority='platform', adopt=True):
        self.test, self.version, self.accounts, self.clock, self.authority = test, version, {}, 1760000000, authority
        # A script-mode node in these tests was adopted by an older panel/agent (no automatic switch), then upgraded.
        self.authority_version = 0 if authority == 'script' else version
        self.protocol_users = {('xray', 'vless', 443): {}, ('singbox', 'hy2', 8443): {}}
        if authority == 'script':
            # A script-managed node keeps script users; without any the panel switches it automatically.
            self.protocol_users[('xray', 'vless', 443)]['old'] = {"used": 1}
        result = test.client.post('/api/nodes', json={"name": name}, headers=test.headers)
        self.id = result.json['node_id']
        script = result.json['script']
        enrollment = json.loads(script.split("<<'VAIO_ENROLLMENT'\n")[1].split('\nVAIO_ENROLLMENT')[0])
        token = test.client.post('/api/enroll', json=enrollment).json['token']
        self.auth = {"Authorization": "Bearer " + token}
        self.poll()
        if adopt:
            test.client.post('/api/nodes/' + self.id + '/adopt', json={"revision": "a" * 64}, headers=test.headers)
        self.authority_version = version
        self.tasks = []
        if adopt:
            self.poll(run=False)

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
        return {"revision": "a" * 64, "instances": instances, "metrics": {}, "accounts_version": self.version, "accounts": accounts,
                "authority_version": self.authority_version, "user_authority": self.authority, "upgrade_version": self.version, "agent_version": "0.3.0-preview.11"}

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
        if task["action"] == "agent_upgrade":
            return "succeeded", "已启动升级"
        if task["action"] in ("install", "share"):
            if task["action"] == "install":
                self.protocol_users[(task["core"], task["protocol"], task["port"])] = {}
            return "succeeded", "操作完成"
        if task["params"]["ops"][0]["op"] == "set_authority":
            self.authority = task["params"]["ops"][0]["mode"]
            if self.authority == "platform":
                self.accounts = {}
                for users in self.protocol_users.values():
                    users.clear()
            return "succeeded", "操作完成"
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
            elif kind == "member_add":
                t = op["target"]
                self.protocol_users[(t["core"], t["protocol"], t["port"])][op["name"]] = {"used": 0, "account_id": identity}
                account["members"].append({**t, "name": op["name"]})
            elif kind in ("reset_credentials", "member_remove", "reset_usage"):
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

    def test_panel_is_the_only_writer_on_platform_nodes(self):
        user, a, b = self.linked_pair()
        identity, account = self.account(a)
        account["expire_date"] = "2000-01-01"; a.touch(account, "expire_date")
        a.settle(); b.settle()
        self.assertEqual((self.user(user)["expire_date"], account["expire_date"], self.account(b)[1]["expire_date"]),
                         ("2099-01-01", "2099-01-01", "2099-01-01"))
        self.assertEqual(a.tasks[-1]["params"]["ops"][0]["fields"], {"expire_date": "2099-01-01"})

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

    def test_expiry_by_panel_clock_blocks_every_node(self):
        # Nodes judge expire_date by their own date (and some ports only daily); the panel's own verdict is pushed as a block.
        user, a, b = self.linked_pair()
        with self.store.connect() as db:
            db.execute("UPDATE platform_users SET expire_date=? WHERE id=?", ((datetime.date.today() - datetime.timedelta(days=1)).isoformat(), user))
        a.settle(); b.settle(); a.settle(); b.settle()
        self.assertEqual(self.user(user)["state"], "expired")
        self.assertEqual((self.account(a)[1].get("platform_block"), self.account(b)[1].get("platform_block")), ("quota", "quota"))
        with self.store.connect() as db:
            db.execute("UPDATE platform_users SET expire_date='2099-01-01' WHERE id=?", (user,))
        a.settle(); b.settle(); a.settle(); b.settle()
        self.assertEqual((self.account(a)[1]["platform_block"], self.account(b)[1]["platform_block"]), ("", ""))

    def test_adopted_script_nodes_switch_automatically_when_empty(self):
        node = SimNode(self, 'E', authority='script')        # adopted before switching existed; has a script user
        self.assertIsNone(node.poll(run=False))              # users present: wait for the operator
        node.protocol_users[('xray', 'vless', 443)].clear()
        task = node.poll(run=False)
        self.assertEqual(task['params']['ops'], [{"op": "set_authority", "mode": "platform"}])
        self.client.post('/api/agent/%s/tasks/%s/result' % (node.id, task['id']), json={"status": "failed", "message": "boom", "result": {}}, headers=node.auth)
        self.assertIsNone(node.poll(run=False))              # failed automatic switch: no tight retry loop
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET created=created-3700 WHERE request_key LIKE 'auto-authority:%'")
        node.settle()
        self.assertEqual(node.authority, 'platform')
        self.assertIsNone(node.poll(run=False))              # already platform: nothing more
        with self.store.connect() as db:
            audit = [r[0] for r in db.execute("SELECT detail FROM audit WHERE detail LIKE '%自动切到平台管理%'")]
        self.assertEqual(len(audit), 2)
        old = SimNode(self, 'O', authority='script')
        old.protocol_users[('xray', 'vless', 443)].clear()
        old.authority_version = 0
        self.assertIsNone(old.poll(run=False))               # old agent cannot switch
        with self.store.connect() as db:
            db.execute("UPDATE nodes SET maintenance=1 WHERE id=?", (old.id,))
            self.assertEqual(platform_users.auto_authority(db), [])

    def test_adopt_switches_to_platform(self):
        node = SimNode(self, 'A', authority='script', adopt=False)
        node.authority_version = 1
        node.protocol_users[('xray', 'vless', 443)]['old'] = {"used": 1}
        node.poll()
        r = self.client.post('/api/nodes/' + node.id + '/adopt', json={"revision": "a" * 64}, headers=self.headers)
        self.assertEqual(r.status_code, 409)
        self.assertIn('1 个脚本用户', r.json['error'])
        self.assertEqual(self.client.get('/api/nodes').json['nodes'][-1]['adopted'], False)
        r = self.client.post('/api/nodes/' + node.id + '/adopt', json={"revision": "a" * 64, "clear_users": True}, headers=self.headers)
        self.assertEqual((r.status_code, r.json['authority']), (200, 'switching'))
        node.settle()
        self.assertEqual((node.authority, node.protocol_users[('xray', 'vless', 443)]), ('platform', {}))
        self.assertEqual(node.tasks[0]['params']['ops'], [{"op": "set_authority", "mode": "platform"}])
        # Already platform: nothing queued. Old agent: adopt only.
        same = SimNode(self, 'B', adopt=False)
        r = self.client.post('/api/nodes/' + same.id + '/adopt', json={"revision": "a" * 64}, headers=self.headers)
        self.assertEqual(r.json['authority'], 'platform')
        self.assertIsNone(same.poll())
        old = SimNode(self, 'C', authority='script', adopt=False)
        old.authority_version = 0
        old.poll()
        r = self.client.post('/api/nodes/' + old.id + '/adopt', json={"revision": "a" * 64}, headers=self.headers)
        self.assertEqual(r.json['authority'], 'unsupported')
        self.assertIsNone(old.poll())
        self.assertEqual(self.client.post('/api/nodes/' + old.id + '/adopt', json={"revision": "a" * 64, "x": 1}, headers=self.headers).status_code, 400)

    def test_authority_switch_requires_confirmation_and_releases_links(self):
        node = SimNode(self, 'N', authority='script')
        node.protocol_users[('xray', 'vless', 443)]['old'] = {"used": 1}
        user = self.post('/users', {"name": "alice"}, 201)['id']
        self.post('/users/' + user + '/links', {"node_id": node.id, "members": []}, 400)
        self.post('/nodes/' + node.id + '/authority', {"mode": "platform", "confirm": "wrong"}, 409)
        self.post('/nodes/' + node.id + '/authority', {"mode": "platform", "confirm": "N"}, 201)
        self.post('/nodes/' + node.id + '/authority', {"mode": "platform", "confirm": "N"}, 409)
        node.settle()
        self.assertEqual((node.authority, node.protocol_users[('xray', 'vless', 443)]), ('platform', {}))
        self.post('/users/' + user + '/links', {"node_id": node.id, "members": [{"core": "xray", "protocol": "vless", "port": 443}]})
        node.settle()
        self.assertEqual(len(node.accounts), 1)
        # Switching back from the panel removes the links; the platform user stays.
        self.post('/nodes/' + node.id + '/authority', {"mode": "script"}, 201)
        node.settle()
        self.assertEqual((node.authority, self.user(user)["links"]), ('script', []))
        # Switching back from the node's own menu is noticed from the snapshot.
        self.post('/nodes/' + node.id + '/authority', {"mode": "platform", "confirm": "N"}, 201)
        node.settle()
        self.post('/users/' + user + '/links', {"node_id": node.id, "members": []})
        node.authority = 'script'
        node.poll()
        self.assertEqual(self.user(user)["links"], [])

    def test_user_tasks_follow_authority_and_upgrade_task(self):
        node = SimNode(self, 'N', authority='script')
        task = {"action": "user_update", "protocol": "vless", "core": "xray", "port": 443, "params": {"name": "x", "enabled": False}, "revision": "a" * 64}
        response = self.client.post('/api/nodes/' + node.id + '/tasks', json=task, headers={**self.headers, "Idempotency-Key": "k1"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("节点脚本管理", response.json["error"])
        old = SimNode(self, 'old', version=0)
        self.post('/nodes/' + old.id + '/upgrade', {}, 409)
        self.post('/nodes/' + old.id + '/authority', {"mode": "platform", "confirm": "old"}, 409)
        queued = self.post('/nodes/' + node.id + '/upgrade', {}, 201)
        self.post('/nodes/' + node.id + '/upgrade', {}, 409)
        self.assertEqual(node.poll()["action"], "agent_upgrade")
        tasks = {t["id"]: t for t in self.client.get('/api/tasks').json["tasks"]}
        self.assertEqual((tasks[queued["id"]]["status"], tasks[queued["id"]]["request"]), ("succeeded", {"action": "agent_upgrade", "params": {}}))
        self.post('/nodes/' + node.id + '/upgrade', {"url": "https://evil"}, 400)

    def test_offline_and_old_nodes(self):
        old = SimNode(self, 'old', version=0)
        user = self.post('/users', {"name": "carol"}, 201)['id']
        self.post('/users/' + user + '/links', {"node_id": old.id, "members": []}, 400)
        self.post('/users/' + user + '/links', {"node_id": SimNode(self, 'S', authority='script').id, "members": []}, 400)
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
        self.assertEqual((account["note"], account["expire_date"], self.user(user)["expire_date"]), ("panel", "2099-01-01", "2099-01-01"))

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


class ProtocolUserModes(PlatformUsersPanel):
    def mode_node(self):
        node = SimNode(self, 'M')
        node.protocol_users[('xray', 'vless-ws', 2083)] = {}
        node.protocol_users[('xray', 'snell-v5', 9001)] = {}
        node.protocol_users[('xray', 'snell-v5', 9002)] = {'busy': {"used": 0}}
        node.protocol_users[('xray', 'naive', 443)] = {}
        original = node.snapshot
        modes = {'vless-ws': ('multi', True), 'snell-v5': ('single', True), 'naive': ('none', False),
                 'vless': ('multi', True), 'hy2': ('multi', True)}
        def snapshot():
            data = original()
            for item in data['instances']:
                item['user_mode'], item['user_available'] = modes[item['protocol']]
            data['share_version'] = 2
            data['config_details_version'] = 2
            return data
        node.snapshot = snapshot
        node.poll()
        return node

    def test_member_targets_follow_user_modes(self):
        node = self.mode_node()
        user = self.post('/users', {"name": "alice"}, 201)['id']
        self.post('/users/' + user + '/links', {"node_id": node.id, "members": [{"core": "xray", "protocol": "naive", "port": 443}]}, 400)
        self.post('/users/' + user + '/links', {"node_id": node.id, "members": [{"core": "xray", "protocol": "snell-v5", "port": 9002}]}, 400)
        self.post('/users/' + user + '/links', {"node_id": node.id, "members": [{"core": "xray", "protocol": "vless-ws", "port": 2083},
                                                                                 {"core": "xray", "protocol": "snell-v5", "port": 9001}]})
        node.settle()
        account = next(iter(node.accounts.values()))
        self.assertEqual(sorted(m["protocol"] for m in account["members"]), ["snell-v5", "vless-ws"])
        link = self.user(user)["links"][0]["id"]
        self.post('/links/' + link + '/members', {"action": "add", "target": {"core": "xray", "protocol": "naive", "port": 443}}, 400)
        self.post('/links/' + link + '/members', {"action": "add", "target": {"core": "xray", "protocol": "snell-v5", "port": 9002}}, 400)

    def test_install_plan_places_selected_users(self):
        node = self.mode_node()
        alice = self.post('/users', {"name": "alice"}, 201)['id']
        bob = self.post('/users', {"name": "bob"}, 201)['id']
        self.post('/users/' + alice + '/links', {"node_id": node.id, "members": []})
        node.settle()
        task = {"action": "install", "protocol": "hy2", "core": "singbox", "port": 8443, "params": {"sni": "a.example"}, "revision": "a" * 64}
        created = self.client.post('/api/nodes/' + node.id + '/tasks', json=task, headers={**self.headers, "Idempotency-Key": "i1"})
        self.assertEqual(created.status_code, 201, created.json)
        task_id = created.json["id"]
        self.post('/nodes/' + node.id + '/install-users', {"task_id": task_id, "user_ids": [alice, bob]})
        self.post('/nodes/' + node.id + '/install-users', {"task_id": task_id, "user_ids": ["missing"]}, 400)
        node.settle()   # install succeeds, then the plan becomes member operations
        names = sorted(a["name"] for a in node.accounts.values())
        self.assertEqual(names, ["alice", "bob"])
        self.assertTrue(all(any(m["protocol"] == "hy2" for m in a["members"]) for a in node.accounts.values()))
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM platform_install_plans").fetchone())
        task = {**task, "protocol": "snell-v5", "core": "xray", "port": 9100, "params": {}}
        created = self.client.post('/api/nodes/' + node.id + '/tasks', json=task, headers={**self.headers, "Idempotency-Key": "i2"})
        self.post('/nodes/' + node.id + '/install-users', {"task_id": created.json["id"], "user_ids": [alice, bob]}, 400)
        script = SimNode(self, 'S', authority='script')
        task = {**task, "port": 9200}
        created = self.client.post('/api/nodes/' + script.id + '/tasks', json=task, headers={**self.headers, "Idempotency-Key": "i3"})
        self.post('/nodes/' + script.id + '/install-users', {"task_id": created.json["id"], "user_ids": [alice]}, 400)

    def test_share_works_for_protocols_outside_adapters(self):
        node = self.mode_node()
        share = {"action": "share", "protocol": "vless-ws", "core": "xray", "port": 2083, "params": {"name": "alice"}}
        response = self.client.post('/api/nodes/' + node.id + '/tasks', json=share, headers={**self.headers, "Idempotency-Key": "s1"})
        self.assertEqual(response.status_code, 201, response.json)
        old = SimNode(self, 'O', version=0)
        response = self.client.post('/api/nodes/' + old.id + '/tasks', json=share, headers={**self.headers, "Idempotency-Key": "s2"})
        self.assertEqual(response.status_code, 409)


if __name__ == '__main__':
    unittest.main()
