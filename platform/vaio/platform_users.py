"""Platform users: one person across nodes, each node holding a unified account.

Only nodes whose user authority is the platform are managed here, and on those the
panel is the single writer: the node account always converges to the panel's
values. Every node change goes through one platform_apply task per node, never
replayed when its outcome is unknown.
"""
import datetime
import hashlib
import json
import re
import time
import uuid

from .common import ACCOUNT_FIELDS, UUID_PATTERN, require_text, validate_platform_task

SCHEMA = '''
CREATE TABLE IF NOT EXISTS platform_users(
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, note TEXT NOT NULL DEFAULT '',
 enabled INTEGER NOT NULL DEFAULT 1, expire_date TEXT NOT NULL DEFAULT '',
 quota INTEGER NOT NULL DEFAULT 0, reset_day INTEGER NOT NULL DEFAULT 0,
 cycle TEXT NOT NULL DEFAULT 'total', mtime TEXT NOT NULL DEFAULT '{}', deleting TEXT,
 created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS platform_links(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES platform_users(id),
 node_id TEXT NOT NULL REFERENCES nodes(id), account_id TEXT NOT NULL,
 origin TEXT NOT NULL, base TEXT, base_rev INTEGER, members TEXT NOT NULL DEFAULT '[]',
 cycle_used INTEGER NOT NULL DEFAULT 0, last_raw TEXT NOT NULL DEFAULT '{}',
 state TEXT NOT NULL DEFAULT 'pending', removing TEXT, notice TEXT NOT NULL DEFAULT '',
 retry_after REAL NOT NULL DEFAULT 0, created REAL NOT NULL,
 UNIQUE(user_id, node_id), UNIQUE(node_id, account_id));
CREATE TABLE IF NOT EXISTS platform_pending(
 id INTEGER PRIMARY KEY, link_id TEXT NOT NULL REFERENCES platform_links(id) ON DELETE CASCADE,
 op TEXT NOT NULL, task_id TEXT, created REAL NOT NULL);
'''

GIB = 1073741824
RETRY_DELAY = 300
ONLINE = 45
STATE_TEXT = {"": "正常", "manual": "已停用", "expired": "已到期", "quota": "流量已用尽", "platform_quota": "平台总流量已用尽"}


def cycle_key(day, today):
    if not day:
        return "total"
    start = today.replace(day=day)
    if today < start:
        start = (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=day)
    return start.isoformat()


def fields_of(row):
    return {"name": row["name"], "note": row["note"], "enabled": bool(row["enabled"]), "expire_date": row["expire_date"],
            "quota": row["quota"], "reset_day": row["reset_day"]}


def validate_fields(data, create=False):
    allowed = {"name", "note", "enabled", "expire_date", "quota_gb", "reset_day"}
    if not isinstance(data, dict) or set(data) - allowed or (create and "name" not in data):
        raise ValueError("用户字段无效")
    out = {}
    if "name" in data:
        out["name"] = require_text(data["name"], "用户名", 32, r"[A-Za-z0-9_-]+")
    if "note" in data:
        if not isinstance(data["note"], str) or len(data["note"]) > 200 or any(ord(c) < 32 for c in data["note"]):
            raise ValueError("备注最多 200 字，且不能包含控制字符")
        out["note"] = data["note"]
    if "enabled" in data:
        if type(data["enabled"]) is not bool:
            raise ValueError("用户状态无效")
        out["enabled"] = data["enabled"]
    if "expire_date" in data:
        value = data["expire_date"]
        if not isinstance(value, str) or (value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
            raise ValueError("到期日期格式应为 YYYY-MM-DD")
        if value:
            datetime.date.fromisoformat(value)
        out["expire_date"] = value
    if "quota_gb" in data:
        if type(data["quota_gb"]) is not int or not 0 <= data["quota_gb"] <= 999999:
            raise ValueError("配额必须为 0–999999 GiB")
        out["quota"] = data["quota_gb"] * GIB
    if "reset_day" in data:
        if type(data["reset_day"]) is not int or not 0 <= data["reset_day"] <= 28:
            raise ValueError("月度重置日必须为 1–28，0 表示不自动重置")
        out["reset_day"] = data["reset_day"]
    return out


def node_accounts(node):
    return json.loads(node["snapshot"]).get("accounts", {})


def platform_managed(snapshot):
    return snapshot.get("authority_version") == 1 and snapshot.get("accounts_version") == 1 and snapshot.get("user_authority") == "platform"


def node_ready(node, now):
    snapshot = json.loads(node["snapshot"])
    return (node["deleted"] is None and not node["revoked"] and node["adopted"] and not node["maintenance"]
            and node["last_seen"] and now - node["last_seen"] < ONLINE and platform_managed(snapshot)
            and not snapshot.get("error"))


def usage(db, user_id):
    return db.execute("SELECT COALESCE(SUM(cycle_used),0) FROM platform_links WHERE user_id=?", (user_id,)).fetchone()[0]


def state_of(user, used, today):
    if not user["enabled"]:
        return "manual"
    if user["expire_date"] and user["expire_date"] < today.isoformat():
        return "expired"
    if user["quota"] and used >= user["quota"]:
        return "quota"
    return ""


# ---------------------------------------------------------------- user API

def create_user(db, data, now=None):
    now = time.time() if now is None else now
    fields = validate_fields(data, create=True)
    if db.execute("SELECT 1 FROM platform_users WHERE lower(name)=lower(?)", (fields["name"],)).fetchone():
        raise ValueError("用户名已存在")
    identity = str(uuid.uuid4())
    # Login is always on; a random password until the admin sets one (server.py does at creation).
    from werkzeug.security import generate_password_hash
    import secrets
    password_hash = generate_password_hash(secrets.token_urlsafe(24), method="pbkdf2:sha256:600000")
    row = {"note": "", "enabled": True, "expire_date": "", "quota": 0, "reset_day": 0, **fields}
    db.execute("INSERT INTO platform_users(id,name,note,enabled,expire_date,quota,reset_day,cycle,mtime,created,updated,password_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (identity, row["name"], row["note"], int(row["enabled"]), row["expire_date"], row["quota"], row["reset_day"],
                cycle_key(row["reset_day"], datetime.date.fromtimestamp(now)), json.dumps({k: int(now) for k in ACCOUNT_FIELDS}), now, now, password_hash))
    return identity


def update_user(db, user_id, data, now=None, mtimes=None):
    """Apply field changes; mtimes (node clock) are used when a node change wins."""
    now = time.time() if now is None else now
    user = db.execute("SELECT * FROM platform_users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise ValueError("用户不存在")
    fields = data if mtimes is not None else validate_fields(data)
    if "name" in fields and db.execute("SELECT 1 FROM platform_users WHERE lower(name)=lower(?) AND id<>?", (fields["name"], user_id)).fetchone():
        raise ValueError("用户名已存在")
    current, mtime = fields_of(user), json.loads(user["mtime"])
    changed = {k: v for k, v in fields.items() if current[k] != v}
    if not changed:
        return {}
    for key, value in changed.items():
        mtime[key] = int((mtimes or {}).get(key, now))
        db.execute("UPDATE platform_users SET " + key + "=? WHERE id=?", (int(value) if key == "enabled" else value, user_id))
    if "reset_day" in changed:
        # Changing the reset day keeps this cycle's usage (same as node billing).
        db.execute("UPDATE platform_users SET cycle=? WHERE id=?", (cycle_key(changed["reset_day"], datetime.date.fromtimestamp(now)), user_id))
    db.execute("UPDATE platform_users SET mtime=?,updated=? WHERE id=?", (json.dumps(mtime), now, user_id))
    return changed


def add_link(db, user_id, node_id, members=None, now=None, trusted=False):
    """Create the user's account on a node whose users are managed by the platform."""
    now = time.time() if now is None else now
    user = db.execute("SELECT * FROM platform_users WHERE id=? AND deleting IS NULL", (user_id,)).fetchone()
    node = db.execute("SELECT * FROM nodes WHERE id=? AND deleted IS NULL AND revoked=0", (node_id,)).fetchone()
    if not user or not node:
        raise ValueError("用户或节点不存在")
    snapshot = json.loads(node["snapshot"])
    if snapshot.get("authority_version") != 1 or snapshot.get("accounts_version") != 1:
        raise ValueError("该节点程序或脚本版本过旧，不支持平台用户管理，请先升级节点")
    if snapshot.get("user_authority") != "platform":
        raise ValueError("该节点的用户由节点脚本管理，请先在节点设置中切换为平台管理")
    if db.execute("SELECT 1 FROM platform_links WHERE user_id=? AND node_id=?", (user_id, node_id)).fetchone():
        raise ValueError("该用户已关联此节点")
    targets = []
    for member in members or []:
        if not isinstance(member, dict) or set(member) != {"core", "protocol", "port"}:
            raise ValueError("协议实例无效")
        if not trusted:
            check_member_target(snapshot, member)
        targets.append({"target": {k: member[k] for k in ("core", "protocol", "port")}, "name": user["name"]})
    validate_platform_task({"action": "platform_apply", "params": {"ops": [{"op": "create", "account_id": str(uuid.uuid4()),
                            "fields": {"name": user["name"]}, "members": targets}]}})
    link_id = str(uuid.uuid4())
    db.execute("INSERT INTO platform_links(id,user_id,node_id,account_id,origin,members,state,created) VALUES(?,?,?,?,?,?,?,?)",
               (link_id, user_id, node_id, str(uuid.uuid4()), "created", json.dumps(targets), "pending", now))
    return link_id


def queue_op(db, link_id, op, now=None):
    validate_platform_task({"action": "platform_apply", "params": {"ops": [op]}})
    db.execute("INSERT INTO platform_pending(link_id,op,created) VALUES(?,?,?)", (link_id, json.dumps(op), time.time() if now is None else now))
    db.execute("UPDATE platform_links SET state='pending',retry_after=0 WHERE id=?", (link_id,))


LEGACY_SINGLE_USER = ("ss-legacy", "ss2022", "snell", "snell-v5", "snell-v6")


def check_member_target(snapshot, target, adding=True):
    """New members follow the node's protocol user modes: any multi-user instance, or an empty
    single-user instance (assigned to the user). Nodes without modes keep the old rule."""
    instance = next((i for i in snapshot.get("instances", []) if (i.get("core"), i.get("protocol"), i.get("port"))
                     == (target["core"], target["protocol"], target["port"])), None)
    if not instance or not instance.get("user_mode"):
        if target["protocol"] in LEGACY_SINGLE_USER:
            raise ValueError("该协议一用户一端口：请先为该用户安装实例，再归入")
        return
    if instance["user_mode"] == "none":
        raise ValueError("该协议不支持用户管理")
    if not instance.get("user_available"):
        raise ValueError("该协议暂未接入用户管理，请升级节点脚本")
    if adding and instance["user_mode"] == "single" and instance.get("users"):
        raise ValueError("该实例已有用户（一用户一实例），请先移除原用户")


def member_op(db, link, data):
    """Queue an explicit member change on a linked node account."""
    if not isinstance(data, dict) or set(data) - {"action", "target", "name", "mode", "count_existing"}:
        raise ValueError("成员操作参数无效")
    target = data.get("target")
    if not isinstance(target, dict) or set(target) != {"core", "protocol", "port"}:
        raise ValueError("协议实例无效")
    action = data.get("action")
    if action == "add":
        node = db.execute("SELECT snapshot FROM nodes WHERE id=?", (link["node_id"],)).fetchone()
        check_member_target(json.loads(node["snapshot"]) if node else {}, target)
        user = db.execute("SELECT name FROM platform_users WHERE id=?", (link["user_id"],)).fetchone()
        op = {"op": "member_add", "account_id": link["account_id"], "target": target, "name": data.get("name") or user["name"]}
    elif action == "claim":
        op = {"op": "member_claim", "account_id": link["account_id"], "target": target, "name": data.get("name"),
              "count_existing": data.get("count_existing", True)}
    elif action == "remove":
        mode = data.get("mode", "release")
        if mode == "delete" and target["protocol"].startswith("snell"):
            raise ValueError("Snell 成员请保留实例，或在实例管理中卸载")
        op = {"op": "member_remove", "account_id": link["account_id"], "target": target, "name": data.get("name"), "mode": mode}
    else:
        raise ValueError("成员操作无效")
    queue_op(db, link["id"], op)


def reset_credentials(db, user_id, link_id=None, member=None):
    links = db.execute("SELECT * FROM platform_links WHERE user_id=? AND removing IS NULL" + (" AND id=?" if link_id else ""),
                       (user_id, link_id) if link_id else (user_id,)).fetchall()
    if not links:
        raise ValueError("没有可重置凭据的节点")
    for link in links:
        queue_op(db, link["id"], {"op": "reset_credentials", "account_id": link["account_id"], **({"member": member} if member else {})})


def release_task(db, task_id):
    """A cancelled or manually resolved sync task: let the next plan recompute."""
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task or task["action"] != "platform_apply":
        return
    db.execute("DELETE FROM platform_pending WHERE task_id=?", (task_id,))
    accounts = {op.get("account_id") for op in json.loads(task["request"])["params"]["ops"]}
    for link in db.execute("SELECT * FROM platform_links WHERE node_id=?", (task["node_id"],)).fetchall():
        if link["account_id"] in accounts:
            db.execute("UPDATE platform_links SET state='pending',notice='',retry_after=0 WHERE id=?", (link["id"],))


INSTALL_PLAN_SCHEMA = "CREATE TABLE IF NOT EXISTS platform_install_plans(task_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, users TEXT NOT NULL, created REAL NOT NULL)"


def plan_install(db, node_id, task_id, user_ids, now=None):
    """Users to place on an instance once its install task succeeds."""
    task = db.execute("SELECT * FROM tasks WHERE id=? AND node_id=?", (task_id, node_id)).fetchone()
    if not task or task["action"] != "install" or task["status"] not in ("queued", "running"):
        raise ValueError("安装任务不存在或已结束")
    node = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    if not platform_managed(json.loads(node["snapshot"])):
        raise ValueError("该节点的用户由节点脚本管理，不能在安装时选择平台用户")
    if not isinstance(user_ids, list) or not user_ids or len(user_ids) > 200 or len(set(user_ids)) != len(user_ids):
        raise ValueError("请选择用户")
    for user_id in user_ids:
        if not db.execute("SELECT 1 FROM platform_users WHERE id=? AND deleting IS NULL", (user_id,)).fetchone():
            raise ValueError("用户不存在")
    request = json.loads(task["request"])
    if request["protocol"].startswith("snell") and len(user_ids) != 1:
        raise ValueError("Snell 一用户一实例，安装时只能选择一个用户")
    db.execute("INSERT INTO platform_install_plans VALUES(?,?,?,?)", (task_id, node_id, json.dumps(user_ids), time.time() if now is None else now))


def install_finished(db, task, status, now=None):
    plan = db.execute("SELECT * FROM platform_install_plans WHERE task_id=?", (task["id"],)).fetchone()
    if not plan:
        return
    db.execute("DELETE FROM platform_install_plans WHERE task_id=?", (task["id"],))
    if status != "succeeded":
        return
    request = json.loads(task["request"])
    target = {"core": request["core"], "protocol": request["protocol"], "port": request["port"]}
    for user_id in json.loads(plan["users"]):
        user = db.execute("SELECT * FROM platform_users WHERE id=? AND deleting IS NULL", (user_id,)).fetchone()
        if not user:
            continue
        link = db.execute("SELECT * FROM platform_links WHERE user_id=? AND node_id=? AND removing IS NULL", (user_id, task["node_id"])).fetchone()
        if link:
            queue_op(db, link["id"], {"op": "member_add", "account_id": link["account_id"], "target": target, "name": user["name"]}, now)
        else:
            # The instance was just installed empty; the snapshot may not show it yet.
            add_link(db, user_id, task["node_id"], [target], now, trusted=True)


def remove_link(db, link_id, mode):
    if mode not in ("release", "delete"):
        raise ValueError("请选择保留或删除节点上的用户")
    link = db.execute("SELECT * FROM platform_links WHERE id=?", (link_id,)).fetchone()
    if not link:
        raise ValueError("关联不存在")
    db.execute("UPDATE platform_links SET removing=?,state='pending',retry_after=0 WHERE id=?", (mode, link_id))


def delete_user(db, user_id, mode):
    if not db.execute("SELECT 1 FROM platform_users WHERE id=?", (user_id,)).fetchone():
        raise ValueError("用户不存在")
    links = db.execute("SELECT id FROM platform_links WHERE user_id=?", (user_id,)).fetchall()
    if not links:
        db.execute("DELETE FROM platform_users WHERE id=?", (user_id,))
        return True
    for link in links:
        remove_link(db, link["id"], mode)
    db.execute("UPDATE platform_users SET deleting=? WHERE id=?", (mode, user_id))
    return False


# ---------------------------------------------------------------- snapshots

def ingest(db, node_id, snapshot, now=None):
    """Called inside the poll transaction: usage accounting. A node that switched back to
    script management (from its own menu) is no longer managed: its links are dropped."""
    now = time.time() if now is None else now
    if snapshot.get("authority_version") == 1 and snapshot.get("user_authority") != "platform":
        forget_node(db, node_id, now)
        return
    accounts = snapshot.get("accounts", {}) if snapshot.get("accounts_version") == 1 else {}
    for link in db.execute("SELECT * FROM platform_links WHERE node_id=?", (node_id,)).fetchall():
        account = accounts.get(link["account_id"])
        if account is None:
            continue
        # Usage: raw script counters per member; a counter drop counts the new value once.
        last, used = json.loads(link["last_raw"]), link["cycle_used"]
        for member in account.get("members", []):
            if type(member.get("used")) is not int:
                continue
            key = "|".join(str(member[k]) for k in ("core", "protocol", "port", "name"))
            previous, raw = last.get(key), member["used"]
            used += raw if previous is None or raw < previous else raw - previous
            last[key] = raw
        db.execute("UPDATE platform_links SET cycle_used=?,last_raw=? WHERE id=?", (used, json.dumps(last), link["id"]))


def forget_node(db, node_id, now=None):
    """Stop managing a node (it is script-managed now); platform users themselves stay."""
    links = db.execute("SELECT id FROM platform_links WHERE node_id=?", (node_id,)).fetchall()
    for link in links:
        db.execute("DELETE FROM platform_pending WHERE link_id=?", (link["id"],))
        db.execute("DELETE FROM platform_links WHERE id=?", (link["id"],))
    if links:
        db.execute("INSERT INTO audit(at,event,node_id,detail) VALUES(?,?,?,?)",
                   (time.time() if now is None else now, "platform.node_released", node_id, str(len(links)) + " 个关联"))
    finish_deletions(db)


def rollover(db, now=None):
    """Panel-timezone cycles; a new cycle clears every link's usage (quota block lifts)."""
    now = time.time() if now is None else now
    today = datetime.date.fromtimestamp(now)
    for user in db.execute("SELECT * FROM platform_users WHERE reset_day>0").fetchall():
        key = cycle_key(user["reset_day"], today)
        if user["cycle"] == "total" or key > user["cycle"]:
            if user["cycle"] != "total":
                db.execute("UPDATE platform_links SET cycle_used=0 WHERE user_id=?", (user["id"],))
            db.execute("UPDATE platform_users SET cycle=? WHERE id=?", (key, user["id"]))


def reset_usage(db, user_id):
    db.execute("UPDATE platform_links SET cycle_used=0 WHERE user_id=?", (user_id,))


# ---------------------------------------------------------------- planning

def plan(db, node, now=None):
    """Operations needed on one node: (ops, pending ids, link ids)."""
    now = time.time() if now is None else now
    accounts, ops, pending_ids, link_ids = node_accounts(node), [], [], []
    for link in db.execute("SELECT * FROM platform_links WHERE node_id=? ORDER BY created", (node["id"],)).fetchall():
        if link["retry_after"] > now:
            continue
        user = db.execute("SELECT * FROM platform_users WHERE id=?", (link["user_id"],)).fetchone()
        account, before = accounts.get(link["account_id"]), len(ops)
        if link["removing"]:
            if account is not None:
                ops.append({"op": "unlink", "account_id": link["account_id"]} if link["removing"] == "release"
                           else {"op": "delete", "account_id": link["account_id"], "mode": "delete"})
        elif account is None:
            # A synced link whose account is missing from this snapshot was just created: the node's
            # report predates the task. Creating again would fail with "account exists".
            if link["origin"] == "created" and link["state"] != "synced":
                op = {"op": "create", "account_id": link["account_id"], "platform_user_id": user["id"],
                      "fields": fields_of(user), "members": json.loads(link["members"])}
                ops.append(op)
        else:
            if account.get("platform_user_id") != user["id"]:
                ops.append({"op": "link", "account_id": link["account_id"], "platform_user_id": user["id"]})
            # The panel is the only writer on platform-managed nodes: converge to its values.
            panel = fields_of(user)
            patch = {k: panel[k] for k in ACCOUNT_FIELDS if panel[k] != account.get(k)}
            if patch:
                ops.append({"op": "update", "account_id": link["account_id"], "base_rev": account.get("rev", 0), "fields": patch})
            # The panel's clock decides expiry too: nodes judge expire_date by their own date (another time zone can be a
            # day behind) and some ports are only checked by the script's daily run. "quota" is the only block value the
            # node script accepts; it stops every member of the account at once.
            block = "quota" if state_of(user, usage(db, user["id"]), datetime.date.fromtimestamp(now)) in ("expired", "quota") else ""
            if account.get("platform_block", "") != block:
                ops.append({"op": "block", "account_id": link["account_id"], "platform_block": block})
            for row in db.execute("SELECT * FROM platform_pending WHERE link_id=? AND task_id IS NULL ORDER BY id", (link["id"],)).fetchall():
                ops.append(json.loads(row["op"]))
                pending_ids.append(row["id"])
        if len(ops) > before:
            link_ids.append(link["id"])
        elif link["state"] in ("pending", "failed") and account is not None and not link["removing"]:
            db.execute("UPDATE platform_links SET state='synced',notice=CASE WHEN notice LIKE '同步失败%' THEN '' ELSE notice END WHERE id=?", (link["id"],))
    return ops[:200], pending_ids, link_ids


def schedule(db, now=None):
    """Queue at most one platform_apply per eligible node; identical plans are not re-queued."""
    now = time.time() if now is None else now
    queued = []
    for node in db.execute("SELECT * FROM nodes WHERE deleted IS NULL").fetchall():
        if not node_ready(node, now):
            continue
        if db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status IN ('queued','running','unknown')", (node["id"],)).fetchone():
            continue
        ops, pending_ids, link_ids = plan(db, node, now)
        if not ops:
            continue
        request = validate_platform_task({"action": "platform_apply", "params": {"ops": ops}})
        key = "platform:" + node["id"] + ":" + hashlib.sha256(json.dumps([node["snapshot"], request], sort_keys=True).encode()).hexdigest()
        if db.execute("SELECT 1 FROM tasks WHERE request_key=?", (key,)).fetchone():
            continue
        task_id = str(uuid.uuid4())
        db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
                   (task_id, node["id"], "platform_apply", json.dumps(request), "queued", now, key))
        db.execute("INSERT INTO audit(at,event,node_id,detail) VALUES(?,?,?,?)", (now, "task.queued", node["id"], task_id + " platform_apply system"))
        for pending in pending_ids:
            db.execute("UPDATE platform_pending SET task_id=? WHERE id=?", (task_id, pending))
        for link_id in link_ids:
            db.execute("UPDATE platform_links SET state='pending' WHERE id=?", (link_id,))
        queued.append(task_id)
    return queued


AUTO_AUTHORITY_RETRY = 3600


def auto_authority(db, now=None):
    """Adopted servers are platform-managed. Switch script-mode nodes that hold no script users;
    nodes with users wait for the operator to confirm clearing them. A failed automatic switch
    is retried after an hour, never in a tight loop."""
    now = time.time() if now is None else now
    queued = []
    for node in db.execute("SELECT id, snapshot FROM nodes WHERE adopted=1 AND deleted IS NULL AND revoked=0 AND maintenance=0 AND last_seen>?",
                           (now - ONLINE,)).fetchall():
        snapshot = json.loads(node["snapshot"])
        if snapshot.get("error") or snapshot.get("authority_version") != 1 or snapshot.get("accounts_version") != 1 \
                or snapshot.get("user_authority") == "platform":
            continue
        if any(item.get("users") for item in snapshot.get("instances", [])):
            continue
        if db.execute("SELECT 1 FROM tasks WHERE node_id=? AND (status IN ('queued','running','unknown') OR "
                      "(request_key LIKE 'auto-authority:%' AND created>?))", (node["id"], now - AUTO_AUTHORITY_RETRY)).fetchone():
            continue
        task_id = str(uuid.uuid4())
        request = validate_platform_task({"action": "platform_apply", "params": {"ops": [{"op": "set_authority", "mode": "platform"}]}})
        db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
                   (task_id, node["id"], "platform_apply", json.dumps(request), "queued", now, "auto-authority:" + task_id))
        db.execute("INSERT INTO audit(at,event,node_id,detail) VALUES(?,?,?,?)",
                   (now, "task.queued", node["id"], task_id + " platform_apply（已接管服务器自动切到平台管理）"))
        queued.append(task_id)
    return queued


def task_finished(db, task, status, message, now=None):
    """Record a platform_apply outcome on the affected links."""
    now = time.time() if now is None else now
    request = json.loads(task["request"])
    switch = [op for op in request["params"]["ops"] if op["op"] == "set_authority"]
    if switch:
        if status == "succeeded" and switch[0]["mode"] == "script":
            forget_node(db, task["node_id"], now)
        return
    accounts = {op["account_id"] for op in request["params"]["ops"]}
    links = [l for l in db.execute("SELECT * FROM platform_links WHERE node_id=?", (task["node_id"],)).fetchall() if l["account_id"] in accounts]
    if status == "succeeded":
        db.execute("DELETE FROM platform_pending WHERE task_id=?", (task["id"],))
        for link in links:
            if link["removing"]:
                db.execute("DELETE FROM platform_pending WHERE link_id=?", (link["id"],))
                db.execute("DELETE FROM platform_links WHERE id=?", (link["id"],))
            else:
                db.execute("UPDATE platform_links SET state='synced',notice=CASE WHEN notice LIKE '同步失败%' THEN '' ELSE notice END WHERE id=?", (link["id"],))
        finish_deletions(db)
    elif status == "failed":
        # Explicit one-shot operations are dropped so they never loop; derived ones are
        # recomputed after a back-off from the next snapshot.
        db.execute("DELETE FROM platform_pending WHERE task_id=?", (task["id"],))
        # A version conflict resolves itself: the next plan uses the newer snapshot's revision.
        delay = 0 if "节点版本" in message or "重新合并" in message else RETRY_DELAY
        for link in links:
            db.execute("UPDATE platform_links SET state='failed',notice=?,retry_after=? WHERE id=?",
                       ("同步失败：" + message[:200], now + delay, link["id"]))
    else:
        for link in links:
            db.execute("UPDATE platform_links SET state='unknown',notice=? WHERE id=?", ("同步结果未确认，请在任务记录中核对", link["id"]))


def finish_deletions(db):
    for user in db.execute("SELECT id FROM platform_users WHERE deleting IS NOT NULL").fetchall():
        if not db.execute("SELECT 1 FROM platform_links WHERE user_id=?", (user["id"],)).fetchone():
            db.execute("DELETE FROM platform_users WHERE id=?", (user["id"],))


def forget_missing(db):
    """A removing link whose node account is already gone needs no task."""
    for link in db.execute("SELECT platform_links.*, nodes.snapshot FROM platform_links JOIN nodes ON nodes.id=platform_links.node_id WHERE removing IS NOT NULL").fetchall():
        snapshot = json.loads(link["snapshot"])
        if snapshot.get("accounts_version") == 1 and link["account_id"] not in snapshot.get("accounts", {}):
            db.execute("DELETE FROM platform_pending WHERE link_id=?", (link["id"],))
            db.execute("DELETE FROM platform_links WHERE id=?", (link["id"],))
    finish_deletions(db)


# ---------------------------------------------------------------- views

def describe(db, user, nodes, now=None):
    now = time.time() if now is None else now
    used = usage(db, user["id"])
    links = []
    for link in db.execute("SELECT * FROM platform_links WHERE user_id=? ORDER BY created", (user["id"],)).fetchall():
        node = nodes.get(link["node_id"])
        snapshot = json.loads(node["snapshot"]) if node else {}
        account = snapshot.get("accounts", {}).get(link["account_id"])
        online = bool(node and node["last_seen"] and now - node["last_seen"] < ONLINE)
        sync = ("removing" if link["removing"] else link["state"]) if online or link["state"] in ("failed", "unknown") else "offline"
        links.append({"id": link["id"], "node_id": link["node_id"], "node_name": node["name"] if node else "已删除的节点",
                      "account_id": link["account_id"], "origin": link["origin"], "cycle_used": link["cycle_used"],
                      "sync": sync, "notice": link["notice"], "online": online,
                      "account": account, "members": (account or {}).get("members", [])})
    return {"id": user["id"], **fields_of(user), "cycle": user["cycle"], "used": used,
            "state": state_of(user, used, datetime.date.fromtimestamp(now)), "deleting": user["deleting"],
            "mtime": json.loads(user["mtime"]), "links": links}
