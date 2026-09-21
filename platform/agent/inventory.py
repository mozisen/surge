import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

from vaio import __version__
from vaio.common import PROTOCOLS, config_revision

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


def mutable(core, proto, row):
    if proto not in PROTOCOLS or core != ("singbox" if proto == "hy2" else "xray"):
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
                          "sni": row.get("sni", ""), "users": [
                              {k: u.get(k, default) for k, default in (("name", ""), ("enabled", True), ("used", 0), ("quota", 0), ("expire_date", ""))}
                              for u in users_for(row)]})
    return {"revision": config_revision(db), "instances": instances,
            "hostname": platform.node(), "os": platform.system() + " " + platform.release(),
            "arch": platform.machine(), "agent_version": __version__, "metrics": metrics(),
            "traffic_status": db.get("meta", {}).get("last_traffic_sync_status", "unavailable"), "at": time.time()}


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
    clean["instances"] = []
    instances = snapshot.get("instances", [])
    if not isinstance(instances, list) or len(instances) > 1000:
        raise ValueError("实例数量无效")
    for item in instances:
        if not isinstance(item, dict) or type(item.get("port")) is not int or not 1 <= item["port"] <= 65535:
            raise ValueError("实例端口无效")
        clean_item = {k: text(item.get(k), 100) for k in ("core", "protocol", "service", "status", "sni")}
        clean_item.update(port=item["port"], managed=item.get("managed") is True, users=[])
        for user in item.get("users", [])[:1000]:
            clean_item["users"].append({"name": text(user.get("name"), 32), "enabled": user.get("enabled") is True,
                                        "used": max(0, int(user.get("used", 0))), "quota": max(0, int(user.get("quota", 0))),
                                        "expire_date": text(user.get("expire_date"), 10)})
        clean["instances"].append(clean_item)
    return clean
