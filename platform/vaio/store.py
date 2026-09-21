import contextlib
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(ip TEXT PRIMARY KEY, count INTEGER NOT NULL, until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS nodes(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, group_name TEXT NOT NULL DEFAULT '',
 enroll_hash TEXT, enroll_expires REAL, token_hash TEXT, revoked INTEGER NOT NULL DEFAULT 0,
 adopted INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, last_seen REAL,
 snapshot TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS tasks(
 id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(id), action TEXT NOT NULL,
 request TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, started REAL, finished REAL,
 result TEXT, message TEXT NOT NULL DEFAULT '', request_key TEXT UNIQUE NOT NULL);
CREATE INDEX IF NOT EXISTS task_node ON tasks(node_id, status, created);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at REAL NOT NULL, event TEXT NOT NULL, node_id TEXT, detail TEXT NOT NULL);
"""


class Store:
    def __init__(self, path):
        self.path = str(path)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), mode=0o700, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise RuntimeError("数据库来自更新版本，请使用对应版本面板")
            columns = {row[1] for row in db.execute("PRAGMA table_info(nodes)")}
            for name, definition in (("notes", "TEXT NOT NULL DEFAULT ''"),
                                     ("deleted", "REAL"), ("maintenance", "INTEGER NOT NULL DEFAULT 0")):
                if name not in columns:
                    db.execute("ALTER TABLE nodes ADD COLUMN " + name + " " + definition)
            db.execute("PRAGMA user_version=1")
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def setting(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
