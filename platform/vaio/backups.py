"""Online SQLite backups and offline, verified restore."""
import datetime
import os
import re
import sqlite3
import tempfile
import uuid
from pathlib import Path


def directory(store):
    path = Path(os.environ.get('VAIO_BACKUP_DIR', str(Path(store.path).parent / 'backups')))
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def resolve(store, name):
    if not re.fullmatch(r'panel-[0-9T-]+-[a-f0-9]{8}\.sqlite', name or ''):
        raise ValueError('备份名称无效')
    path = directory(store) / name
    if path.is_symlink() or not path.is_file():
        raise ValueError('备份不存在')
    return path


def verify(path):
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('备份完整性校验失败')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'settings', 'nodes', 'tasks', 'sessions', 'audit'} <= tables or db.execute('PRAGMA user_version').fetchone()[0] > 1:
            raise ValueError('备份格式不兼容')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('备份关联校验失败')
        return {'nodes': db.execute('SELECT count(*) FROM nodes').fetchone()[0], 'tasks': db.execute('SELECT count(*) FROM tasks').fetchone()[0]}


def create(store):
    name = 'panel-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H-%M-%S') + '-' + uuid.uuid4().hex[:8] + '.sqlite'
    target = directory(store) / name
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix='.backup-')
    os.close(fd)
    try:
        with store.connect() as source, sqlite3.connect(temp) as dest:
            source.backup(dest)
        verify(temp)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    # Retain seven newest verified online snapshots, never unrelated files.
    for old in sorted(directory(store).glob('panel-*.sqlite'), reverse=True)[7:]:
        old.unlink()
    return name


def listing(store):
    return [{'name': p.name, 'size': p.stat().st_size, 'at': p.stat().st_mtime} for p in sorted(directory(store).glob('panel-*.sqlite'), reverse=True) if not p.is_symlink()][:7]


def drill(store, name):
    source = resolve(store, name)
    with tempfile.TemporaryDirectory(dir=directory(store)) as temp:
        copy = Path(temp) / 'restore.sqlite'
        with sqlite3.connect(str(source)) as src, sqlite3.connect(str(copy)) as dst:
            src.backup(dst)
        return verify(copy)


def restore(store, name):
    source = resolve(store, name)
    verify(source)
    # Caller must stop the panel first; preserve a fresh fallback before replacement.
    fd, temp = tempfile.mkstemp(dir=Path(store.path).parent, prefix='.restore-')
    os.close(fd)
    try:
        with sqlite3.connect(str(source)) as src, sqlite3.connect(temp) as dst:
            src.backup(dst)
            dst.execute('DELETE FROM sessions')
            dst.execute('UPDATE nodes SET enroll_hash=NULL,enroll_expires=NULL')
            if dst.execute("SELECT 1 FROM sqlite_master WHERE name='notifications'").fetchone():
                dst.execute("UPDATE notifications SET status='unknown' WHERE status IN ('pending','sending')")
            dst.execute("UPDATE tasks SET status='cancelled',message='备份恢复后取消排队任务' WHERE status='queued'")
            dst.execute("UPDATE tasks SET status='unknown',message='备份恢复后结果未知，请人工核对' WHERE status='running'")
            dst.commit()
        verify(temp)
        create(store)
        stat = Path(store.path).stat()
        os.chown(temp, stat.st_uid, stat.st_gid)
        os.replace(temp, store.path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
