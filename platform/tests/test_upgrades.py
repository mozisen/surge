import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from vaio.server import agent_archive
from vaio import __version__


def load(name):
    spec = importlib.util.spec_from_file_location(name,Path(__file__).resolve().parents[1]/'scripts'/(name.replace('_','-')+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UpgradeTests(unittest.TestCase):
    def test_monorepo_extracts_only_platform(self):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode='w:gz') as archive:
            for name, content in [('surge/platform/requirements.txt', b'Flask'),
                                  ('surge/platform/vaio/server.py', b'code'),
                                  ('surge/vless-server.sh', b'not panel')]:
                item = tarfile.TarInfo(name)
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            load('update_panel').extract(payload.getvalue(), root)
            self.assertEqual((root/'vaio/server.py').read_bytes(), b'code')
            self.assertFalse((root/'vless-server.sh').exists())

    def test_agent_bundle_extracts_and_reports_version(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(load('update_agent').extract_bundle(agent_archive(),root),__version__)
            self.assertTrue((root/'scripts/vaio-agent').exists())

    def test_archives_reject_path_traversal_and_links_before_writing(self):
        for name, kind in [('../escape',tarfile.REGTYPE),('/tmp/escape',tarfile.REGTYPE),('agent/link',tarfile.SYMTYPE)]:
            payload=io.BytesIO()
            with tarfile.open(fileobj=payload,mode='w:gz') as tar:
                item=tarfile.TarInfo(name)
                item.type=kind
                item.linkname='/etc/passwd' if kind==tarfile.SYMTYPE else ''
                tar.addfile(item)
            for module, method in [('update_agent','extract_bundle'),('update_panel','extract')]:
                with tempfile.TemporaryDirectory() as folder:
                    with self.assertRaises(ValueError):
                        getattr(load(module),method)(payload.getvalue(),Path(folder))
                    self.assertEqual(list(Path(folder).iterdir()),[])

    def test_panel_failed_health_restores_code_and_keeps_database(self):
        import sqlite3
        from unittest.mock import patch
        module = load('update_panel')
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            def mapped(value):
                p = Path(value)
                return base / str(p).lstrip('/') if p.is_absolute() else p
            root = mapped('/opt/vaio-panel')
            root.mkdir(parents=True)
            (root/'old-marker').write_text('previous release')
            env = mapped('/etc/vaio-panel/panel.env')
            env.parent.mkdir(parents=True)
            env.write_text('VAIO_DATABASE=/data/panel.sqlite\n')
            db_path = mapped('/data/panel.sqlite')
            db_path.parent.mkdir(parents=True)
            with sqlite3.connect(db_path) as db:
                db.execute('CREATE TABLE tasks(status TEXT)')
                db.execute("INSERT INTO tasks VALUES('succeeded')")
            archive = mapped('/tmp/release.tar.gz')
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b'test fixture')
            def extract(payload, target):
                (target/'scripts').mkdir()
                (target/'scripts/vaio-panel').write_text('new wrapper')
            def copy(source, target):
                source = mapped(source) if isinstance(source, str) else source
                Path(target).write_bytes(source.read_bytes())
            with patch.object(module, 'Path', side_effect=mapped), patch.object(module.os, 'geteuid', return_value=0), patch.object(module.os, 'umask'), patch.object(module, 'extract', side_effect=extract), patch.object(module.shutil, 'copy2', side_effect=copy), patch.object(module.subprocess, 'run') as run, patch.object(module.subprocess, 'check_output', return_value='0.2.1'), patch.object(module, 'download', return_value=b'{"version":"wrong"}'), patch.object(module.time, 'sleep'), patch('sys.argv',['update-panel','--archive','/tmp/release.tar.gz']):
                with self.assertRaisesRegex(RuntimeError, '健康检查失败'):
                    module.main()
            self.assertEqual((root/'old-marker').read_text(), 'previous release')
            self.assertFalse(root.is_symlink())
            self.assertEqual(run.call_args.args[0], ['systemctl','start','vaio-panel'])
            with sqlite3.connect(db_path) as db:
                self.assertEqual(db.execute('SELECT status FROM tasks').fetchone()[0], 'succeeded')
            backups=list(mapped('/var/backups/vaio-panel').glob('*/panel.sqlite'))
            self.assertEqual(len(backups),1)
