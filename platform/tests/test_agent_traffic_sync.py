"""用户流量同步：节点程序每次例行维护先运行节点脚本 --sync-traffic（不依赖脚本自己的定时任务），失败不影响到期检查。"""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import runtime as runtime_module
from agent.__main__ import Agent
from agent.runtime import Runtime


class Process:
    def __init__(self, code=0, hang=False):
        self.returncode, self.hang, self.pid = code, hang, 4242

    def wait(self, timeout=None):
        if self.hang and timeout is not None:
            raise subprocess.TimeoutExpired('bash', timeout)
        return self.returncode


class SyncTraffic(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Runtime(self.tmp.name, Path(self.tmp.name) / 'state')

    def tearDown(self):
        self.tmp.cleanup()

    def test_runs_vendored_script_and_logs_beside_db(self):
        with patch.object(runtime_module.subprocess, 'Popen', return_value=Process()) as popen:
            self.runtime.sync_traffic()
        argv = popen.call_args.args[0]
        self.assertEqual(argv, ['bash', str(runtime_module.ROOT / 'vendor/vless-server.sh'), '--sync-traffic'])
        self.assertEqual(Path(popen.call_args.kwargs['stdout'].name), Path(self.tmp.name) / 'traffic-sync.log')
        self.assertIs(popen.call_args.kwargs['stdin'], subprocess.DEVNULL)

    def test_failure_timeout_and_integrity(self):
        with patch.object(runtime_module.subprocess, 'Popen', return_value=Process(code=1)):
            with self.assertRaisesRegex(RuntimeError, '退出码 1'):
                self.runtime.sync_traffic()
        with patch.object(runtime_module.subprocess, 'Popen', return_value=Process(hang=True)), \
                patch.object(runtime_module.os, 'killpg') as kill:
            with self.assertRaisesRegex(RuntimeError, '超时'):
                self.runtime.sync_traffic(timeout=1)
            kill.assert_called_once()
        with patch.object(runtime_module, 'UPSTREAM_SHA', '0' * 64), \
                patch.object(runtime_module.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(RuntimeError, '完整性'):
                self.runtime.sync_traffic()
            popen.assert_not_called()

    def test_log_is_capped(self):
        log = Path(self.tmp.name) / 'traffic-sync.log'
        log.write_bytes(b'x' * (1024 * 1024 + 1))
        with patch.object(runtime_module.subprocess, 'Popen', return_value=Process()):
            self.runtime.sync_traffic()
        self.assertEqual(log.stat().st_size, 0)


class Maintain(unittest.TestCase):
    def agent(self, tmp, script_api=True):
        calls = []
        bridge = MagicMock()
        bridge.runtime.sync_traffic.side_effect = lambda: calls.append('sync')
        bridge.reconcile.side_effect = lambda: calls.append('reconcile')
        agent = Agent({'url': 'https://panel.example', 'node_id': 'n', 'token': 't'}, Path(tmp) / 'state', cfg=Path(tmp), bridge=bridge)
        agent.script_api = object() if script_api else None
        return agent, bridge, calls

    def test_sync_before_reconcile_and_refresh_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, bridge, calls = self.agent(tmp)
            agent.snapshot_at = 10 ** 9
            agent.maintain()
            self.assertEqual(calls, ['sync', 'reconcile'])
            self.assertEqual(agent.snapshot_at, 0)

    def test_sync_failure_does_not_block_enforcement(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, bridge, calls = self.agent(tmp)
            bridge.runtime.sync_traffic.side_effect = RuntimeError('流量同步失败（退出码 1）')
            with self.assertLogs(level='WARNING') as logs:
                agent.maintain()
            bridge.reconcile.assert_called_once()
            self.assertIn('用户流量同步失败', logs.output[0])

    def test_no_sync_without_node_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, bridge, calls = self.agent(tmp, script_api=False)
            agent.maintain()
            self.assertEqual(calls, ['reconcile'])


if __name__ == '__main__':
    unittest.main()
