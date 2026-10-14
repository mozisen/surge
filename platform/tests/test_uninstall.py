"""卸载命令：vaio-panel uninstall 删除面板全部文件（可先备份），vaio-agent uninstall 只删节点程序并把定时任务改回节点脚本。在临时根目录中运行，系统命令为桩。"""
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
STUB = '''#!/bin/sh
echo "$(basename "$0") $*" >> "{log}"
case "$(basename "$0")" in
  id) echo 0 ;;
  # Like the real crontab: read all input, then replace the table (a pipeline reading -l must not see it truncated).
  crontab) if [ "$1" = -l ]; then cat "{cron}"; else t=$(mktemp); cat > "$t"; mv "$t" "{cron}"; fi ;;
esac
exit 0
'''


class Uninstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'root'
        self.bin = Path(self.tmp.name) / 'bin'
        self.bin.mkdir()
        self.log = Path(self.tmp.name) / 'calls'
        self.cron = Path(self.tmp.name) / 'crontab'
        self.cron.write_text('0 3 * * * /usr/bin/bash /opt/vaio-agent/vendor/vless-server.sh --check-expire # check-expire\n')
        for name in ('id', 'systemctl', 'nginx', 'userdel', 'crontab'):
            (self.bin / name).write_text(STUB.format(log=self.log, cron=self.cron))
            (self.bin / name).chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, *paths):
        for path in paths:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('x')

    def run_script(self, name, *args):
        env = {**os.environ, 'PATH': str(self.bin) + ':/usr/bin:/bin', 'VAIO_UNINSTALL_PREFIX': str(self.root)}
        return subprocess.run(['sh', str(SCRIPTS / name), 'uninstall', *args], env=env, capture_output=True, text=True, timeout=30)

    def test_panel_uninstall_with_backup(self):
        keep = ['etc/letsencrypt/live/io.example.com/fullchain.pem', 'etc/nginx/sites-available/other', 'opt/vaio-agent/agent/__main__.py']
        gone = ['opt/vaio-panel/vaio/server.py', 'opt/vaio-panel-releases/1/vaio/server.py', 'opt/vaio-panel-before-1/x', 'etc/vaio-panel/panel.env',
                'var/lib/vaio-panel/panel.sqlite', 'var/backups/vaio-panel/1/panel.sqlite', 'etc/nginx/sites-available/vaio-panel',
                'etc/nginx/sites-enabled/vaio-panel', 'etc/systemd/system/vaio-panel.service', 'etc/systemd/system/vaio-panel-address.path',
                'etc/systemd/system/vaio-panel-address.service', 'etc/systemd/system/vaio-panel-update.path', 'usr/local/bin/vaio-panel']
        self.make(*keep, *gone)
        backup = Path(self.tmp.name) / 'final.tar.gz'
        result = self.run_script('vaio-panel', '--yes', '--backup', str(backup))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in gone:
            self.assertFalse((self.root / path).exists(), path)
        for path in keep:
            self.assertTrue((self.root / path).exists(), path)
        with tarfile.open(backup) as archive:
            self.assertIn('var/lib/vaio-panel/panel.sqlite', archive.getnames())
        calls = self.log.read_text()
        self.assertIn('systemctl stop vaio-panel-address.path vaio-panel-address.service vaio-panel-update.path vaio-panel', calls)
        self.assertIn('userdel vaio-panel', calls)
        self.assertNotIn('vaio-agent', calls)

    def test_panel_uninstall_needs_confirmation(self):
        self.make('etc/vaio-panel/panel.env')
        env = {**os.environ, 'PATH': str(self.bin) + ':/usr/bin:/bin', 'VAIO_UNINSTALL_PREFIX': str(self.root)}
        result = subprocess.run(['sh', str(SCRIPTS / 'vaio-panel'), 'uninstall', '--bogus'], env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.root / 'etc/vaio-panel/panel.env').exists())

    def test_agent_uninstall_keeps_proxies_and_repoints_cron(self):
        keep = ['etc/vless-reality/db.json', 'usr/local/bin/vless-server.sh', 'opt/vaio-panel/vaio/server.py']
        gone = ['opt/vaio-agent/agent/__main__.py', 'opt/vaio-agent-backup-1/x', 'etc/vaio-agent/config.json', 'var/lib/vaio-agent/journal.json',
                'etc/systemd/system/vaio-agent.service', 'usr/local/bin/vaio-agent']
        self.make(*keep, *gone)
        (self.root / 'usr/local/bin/vless-server.sh').chmod(0o755)
        result = self.run_script('vaio-agent', '--yes')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path in gone:
            self.assertFalse((self.root / path).exists(), path)
        for path in keep:
            self.assertTrue((self.root / path).exists(), path)
        self.assertIn('/usr/local/bin/vless-server.sh --check-expire', self.cron.read_text())
        self.assertNotIn('/opt/vaio-agent/', self.cron.read_text())
        self.assertIn('systemctl stop vaio-agent', self.log.read_text())


if __name__ == '__main__':
    unittest.main()
