"""Platform user's own page: what a signed-in user may see and export. Only this user's data; no admin note,
node or account IDs, server addresses or server-side configuration."""
import datetime
import json
import time
import uuid

from . import platform_users
from .common import validate_task

SHARE_TTL = 600


def view(db, user, now=None):
    now = time.time() if now is None else now
    nodes = {n["id"]: n for n in db.execute("SELECT * FROM nodes")}
    used = platform_users.usage(db, user["id"])
    links = []
    for link in db.execute("SELECT * FROM platform_links WHERE user_id=? AND removing IS NULL ORDER BY created", (user["id"],)):
        node = nodes.get(link["node_id"])
        snapshot = json.loads(node["snapshot"]) if node else {}
        account = (snapshot.get("accounts") or {}).get(link["account_id"]) or {}
        links.append({"id": link["id"], "node_name": node["name"] if node and not node["deleted"] else "已删除的服务器",
                      "online": bool(node and node["last_seen"] and now - node["last_seen"] < platform_users.ONLINE),
                      "cycle_used": link["cycle_used"],
                      "members": [{"core": m.get("core"), "protocol": m.get("protocol"), "port": m.get("port"), "enabled": m.get("enabled") is not False}
                                  for m in account.get("members", []) if isinstance(m, dict)]})
    relays = []
    from . import relays as relay_module
    for line in db.execute("SELECT * FROM relay_lines WHERE user_id=? AND removing=0 ORDER BY created", (user["id"],)):
        item = relay_module.describe(db, line, nodes)
        relays.append({"id": item["id"], "chain": [h["node_name"] for h in item["hops"]] + [item["landing"]["node_name"]],
                       "entry": "%s:%s" % (item["entry"]["host"], item["entry"]["port"]) if item["entry"]["host"] else "",
                       "protocol": item["landing"]["protocol"], "state": item["state"], "port_only": item["port_only"]})
    tg = db.execute("SELECT * FROM platform_tg WHERE user_id=?", (user["id"],)).fetchone()
    return {"name": user["name"], "enabled": bool(user["enabled"]), "expire_date": user["expire_date"], "quota": user["quota"],
            "reset_day": user["reset_day"], "cycle": user["cycle"], "used": used,
            "state": platform_users.state_of(user, used, datetime.date.fromtimestamp(now)),
            "links": links, "relays": relays,
            "telegram": {"bound": bool(tg and tg["chat_id"] is not None), "username": (tg["username"] or "") if tg else "",
                         "bound_at": tg["bound_at"] if tg else None, "code_pending": bool(tg and tg["code_expires"] and tg["code_expires"] > now)}}


BUSY = 120


def busy(db, user_id, now=None):
    """One export at a time; a request a server never picked up (it went offline) stops blocking after two minutes."""
    now = time.time() if now is None else now
    return db.execute("SELECT 1 FROM tasks WHERE request_key LIKE ? AND status IN ('queued','running') AND created>?",
                      ("user-share:" + user_id + ":%", now - BUSY)).fetchone()


def share_link(db, user, data, now=None):
    """Connection for one of the user's own protocol members; returns (node_id, request)."""
    now = time.time() if now is None else now
    if set(data) != {"link_id", "core", "protocol", "port"} or not all(isinstance(data[k], str) for k in ("link_id", "core", "protocol")) \
            or type(data["port"]) is not int:
        raise ValueError("导出参数无效")
    link = db.execute("SELECT * FROM platform_links WHERE id=? AND user_id=? AND removing IS NULL", (data["link_id"], user["id"])).fetchone()
    node = db.execute("SELECT * FROM nodes WHERE id=? AND deleted IS NULL AND revoked=0", (link["node_id"],)).fetchone() if link else None
    if not link or not node:
        raise LookupError("协议不存在")
    snapshot = json.loads(node["snapshot"])
    account = (snapshot.get("accounts") or {}).get(link["account_id"]) or {}
    member = next((m for m in account.get("members", []) if isinstance(m, dict)
                   and (m.get("core"), m.get("protocol"), m.get("port")) == (data["core"], data["protocol"], data["port"])), None)
    if not member:
        raise LookupError("协议不存在")
    if member.get("enabled") is False:
        raise ValueError("该协议已停用，无法导出连接")
    if not node["last_seen"] or now - node["last_seen"] >= platform_users.ONLINE or node["maintenance"]:
        raise ValueError("服务器离线或维护中，请稍后再试")
    if snapshot.get("config_details_version") != 2:
        raise ValueError("服务器的节点程序需要升级后才能导出，请联系管理员")
    request = validate_task({"action": "share", "protocol": data["protocol"], "core": data["core"], "port": data["port"],
                             "params": {"name": member.get("name") or user["name"]}})
    return node["id"], request


def queue(db, user_id, node_id, request, now=None):
    task_id = str(uuid.uuid4())
    db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
               (task_id, node_id, "share", json.dumps(request), "queued", time.time() if now is None else now,
                "user-share:" + user_id + ":" + task_id))
    return task_id


def own_task(db, user_id, task_id):
    return db.execute("SELECT * FROM tasks WHERE id=? AND action='share' AND request_key LIKE ?",
                      (task_id, "user-share:" + user_id + ":%")).fetchone()


def task_view(row, now=None):
    now = time.time() if now is None else now
    result = json.loads(row["result"] or "{}")
    fresh = row["status"] == "succeeded" and row["finished"] and now - row["finished"] < SHARE_TTL
    return {"status": row["status"], "message": row["message"], "connection": result.get("connection", "") if fresh else ""}
