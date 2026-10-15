"""Relay lines: a platform user's landing protocol reached through one or more relay servers.

Each relay hop is one port-forward rule on that server (Realm or nftables), created and removed
through ordinary forward_apply node tasks. The line keeps per-hop task and rule ids; its state is
derived from the hops. Tasks are never replayed: a failed hop waits for an explicit retry.
"""
import ipaddress
import json
import re
import time
import uuid

from .common import DNS_NAME, validate_forward_rule, validate_forward_task, validate_task
from . import platform_users

SCHEMA = '''
CREATE TABLE IF NOT EXISTS relay_lines(
 id TEXT PRIMARY KEY, user_id TEXT REFERENCES platform_users(id) ON DELETE CASCADE,
 landing_node_id TEXT NOT NULL, landing_core TEXT NOT NULL, landing_protocol TEXT NOT NULL, landing_port INTEGER NOT NULL,
 landing_host TEXT NOT NULL, hops TEXT NOT NULL, removing INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
'''

MAX_HOPS = 5
PORT_ONLY_KEYS = {"node_id", "port", "host", "transport"}


def migrate(db):
    """0.3.0-preview.25 created user_id NOT NULL; port-only lines may have no user.

    executescript commits before running and leaves no transaction open (the caller starts one next).
    The copy runs as one explicit transaction; a relay_lines_old left by the 0.3.0-preview.26 migration,
    whose copy was rolled back, is recovered here too."""
    if any(row[1] == "user_id" and row[3] for row in db.execute("PRAGMA table_info(relay_lines)")):
        db.executescript("ALTER TABLE relay_lines RENAME TO relay_lines_old;" + SCHEMA)
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='relay_lines_old'").fetchone():
        db.executescript("BEGIN; INSERT OR IGNORE INTO relay_lines SELECT * FROM relay_lines_old; DROP TABLE relay_lines_old; COMMIT;")
UDP_PROTOCOLS = {"hy2", "tuic"}
BOTH_PROTOCOLS = {"ss2022", "ss-legacy", "snell", "snell-v5", "snell-v6", "snell-shadowtls", "snell-v5-shadowtls", "ss2022-shadowtls"}
STATE_TEXT = {"creating": "创建中", "active": "正常", "partial": "部分失败", "removing": "删除中"}


def transport_for(protocol):
    return "udp" if protocol in UDP_PROTOCOLS else "tcp+udp" if protocol in BOTH_PROTOCOLS else "tcp"


def _online(node, now):
    return bool(node["last_seen"]) and now - node["last_seen"] < platform_users.ONLINE


def _relay_ready(node, now):
    snapshot = json.loads(node["snapshot"])
    if not node["adopted"] or node["maintenance"] or not _online(node, now):
        return "%s 离线、维护中或尚未接管" % node["name"]
    if snapshot.get("forward_version") != 1:
        return "%s 的节点程序版本过旧，请先升级节点" % node["name"]
    return None


def _address(node, ipv4_only=False):
    addresses = json.loads(node["snapshot"]).get("addresses") or {}
    return addresses.get("ipv4") or ("" if ipv4_only else addresses.get("ipv6", ""))


def _busy(db, node_id):
    return db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status IN ('queued','running','unknown')", (node_id,)).fetchone()


def _port_conflict(snapshot, port, transport):
    kinds = lambda t: {"tcp", "udp"} if t == "tcp+udp" else {t}
    if any(i.get("port") == port for i in snapshot.get("instances", [])):
        return True
    return any(r.get("listen_port") == port and kinds(r.get("transport")) & kinds(transport) for r in snapshot.get("forwards", []))


def _queue_forward(db, node_id, op, key, now):
    request = validate_forward_task({"action": "forward_apply", "params": {"ops": [op]}})
    task_id = str(uuid.uuid4())
    db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
               (task_id, node_id, "forward_apply", json.dumps(request), "queued", now, key))
    return task_id


def _is_member(db, link, target):
    node = db.execute("SELECT snapshot FROM nodes WHERE id=?", (link["node_id"],)).fetchone()
    account = (json.loads(node["snapshot"]).get("accounts", {}) if node else {}).get(link["account_id"]) or {}
    members = account.get("members") or json.loads(link["members"] or "[]")
    for m in members:
        t = m.get("target", m)
        if (t.get("core"), t.get("protocol"), t.get("port")) == (target["core"], target["protocol"], target["port"]):
            return True
    return False


def create(db, data, now=None):
    now = time.time() if now is None else now
    if not isinstance(data, dict) or set(data) != {"user_id", "hops", "landing"}:
        raise ValueError("中转线路参数无效")
    hops, landing = data["hops"], data["landing"]
    if not isinstance(hops, list) or not 1 <= len(hops) <= MAX_HOPS:
        raise ValueError("中转服务器为 1–%d 层" % MAX_HOPS)
    # Port-only (exit machine): no protocol, just forward to host:port; the user is optional and never linked.
    port_only = isinstance(landing, dict) and set(landing) == PORT_ONLY_KEYS
    if not isinstance(landing, dict) or not port_only and set(landing) != {"node_id", "core", "protocol", "port", "host"}:
        raise ValueError("落地参数无效")
    user = None
    if data["user_id"] is not None or not port_only:
        user = db.execute("SELECT * FROM platform_users WHERE id=? AND deleting IS NULL", (data["user_id"],)).fetchone() \
            if isinstance(data["user_id"], str) else None
        if not user:
            raise ValueError("请选择用户" if data["user_id"] is None else "用户不存在")
    landing_node = db.execute("SELECT * FROM nodes WHERE id=? AND deleted IS NULL AND revoked=0 AND adopted=1", (landing.get("node_id"),)).fetchone()
    if not landing_node:
        raise ValueError("落地服务器不存在或尚未接管")
    if type(landing.get("port")) is not int or not 1 <= landing["port"] <= 65535:
        raise ValueError("落地端口必须是 1–65535 的整数")
    if port_only:
        if landing["transport"] not in ("tcp", "udp", "tcp+udp"):
            raise ValueError("转发协议无效")
        target = {"core": "", "protocol": "", "port": landing["port"]}
    else:
        target = {k: landing[k] for k in ("core", "protocol", "port")}
        if not any((i.get("core"), i.get("protocol"), i.get("port")) == (target["core"], target["protocol"], target["port"])
                   for i in json.loads(landing_node["snapshot"]).get("instances", [])):
            raise ValueError("落地协议不存在，请刷新后重试")
    host = landing["host"]
    if not isinstance(host, str) or not 1 <= len(host) <= 253 or not (_is_ip(host) or re.fullmatch(DNS_NAME, host)):
        raise ValueError("落地地址必须是 IP 地址或域名")
    nodes = []
    for hop in hops:
        if not isinstance(hop, dict) or set(hop) != {"node_id", "backend", "listen_port"} or hop["backend"] not in ("realm", "nftables") \
                or type(hop["listen_port"]) is not int or not 1 <= hop["listen_port"] <= 65535:
            raise ValueError("中转服务器参数无效")
        node = db.execute("SELECT * FROM nodes WHERE id=? AND deleted IS NULL AND revoked=0", (hop["node_id"],)).fetchone()
        if not node:
            raise ValueError("中转服务器不存在")
        error = _relay_ready(node, now)
        if error:
            raise ValueError(error)
        nodes.append(node)
    ids = [n["id"] for n in nodes] + [landing_node["id"]]
    if len(set(ids)) != len(ids):
        raise ValueError("同一条线路中服务器不能重复，中转服务器也不能是落地服务器")
    line_id = str(uuid.uuid4())
    remark = ("中转：%s → %s" % (user["name"] if user else "端口", landing_node["name"]))[:64].replace('"', "")
    planned = []
    for index, (hop, node) in enumerate(zip(hops, nodes)):
        transport = "tcp+udp" if hop["backend"] == "nftables" else landing["transport"] if port_only else transport_for(target["protocol"])
        if index + 1 < len(hops):
            next_node = nodes[index + 1]
            target_host = _address(next_node, ipv4_only=hop["backend"] == "nftables")
            if not target_host:
                raise ValueError("%s 未上报公网 IP%s，请升级节点程序后重试" % (next_node["name"], "v4" if hop["backend"] == "nftables" else ""))
            target_port = hops[index + 1]["listen_port"]
        else:
            target_host, target_port = host, target["port"]
            if hop["backend"] == "nftables" and not _is_ip(host, 4):
                raise ValueError("nftables 中转的落地地址必须是 IPv4")
        if not _address(nodes[0]) and index == 0:
            raise ValueError("%s 未上报公网 IP，无法生成入口地址，请升级节点程序后重试" % node["name"])
        if _port_conflict(json.loads(node["snapshot"]), hop["listen_port"], transport):
            raise ValueError("%s 的入口端口 %d 已被转发规则或代理协议使用" % (node["name"], hop["listen_port"]))
        if _busy(db, node["id"]):
            raise ValueError("%s 有未完成的任务，请稍后再试" % node["name"])
        rule = validate_forward_rule({"backend": hop["backend"], "remark": remark, "transport": transport, "listen_host": "0.0.0.0",
                                      "listen_port": hop["listen_port"], "remote_host": target_host, "remote_port": target_port, "enabled": True})
        planned.append({"node_id": node["id"], "rule": rule})
    # The user gets the landing protocol if not yet a member (platform-managed landing node only).
    link = None if port_only else db.execute("SELECT * FROM platform_links WHERE user_id=? AND node_id=? AND removing IS NULL",
                                             (user["id"], landing_node["id"])).fetchone()
    if port_only:
        pass
    elif link is None:
        platform_users.add_link(db, user["id"], landing_node["id"], [target], now)
    elif not _is_member(db, link, target):
        platform_users.member_op(db, link, {"action": "add", "target": target})
    stored = []
    for index, item in enumerate(planned):
        task_id = _queue_forward(db, item["node_id"], {"op": "add", "rule": item["rule"]}, "relay:%s:%d:add:%s" % (line_id, index, uuid.uuid4().hex[:8]), now)
        stored.append({**item, "forward_id": None, "task_id": task_id, "status": "pending"})
    db.execute("INSERT INTO relay_lines VALUES(?,?,?,?,?,?,?,?,0,?,?)",
               (line_id, user["id"] if user else None, landing_node["id"], target["core"], target["protocol"], target["port"], host, json.dumps(stored), now, now))
    return line_id


def _is_ip(value, version=None):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return version is None or address.version == version


def _save(db, line_id, hops, now):
    db.execute("UPDATE relay_lines SET hops=?, updated=? WHERE id=?", (json.dumps(hops), now, line_id))


def task_finished(db, task, status, result, now=None, message=""):
    """Write a relay hop's forward task outcome back into its line."""
    now = time.time() if now is None else now
    key = task["request_key"] or ""
    match = re.fullmatch(r"relay:([0-9a-f-]{36}):(\d+):(add|delete):[0-9a-f]{8}", key)
    if not match:
        return
    line = db.execute("SELECT * FROM relay_lines WHERE id=?", (match.group(1),)).fetchone()
    if not line:
        return
    hops, index, op = json.loads(line["hops"]), int(match.group(2)), match.group(3)
    if index >= len(hops) or hops[index].get("task_id") != task["id"]:
        return
    hop = hops[index]
    if op == "add":
        rule = (result or {}).get("rule") or {}
        if status == "succeeded" and isinstance(rule.get("id"), str):
            hop.update(status="active", forward_id=rule["id"])
        else:
            hop["status"] = "failed"
    else:
        hop["status"] = "removed" if status == "succeeded" or "已不存在" in (message or "") else "remove_failed"
    _save(db, line["id"], hops, now)
    _finish_removal(db, line["id"])


def _finish_removal(db, line_id):
    line = db.execute("SELECT * FROM relay_lines WHERE id=?", (line_id,)).fetchone()
    if line and line["removing"] and all(h["status"] == "removed" for h in json.loads(line["hops"])):
        db.execute("DELETE FROM relay_lines WHERE id=?", (line_id,))


def remove(db, line_id, now=None):
    """Delete the line: remove each hop's forward rule, then the line itself."""
    now = time.time() if now is None else now
    line = db.execute("SELECT * FROM relay_lines WHERE id=?", (line_id,)).fetchone()
    if not line:
        raise ValueError("中转线路不存在")
    hops = json.loads(line["hops"])
    if any(h["status"] == "pending" for h in hops):
        raise ValueError("线路仍在创建中，请等待任务完成后再删除")
    plans = []
    for index, hop in enumerate(hops):
        if hop["status"] == "removed" or not hop.get("forward_id"):
            hop["status"] = "removed"
            continue
        node = db.execute("SELECT * FROM nodes WHERE id=? AND deleted IS NULL AND revoked=0", (hop["node_id"],)).fetchone()
        if node is None:
            hop["status"] = "removed"  # the server is gone, and its rules with it
            continue
        # The snapshot may lag behind a just-created rule: always ask the node; "no such rule" counts as removed.
        current = next((r for r in json.loads(node["snapshot"]).get("forwards", []) if r.get("id") == hop["forward_id"]), None) \
            or {**hop["rule"], "id": hop["forward_id"]}
        if _relay_ready(node, now):
            raise ValueError(_relay_ready(node, now) + "，暂时无法删除其转发规则")
        if _busy(db, node["id"]):
            raise ValueError("%s 有未完成的任务，请稍后再试" % node["name"])
        plans.append((index, node["id"], {k: current[k] for k in ("id", "backend", "remark", "transport", "listen_host", "listen_port",
                                                                  "remote_host", "remote_port", "enabled")}))
    for index, node_id, base in plans:
        hops[index]["task_id"] = _queue_forward(db, node_id, {"op": "delete", "id": base["id"], "base": base},
                                                "relay:%s:%d:delete:%s" % (line_id, index, uuid.uuid4().hex[:8]), now)
        hops[index]["status"] = "removing"
    db.execute("UPDATE relay_lines SET removing=1, hops=?, updated=? WHERE id=?", (json.dumps(hops), now, line_id))
    _finish_removal(db, line_id)


def retry(db, line_id, now=None):
    """Queue failed hops again (add, or delete while the line is being removed)."""
    now = time.time() if now is None else now
    line = db.execute("SELECT * FROM relay_lines WHERE id=?", (line_id,)).fetchone()
    if not line:
        raise ValueError("中转线路不存在")
    hops = json.loads(line["hops"])
    failed = [i for i, h in enumerate(hops) if h["status"] in ("failed", "remove_failed")]
    if not failed:
        raise ValueError("没有需要重试的中转服务器")
    if line["removing"]:
        for i in failed:
            hops[i]["status"] = "active"
        _save(db, line_id, hops, now)
        return remove(db, line_id, now)
    for i in failed:
        node = db.execute("SELECT * FROM nodes WHERE id=? AND deleted IS NULL AND revoked=0", (hops[i]["node_id"],)).fetchone()
        if not node or _relay_ready(node, now):
            raise ValueError((_relay_ready(node, now) if node else "中转服务器不存在") or "")
        if _busy(db, node["id"]):
            raise ValueError("%s 有未完成的任务，请稍后再试" % node["name"])
        if _port_conflict(json.loads(node["snapshot"]), hops[i]["rule"]["listen_port"], hops[i]["rule"]["transport"]):
            raise ValueError("%s 的入口端口 %d 已被占用" % (node["name"], hops[i]["rule"]["listen_port"]))
    for i in failed:
        hops[i]["task_id"] = _queue_forward(db, hops[i]["node_id"], {"op": "add", "rule": hops[i]["rule"]},
                                            "relay:%s:%d:add:%s" % (line_id, i, uuid.uuid4().hex[:8]), now)
        hops[i]["status"] = "pending"
    _save(db, line_id, hops, now)


def share(db, line_id, now=None, key_prefix="relay-share:"):
    """Export the user's connection for the landing protocol, addressed to the first relay's entry."""
    now = time.time() if now is None else now
    line = db.execute("SELECT * FROM relay_lines WHERE id=?", (line_id,)).fetchone()
    if not line:
        raise ValueError("中转线路不存在")
    hops = json.loads(line["hops"])
    if not line["landing_protocol"]:
        raise ValueError("仅转发端口的线路没有落地协议，无法导出连接信息")
    if line["removing"] or any(h["status"] != "active" for h in hops):
        raise ValueError("线路尚未全部就绪，暂时无法导出连接")
    user = db.execute("SELECT name FROM platform_users WHERE id=?", (line["user_id"],)).fetchone()
    entry = db.execute("SELECT * FROM nodes WHERE id=?", (hops[0]["node_id"],)).fetchone()
    landing = db.execute("SELECT * FROM nodes WHERE id=? AND deleted IS NULL AND revoked=0", (line["landing_node_id"],)).fetchone()
    if not landing or not _online(landing, now) or landing["maintenance"]:
        raise ValueError("落地服务器离线或维护中")
    host = _address(entry) if entry else ""
    if not host:
        raise ValueError("入口中转服务器未上报公网 IP")
    request = validate_task({"action": "share", "protocol": line["landing_protocol"], "core": line["landing_core"], "port": line["landing_port"],
                             "params": {"name": user["name"], "host": host, "port": hops[0]["rule"]["listen_port"]}})
    task_id = str(uuid.uuid4())
    db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
               (task_id, landing["id"], "share", json.dumps(request), "queued", now, key_prefix + task_id))
    return task_id


def blocked(db, line, nodes, now=None):
    """Why the line carries no traffic for its user even though every forward runs: the user is stopped,
    expired or out of quota (the panel disables the user's accounts), or the landing protocol member is off."""
    if not line["user_id"] or not line["landing_protocol"]:
        return ""
    user = db.execute("SELECT * FROM platform_users WHERE id=?", (line["user_id"],)).fetchone()
    if not user:
        return ""
    now = time.time() if now is None else now
    import datetime
    state = platform_users.state_of(user, platform_users.usage(db, user["id"]), datetime.date.fromtimestamp(now))
    if state:
        return "用户" + platform_users.STATE_TEXT[state]
    link = db.execute("SELECT account_id FROM platform_links WHERE user_id=? AND node_id=? AND removing IS NULL",
                      (line["user_id"], line["landing_node_id"])).fetchone()
    node = nodes.get(line["landing_node_id"])
    account = (json.loads(node["snapshot"]).get("accounts") or {}).get(link["account_id"]) if link and node else None
    member = next((m for m in (account or {}).get("members", []) if isinstance(m, dict)
                   and (m.get("core"), m.get("protocol"), m.get("port")) == (line["landing_core"], line["landing_protocol"], line["landing_port"])), None)
    return "落地协议已停用" if member and member.get("enabled") is False else ""


def describe(db, line, nodes):
    hops = json.loads(line["hops"])
    statuses = {h["status"] for h in hops}
    state = "removing" if line["removing"] else "creating" if "pending" in statuses else "partial" if statuses & {"failed", "remove_failed"} else "active"
    entry_node = nodes.get(hops[0]["node_id"]) if hops else None
    user = db.execute("SELECT name FROM platform_users WHERE id=?", (line["user_id"],)).fetchone() if line["user_id"] else None
    return {"id": line["id"], "user_id": line["user_id"], "user_name": user["name"] if user else "", "state": state, "port_only": not line["landing_protocol"],
            "landing": {"node_id": line["landing_node_id"], "node_name": nodes[line["landing_node_id"]]["name"] if line["landing_node_id"] in nodes else "已删除的服务器",
                        "core": line["landing_core"], "protocol": line["landing_protocol"], "port": line["landing_port"], "host": line["landing_host"]},
            "entry": {"host": _address(entry_node) if entry_node else "", "port": hops[0]["rule"]["listen_port"] if hops else None},
            "hops": [{"node_id": h["node_id"], "node_name": nodes[h["node_id"]]["name"] if h["node_id"] in nodes else "已删除的服务器",
                      "backend": h["rule"]["backend"], "transport": h["rule"]["transport"], "listen_port": h["rule"]["listen_port"],
                      "target": "%s:%d" % (h["rule"]["remote_host"], h["rule"]["remote_port"]), "status": h["status"], "forward_id": h.get("forward_id")}
                     for h in hops],
            "created": line["created"], "blocked": blocked(db, line, nodes)}
