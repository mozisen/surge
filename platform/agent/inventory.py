import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

from .billing import effective_usage, traffic_state
from vaio import __version__
from vaio.common import ACCOUNT_FIELDS, PROTOCOLS, PROTOCOL_CORES, UUID_PATTERN, config_revision, sanitize_forwards, sanitize_install_schema, user_mode, user_stats, write_capabilities

SNELL_USERS = {"snell", "snell-v5", "snell-v6"}
STANDALONE = {"snell", "snell-v5", "snell-v6", "snell-shadowtls", "snell-v5-shadowtls", "ss2022-shadowtls", "naive"}


def read_db(cfg):
    path = Path(cfg) / "db.json"
    if not path.exists():
        return {"version": "4.0.0", "xray": {}, "singbox": {}, "meta": {}}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or any(not isinstance(data.get(k, {}), dict) for k in ("xray", "singbox", "meta")):
        raise ValueError("节点数据库格式无效")
    return data


def rows(db):
    for core in ("xray", "singbox"):
        for protocol, value in db.get(core, {}).items():
            for row in value if isinstance(value, list) else [value]:
                if not isinstance(row, dict) or type(row.get("port")) is not int:
                    raise ValueError("协议实例数据格式无效")
                yield core, protocol, row


def service_for(core, protocol, row):
    if protocol.startswith("snell") and re.fullmatch(r"[0-9a-f]{24}", str(row.get("snell_id", ""))):
        return "vless-snellu-" + row["snell_id"]
    if protocol in STANDALONE:
        return "vless-" + protocol
    return "vless-singbox" if core == "singbox" else "vless-reality"


def service_status(name):
    if not re.fullmatch(r"vless-[a-z0-9-]+", name):
        return "unknown"
    try:
        cmd = ["rc-service", name, "status"] if Path("/sbin/openrc").exists() else ["systemctl", "is-active", name]
        result = subprocess.run(cmd, capture_output=True, timeout=3)
        return "running" if result.returncode == 0 else "stopped"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def ss_server_key(row):
    """SS2022 instance key; instances installed by the panel keep it as their first user's key."""
    users = row.get("users") if isinstance(row.get("users"), list) else []
    return row.get("password") or (users[0].get("uuid") if users else "") or ""


def ss_user_stats(proto, row):
    """True when the shared renderer gives this SS / SS2022 instance named users (counted per user);
    otherwise it is one password on the inbound (counted per inbound). Mirrors _platform_render_inbound."""
    users = row.get("users") if isinstance(row.get("users"), list) else []
    if proto == "ss-legacy":
        return len(users) > 1
    if proto == "ss2022":
        key = ss_server_key(row)
        return bool(key) and (len(users) != 1 or users[0].get("uuid") != key)
    return False


def mutable(core, proto, row):
    # SS / SS2022 with any number of users: the shared renderer writes single and multi-user inbounds;
    # runtime still refuses inbounds that are not plain managed shadowsocks (relays, other types).
    if proto not in PROTOCOLS or core not in PROTOCOL_CORES[proto]:
        return False
    if proto == "vless" and row.get("security_mode", "reality") != "reality":
        return False
    # Port hopping requires NAT transactions outside the first release's adapter.
    if proto == "hy2" and str(row.get("hop_enable", "0")) == "1":
        return False
    return True


def users_for(row):
    if isinstance(row.get("users"), list):
        return row["users"]
    credential = row.get("uuid") or row.get("password") or row.get("psk")
    return [{"name": "default", "uuid": credential, "enabled": True, "used": 0, "quota": 0}] if credential else []


def inventory(cfg, status=service_status):
    db = read_db(cfg)
    instances, services = [], {}
    for core, proto, row in rows(db):
        service = service_for(core, proto, row)
        if service not in services:
            services[service] = status(service)
        instances.append({"core": core, "protocol": proto, "port": row["port"],
                          "service": service, "status": services[service], "managed": mutable(core, proto, row),
                          "sni": row.get("sni", ""), "traffic_state": traffic_state(db, core, proto, row),
                          "user_mode": user_mode(proto, row), "user_stats": user_stats(proto, row),
                          "user_available": user_mode(proto, row) == "multi" or (user_mode(proto, row) == "single" and (
                              proto not in SNELL_USERS or db.get("meta", {}).get("snell_users", {}).get(proto) is True)),
                          "users": [
                              {**{k: u.get(k, default) for k, default in (("name", ""), ("enabled", True), ("expire_date", ""))}, "used": effective_usage(u)[0], "quota": effective_usage(u)[1], "reset_day": u.get("panel_reset_day", 0),
                               "account_id": u.get("account_id") or ""}
                              for u in users_for(row)]})
    return {"revision": config_revision(db), "instances": instances, "accounts": accounts(db), "share_version": 2,
            "user_authority": "platform" if db.get("meta", {}).get("user_authority") == "platform" else "script",
            "authority_version": 1, "upgrade_version": 1, "write_capabilities": write_capabilities(), "task_api_version": 2,
            "config_details_version": 2, "install_options_version": 2, "billing_version": 1,
            "hostname": platform.node(), "os": platform.system() + " " + platform.release(),
            "arch": platform.machine(), "agent_version": __version__, "metrics": metrics(),
            "traffic_status": db.get("meta", {}).get("last_traffic_sync_status", "unavailable"), "at": time.time()}


def _global_ip(value, version):
    import ipaddress
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.version == version and address.is_global


def public_addresses():
    """Node public IPv4/IPv6 for relay targets (cached five minutes by addresses.discover)."""
    from .addresses import discover
    try:
        found = discover()
    except Exception:
        return {}
    return {k: found[k] for k in ("ipv4", "ipv6") if found.get(k)}


def account_state(account, today=None):
    """Same precedence as the script: manual > expired > quota > platform_quota."""
    today = (today or datetime.date.today()).isoformat()
    if account.get("enabled") is False:
        return "manual"
    if account.get("expire_date") and account["expire_date"] < today:
        return "expired"
    if account.get("quota", 0) and account.get("cycle_used", 0) >= account["quota"]:
        return "quota"
    if account.get("platform_block"):
        return "platform_quota"
    return ""


def accounts(db):
    """Unified accounts (no credentials) with each member's raw counter and state."""
    found = {}
    for core, proto, row in rows(db):
        for user in users_for(row):
            found[(core, proto, row["port"], user.get("name"))] = user
    result = {}
    for identity, account in (db.get("accounts") or {}).items():
        if not isinstance(account, dict):
            continue
        members = []
        for member in account.get("members", []):
            if not isinstance(member, dict):
                continue
            user = found.get((member.get("core"), member.get("protocol"), member.get("port"), member.get("name")))
            members.append({"core": member.get("core"), "protocol": member.get("protocol"), "port": member.get("port"),
                            "name": member.get("name"), "used": user.get("used", 0) if user else None,
                            "enabled": user.get("enabled", True) if user else None,
                            "disable_reason": user.get("disable_reason", "") if user else ""})
        result[identity] = {**{k: account.get(k) for k in ACCOUNT_FIELDS}, "cycle": account.get("cycle", ""),
                            "cycle_used": account.get("cycle_used", 0), "rev": account.get("rev", 0),
                            "mtime": account.get("mtime", {}), "platform_user_id": account.get("platform_user_id"),
                            "platform_block": account.get("platform_block", ""), "state": account_state(account),
                            "members": members}
    return result


def metrics():
    result = {"load": round(os.getloadavg()[0], 2), "cpu_count": os.cpu_count() or 1}
    disk = shutil.disk_usage("/")
    result.update(disk_total=disk.total, disk_used=disk.used)
    try:
        mem = dict((line.split(":")[0], int(line.split()[1]) * 1024) for line in Path("/proc/meminfo").read_text().splitlines())
        result.update(memory_total=mem["MemTotal"], memory_used=mem["MemTotal"] - mem.get("MemAvailable", mem.get("MemFree", 0)))
        result["uptime"] = float(Path("/proc/uptime").read_text().split()[0])
        rx, tx = 0, 0
        for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
            name, fields = line.split(":")
            if name.strip() != "lo":
                values = fields.split()
                rx += int(values[0]); tx += int(values[8])
        result.update(network_rx=rx, network_tx=tx)
    except (OSError, ValueError, KeyError):
        pass
    return result


def sanitize_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("节点快照格式无效")
    def text(value, maximum=253):
        return str(value or "")[:maximum]
    clean = {k: text(snapshot.get(k)) for k in ("hostname", "os", "arch", "agent_version", "traffic_status", "error")}
    revision = snapshot.get("revision", "")
    clean["revision"] = revision if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{64}", revision) else ""
    numeric = {"load", "cpu_count", "disk_total", "disk_used", "memory_total", "memory_used", "uptime", "network_rx", "network_tx"}
    metrics_data = snapshot.get("metrics", {})
    clean["metrics"] = {k: v for k, v in metrics_data.items() if k in numeric and type(v) in (int, float) and 0 <= v < 1e22} if isinstance(metrics_data, dict) else {}
    api = snapshot.get("script_api")
    if isinstance(api, dict):
        clean["script_api"] = {"status": "ready" if api.get("status") == "ready" else "unavailable",
                               "stage": "read_only", "version": text(api.get("version"), 40)}
        for key in ("protocol_count", "instance_count"):
            if type(api.get(key)) is int and 0 <= api[key] <= 1000:
                clean["script_api"][key] = api[key]
    clean["config_details_version"] = 2 if snapshot.get("config_details_version") == 2 else 0
    clean["billing_version"] = 1 if snapshot.get("billing_version") == 1 else 0
    clean["instances"] = []
    clean["task_api_version"] = 2 if snapshot.get("task_api_version") == 2 else 1
    clean["install_options_version"] = snapshot.get("install_options_version") if type(snapshot.get("install_options_version")) is int and snapshot["install_options_version"] in (1, 2) else 0
    declared = snapshot.get("write_capabilities", [])
    clean["write_capabilities"] = [item for item in write_capabilities() if item in declared] if isinstance(declared, list) else []
    instances = snapshot.get("instances", [])
    if not isinstance(instances, list) or len(instances) > 1000:
        raise ValueError("实例数量无效")
    for item in instances:
        if not isinstance(item, dict) or type(item.get("port")) is not int or not 1 <= item["port"] <= 65535:
            raise ValueError("实例端口无效")
        clean_item = {k: text(item.get(k), 100) for k in ("core", "protocol", "service", "status", "sni")}
        clean_item["traffic_state"] = item.get("traffic_state") if item.get("traffic_state") in ("ready", "unavailable", "unsupported") else "unavailable"
        clean_item["user_mode"] = item.get("user_mode") if item.get("user_mode") in ("multi", "single", "none") else ""
        clean_item["user_stats"] = item.get("user_stats") if item.get("user_stats") in ("user", "inbound", "port", "none") else ""
        clean_item["user_available"] = item.get("user_available") is True
        clean_item.update(port=item["port"], managed=item.get("managed") is True, users=[])
        for user in item.get("users", [])[:1000]:
            owner = user.get("account_id")
            clean_item["users"].append({"name": text(user.get("name"), 32), "enabled": user.get("enabled") is True,
                                        "used": max(0, int(user.get("used", 0))), "quota": max(0, int(user.get("quota", 0))),
                                        "reset_day": max(0, min(28, int(user.get("reset_day", 0)))), "expire_date": text(user.get("expire_date"), 10),
                                        "account_id": owner if isinstance(owner, str) and re.fullmatch(UUID_PATTERN, owner) else ""})
        clean["instances"].append(clean_item)
    clean["accounts_version"] = 1 if snapshot.get("accounts_version") == 1 else 0
    clean["authority_version"] = 1 if snapshot.get("authority_version") == 1 else 0
    clean["user_authority"] = "platform" if snapshot.get("user_authority") == "platform" else "script"
    clean["upgrade_version"] = 1 if snapshot.get("upgrade_version") == 1 else 0
    clean["share_version"] = 2 if snapshot.get("share_version") == 2 else 0
    addresses = snapshot.get("addresses")
    clean["addresses"] = {k: v for k, v in addresses.items() if k in ("ipv4", "ipv6") and isinstance(v, str) and _global_ip(v, 4 if k == "ipv4" else 6)} \
        if isinstance(addresses, dict) else {}
    clean["forward_version"] = 1 if snapshot.get("forward_version") == 1 else 0
    clean["core_update_version"] = 1 if snapshot.get("core_update_version") == 1 else 0
    cores = snapshot.get("cores")
    clean["cores"] = {}
    for name, item in (cores.items() if isinstance(cores, dict) else []):
        if name not in ("xray", "singbox", "snell-v5", "snell-v6") or not isinstance(item, dict):
            continue
        entry = {k: v for k, v in item.items() if k in ("current", "latest", "official") and isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v)}
        if "current" in entry:
            if name == "singbox":
                entry["stats"] = item.get("stats") is True
            clean["cores"][name] = entry
    clean["forwards"] = sanitize_forwards(snapshot.get("forwards")) if clean["forward_version"] else []
    schema = sanitize_install_schema(snapshot.get("install_schema")) if snapshot.get("install_version") == 1 else None
    clean["install_version"] = 1 if schema else 0
    if schema:
        clean["install_schema"] = schema
    upgrade = snapshot.get("last_upgrade")
    if isinstance(upgrade, dict):
        clean["last_upgrade"] = {"status": upgrade.get("status") if upgrade.get("status") in ("succeeded", "rolled_back", "failed") else "failed",
                                 "at": upgrade["at"] if type(upgrade.get("at")) in (int, float) and 0 < upgrade["at"] < 1e11 else 0,
                                 **{k: text(upgrade.get(k), 40) for k in ("from", "to", "script_from", "script_to", "task")},
                                 "message": text(upgrade.get("message"), 300)}
    clean["accounts"] = sanitize_accounts(snapshot.get("accounts", {}))
    return clean


def sanitize_accounts(data):
    if not isinstance(data, dict) or len(data) > 1000:
        raise ValueError("统一用户数量无效")
    def number(value, high=10 ** 18):
        return value if type(value) is int and 0 <= value < high else 0
    def date(value):
        return value if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else ""
    def uuid_or_none(value):
        return value if isinstance(value, str) and re.fullmatch(UUID_PATTERN, value) else None
    clean, total = {}, 0
    for identity, account in data.items():
        if not isinstance(identity, str) or not re.fullmatch(UUID_PATTERN, identity) or not isinstance(account, dict):
            raise ValueError("统一用户数据无效")
        members = account.get("members", [])
        if not isinstance(members, list) or len(members) > 50:
            raise ValueError("统一用户成员无效")
        total += len(members)
        if total > 20000:
            raise ValueError("统一用户成员数量无效")
        name = account.get("name")
        mtime = account.get("mtime") if isinstance(account.get("mtime"), dict) else {}
        clean[identity] = {
            "name": name if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) else "",
            "note": "".join(c for c in str(account.get("note") or "")[:200] if ord(c) >= 32),
            "enabled": account.get("enabled") is not False, "expire_date": date(account.get("expire_date")),
            "quota": number(account.get("quota")), "reset_day": number(account.get("reset_day"), 29),
            "cycle": str(account.get("cycle") or "")[:10], "cycle_used": number(account.get("cycle_used")),
            "rev": number(account.get("rev")),
            "mtime": {k: mtime[k] for k in (*ACCOUNT_FIELDS, "members") if type(mtime.get(k)) is int and 0 <= mtime[k] < 10 ** 11},
            "platform_user_id": uuid_or_none(account.get("platform_user_id")),
            "platform_block": "quota" if account.get("platform_block") == "quota" else "",
            "state": account.get("state") if account.get("state") in ("", "manual", "expired", "quota", "platform_quota") else "",
            "members": []}
        for member in members:
            if not isinstance(member, dict) or member.get("core") not in ("xray", "singbox") or type(member.get("port")) is not int \
                    or not 1 <= member["port"] <= 65535:
                raise ValueError("统一用户成员无效")
            used = member.get("used")
            clean[identity]["members"].append({
                "core": member["core"], "protocol": str(member.get("protocol") or "")[:32], "port": member["port"],
                "name": str(member.get("name") or "")[:32], "used": used if type(used) is int and used >= 0 else None,
                "enabled": member.get("enabled") if type(member.get("enabled")) is bool else None,
                "disable_reason": member.get("disable_reason") if member.get("disable_reason") in ("", "manual", "expired", "quota", "platform_quota") else ""})
    return clean
