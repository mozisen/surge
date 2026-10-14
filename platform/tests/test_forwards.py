"""端口转发：共享校验、面板接口（快照作为修改基准、冲突预检、旧节点）、节点程序执行与快照清洗。"""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from agent.__main__ import Agent
from agent.bridge import Bridge, TransactionRolledBack, TransactionUnknown
from agent.inventory import sanitize_snapshot
from agent.runtime import atomic_write
from agent.script_api import ScriptAPI
from vaio.common import sanitize_forwards, validate_forward_rule, validate_forward_task
from vaio.server import create_app
from test_agent import FakeRuntime
from test_platform_users_panel import SimNode

REALM = {"backend": "realm", "remark": "web", "transport": "tcp", "listen_host": "0.0.0.0", "listen_port": 20000,
         "remote_host": "example.com", "remote_port": 80, "enabled": True}
NFT = {"backend": "nftables", "remark": "", "transport": "tcp+udp", "listen_host": "0.0.0.0", "listen_port": 30000,
       "remote_host": "1.2.3.4", "remote_port": 53, "enabled": True}


class Validation(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(validate_forward_rule(REALM), REALM)
        self.assertEqual(validate_forward_rule(NFT), NFT)
        for bad in ({**NFT, "remote_host": "example.com"}, {**NFT, "transport": "tcp"}, {**NFT, "listen_host": "1.1.1.1"},
                    {**REALM, "remark": 'a"b'}, {**REALM, "remark": "a\nb"}, {**REALM, "remark": "x" * 65}, {**REALM, "listen_port": 0},
                    {**REALM, "remote_port": True}, {**REALM, "transport": "sctp"}, {**REALM, "backend": "gost"}, {**REALM, "listen_host": "a.com"},
                    {**REALM, "remote_host": "bad host"}, {**REALM, "enabled": 1}, {**REALM, "extra": 1}, {k: v for k, v in REALM.items() if k != "remark"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                validate_forward_rule(bad)
        self.assertEqual(validate_forward_rule({**REALM, "remote_host": "2001:db8::1", "listen_host": "::"})["remote_host"], "2001:db8::1")

    def test_tasks(self):
        ok = [{"op": "add", "rule": REALM}, {"op": "update", "id": "abcdef012345", "base": {**REALM, "id": "abcdef012345"}, "rule": REALM},
              {"op": "delete", "id": "nft-30000", "base": NFT}, {"op": "enable", "id": "nft-30000", "base": NFT}, {"op": "disable", "id": "nft-30000", "base": NFT}]
        for op in ok:
            self.assertEqual(validate_forward_task({"action": "forward_apply", "params": {"ops": [op]}})["params"]["ops"], [op])
        for op in ({"op": "add"}, {"op": "add", "rule": REALM, "id": "abcdef012345"}, {"op": "delete", "id": "../x", "base": {}},
                   {"op": "delete", "id": "nft-1"}, {"op": "drop", "id": "nft-1", "base": {}}, {"op": "delete", "id": "nft-1", "base": {"shell": 1}}):
            with self.assertRaises(ValueError, msg=str(op)):
                validate_forward_task({"action": "forward_apply", "params": {"ops": [op]}})
        with self.assertRaises(ValueError):
            validate_forward_task({"action": "forward_apply", "params": {"ops": ok[:2]}})

    def test_sanitize(self):
        rows = [{**REALM, "id": "abcdef012345", "status": "running", "bytes": 5, "secret": "x"}, {**NFT, "id": "nft-30000", "status": "weird", "bytes": -1},
                {**NFT, "id": "bad id"}, {**NFT, "remote_host": "example.com", "id": "nft-1"}, "x"]
        clean = sanitize_forwards(rows)
        self.assertEqual([r["id"] for r in clean], ["abcdef012345", "nft-30000"])
        self.assertNotIn("secret", clean[0])
        self.assertEqual((clean[1]["status"], clean[1]["bytes"]), ("stopped", None))
        self.assertEqual(len(sanitize_forwards([{**NFT, "id": "nft-%d" % i} for i in range(600)])), 500)
        snap = sanitize_snapshot({"instances": [], "forward_version": 1, "forwards": rows})
        self.assertEqual(len(snap["forwards"]), 2)
        self.assertEqual(sanitize_snapshot({"instances": [], "forwards": rows})["forwards"], [])  # no capability, nothing kept


class ForwardNode(SimNode):
    def __init__(self, test, name, forward_version=1):
        self.forward_version = forward_version
        self.forwards = [{**REALM, "id": "abcdef012345", "status": "running", "bytes": 100}, {**NFT, "id": "nft-30000", "status": "running", "bytes": None}]
        super().__init__(test, name)

    def snapshot(self):
        return {**super().snapshot(), "forward_version": self.forward_version, "forwards": self.forwards}


class PanelAPI(unittest.TestCase):
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

    def post(self, node, data, status):
        r = self.client.post('/api/nodes/%s/forwards' % node.id, json=data, headers=self.headers)
        self.assertEqual(r.status_code, status, r.json)
        return r.json

    def test_changes_become_node_tasks_with_snapshot_base(self):
        node = ForwardNode(self, 'F')
        node.poll(run=False)
        self.assertEqual(self.client.get('/api/nodes').json['nodes'][-1]['snapshot']['forwards'][0]['id'], 'abcdef012345')
        self.post(node, {"op": "add", "rule": {**NFT, "listen_port": 20000}}, 409)       # same port as the Realm TCP rule
        self.post(node, {"op": "add", "rule": {**REALM, "listen_port": 443}}, 409)       # proxy instance port
        self.post(node, {"op": "add", "rule": {**REALM, "transport": "udp", "listen_port": 20000}}, 201)  # UDP does not collide with TCP
        task = node.poll(run=False)
        self.assertEqual(task["action"], "forward_apply")
        self.assertEqual(task["params"]["ops"][0]["rule"]["transport"], "udp")
        self.client.post('/api/agent/%s/tasks/%s/result' % (node.id, task["id"]), json={"status": "succeeded", "message": "ok", "result": {}}, headers=node.auth)
        self.post(node, {"op": "update", "id": "abcdef012345", "rule": {**REALM, "remote_port": 8080}}, 201)
        task = node.poll(run=False)
        self.assertEqual(task["params"]["ops"][0]["base"], {**REALM, "id": "abcdef012345"})  # base comes from the node's snapshot
        self.post(node, {"op": "disable", "id": "nft-30000"}, 409)                       # one unfinished task per node
        self.client.post('/api/agent/%s/tasks/%s/result' % (node.id, task["id"]), json={"status": "succeeded", "message": "ok", "result": {}}, headers=node.auth)
        self.post(node, {"op": "disable", "id": "nft-30000"}, 201)
        self.assertEqual(set(node.poll(run=False)["params"]["ops"][0]), {"op", "id", "base"})

    def test_rejections(self):
        node = ForwardNode(self, 'G')
        node.poll(run=False)
        for data in ({"op": "add"}, {"op": "add", "rule": {**NFT, "remote_host": "example.com"}}, {"op": "delete", "id": "nft-30000", "base": {}},
                     {"op": "drop", "id": "nft-30000"}, {"op": "update", "id": "nft-30000"}):
            self.post(node, data, 400)
        self.post(node, {"op": "delete", "id": "nft-99999"}, 409)
        old = ForwardNode(self, 'H', forward_version=0)
        old.poll(run=False)
        self.assertIn("升级", self.post(old, {"op": "add", "rule": REALM}, 409)["error"])
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.post('/api/nodes/%s/forwards' % node.id, json={"op": "add", "rule": REALM}).status_code, 401)


class FakeForwardAPI:
    def __init__(self, replies, results=()):
        self.replies, self.results, self.calls, self.invalidated = list(replies), list(results), [], 0

    def forward(self, params, request_id):
        self.calls.append((params, request_id))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def result(self, request_id):
        return self.results.pop(0)

    def invalidate(self):
        self.invalidated += 1


class AgentSide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / 'cfg'; self.cfg.mkdir()
        self.state = Path(self.tmp.name) / 'state'
        atomic_write(self.cfg / 'db.json', json.dumps({"xray": {}, "singbox": {}, "meta": {}}))
        self.runtime = FakeRuntime(self.cfg / 'config.json'); self.runtime.path.write_text('x')

    def tearDown(self):
        self.tmp.cleanup()

    def run_task(self, api, op=None):
        task = {"id": str(uuid.uuid4()), "action": "forward_apply", "params": {"ops": [op or {"op": "add", "rule": REALM}]}}
        return Bridge(self.cfg, self.state, self.runtime, script_api=api).execute(task), task

    def test_success_failure_and_unknown(self):
        api = FakeForwardAPI([{"status": "succeeded", "data": {"rule": {"id": "abcdef012345", "remote_host": "x"}}}])
        result, task = self.run_task(api)
        self.assertEqual(result["rule"], {"id": "abcdef012345"})
        self.assertEqual((api.calls[0][1], api.invalidated), (task["id"], 1))
        for code, message in (("port_conflict", "冲突"), ("rule_changed", "刷新"), ("weird", "拒绝")):
            with self.assertRaisesRegex(ValueError, message):
                self.run_task(FakeForwardAPI([{"status": "failed", "code": code, "data": {}}]))
        with self.assertRaisesRegex(TransactionRolledBack, "已回滚：端口被占用"):
            self.run_task(FakeForwardAPI([{"status": "failed", "code": "apply_failed", "data": {"message": "端口被占用"}}]))
        with self.assertRaises(TransactionUnknown):
            self.run_task(FakeForwardAPI([OSError("killed")], [{"status": "unknown"}]))
        result, _ = self.run_task(FakeForwardAPI([{"status": "unknown"}], [{"status": "succeeded", "data": {}}]))
        self.assertIsNone(result["rule"])
        with self.assertRaises(ValueError):
            self.run_task(FakeForwardAPI([]), {"op": "add", "rule": {**NFT, "remote_host": "example.com"}})

    def test_script_api_and_snapshot(self):
        api, sent = ScriptAPI(), []
        def call(request, timeout):
            sent.append((request, timeout))
            return 0, {'api_version': 1, 'request_id': request['request_id'], 'status': 'succeeded', 'data': {}}
        task = str(uuid.uuid4())
        with patch.object(api, '_call', side_effect=call):
            api.forward({"ops": [{"op": "add", "rule": REALM}]}, task)
        self.assertEqual((sent[0][0]['action'], sent[0][0]['request_id'], sent[0][1]), ('forward_apply', task, 300))
        caps = dict(script_version='v', data=dict(stage='read_only_foundation', write_actions=[], protocols=[dict(write_supported=False)],
                                                   forward_api={'version': 1}))
        inv = dict(script_version='v', data=dict(instances=[], forwards=[{**REALM, "id": "abcdef012345", "status": "running", "bytes": 1}, {"id": "bad"}]))
        with patch.object(ScriptAPI, 'read', side_effect=[caps, inv]):
            status = ScriptAPI().status()
        self.assertEqual((status['forward_api'], [r['id'] for r in status['forwards']]), (1, ['abcdef012345']))
        with tempfile.TemporaryDirectory() as tmp:
            agent = Agent({'url': 'https://panel.example', 'node_id': 'n', 'token': 't'}, Path(tmp) / 'state', cfg=Path(tmp))
            agent.script_api = type('API', (), {'status': lambda self: {'status': 'ready', 'accounts_api': 1, 'forward_api': 1, 'forwards': status['forwards']}})()
            payloads = []
            with patch.object(agent, 'api', side_effect=lambda suffix, payload: payloads.append(payload) or {}):
                agent.cycle(None, None)
            snap = payloads[-1]['snapshot']
            self.assertEqual((snap['forward_version'], len(snap['forwards'])), (1, 1))
            self.assertNotIn('forwards', snap['script_api'])


if __name__ == '__main__':
    unittest.main()
