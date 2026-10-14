"""中转线路：创建校验、各层转发任务与结果回写、用户关联落地协议、重试、删除、导出经中转的连接。"""
import json
import sqlite3
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from vaio import relays
from vaio.server import create_app
from test_platform_users_panel import SimNode


class RelayNode(SimNode):
    """SimNode that also executes forward_apply like the script (rule ids, snapshot forwards) and reports a public address."""

    def __init__(self, test, name, ip, forward_version=1):
        self.forward_version, self.ip, self.forwards, self.fail_forward = forward_version, ip, [], False
        super().__init__(test, name)

    def snapshot(self):
        return {**super().snapshot(), "forward_version": self.forward_version, "forwards": self.forwards, "addresses": {"ipv4": self.ip} if self.ip else {}}

    def poll(self, run=True):
        reply = self.test.client.post('/api/agent/' + self.id + '/poll', json={"snapshot": self.snapshot(), "ready": True}, headers=self.auth).json
        task = reply.get('task') if reply else None
        if not task or not run:
            return task
        self.tasks.append(task)
        result = {}
        if task["action"] == "forward_apply":
            op = task["params"]["ops"][0]
            if self.fail_forward:
                status, message = "failed", "端口被占用"
            elif op["op"] == "add":
                rule = {**op["rule"], "id": "nft-%d" % op["rule"]["listen_port"] if op["rule"]["backend"] == "nftables" else "%012x" % (len(self.forwards) + 1)}
                self.forwards.append({**rule, "status": "running", "bytes": 0})
                status, message, result = "succeeded", "ok", {"rule": {"id": rule["id"]}, "steps": []}
            else:
                self.forwards = [r for r in self.forwards if r["id"] != op["id"]]
                status, message, result = "succeeded", "ok", {"rule": None, "steps": []}
        elif task["action"] == "share":
            status, message, result = "succeeded", "ok", {"connection": "vless://x@%s:%d" % (task["params"]["host"], task["params"]["port"])}
        else:
            status, message = self.execute(task)
        self.test.client.post('/api/agent/' + self.id + '/tasks/' + task['id'] + '/result',
                              json={"status": status, "message": message, "result": result}, headers=self.auth)
        return task


class Relays(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE": self.tmp.name + "/panel.sqlite"})
        self.store = self.app.extensions["store"]
        with self.store.connect() as db:
            db.execute("INSERT INTO settings VALUES('password',?)", (generate_password_hash("a-long-test-password", method="pbkdf2:sha256:1000"),))
        self.client = self.app.test_client()
        self.headers = {"X-CSRF-Token": self.client.post('/api/login', json={"username": "admin", "password": "a-long-test-password"}).json['csrf']}
        self.user = self.client.post('/api/users', json={"name": "alice"}, headers=self.headers).json['id']

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, path, data, status):
        r = self.client.post('/api' + path, json=data, headers=self.headers)
        self.assertEqual(r.status_code, status, r.json)
        return r.json

    def lines(self):
        return self.client.get('/api/relays').json['relays']

    def body(self, hops, landing, **landing_extra):
        return {"user_id": self.user, "hops": hops, "landing": {"node_id": landing.id, "core": "singbox", "protocol": "hy2", "port": 8443,
                                                                  "host": landing.ip, **landing_extra}}

    def test_two_hop_line_lifecycle(self):
        a, b, land = RelayNode(self, 'A', '9.9.9.1'), RelayNode(self, 'B', '9.9.9.2'), RelayNode(self, 'L', '8.8.4.9')
        for node in (a, b, land):
            node.poll(run=False)
        hops = [{"node_id": a.id, "backend": "realm", "listen_port": 30001}, {"node_id": b.id, "backend": "nftables", "listen_port": 30002}]
        line_id = self.post('/relays', self.body(hops, land), 201)['id']
        line = self.lines()[0]
        self.assertEqual((line['state'], line['entry'], line['user_name']), ('creating', {"host": "9.9.9.1", "port": 30001}, 'alice'))
        self.assertEqual([h['target'] for h in line['hops']], ['9.9.9.2:30002', '8.8.4.9:8443'])
        self.assertEqual([h['transport'] for h in line['hops']], ['udp', 'tcp+udp'])           # hy2 → UDP on Realm; nftables always TCP+UDP
        task = a.poll()
        self.assertTrue(task['params']['ops'][0]['rule']['remark'].startswith('中转：alice → L'))
        b.poll()
        land.settle()                                                                       # landing link for the user (hy2 member)
        line = self.lines()[0]
        self.assertEqual((line['state'], [h['forward_id'] for h in line['hops']]), ('active', ['000000000001', 'nft-30002']))
        user = self.client.get('/api/users/' + self.user).json['user']
        self.assertEqual(user['links'][0]['node_id'], land.id)
        share = self.post('/relays/%s/share' % line_id, {}, 201)['id']
        task = land.poll()
        self.assertEqual((task['id'], task['action'], task['params']), (share, 'share', {"name": "alice", "host": "9.9.9.1", "port": 30001}))
        # Delete: each hop's rule is removed, then the line.
        self.post('/relays/%s/delete' % line_id, {}, 200)
        self.assertEqual(self.lines()[0]['state'], 'removing')
        a.poll(); b.poll()
        self.assertEqual(self.lines(), [])
        self.assertEqual((a.forwards, b.forwards), ([], []))

    def test_validation(self):
        a, land = RelayNode(self, 'A', '9.9.9.1'), RelayNode(self, 'L', '8.8.4.9')
        old, quiet = RelayNode(self, 'O', '9.9.9.3', forward_version=0), RelayNode(self, 'Q', '')
        for node in (a, land, old, quiet):
            node.poll(run=False)
        hop = {"node_id": a.id, "backend": "realm", "listen_port": 30001}
        cases = [
            (self.body([hop, dict(hop)], land), "不能重复"),
            (self.body([{**hop, "node_id": land.id}], land), "不能重复"),
            (self.body([{**hop, "node_id": old.id}], land), "升级"),
            (self.body([{**hop, "listen_port": 443}], land), "已被"),                       # proxy instance port on the relay
            (self.body([hop], land, port=9), "不存在"),
            (self.body([hop], land, host="bad host"), "IP 地址或域名"),
            (self.body([{**hop, "backend": "nftables"}], land, host="land.example.com"), "IPv4"),
            (self.body([hop, {"node_id": quiet.id, "backend": "realm", "listen_port": 30002}], land), None),  # quiet is the 2nd hop: fine
            (self.body([{"node_id": quiet.id, "backend": "realm", "listen_port": 30002}, hop], land), "公网 IP"),
            ({**self.body([hop], land), "user_id": "nobody"}, "用户不存在"),
            ({**self.body([hop], land), "user_id": None}, "请选择用户"),                       # a protocol landing needs a user
            ({"user_id": None, "hops": [hop], "landing": {"node_id": land.id, "port": 70000, "host": "8.8.4.9", "transport": "tcp"}}, "落地端口"),
            ({"user_id": None, "hops": [hop], "landing": {"node_id": land.id, "port": 9000, "host": "8.8.4.9", "transport": "sctp"}}, "转发协议"),
            (self.body([], land), "1–5"),
        ]
        for data, message in cases:
            if message is None:
                continue
            r = self.client.post('/api/relays', json=data, headers=self.headers)
            self.assertEqual(r.status_code, 400, (data, r.json))
            self.assertIn(message, r.json['error'])
        self.assertEqual(self.lines(), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM tasks WHERE action='forward_apply'").fetchone()[0], 0)  # nothing half-created

    def test_failed_hop_retry_and_busy_nodes(self):
        a, land = RelayNode(self, 'A', '9.9.9.1'), RelayNode(self, 'L', '8.8.4.9')
        a.poll(run=False); land.poll(run=False)
        hop = {"node_id": a.id, "backend": "realm", "listen_port": 30001}
        line_id = self.post('/relays', self.body([hop], land), 201)['id']
        self.post('/relays', self.body([{**hop, "listen_port": 30005}], land), 400)        # A already has an unfinished task
        self.post('/relays/%s/delete' % line_id, {}, 400)                                  # still creating
        a.fail_forward = True
        a.poll()
        self.assertEqual(self.lines()[0]['state'], 'partial')
        self.post('/relays/%s/share' % line_id, {}, 400)
        a.fail_forward = False
        self.post('/relays/%s/retry' % line_id, {}, 200)
        a.poll()
        self.assertEqual(self.lines()[0]['state'], 'active')
        self.post('/relays/%s/retry' % line_id, {}, 400)                                   # nothing failed any more
        # A rule already deleted on the node (script menu): the node answers "no such rule", which counts as removed.
        a.forwards = []
        a.poll(run=False)
        self.post('/relays/%s/delete' % line_id, {}, 200)
        a.fail_forward = True
        task = a.poll(run=False)
        self.client.post('/api/agent/%s/tasks/%s/result' % (a.id, task['id']), json={"status": "failed", "message": "转发规则在节点上已不存在，请刷新后重试", "result": {}}, headers=a.auth)
        self.assertEqual(self.lines(), [])

    def test_port_only_line(self):
        a, land = RelayNode(self, 'A', '9.9.9.1'), RelayNode(self, 'L', '8.8.4.9')
        a.poll(run=False); land.poll(run=False)
        body = {"user_id": None, "hops": [{"node_id": a.id, "backend": "realm", "listen_port": 9000}],
                "landing": {"node_id": land.id, "port": 9000, "host": "8.8.4.9", "transport": "tcp"}}
        line_id = self.post('/relays', body, 201)['id']
        task = a.poll()
        rule = task['params']['ops'][0]['rule']
        self.assertEqual((rule['remote_host'], rule['remote_port'], rule['transport'], rule['remark']), ('8.8.4.9', 9000, 'tcp', '中转：端口 → L'))
        line = self.lines()[0]
        self.assertEqual((line['state'], line['port_only'], line['user_name'], line['landing']['protocol']), ('active', True, '', ''))
        self.assertIsNone(land.poll(run=False))                                             # no user link, nothing on the landing node
        self.assertIn('无法导出', self.post('/relays/%s/share' % line_id, {}, 400)['error'])
        # With a user it is only ownership: still no link on the landing node.
        body = {**body, "user_id": self.user, "hops": [{"node_id": a.id, "backend": "nftables", "listen_port": 9001}], "landing": {**body["landing"], "transport": "udp"}}
        self.post('/relays', body, 201)
        self.assertEqual(a.poll()['params']['ops'][0]['rule']['transport'], 'tcp+udp')     # nftables is always TCP+UDP
        self.assertEqual(self.client.get('/api/users/' + self.user).json['user']['links'], [])
        self.assertEqual(sorted(l['user_name'] for l in self.lines()), ['', 'alice'])

    def test_migrates_not_null_user_column(self):
        path = self.tmp.name + '/old.sqlite'
        from vaio.store import Store
        Store(path)
        def legacy(extra=""):
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA foreign_keys=OFF")
                db.execute("DROP TABLE IF EXISTS relay_lines")
                db.execute(relays.SCHEMA.replace("user_id TEXT REFERENCES", "user_id TEXT NOT NULL REFERENCES"))
                db.execute("INSERT OR IGNORE INTO platform_users(id,name,created,updated) VALUES('u','alice',0,0)")
                db.execute("INSERT INTO relay_lines VALUES('l1','u','n','xray','vless',443,'1.1.1.1','[]',0,0,0)")
                if extra:
                    db.executescript(extra)
        def check():
            with sqlite3.connect(path) as db:
                self.assertEqual([r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'relay%'")], ['relay_lines'])
                self.assertEqual(db.execute("SELECT id, user_id FROM relay_lines").fetchall(), [('l1', 'u')])
                self.assertEqual([r[3] for r in db.execute("PRAGMA table_info(relay_lines)") if r[1] == "user_id"], [0])
        legacy()
        Store(path)          # the panel starts: migration copies the rows and leaves no transaction open
        check()
        # The 0.3.0-preview.26 failure: renamed and recreated, copy rolled back. The next start recovers the rows.
        legacy("ALTER TABLE relay_lines RENAME TO relay_lines_old;" + relays.SCHEMA)
        Store(path)
        check()

    def test_transport_mapping(self):
        self.assertEqual([relays.transport_for(p) for p in ("hy2", "tuic", "ss2022", "snell-v5", "vless", "trojan")],
                         ["udp", "udp", "tcp+udp", "tcp+udp", "tcp", "tcp"])
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/api/relays').status_code, 401)
        self.assertEqual(self.client.post('/api/relays', json={}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
