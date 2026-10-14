import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent.bridge import Bridge
from agent.inventory import inventory, sanitize_snapshot
from agent.runtime import atomic_write
from agent.script_api import ScriptAPI
from vaio.common import config_revision, user_mode, user_stats, validate_task
from test_agent import FakeRuntime, fixture


def node_db():
    db = fixture()
    db["xray"]["vless-ws"] = {"port": 2083, "uuid": "WS_SECRET", "users": [{"name": "alice", "uuid": "WS_SECRET"}]}
    db["xray"]["socks"] = [{"port": 1080, "username": "u", "password": "p"}, {"port": 1081, "auth_mode": "noauth"}]
    db["xray"]["snell-v5"] = [{"port": 9001, "psk": "S", "snell_id": "a" * 24, "users": []}]
    db["xray"]["naive"] = {"port": 443, "username": "n", "password": "p"}
    db["meta"]["snell_users"] = {"snell-v5": True}
    return db


class FakeShare:
    def __init__(self):
        self.calls = []

    def share(self, target, name, host, port=None):
        self.calls.append((target, name, host))
        return "vless://link@" + host


class ProtocolUsersAgent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "cfg"; self.cfg.mkdir()
        self.state = Path(self.tmp.name) / "state"
        atomic_write(self.cfg / "db.json", json.dumps(node_db()))
        self.runtime = FakeRuntime(self.cfg / "config.json"); self.runtime.path.write_text("original")
        self.api = FakeShare()
        self.bridge = Bridge(self.cfg, self.state, self.runtime, script_api=self.api)

    def tearDown(self):
        self.tmp.cleanup()

    def test_capability_table_matches_script(self):
        expected = {"vless-ws": ("multi", "user"), "ss2022": ("multi", "user"), "tuic": ("multi", "user"), "socks": ("single", "inbound"),
                    "snell": ("single", "port"), "ss2022-shadowtls": ("single", "port"), "naive": ("none", "none")}
        for proto, modes in expected.items():
            self.assertEqual((user_mode(proto), user_stats(proto)), modes, proto)
        self.assertEqual(user_mode("socks", {"auth_mode": "noauth"}), "none")

    def test_share_for_protocols_outside_adapters_uses_the_script(self):
        task = {"id": str(uuid.uuid4()), "action": "share", "protocol": "vless-ws", "core": "xray", "port": 2083,
                "params": {"name": "alice", "host": "203.0.113.5"}}
        self.assertEqual(self.bridge.execute(task), {"connection": "vless://link@203.0.113.5"})
        self.assertEqual(self.api.calls[0], ({"core": "xray", "protocol": "vless-ws", "port": 2083}, "alice", "203.0.113.5"))
        with patch("agent.bridge.discover", return_value={"ipv4": "198.51.100.7"}):
            self.bridge.execute({**task, "id": str(uuid.uuid4()), "params": {"name": "alice"}})
        self.assertEqual(self.api.calls[-1][2], "198.51.100.7")
        with self.assertRaisesRegex(ValueError, "脚本接口不可用"):
            Bridge(self.cfg, self.state, self.runtime).execute({**task, "id": str(uuid.uuid4())})
        for bad in ({"action": "user_update", "protocol": "vless-ws"}, {"action": "share", "protocol": "unknown"},
                    {"action": "share", "protocol": "vless-ws", "core": "standalone"}):
            data = {"action": "share", "protocol": "vless-ws", "core": "xray", "port": 2083, "params": {"name": "alice"}, "revision": "a" * 64, **bad}
            with self.assertRaises(ValueError):
                validate_task(data)

    def test_platform_mode_installs_an_empty_instance(self):
        db = node_db(); db["meta"]["user_authority"] = "platform"
        atomic_write(self.cfg / "db.json", json.dumps(db))
        self.runtime.install = lambda *a: None
        task = {"id": str(uuid.uuid4()), "action": "install", "protocol": "ss2022", "core": "singbox", "port": 28388,
                "params": {}, "revision": config_revision(db)}
        self.bridge.execute(task)
        row = json.loads((self.cfg / "db.json").read_text())["singbox"]["ss2022"]
        row = row[0] if isinstance(row, list) else row
        self.assertEqual((row["users"], bool(row["password"])), ([], True))

    def test_snapshot_reports_user_modes(self):
        data = sanitize_snapshot(inventory(self.cfg, status=lambda _: "running"))
        modes = {(i["protocol"], i["port"]): (i["user_mode"], i["user_stats"], i["user_available"]) for i in data["instances"]}
        self.assertEqual(modes[("vless-ws", 2083)], ("multi", "user", True))
        self.assertEqual(modes[("socks", 1080)], ("single", "inbound", True))
        self.assertEqual(modes[("socks", 1081)], ("none", "none", False))
        self.assertEqual(modes[("snell-v5", 9001)], ("single", "port", True))
        self.assertEqual(modes[("naive", 443)], ("none", "none", False))
        self.assertEqual(data["share_version"], 2)
        clean = sanitize_snapshot({"instances": [{"port": 1, "user_mode": "root", "user_stats": "x", "user_available": "yes"}]})
        self.assertEqual({k: clean["instances"][0][k] for k in ("user_mode", "user_stats", "user_available")}, {"user_mode": "", "user_stats": "", "user_available": False})

    def test_script_share_errors_are_mapped(self):
        api = ScriptAPI()
        reply = lambda code: (1, {"api_version": 1, "request_id": "x", "status": "failed", "code": code})
        with patch.object(api, "_call", return_value=reply("user_not_found")), self.assertRaisesRegex(ValueError, "用户不存在"):
            api.share({"core": "xray", "protocol": "vless-ws", "port": 1}, "a", "")
        with patch.object(api, "_call", return_value=(0, {"status": "succeeded", "data": {"connection": "x" * 9000}})):
            self.assertEqual(len(api.share({"core": "xray", "protocol": "vless-ws", "port": 1}, "a", "h")), 8000)


if __name__ == "__main__":
    unittest.main()
