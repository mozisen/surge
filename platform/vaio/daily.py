"""Per-day traffic of every server (network interface receive + send), for the overview's today / this month totals.
Added once a minute from the cumulative counters the nodes report; a counter that drops (reboot) counts its new value."""
import datetime
import json
import time

SCHEMA = '''
CREATE TABLE IF NOT EXISTS traffic_daily(node_id TEXT NOT NULL, day TEXT NOT NULL, rx INTEGER NOT NULL DEFAULT 0, tx INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(node_id, day));
CREATE TABLE IF NOT EXISTS traffic_last(node_id TEXT PRIMARY KEY, rx INTEGER NOT NULL, tx INTEGER NOT NULL);
'''
KEEP_DAYS = 400


def _day(at):
    return datetime.date.fromtimestamp(at).isoformat()


def _counters(metrics):
    rx, tx = (metrics or {}).get("network_rx"), (metrics or {}).get("network_tx")
    if type(rx) not in (int, float) or type(tx) not in (int, float) or rx < 0 or tx < 0:
        return None
    return int(rx), int(tx)


def record(db, node_id, metrics, now=None):
    """Called inside the poll transaction once per new minute sample."""
    counters = _counters(metrics)
    if counters is None:
        return
    now = time.time() if now is None else now
    rx, tx = counters
    last = db.execute("SELECT rx, tx FROM traffic_last WHERE node_id=?", (node_id,)).fetchone()
    if last is not None:
        drx = rx - last[0] if rx >= last[0] else rx
        dtx = tx - last[1] if tx >= last[1] else tx
        if drx or dtx:
            db.execute("INSERT INTO traffic_daily(node_id, day, rx, tx) VALUES(?,?,?,?) "
                       "ON CONFLICT(node_id, day) DO UPDATE SET rx=rx+excluded.rx, tx=tx+excluded.tx", (node_id, _day(now), drx, dtx))
    db.execute("INSERT OR REPLACE INTO traffic_last(node_id, rx, tx) VALUES(?,?,?)", (node_id, rx, tx))


def backfill(db):
    """Once, on upgrade: rebuild the days still covered by the minute samples (kept 7 days)."""
    if db.execute("SELECT 1 FROM settings WHERE key='traffic_daily_backfilled'").fetchone():
        return
    if not db.execute("SELECT 1 FROM traffic_last LIMIT 1").fetchone():
        for (node_id,) in db.execute("SELECT DISTINCT node_id FROM samples").fetchall():
            for bucket, metrics in db.execute("SELECT bucket, metrics FROM samples WHERE node_id=? ORDER BY bucket", (node_id,)).fetchall():
                try:
                    record(db, node_id, json.loads(metrics), bucket * 60)
                except ValueError:
                    continue
    db.execute("INSERT OR REPLACE INTO settings VALUES('traffic_daily_backfilled','1')")


def prune(db, now=None):
    now = time.time() if now is None else now
    db.execute("DELETE FROM traffic_daily WHERE day < ?", (_day(now - KEEP_DAYS * 86400),))


def totals(db, now=None):
    """{today: {rx, tx}, month: {rx, tx}} over all servers, in the panel's time zone."""
    today = _day(time.time() if now is None else now)
    row = db.execute("SELECT COALESCE(SUM(rx),0), COALESCE(SUM(tx),0) FROM traffic_daily WHERE day=?", (today,)).fetchone()
    month = db.execute("SELECT COALESCE(SUM(rx),0), COALESCE(SUM(tx),0) FROM traffic_daily WHERE day>=? AND day<=?",
                       (today[:8] + "01", today)).fetchone()
    return {"today": {"rx": row[0], "tx": row[1]}, "month": {"rx": month[0], "tx": month[1]}}
