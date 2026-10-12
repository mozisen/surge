import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent.__main__ import Agent
from agent.bridge import Bridge
from agent.inventory import inventory, sanitize_snapshot
from agent.runtime import Runtime, atomic_write
from vaio.common import config_revision, validate_platform_task, validate_upgrade_task
from test_agent import FakeRuntime, fixture

spec = importlib.util.spec_from_file_location("update_agent", Path(__file__).resolve().parent.parent / "scripts/update-agent.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def stage_with(tmp, script, pin=None):
    stage = Path(tmp) / "stage"
    (stage / "vendor").mkdir(parents=True)
    (stage / "agent").mkdir()
    (stage / "vendor/vless-server.sh").write_bytes(script)
    (stage / "agent/runtime.py").write_text('UPSTREAM_SHA = "%s"\n' % (pin or hashlib.sha256(script).hexdigest()))
    return stage


class MainScriptReplacement(unittest.TestCase):
    def test_pin_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = stage_with(tmp, b'readonly VERSION="3.7.4-preview.5"\n', pin="0" * 64)
            with self.assertRaisesRegex(RuntimeError, "校验失败"):
                updater.bundle_script(stage)

    def test_install_replace_unchanged_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            new = b'readonly VERSION="3.7.4-preview.5"\n'
            stage, target = stage_with(tmp, new), Path(tmp) / "bin/vless-server.sh"
            target.parent.mkdir()
            self.assertEqual(updater.replace_main_script(stage, target), "installed")
            self.assertEqual((target.read_bytes(), oct(target.stat().st_mode & 0o777)), (new, "0o755"))
            updater.restore_main_script("installed", target)
            self.assertFalse(target.exists())
            target.write_bytes(b'readonly VERSION="3.7.4-preview.2"\n')
            backup = updater.replace_main_script(stage, target)
            self.assertEqual((Path(backup).read_bytes(), target.read_bytes()), (b'readonly VERSION="3.7.4-preview.2"\n', new))
            self.assertEqual(updater.script_version(target), "3.7.4-preview.5")
            self.assertIsNone(updater.replace_main_script(stage, target))
            updater.restore_main_script(backup, target)
            self.assertEqual(updater.script_version(target), "3.7.4-preview.2")
            self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["vless-server.sh"])

    def test_symlink_target_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage, target = stage_with(tmp, b'x\n'), Path(tmp) / "vless-server.sh"
            target.symlink_to(Path(tmp) / "elsewhere")
            with self.assertRaisesRegex(RuntimeError, "普通文件"):
                updater.replace_main_script(stage, target)

    def test_waits_for_task_report_and_writes_bounded_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal, task = Path(tmp) / "journal.json", str(uuid.uuid4())
            journal.write_text(json.dumps({task: {"status": "succeeded", "sent": True}}))
            updater.wait_reported(journal, task, timeout=1, pause=0)
            journal.write_text(json.dumps({task: {"status": "running", "sent": False}}))
            with self.assertRaisesRegex(RuntimeError, "未能上报"):
                updater.wait_reported(journal, task, timeout=0.05, pause=0.01)
            result = Path(tmp) / "last-upgrade.json"
            updater.write_result({"status": "rolled_back", "message": "x" * 500}, result)
            self.assertEqual(len(json.loads(result.read_text())["message"]), 300)


class LaunchUpgrade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Runtime(Path(self.tmp.name) / "cfg", Path(self.tmp.name) / "state")
        self.task = str(uuid.uuid4())

    def tearDown(self):
        self.tmp.cleanup()

    def test_systemd_runs_in_its_own_unit(self):
        calls = []
        with patch("agent.runtime.Path.exists", return_value=False), patch("agent.runtime.shutil.which", return_value="/usr/bin/systemd-run"), \
                patch.object(Runtime, "command", side_effect=lambda argv, timeout=120, capture=False: calls.append(argv)):
            self.assertEqual(self.runtime.launch_upgrade(self.task), "systemd-run")
        argv = calls[0]
        self.assertEqual(argv[:3], ["systemd-run", "--unit", "vaio-agent-upgrade-" + self.task[:8]])
        self.assertIn("--collect", argv)
        self.assertIn("KillMode=process", argv)
        self.assertEqual(argv[-2:], ["--task", self.task])
        self.assertTrue(argv[-3].endswith("scripts/update-agent.py"))

    def test_openrc_detaches_into_new_session(self):
        with patch("agent.runtime.Path.exists", side_effect=lambda: True), patch("agent.runtime.subprocess.Popen") as popen:
            self.assertEqual(self.runtime.launch_upgrade(self.task), "detached")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.args[0][-2:], ["--task", self.task])

    def test_invalid_task_id_rejected(self):
        with self.assertRaises(ValueError):
            self.runtime.launch_upgrade("../../etc")


class UpgradeTask(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "cfg"; self.cfg.mkdir()
        self.state = Path(self.tmp.name) / "state"
        atomic_write(self.cfg / "db.json", json.dumps(fixture()))
        self.runtime = FakeRuntime(self.cfg / "config.json"); self.runtime.path.write_text("original")
        self.launched = []
        self.runtime.launch_upgrade = lambda task_id: self.launched.append(task_id) or "systemd-run"
        self.bridge = Bridge(self.cfg, self.state, self.runtime)

    def tearDown(self):
        self.tmp.cleanup()

    def test_launches_once_and_is_journaled(self):
        task = {"id": str(uuid.uuid4()), "action": "agent_upgrade", "params": {}}
        result = self.bridge.execute(task)
        self.assertIn("独立进程", result["steps"][0])
        self.assertEqual(self.bridge.execute(task), result)
        self.assertEqual(self.launched, [task["id"]])
        for bad in ({"action": "agent_upgrade", "params": {"url": "https://evil"}}, {"action": "agent_upgrade"}):
            with self.assertRaises(ValueError):
                validate_upgrade_task(bad)

    def test_platform_mode_rejects_instance_user_tasks(self):
        db = fixture(); db["meta"]["user_authority"] = "platform"
        atomic_write(self.cfg / "db.json", json.dumps(db))
        task = {"id": str(uuid.uuid4()), "action": "user_update", "protocol": "vless", "core": "xray", "port": 24443,
                "params": {"name": "default", "enabled": False}, "revision": config_revision(db)}
        with self.assertRaisesRegex(ValueError, "平台管理"):
            self.bridge.execute(task)
        self.assertEqual(self.bridge.authority(), "platform")

    def test_set_authority_validation(self):
        validate_platform_task({"action": "platform_apply", "params": {"ops": [{"op": "set_authority", "mode": "platform"}]}})
        for ops in ([{"op": "set_authority", "mode": "both"}], [{"op": "set_authority", "mode": "script", "account_id": str(uuid.uuid4())}],
                    [{"op": "set_authority", "mode": "script"}, {"op": "reset_usage", "account_id": str(uuid.uuid4())}]):
            with self.assertRaises(ValueError):
                validate_platform_task({"action": "platform_apply", "params": {"ops": ops}})


class Snapshot(unittest.TestCase):
    def test_authority_upgrade_fields_and_last_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = fixture(); db["meta"]["user_authority"] = "platform"
            atomic_write(Path(tmp) / "db.json", json.dumps(db))
            data = sanitize_snapshot(inventory(tmp, status=lambda _: "running"))
            self.assertEqual((data["user_authority"], data["authority_version"], data["upgrade_version"]), ("platform", 1, 1))
            clean = sanitize_snapshot({"instances": [], "user_authority": "root", "authority_version": 2,
                                       "last_upgrade": {"status": "pwned", "at": "x", "to": "0.3.0-preview.12" * 9, "message": "m" * 999}})
            self.assertEqual((clean["user_authority"], clean["authority_version"], clean["last_upgrade"]["status"], clean["last_upgrade"]["at"]), ("script", 0, "failed", 0))
            self.assertEqual((len(clean["last_upgrade"]["to"]), len(clean["last_upgrade"]["message"])), (40, 300))
            state = Path(tmp) / "state"
            agent = Agent({"url": "https://panel.example", "node_id": "n", "token": "t"}, state, cfg=Path(tmp))
            atomic_write(state / "last-upgrade.json", json.dumps({"status": "succeeded", "to": "0.3.0-preview.12", "at": 1}))
            sent = []
            with patch.object(agent, "api", side_effect=lambda suffix, payload: sent.append(payload) or {}):
                agent.cycle(None, None)
            self.assertEqual(sent[-1]["snapshot"]["last_upgrade"]["to"], "0.3.0-preview.12")


if __name__ == "__main__":
    unittest.main()
