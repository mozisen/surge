"""Wire contract shared by panel and agent. No shell fragments cross this boundary."""
import datetime
import hashlib
import json
import re
from .install_options import ADVANCED_INSTALL_FIELDS, validate_install_options

PROTOCOLS = {"vless": "VLESS Reality", "hy2": "Hysteria2", "snell": "Snell v4",
             "snell-v5": "Snell v5", "snell-v6": "Snell v6", "trojan": "Trojan", "anytls": "AnyTLS", "ss-legacy": "SS", "ss2022": "SS2022"}
PROTOCOL_CORES = {"ss-legacy": ("singbox",), "ss2022": ("singbox",), "vless": ("xray", "singbox"), "hy2": ("singbox",), "anytls": ("singbox",),
                  "trojan": ("xray", "singbox"), "snell": ("xray",), "snell-v5": ("xray",), "snell-v6": ("xray",)}
LEGACY_COMBINATIONS = {("xray", "vless"), ("singbox", "hy2"), ("xray", "snell"), ("xray", "snell-v5"), ("xray", "snell-v6")}


def write_capabilities():
    return [{"core": core, "protocol": proto} for proto, cores in PROTOCOL_CORES.items() for core in cores]
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
        raise ValueError("协议尚未实现安全写入适配，请查看节点能力列表")
    core = data.get("core")
    if core not in PROTOCOL_CORES[p]:
        raise ValueError("协议内核不受支持，请查看节点能力列表")
    port(data.get("port"))
    params = data.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("参数无效")
    allowed = {"install": {"sni", "name"} | ADVANCED_INSTALL_FIELDS, "update": {"port"},
               "user_add": {"name", "quota_gb", "reset_day", "expire_date"},
               "user_update": {"name", "quota_gb", "reset_day", "expire_date", "enabled", "reset_credentials"},
               "user_delete": {"name"}, "share": {"name", "host"}}
    if set(params) - allowed.get(action, set()):
        raise ValueError("不支持的参数")
    if action in ("user_add", "user_update", "user_delete"):
        require_text(params.get("name"), "用户名", 32, r"[A-Za-z0-9_-]+")
    if action == "install":
        validate_install_options(p, params)
        require_text(params.get("name", "default"), "用户名", 32, r"[A-Za-z0-9_-]+")
        if p in ("vless", "hy2", "trojan", "anytls"):
            require_text(params.get("sni"), "SNI", 253, r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
    if action == "update":
        port(params.get("port"))
    if "reset_credentials" in params and type(params["reset_credentials"]) is not bool:
        raise ValueError("凭据重置选项无效")
    if "enabled" in params and type(params["enabled"]) is not bool:
        raise ValueError("用户状态无效")
    if "quota_gb" in params and (type(params["quota_gb"]) is not int or not 0 <= params["quota_gb"] <= 999999):
        raise ValueError("配额必须为 0–999999 GiB")
    if "reset_day" in params and (type(params["reset_day"]) is not int or not 0 <= params["reset_day"] <= 28):
        raise ValueError("月度重置日必须为 1–28，0 表示不自动重置")
    if params.get("expire_date"):
        try:
            datetime.date.fromisoformat(params["expire_date"])
        except (TypeError, ValueError):
            raise ValueError("到期日期格式应为 YYYY-MM-DD")
    if action == "share":
        if "host" in params: require_text(params.get("host"), "连接地址", 253, r"[A-Za-z0-9.:-]+")
        require_text(params.get("name"), "用户名", 32, r"[A-Za-z0-9_-]+")
    if action in MUTATIONS:
        require_text(data.get("revision"), "配置版本", 64, r"[0-9a-f]{64}")
    return {"action": action, "protocol": p, "core": core, "port": data["port"],
            "params": params, "revision": data.get("revision", "")}


UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ACCOUNT_FIELDS = ("name", "note", "enabled", "expire_date", "quota", "reset_day")
ACCOUNT_OPS = {
    "create": {"op", "account_id", "fields", "platform_user_id", "members"},
    "update": {"op", "account_id", "base_rev", "fields"},
    "link": {"op", "account_id", "platform_user_id"},
    "unlink": {"op", "account_id"},
    "block": {"op", "account_id", "platform_block"},
    "member_add": {"op", "account_id", "target", "name"},
    "member_claim": {"op", "account_id", "target", "name", "count_existing"},
    "member_remove": {"op", "account_id", "target", "name", "mode"},
    "reset_credentials": {"op", "account_id", "member"},
    "reset_usage": {"op", "account_id"},
    "delete": {"op", "account_id", "mode"},
}


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _account_target(value):
    if not isinstance(value, dict) or set(value) != {"core", "protocol", "port"}:
        raise ValueError("统一用户成员目标无效")
    if value["core"] not in ("xray", "singbox") or not isinstance(value["protocol"], str) or not re.fullmatch(r"[a-z0-9-]{1,32}", value["protocol"]):
        raise ValueError("统一用户成员目标无效")
    port(value["port"])


def _account_fields(value, create=False):
    if not isinstance(value, dict) or not value or set(value) - set(ACCOUNT_FIELDS) or (create and "name" not in value):
        raise ValueError("统一用户字段无效")
    if "name" in value:
        require_text(value["name"], "用户名", 32, r"[A-Za-z0-9_-]+")
    if "note" in value and (not isinstance(value["note"], str) or len(value["note"]) > 200 or any(ord(c) < 32 for c in value["note"])):
        raise ValueError("备注最多 200 字，且不能包含控制字符")
    if "enabled" in value and type(value["enabled"]) is not bool:
        raise ValueError("用户状态无效")
    if "expire_date" in value:
        if not isinstance(value["expire_date"], str) or (value["expire_date"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["expire_date"])):
            raise ValueError("到期日期格式应为 YYYY-MM-DD")
    if "quota" in value and not _integer(value["quota"], 0, 9999999999999999):
        raise ValueError("配额无效")
    if "reset_day" in value and not _integer(value["reset_day"], 0, 28):
        raise ValueError("月度重置日必须为 1–28，0 表示不自动重置")


def validate_platform_task(data):
    """Node-wide unified-account sync task; mirrors the script's account_apply contract."""
    if not isinstance(data, dict) or set(data) != {"action", "params"} or data["action"] != "platform_apply":
        raise ValueError("任务字段无效")
    params = data["params"]
    if not isinstance(params, dict) or set(params) != {"ops"} or not isinstance(params["ops"], list) or not 1 <= len(params["ops"]) <= 200:
        raise ValueError("统一用户操作列表无效")
    for op in params["ops"]:
        if not isinstance(op, dict) or op.get("op") not in ACCOUNT_OPS or set(op) - ACCOUNT_OPS[op["op"]]:
            raise ValueError("统一用户操作无效")
        if not isinstance(op.get("account_id"), str) or not re.fullmatch(UUID_PATTERN, op["account_id"]):
            raise ValueError("统一用户 ID 无效")
        kind = op["op"]
        if kind == "create":
            _account_fields(op.get("fields"), create=True)
            members = op.get("members", [])
            if not isinstance(members, list) or len(members) > 50:
                raise ValueError("统一用户成员无效")
            for member in members:
                if not isinstance(member, dict) or set(member) - {"target", "name"}:
                    raise ValueError("统一用户成员无效")
                _account_target(member.get("target"))
                if "name" in member:
                    require_text(member["name"], "用户名", 32, r"[A-Za-z0-9_-]+")
        if kind == "update":
            if not _integer(op.get("base_rev"), 0, 999999999999):
                raise ValueError("统一用户版本无效")
            _account_fields(op.get("fields"))
        if kind in ("create", "link") and ("platform_user_id" in op or kind == "link"):
            if not isinstance(op.get("platform_user_id"), str) or not re.fullmatch(UUID_PATTERN, op["platform_user_id"]):
                raise ValueError("平台用户 ID 无效")
        if kind == "block" and op.get("platform_block") not in ("", "quota"):
            raise ValueError("平台停用原因无效")
        if kind in ("member_add", "member_claim", "member_remove"):
            _account_target(op.get("target"))
            if kind != "member_add" or "name" in op:
                require_text(op.get("name"), "用户名", 32, r"[A-Za-z0-9_-]+")
        if kind == "member_claim" and "count_existing" in op and type(op["count_existing"]) is not bool:
            raise ValueError("用量计入选项无效")
        if kind in ("member_remove", "delete") and op.get("mode", "release") not in ("release", "delete"):
            raise ValueError("移除方式无效")
        if kind == "reset_credentials" and "member" in op:
            member = op["member"]
            if not isinstance(member, dict) or set(member) != {"core", "protocol", "port", "name"}:
                raise ValueError("统一用户成员无效")
            _account_target({k: member[k] for k in ("core", "protocol", "port")})
            require_text(member["name"], "用户名", 32, r"[A-Za-z0-9_-]+")
    return {"action": "platform_apply", "params": params}


def config_revision(db):
    # Counters and notification metadata change independently of configuration.
    volatile = {"used", "counter_up", "counter_down", "counter_generation", "last_alert_percent",
                "last_alert_date", "last_expire_notice", "updated", "last_sync", "traffic_observed_at",
                "traffic_observed_xray", "traffic_observed_singbox", "panel_used", "panel_last_used", "panel_cycle",
                # Script unified-account settlement updates these on every traffic sync.
                "cycle_used", "last_raw", "accounts_reload_pending"}
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in volatile and not k.startswith("last_traffic_")}
        if isinstance(value, list):
            return [clean(x) for x in value]
        return value
    return digest(json.dumps(clean(db), sort_keys=True, separators=(",", ":")))
