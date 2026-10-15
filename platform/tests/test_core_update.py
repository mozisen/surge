"""内核更新：版本读取与最新版本（Sing-box 取统计版预编译包）、节点端更新流程（先同步流量、停启服务、失败恢复）、面板单台与批量接口。"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from agent import cores
from agent.bridge import Bridge, TransactionUnknown
from agent.inventory import sanitize_snapshot
from vaio.common import validate_core_task
from vaio.server import create_app


def fake_binary(path, text):
    path.write_text("#!/bin/sh\necho '%s'\n" % text)
    path.chmod(0o755)


class Runtime:
    """Records what the update does; installs by rewriting the fake binary."""
    def __init__(self, root, install_to=None, fail_install=False, start_fails=(), latest="25.3.6", lookups=None):
        self.root, self.calls, self.running = root, [], {"vless-reality", "vless-snellu-aaaaaaaaaaaaaaaaaaaaaaaa"}
        self.install_to, self.fail_install, self.start_fails, self.latest_version = install_to, fail_install, set(start_fails), latest
        self.lookups = lookups or {}

    def sync_traffic(self):
        self.calls.append(("sync",))

    def upstream_output(self, operation, *args):
        self.calls.append(("lookup", operation) + args)
        if operation in self.lookups:
            return self.lookups[operation]
        return "\x1b[32m[INFO]\x1b[0m checking\n" + self.latest_version + "\n"

    def upstream(self, operation, *args):
        self.calls.append(("install", operation) + args)
        if self.fail_install:
            raise RuntimeError("download failed")
        if self.install_to:
            self.install_to()

    def is_running(self, service):
        return service in self.running

    def service(self, name, action):
        self.calls.append((action, name))
        if action == "stop":
            self.running.discard(name)
        elif action == "start" and name not in self.start_fails:
            self.running.add(name)


class Cores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "cfg"
        self.cfg.mkdir()
        self.state = self.root / "state"
        self.bins = {name: self.root / name for name in ("xray", "sing-box", "snell-server-v5", "snell-server-v6")}
        self.patch = patch.dict(cores.CORES, {
            "xray": {**cores.CORES["xray"], "binary": str(self.bins["xray"])},
            "singbox": {**cores.CORES["singbox"], "binary": str(self.bins["sing-box"])},
            "snell-v5": {**cores.CORES["snell-v5"], "binary": str(self.bins["snell-server-v5"])},
            "snell-v6": {**cores.CORES["snell-v6"], "binary": str(self.bins["snell-server-v6"])}})
        self.patch.start()
        db = {"xray": {"vless": {"port": 443, "users": []}, "trojan": [{"port": 8443, "users": []}],
                       "snell-v6": {"port": 38915, "snell_id": "a" * 24, "users": []}},
              "singbox": {"hy2": {"port": 8444, "users": []}},
              "meta": {"panel_paused_services": []}}
        (self.cfg / "db.json").write_text(json.dumps(db))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_versions_and_latest(self):
        self.assertEqual(cores.read_version("xray"), ("", False))
        fake_binary(self.bins["xray"], "Xray 25.1.30 (Xray, Penetrates Everything.) 0123 (go1.24 linux/amd64)")
        fake_binary(self.bins["sing-box"], "sing-box version 1.14.2\\nTags: with_gvisor,with_v2ray_api")
        fake_binary(self.bins["snell-server-v6"], "snell-server v6.0.0b4")
        self.assertEqual(cores.read_version("xray"), ("25.1.30", False))
        self.assertEqual(cores.read_version("singbox"), ("1.14.2", True))
        self.assertEqual(cores.read_version("snell-v6")[0], "6.0.0")
        tree = {"tree": [{"path": p} for p in ("v1.14.0/linux-amd64-glibc/manifest.json", "v1.14.2/linux-amd64-glibc/manifest.json",
                                                "v1.14.3/linux-arm64-musl/manifest.json", "v1.14.10/linux-amd64-musl/manifest.json", "README.md")]}
        self.assertEqual(cores.stats_latest("linux-amd64-glibc", lambda: tree), "1.14.2")    # 1.14.3 is not built for this machine
        self.assertEqual(cores.stats_latest("linux-amd64-musl", lambda: tree), "1.14.10")
        self.assertEqual(cores.stats_latest("linux-riscv64-glibc", lambda: tree), "")
        runtime = Runtime(self.root)
        self.assertEqual(cores.latest(runtime, "xray"), "25.3.6")
        self.assertIn(("lookup", "_get_latest_version", "XTLS/Xray-core", "true"), runtime.calls)
        # Snell: the release notes list 6.x above 5.x; each core only takes its own major version.
        notes = "6.0.0\n6.0.0b4\n5.0.1\n5.0.0\n4.1.1\n"
        runtime = Runtime(self.root, lookups={"_get_snell_versions_from_kb": notes, "_get_snell_v6_stable_version": "无\n"})
        self.assertEqual(cores.latest(runtime, "snell-v5"), "5.0.1")
        self.assertEqual(cores.latest(runtime, "snell-v6"), "6.0.0")
        self.assertIn(("lookup", "_get_snell_versions_from_kb", "50"), runtime.calls)
        runtime = Runtime(self.root, lookups={"_get_snell_versions_from_kb": "6.1.0\n6.0.0\n", "_get_snell_v6_stable_version": ""})
        self.assertEqual(cores.latest(runtime, "snell-v5"), "")                 # no 5.x listed: no update offered
        snap = cores.snapshot({"xray": ("25.1.30", False), "singbox": ("1.14.2", True), "snell-v5": ("", False)}, {"xray": "25.3.6", "singbox": "1.14.2"}, "1.14.3")
        self.assertEqual(snap, {"xray": {"current": "25.1.30", "latest": "25.3.6"},
                                "singbox": {"current": "1.14.2", "latest": "1.14.2", "stats": True, "official": "1.14.3"}})

    def test_services_per_core(self):
        db = json.loads((self.cfg / "db.json").read_text())
        self.assertEqual(cores.services(db, "xray"), ["vless-reality"])
        self.assertEqual(cores.services(db, "snell-v6"), ["vless-snellu-" + "a" * 24])
        self.assertEqual(cores.services(db, "snell-v5"), [])

    def test_xray_update_syncs_first_and_restarts(self):
        fake_binary(self.bins["xray"], "Xray 25.1.30 x")
        runtime = Runtime(self.root, install_to=lambda: fake_binary(self.bins["xray"], "Xray 25.3.6 x"))
        result = cores.update(runtime, self.cfg, self.state, "xray", wait=0)
        self.assertEqual(result, {"core": "xray", "from": "25.1.30", "to": "25.3.6", "changed": True})
        order = [c[0] if c[0] != "install" else c[1] for c in runtime.calls if c[0] != "lookup"]
        self.assertEqual(order, ["sync", "stop", "install_xray", "start"])
        self.assertIn(("install", "install_xray", "stable", "true", "25.3.6"), runtime.calls)
        self.assertIn("vless-reality", runtime.running)
        self.assertTrue(list((self.state / "core-backups").glob("xray-25.1.30-*")))
        # Already latest: nothing happens, not even a traffic sync.
        again = Runtime(self.root)
        self.assertFalse(cores.update(again, self.cfg, self.state, "xray")["changed"])
        self.assertEqual([c[0] for c in again.calls], ["lookup"])

    def test_failed_install_restores_old_core(self):
        fake_binary(self.bins["xray"], "Xray 25.1.30 x")
        runtime = Runtime(self.root, fail_install=True)
        with self.assertRaisesRegex(RuntimeError, "已恢复 25.1.30"):
            cores.update(runtime, self.cfg, self.state, "xray", wait=0)
        self.assertEqual(cores.read_version("xray")[0], "25.1.30")
        self.assertIn("vless-reality", runtime.running)
        # Wrong version after install also counts as a failure.
        runtime = Runtime(self.root, install_to=lambda: fake_binary(self.bins["xray"], "Xray 25.2.0 x"))
        with self.assertRaisesRegex(RuntimeError, "不是 25.3.6"):
            cores.update(runtime, self.cfg, self.state, "xray", wait=0)
        self.assertEqual(cores.read_version("xray")[0], "25.1.30")

    def test_service_that_will_not_start_restores(self):
        fake_binary(self.bins["snell-server-v6"], "snell-server v6.0.0")
        unit = "vless-snellu-" + "a" * 24
        runtime = Runtime(self.root, install_to=lambda: fake_binary(self.bins["snell-server-v6"], "snell-server v6.1.0"),
                          start_fails={unit}, lookups={"_get_snell_versions_from_kb": "6.1.0\n5.0.1\n", "_get_snell_v6_stable_version": "6.0.0\n"})
        runtime.start_fails_once = True
        original_service = runtime.service
        def service(name, action):                  # fails with the new binary, works again with the old one
            if action == "start" and cores.read_version("snell-v6")[0] == "6.0.0":
                runtime.start_fails.discard(name)
            original_service(name, action)
        runtime.service = service
        with self.assertRaisesRegex(RuntimeError, "启动失败"):
            cores.update(runtime, self.cfg, self.state, "snell-v6", wait=0)
        self.assertEqual(cores.read_version("snell-v6")[0], "6.0.0")
        self.assertIn(("install", "install_snell_v6", "6.1.0"), runtime.calls)
        self.assertIn(unit, runtime.running)

    def test_paused_service_is_not_started(self):
        db = json.loads((self.cfg / "db.json").read_text())
        db["meta"]["panel_paused_services"] = ["vless-reality"]
        (self.cfg / "db.json").write_text(json.dumps(db))
        fake_binary(self.bins["xray"], "Xray 25.1.30 x")
        runtime = Runtime(self.root, install_to=lambda: fake_binary(self.bins["xray"], "Xray 25.3.6 x"))
        runtime.running.discard("vless-reality")
        cores.update(runtime, self.cfg, self.state, "xray", wait=0)
        self.assertNotIn(("start", "vless-reality"), runtime.calls)

    def test_snell_v5_never_gets_v6(self):
        fake_binary(self.bins["snell-server-v5"], "snell-server v5.0.1")
        runtime = Runtime(self.root, lookups={"_get_snell_versions_from_kb": "6.0.0\n5.0.1\n"})
        self.assertFalse(cores.update(runtime, self.cfg, self.state, "snell-v5")["changed"])
        self.assertFalse([c for c in runtime.calls if c[0] == "install"])
        runtime = Runtime(self.root, lookups={"_get_snell_versions_from_kb": "6.0.0\n"})
        with self.assertRaisesRegex(ValueError, "最新稳定版本"):
            cores.update(runtime, self.cfg, self.state, "snell-v5")

    def test_restore_failure_is_unknown(self):
        fake_binary(self.bins["xray"], "Xray 25.1.30 x")
        runtime = Runtime(self.root, fail_install=True)
        with patch.object(cores, "_restore", side_effect=OSError("disk full")):
            with self.assertRaises(cores.RestoreFailed):
                cores.update(runtime, self.cfg, self.state, "xray", wait=0)

    def test_singbox_uses_statistics_build(self):
        fake_binary(self.bins["sing-box"], "sing-box version 1.14.0\\nTags: with_v2ray_api")
        runtime = Runtime(self.root, install_to=lambda: fake_binary(self.bins["sing-box"], "sing-box version 1.14.2\\nTags: with_v2ray_api"))
        with patch.object(cores, "stats_latest", return_value="1.14.2"):
            result = cores.update(runtime, self.cfg, self.state, "singbox")
        self.assertEqual(result["to"], "1.14.2")
        self.assertEqual([c for c in runtime.calls if c[0] == "install"], [("install", "_update_singbox_preserving_stats", "stable", "1.14.2")])
        self.assertEqual(runtime.calls[0], ("sync",))
        # A build without statistics is updated even at the same version; one that loses them is an error.
        fake_binary(self.bins["sing-box"], "sing-box version 1.14.2")
        runtime = Runtime(self.root, install_to=lambda: fake_binary(self.bins["sing-box"], "sing-box version 1.14.2"))
        with patch.object(cores, "stats_latest", return_value="1.14.2"):
            with self.assertRaisesRegex(RuntimeError, "校验失败"):
                cores.update(runtime, self.cfg, self.state, "singbox")
        with patch.object(cores, "stats_latest", return_value=""):
            with self.assertRaisesRegex(ValueError, "统计版"):
                cores.update(Runtime(self.root), self.cfg, self.state, "singbox")

    def test_bridge_task(self):
        with self.assertRaises(ValueError):
            validate_core_task({"action": "core_update", "params": {"core": "nginx"}})
        with self.assertRaises(ValueError):
            validate_core_task({"action": "core_update", "params": {"core": "xray", "version": "1.0.0"}})
        fake_binary(self.bins["xray"], "Xray 25.1.30 x")
        runtime = Runtime(self.root, fail_install=True)
        bridge = Bridge(self.cfg, self.state, runtime=runtime)
        task = {"id": "00000000-0000-4000-8000-000000000001", "action": "core_update", "params": {"core": "xray"}}
        with patch.object(cores, "_restore", side_effect=OSError("disk full")):
            with self.assertRaises(TransactionUnknown):
                bridge.execute(task)
        with self.assertRaises(TransactionUnknown):                       # never replayed
            bridge.execute(task)

    def test_snapshot_sanitized(self):
        clean = sanitize_snapshot({"core_update_version": 1, "cores": {
            "xray": {"current": "25.1.30", "latest": "25.3.6", "evil": "x"}, "singbox": {"current": "1.14.2", "latest": "<b>", "stats": "yes"},
            "nginx": {"current": "1.0.0"}, "snell-v5": {"latest": "5.0.1"}}})
        self.assertEqual(clean["core_update_version"], 1)
        self.assertEqual(clean["cores"], {"xray": {"current": "25.1.30", "latest": "25.3.6"}, "singbox": {"current": "1.14.2", "stats": False}})


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

    def node(self, nid, cores_field, version=1, seen=None, adopted=1, maintenance=0):
        with self.store.connect() as db:
            db.execute("INSERT INTO nodes(id,name,created,adopted,last_seen,maintenance,snapshot) VALUES(?,?,?,?,?,?,?)",
                       (nid, nid, time.time(), adopted, time.time() if seen is None else seen, maintenance,
                        json.dumps({"core_update_version": version, "cores": cores_field})))

    def test_single_node(self):
        self.node("a", {"xray": {"current": "25.1.30", "latest": "25.3.6"}, "singbox": {"current": "1.14.2", "latest": "1.14.2", "stats": True}})
        self.node("old", {}, version=0)
        for body in ({}, {"core": "nginx"}, {"core": "xray", "x": 1}):
            self.assertEqual(self.client.post('/api/nodes/a/core-update', json=body, headers=self.h).status_code, 400)
        self.assertIn("已是最新", self.client.post('/api/nodes/a/core-update', json={'core': 'singbox'}, headers=self.h).json['error'])
        self.assertIn("未安装", self.client.post('/api/nodes/a/core-update', json={'core': 'snell-v5'}, headers=self.h).json['error'])
        self.assertIn("1.4.0", self.client.post('/api/nodes/old/core-update', json={'core': 'xray'}, headers=self.h).json['error'])
        r = self.client.post('/api/nodes/a/core-update', json={'core': 'xray'}, headers=self.h)
        self.assertEqual(r.status_code, 201, r.json)
        with self.store.connect() as db:
            task = db.execute("SELECT * FROM tasks WHERE id=?", (r.json['id'],)).fetchone()
        self.assertEqual((task['action'], json.loads(task['request'])), ('core_update', {'action': 'core_update', 'params': {'core': 'xray'}}))
        self.assertIn("未完成", self.client.post('/api/nodes/a/core-update', json={'core': 'xray'}, headers=self.h).json['error'])

    def test_all_nodes(self):
        newer = {"xray": {"current": "25.1.30", "latest": "25.3.6"}}
        self.node("ok", newer)
        self.node("latest", {"xray": {"current": "25.3.6", "latest": "25.3.6"}})
        self.node("none", {"singbox": {"current": "1.14.2", "latest": "1.14.2", "stats": True}})
        self.node("offline", newer, seen=time.time() - 600)
        self.node("maint", newer, maintenance=1)
        self.node("old", {}, version=0)
        self.node("unknown", {"xray": {"current": "25.1.30"}})
        self.node("snell", {"snell-v5": {"current": "5.0.1", "latest": "6.0.0"}})       # reported by a 1.4.1 node
        r = self.client.post('/api/nodes/core-update-all', json={'core': 'xray'}, headers=self.h).json
        self.assertEqual(r['queued'], ['ok'])
        self.assertEqual({s['name']: s['reason'] for s in r['skipped']}, {
            'offline': '节点离线', 'maint': '节点正在维护', 'old': '节点程序需更新到 1.4.0 及以上', 'unknown': '暂未获取到最新稳定版本'})
        again = self.client.post('/api/nodes/core-update-all', json={'core': 'xray'}, headers=self.h).json
        self.assertEqual(again['queued'], [])
        self.assertIn({'name': 'ok', 'reason': '有未完成或待核对的任务'}, again['skipped'])
        self.assertEqual(self.client.post('/api/nodes/core-update-all', json={'core': 'x'}, headers=self.h).status_code, 400)
        r = self.client.post('/api/nodes/core-update-all', json={'core': 'snell-v5'}, headers=self.h).json
        self.assertEqual(r['queued'], [])
        self.assertIn({'name': 'snell', 'reason': '暂未获取到最新稳定版本'}, r['skipped'])
        self.assertIn('最新稳定版本', self.client.post('/api/nodes/snell/core-update', json={'core': 'snell-v5'}, headers=self.h).json['error'])


if __name__ == '__main__':
    unittest.main()
