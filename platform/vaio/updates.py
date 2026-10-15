"""Panel update check: the newest vX.Y.Z tag of mozisen/vaio-panel, cached so opening the panel stays fast."""
import json
import re
import time
import urllib.request

REPOSITORY = "mozisen/vaio-panel"
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
CACHE = 3600              # a successful check (background badge)
FORCED = 60               # opening the update dialog re-checks, at most once a minute
RETRY = 30 * 60           # after GitHub could not be reached


def version_key(text):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in match.groups()) if match else None


def fetch_latest():
    """Largest release tag (only vX.Y.Z; preview builds are never offered)."""
    request = urllib.request.Request("https://api.github.com/repos/%s/tags?per_page=100" % REPOSITORY,
                                     headers={"User-Agent": "Vaio-Panel", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        tags = json.loads(response.read(1024 * 1024))
    versions = [t["name"] for t in tags if isinstance(t, dict) and isinstance(t.get("name"), str) and TAG.fullmatch(t["name"])]
    return max(versions, key=version_key) if versions else None


def _cached(db):
    row = db.execute("SELECT value FROM settings WHERE key='update_check'").fetchone()
    return json.loads(row[0]) if row else {}


def _due(cached, now, force):
    age = now - cached.get("at", 0)
    return not cached or age > (FORCED if force else CACHE if cached.get("ok") else RETRY)


def _fetch(cached, now, fetch):
    try:
        return {"at": now, "ok": True, "latest": (fetch or fetch_latest)()}
    except Exception:
        return {"at": now, "ok": False, "latest": cached.get("latest")}


def _result(cached, current):
    latest = cached.get("latest")
    newer = bool(latest and version_key(latest) and version_key(current) and version_key(latest) > version_key(current))
    return {"current": current, "latest": latest, "newer": newer, "checked": cached["at"], "reachable": cached.get("ok", False)}


def check(db, current, now=None, fetch=None, force=False):
    """Cached result {latest, newer, checked}; a failed check is silent and retried later.
    force (the admin opened the update dialog) re-checks unless the last check is under a minute old."""
    now = time.time() if now is None else now
    cached = _cached(db)
    if _due(cached, now, force):
        cached = _fetch(cached, now, fetch)
        db.execute("INSERT OR REPLACE INTO settings VALUES('update_check',?)", (json.dumps(cached),))
    return _result(cached, current)


def refresh(store, current, now=None, fetch=None, force=False):
    """check() for request handlers: GitHub is asked with no transaction open, so the database write lock is
    never held for the request (up to 5 s); the newer of two concurrent checks is kept."""
    now = time.time() if now is None else now
    with store.connect() as db:
        cached = _cached(db)
    if _due(cached, now, force):
        fresh = _fetch(cached, now, fetch)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            stored = _cached(db)
            if stored.get("at", 0) > fresh["at"]:
                fresh = stored
            else:
                db.execute("INSERT OR REPLACE INTO settings VALUES('update_check',?)", (json.dumps(fresh),))
        cached = fresh
    return _result(cached, current)
