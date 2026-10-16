"""面板通过节点脚本安装协议（--api install）：脚本声明的字段清单清洗、任务校验、节点程序执行与快照、面板接口。"""
import json
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from agent.__main__ import Agent
from agent.bridge import Bridge, TransactionRolledBack, TransactionUnknown
from agent.inventory import sanitize_snapshot
from agent.runtime import ROOT, atomic_write
from agent.script_api import ScriptAPI
from vaio.common import sanitize_install_schema, validate_script_install_task
from vaio.server import create_app
from test_agent import FakeRuntime


def script_schema():
    """The schema exactly as the pinned script declares it (only jq is needed, any Bash works)."""
    body = subprocess.run(['awk', 'index($0, "_api_install_schema() {") == 1 {on=1} on {print} on && $0 == "}" {exit}',
                           str(ROOT / 'vendor/vless-server.sh')], capture_output=True, text=True, check=True).stdout
    return json.loads(subprocess.run(['bash', '-c', body + '\n_api_install_schema'], capture_output=True, text=True, check=True).stdout)


SCHEMA = script_schema()


def task(answers=None, protocol="vless-vision", core="xray"):
    return {"action": "script_install", "params": {"protocol": protocol, "core": core, "answers": answers or {}}}


class Schema(unittest.TestCase):
    def test_script_schema_survives_sanitizing(self):
        clean = sanitize_install_schema(SCHEMA)
        vision = clean["protocols"]["vless-vision"]
        self.assertEqual(vision["cores"], ["xray"])
        self.assertEqual([f["key"] for f in vision["fields"]], ["port", "cert.mode", "cert.domain", "sni", "install.master_conflict"])
        self.assertEqual(vision["fields"][1]["default"], "self")
        self.assertEqual(vision["fields"][2]["when"], {"cert.mode": "acme"})
        self.assertTrue(vision["fields"][0]["optional"])

    def test_malformed_parts_are_dropped(self):
        evil = {"version": 1, "protocols": {
            "vless-vision": {"name": "VLESS-Vision", "cores": ["xray", "rm -rf"], "fields": [
                {"key": "port", "type": "port", "label": "端口"},
                {"key": "x", "type": "script", "label": "x"},
                {"key": "Bad Key", "type": "host", "label": "k"},
                {"key": "sni", "type": "host", "label": "<img src=x>"},
                {"key": "mode", "type": "enum", "label": "模式", "options": [{"value": "a;b", "label": "x"}]},
                {"key": "w", "type": "host", "label": "w", "when": {"mode": "<x>"}}]},
            "../etc": {"name": "x", "cores": ["xray"], "fields": []},
            "nocore": {"name": "x", "cores": ["nginx"], "fields": []}}}
        clean = sanitize_install_schema(evil)
        self.assertEqual(list(clean["protocols"]), ["vless-vision"])
        self.assertEqual(clean["protocols"]["vless-vision"]["cores"], ["xray"])
        self.assertEqual([f["key"] for f in clean["protocols"]["vless-vision"]["fields"]], ["port"])
        self.assertIsNone(sanitize_install_schema({"version": 2, "protocols": SCHEMA["protocols"]}))
        self.assertIsNone(sanitize_install_schema("x"))

    def test_task_validation(self):
        schema = sanitize_install_schema(SCHEMA)
        ok = validate_script_install_task(task({"port": 8443, "cert.mode": "acme", "cert.domain": "a.example.com"}), schema)
        self.assertEqual(ok["params"]["answers"]["port"], 8443)
        validate_script_install_task(task({"anything": "x"}))                     # node side: structure only
        for bad, message in ((task({"port": "8443"}), "端口"), (task({"cert.mode": "dns"}), "证书"), (task({"sni": "a..b"}), "SNI"),
                             (task({"zzz": "1"}), "zzz"), (task(protocol="hy2"), "不支持"), (task(core="singbox"), "不支持")):
            with self.assertRaisesRegex(ValueError, message):
                validate_script_install_task(bad, schema)
        for bad in (task({"sni": "a b"}), task({"port": 0}), task({"x": True}), task({"Bad": "1"}), task(core="nginx"),
                    {**task(), "extra": 1}, {"action": "script_install", "params": {"protocol": "vless-vision", "core": "xray"}},
                    task({str(i): "a" for i in range(21)})):
            with self.assertRaises(ValueError):
                validate_script_install_task(bad)


class FakeInstallAPI:
    def __init__(self, replies, results=()):
        self.replies, self.results, self.calls, self.invalidated = list(replies), list(results), [], 0

    def install(self, params, request_id):
        self.calls.append((params, request_id))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def result(self, request_id):
        return self.results.pop(0)

    def invalidate(self):
        self.invalidated += 1

    def status(self):
        return {"status": "ready"}


class AgentSide(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / 'cfg'; self.cfg.mkdir()
        self.state = Path(self.tmp.name) / 'state'
        atomic_write(self.cfg / 'db.json', json.dumps({"xray": {}, "singbox": {}, "meta": {}}))
        self.runtime = FakeRuntime(self.cfg / 'config.json'); self.runtime.path.write_text('x')

    def tearDown(self):
        self.tmp.cleanup()

    def run_task(self, api, answers=None):
        item = {"id": str(uuid.uuid4()), **task(answers or {"port": 24443})}
        return Bridge(self.cfg, self.state, self.runtime, script_api=api).execute(item), item

    def test_success_failure_and_unknown(self):
        ok = {"status": "succeeded", "data": {"target": {"core": "xray", "protocol": "vless-vision", "port": 24443}}}
        api = FakeInstallAPI([ok])
        result, item = self.run_task(api)
        self.assertEqual(result["target"], {"core": "xray", "protocol": "vless-vision", "port": 24443})
        self.assertEqual(api.calls[0], ({"protocol": "vless-vision", "core": "xray", "answers": {"port": 24443}}, item["id"]))
        # Replays never reach the script again
        bridge = Bridge(self.cfg, self.state, self.runtime, script_api=FakeInstallAPI([]))
        self.assertEqual(bridge.execute(item)["target"]["port"], 24443)
        with self.assertRaisesRegex(TransactionRolledBack, "参数无效或被节点拒绝：端口（节点已恢复"):
            self.run_task(FakeInstallAPI([{"status": "failed", "code": "invalid_answer", "data": {"field": "port", "rolled_back": True}}]))
        with self.assertRaisesRegex(TransactionRolledBack, "安装失败：Xray 安装失败"):
            self.run_task(FakeInstallAPI([{"status": "failed", "code": "install_failed", "data": {"message": "Xray 安装失败", "rolled_back": True}}]))
        with self.assertRaisesRegex(TransactionRolledBack, "Let's Encrypt"):
            self.run_task(FakeInstallAPI([{"status": "failed", "code": "acme_failed", "data": {"field": "cert.domain", "rolled_back": True}}]))
        with self.assertRaisesRegex(ValueError, "缺少必填参数：域名"):
            self.run_task(FakeInstallAPI([{"status": "failed", "code": "missing_answer", "data": {"field": "cert.domain"}}]))
        with self.assertRaisesRegex(ValueError, "拒绝"):
            self.run_task(FakeInstallAPI([{"status": "failed", "code": "weird", "data": {}}]))
        with self.assertRaises(TransactionUnknown):
            self.run_task(FakeInstallAPI([OSError("killed")], [{"status": "unknown"}]))
        with self.assertRaises(TransactionUnknown):          # a success that names another protocol is not trusted
            self.run_task(FakeInstallAPI([{"status": "succeeded", "data": {"target": {"protocol": "trojan", "port": 1}}}]))
        result, _ = self.run_task(FakeInstallAPI([{"status": "unknown"}], [ok]))
        self.assertEqual(result["target"]["port"], 24443)
        with self.assertRaisesRegex(ValueError, "不可用"):
            Bridge(self.cfg, self.state, self.runtime).execute({"id": str(uuid.uuid4()), **task()})

    def test_script_api_and_snapshot(self):
        api, sent = ScriptAPI(), []
        def call(request, timeout):
            sent.append((request, timeout))
            return 0, {'api_version': 1, 'request_id': request['request_id'], 'status': 'succeeded', 'data': {}}
        request_id = str(uuid.uuid4())
        with patch.object(api, '_call', side_effect=call):
            api.install(task()["params"], request_id)
        self.assertEqual((sent[0][0]['action'], sent[0][0]['request_id'], sent[0][1]), ('install', request_id, 1200))
        caps = dict(script_version='v', data=dict(stage='read_only_foundation', write_actions=[], protocols=[dict(write_supported=False)],
                                                   install_api={'version': 1, 'schema': SCHEMA}))
        inv = dict(script_version='v', data=dict(instances=[]))
        with patch.object(ScriptAPI, 'read', side_effect=[caps, inv]):
            status = ScriptAPI().status()
        self.assertEqual(list(status['install_schema']['protocols']), ['vless-vision'])
        with patch.object(ScriptAPI, 'read', side_effect=[{**caps, 'data': {**caps['data'], 'install_api': {'version': 2, 'schema': SCHEMA}}}, inv]):
            self.assertNotIn('install_schema', ScriptAPI().status())
        agent = Agent({'url': 'https://panel.example', 'node_id': 'n', 'token': 't'}, self.state, cfg=self.cfg)
        agent.script_api = type('API', (), {'status': lambda self: dict(status)})()
        payloads = []
        with patch.object(agent, 'api', side_effect=lambda suffix, payload: payloads.append(payload) or {}):
            agent.cycle(None, None)
        snap = payloads[-1]['snapshot']
        self.assertEqual((snap['install_version'], list(snap['install_schema']['protocols'])), (1, ['vless-vision']))
        self.assertNotIn('install_schema', snap['script_api'])
        clean = sanitize_snapshot({**snap, 'instances': []})
        self.assertEqual((clean['install_version'], list(clean['install_schema']['protocols'])), (1, ['vless-vision']))
        self.assertEqual(sanitize_snapshot({'instances': [], 'install_schema': SCHEMA})['install_version'], 0)

    def test_run_task_message_and_refresh(self):
        agent = Agent({'url': 'https://panel.example', 'node_id': 'n', 'token': 't'}, self.state, cfg=self.cfg)
        api = FakeInstallAPI([{"status": "succeeded", "data": {"target": {"protocol": "vless-vision", "port": 24443}}}])
        agent.script_api = api
        agent.bridge = Bridge(self.cfg, self.state, self.runtime, script_api=api)
        reply = agent.run_task({"id": str(uuid.uuid4()), **task()})
        self.assertEqual((reply['status'], reply['message'], api.invalidated), ('succeeded', '已安装 vless-vision，端口 24443', 1))
        self.assertNotIn('target', reply['result'])


class PanelAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'DATABASE': self.tmp.name + '/panel.sqlite', 'PUBLIC_URL': 'https://p.example.com'})
        self.store = self.app.extensions['store']
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('password',?)", (generate_password_hash('a-long-test-password', method='pbkdf2:sha256:1000'),))
        self.client = self.app.test_client()
        self.h = {'X-CSRF-Token': self.client.post('/api/login', json={'username': 'admin', 'password': 'a-long-test-password'}).json['csrf']}

    def tearDown(self):
        self.tmp.cleanup()

    def node(self, nid, snapshot):
        with self.store.connect() as db:
            db.execute("INSERT INTO nodes(id,name,created,adopted,last_seen,maintenance,snapshot) VALUES(?,?,?,?,?,?,?)",
                       (nid, nid, time.time(), 1, time.time(), 0, json.dumps(snapshot)))

    def test_queue_install(self):
        self.node("a", {"install_version": 1, "install_schema": sanitize_install_schema(SCHEMA), "instances": []})
        self.node("old", {"instances": []})
        post = lambda nid, data: self.client.post('/api/nodes/%s/script-install' % nid, json=data, headers=self.h)
        body = {"protocol": "vless-vision", "core": "xray", "answers": {"port": 24443, "sni": "cdn.example.com"}}
        self.assertIn("1.6.0", post("old", body).json['error'])
        for bad in ({**body, "x": 1}, {**body, "answers": {"port": "x"}}, {**body, "protocol": "hy2"}, {**body, "answers": {"cert.mode": "dns"}}):
            self.assertEqual(post("a", bad).status_code, 400, bad)
        r = post("a", body)
        self.assertEqual(r.status_code, 201, r.json)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (r.json['id'],)).fetchone()
        self.assertEqual((row['action'], json.loads(row['request'])), ('script_install', {"action": "script_install", "params": body}))
        self.assertIn("未完成", post("a", body).json['error'])
        # The agent picks it up exactly as stored
        tasks = self.client.get('/api/tasks', headers=self.h).json
        listed = tasks['tasks'] if isinstance(tasks, dict) else tasks
        self.assertTrue(any(t['id'] == r.json['id'] and t['action'] == 'script_install' for t in listed))


if __name__ == '__main__':
    unittest.main()
