"""Wire contract shared by panel and agent. No shell fragments cross this boundary."""
import datetime
import hashlib
import json
import re

PROTOCOLS = {"vless": "VLESS Reality", "hy2": "Hysteria2", "snell": "Snell v4",
             "snell-v5": "Snell v5", "snell-v6": "Snell v6"}
MUTATIONS = {"install", "update", "delete", "restart", "start", "stop", "user_add", "user_update", "user_delete"}
ACTIONS = MUTATIONS | {"share", "inspect"}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def require_text(value, name, maximum=80, pattern=None):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError(name + " 格式无效")
    if pattern and not re.fullmatch(pattern, value):
        raise ValueError(name + " 格式无效")
    return value


def port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("端口必须是 1–65535 的整数")
    return value


def validate_task(data):
    if not isinstance(data, dict) or set(data) - {"action", "protocol", "core", "port", "params", "revision"}:
        raise ValueError("任务字段无效")
    action = data.get("action")
    if action not in ACTIONS:
        raise ValueError("不支持的操作")
    p = data.get("protocol")
    if p not in PROTOCOLS:
        raise ValueError("首版支持 VLESS Reality、Hysteria2、Snell v4/v5/v6 的写入操作")
    core = data.get("core")
    if core != ("singbox" if p == "hy2" else "xray"):
        raise ValueError("协议内核不受支持；首版 VLESS 写入仅支持 Xray")
    port(data.get("port"))
    params = data.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("参数无效")
    allowed = {"install": {"sni", "name"}, "update": {"port"},
               "user_add": {"name", "quota_gb", "expire_date"},
               "user_update": {"name", "quota_gb", "expire_date", "enabled"},
               "user_delete": {"name"}, "share": {"name", "host"}}
    if set(params) - allowed.get(action, set()):
        raise ValueError("不支持的参数")
    if action in ("user_add", "user_update", "user_delete"):
        require_text(params.get("name"), "用户名", 32, r"[A-Za-z0-9_-]+")
    if action == "install":
        require_text(params.get("name", "default"), "用户名", 32, r"[A-Za-z0-9_-]+")
        if p in ("vless", "hy2"):
            require_text(params.get("sni"), "SNI", 253, r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
    if action == "update":
        port(params.get("port"))
    if "enabled" in params and type(params["enabled"]) is not bool:
        raise ValueError("用户状态无效")
    if "quota_gb" in params and (type(params["quota_gb"]) is not int or not 0 <= params["quota_gb"] <= 999999):
        raise ValueError("配额必须为 0–999999 GiB")
    if params.get("expire_date"):
        try:
            datetime.date.fromisoformat(params["expire_date"])
        except (TypeError, ValueError):
            raise ValueError("到期日期格式应为 YYYY-MM-DD")
    if action == "share":
        require_text(params.get("host"), "连接地址", 253, r"[A-Za-z0-9.:-]+")
        require_text(params.get("name"), "用户名", 32, r"[A-Za-z0-9_-]+")
    if action in MUTATIONS:
        require_text(data.get("revision"), "配置版本", 64, r"[0-9a-f]{64}")
    return {"action": action, "protocol": p, "core": core, "port": data["port"],
            "params": params, "revision": data.get("revision", "")}


def config_revision(db):
    # Counters and notification metadata change independently of configuration.
    volatile = {"used", "counter_up", "counter_down", "counter_generation", "last_alert_percent",
                "last_alert_date", "last_expire_notice", "updated", "last_sync"}
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in volatile and not k.startswith("last_traffic_")}
        if isinstance(value, list):
            return [clean(x) for x in value]
        return value
    return digest(json.dumps(clean(db), sort_keys=True, separators=(",", ":")))
