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
# Every protocol id the node script knows. Instance writes stay limited to PROTOCOL_CORES;
# reading a member's connection (share) and inspect work for all of them.
SCRIPT_PROTOCOLS = {"vless", "vless-xhttp", "vless-xhttp-cdn", "vless-ws", "vless-ws-notls", "vmess-ws", "vless-vision",
                    "trojan", "trojan-ws", "socks", "ss2022", "ss-legacy", "hy2", "tuic", "anytls", "snell", "snell-v5",
                    "snell-v6", "snell-shadowtls", "snell-v5-shadowtls", "ss2022-shadowtls", "naive"}
MULTI_USER = {"vless", "vless-vision", "vless-ws", "vless-ws-notls", "vless-xhttp", "vless-xhttp-cdn", "vmess-ws", "trojan",
              "trojan-ws", "ss-legacy", "ss2022", "hy2", "tuic", "anytls"}
SINGLE_USER = {"socks", "snell", "snell-v5", "snell-v6", "snell-shadowtls", "snell-v5-shadowtls", "ss2022-shadowtls"}


def user_mode(protocol, row=None):
    """Same table as the script's _proto_user_mode."""
    if protocol == "socks" and (row or {}).get("auth_mode") == "noauth":
        return "none"
    return "multi" if protocol in MULTI_USER else "single" if protocol in SINGLE_USER else "none"


def user_stats(protocol, row=None):
    mode = user_mode(protocol, row)
    return "user" if mode == "multi" else ("inbound" if protocol == "socks" else "port") if mode == "single" else "none"


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
    core = data.get("core")
    if action in ("share", "inspect") and p in SCRIPT_PROTOCOLS and p not in PROTOCOLS:
        if core not in ("xray", "singbox"):
            raise ValueError("协议内核不受支持，请查看节点能力列表")
    else:
        if p not in PROTOCOLS:
            raise ValueError("协议尚未实现安全写入适配，请查看节点能力列表")
        if core not in PROTOCOL_CORES[p]:
            raise ValueError("协议内核不受支持，请查看节点能力列表")
    port(data.get("port"))
    params = data.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("参数无效")
    allowed = {"install": {"sni", "name"} | ADVANCED_INSTALL_FIELDS, "update": {"port"},
               "user_add": {"name", "quota_gb", "reset_day", "expire_date"},
               "user_update": {"name", "quota_gb", "reset_day", "expire_date", "enabled", "reset_credentials"},
               "user_delete": {"name"}, "share": {"name", "host", "port"}}
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
        # The agent compares dates as strings, so only the exact YYYY-MM-DD form is valid (Python 3.11+
        # fromisoformat also takes 20260101; [0-9] keeps out non-ASCII digits).
        value = params["expire_date"]
        try:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError
            datetime.date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValueError("到期日期格式应为 YYYY-MM-DD")
    if action == "share":
        if "host" in params: require_text(params.get("host"), "连接地址", 253, r"[A-Za-z0-9.:-]+")
        if "port" in params: port(params["port"])  # relay entry port shown instead of the instance port
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
    "set_authority": {"op", "mode"},
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
    if any(isinstance(op, dict) and op.get("op") == "set_authority" for op in params["ops"]) and len(params["ops"]) != 1:
        raise ValueError("切换用户管理方式必须单独提交")
    for op in params["ops"]:
        if not isinstance(op, dict) or op.get("op") not in ACCOUNT_OPS or set(op) - ACCOUNT_OPS[op["op"]]:
            raise ValueError("统一用户操作无效")
        if op["op"] == "set_authority":
            if op.get("mode") not in ("script", "platform"):
                raise ValueError("用户管理方式无效")
            continue
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


def validate_upgrade_task(data):
    """One-click node upgrade: the agent and the node's main script, no parameters."""
    if not isinstance(data, dict) or data != {"action": "agent_upgrade", "params": {}}:
        raise ValueError("升级任务字段无效")
    return {"action": "agent_upgrade", "params": {}}


CORE_NAMES = ("xray", "singbox", "snell-v5", "snell-v6")


def validate_core_task(data):
    """Update one proxy core to its latest stable version (Sing-box: the statistics build)."""
    if not isinstance(data, dict) or set(data) != {"action", "params"} or data["action"] != "core_update" \
            or not isinstance(data["params"], dict) or set(data["params"]) != {"core"} or data["params"]["core"] not in CORE_NAMES:
        raise ValueError("内核更新任务字段无效")
    return {"action": "core_update", "params": {"core": data["params"]["core"]}}


def validate_set_url_task(data):
    """Point a node at the panel's new HTTPS address (after binding a domain)."""
    from urllib.parse import urlsplit
    if not isinstance(data, dict) or set(data) != {"action", "params"} or data["action"] != "agent_set_url" \
            or not isinstance(data["params"], dict) or set(data["params"]) != {"url"} or not isinstance(data["params"]["url"], str):
        raise ValueError("面板地址任务字段无效")
    url = data["params"]["url"].rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.path or parts.query or parts.fragment or parts.username or len(url) > 300:
        raise ValueError("新的面板地址必须是 HTTPS 根地址")
    return {"action": "agent_set_url", "params": {"url": url}}


SCRIPT_INSTALL_CORES = ("xray", "singbox", "standalone")
SCRIPT_INSTALL_TYPES = ("port", "enum", "domain", "host")
_ANSWER_KEY = r"[a-z][a-z0-9._-]{0,40}"
_ANSWER_TEXT = r"[A-Za-z0-9._-]{1,253}"


def _plain(value, maximum):
    return value if isinstance(value, str) and len(value) <= maximum and not re.search(r"[\x00-\x1f\x7f<>]", value) else None


def sanitize_install_schema(data):
    """Install form schema declared by the node script (--api capabilities); anything malformed is dropped.
    It only drives the form: the script validates every answer again before installing."""
    clean = {}
    protocols = data.get("protocols") if isinstance(data, dict) and data.get("version") == 1 else None
    for name, item in (protocols.items() if isinstance(protocols, dict) else []):
        if len(clean) >= 40 or not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]{1,32}", name) or not isinstance(item, dict):
            continue
        cores = [c for c in item.get("cores", []) if c in SCRIPT_INSTALL_CORES] if isinstance(item.get("cores"), list) else []
        fields = []
        for field in item.get("fields", [])[:20] if isinstance(item.get("fields"), list) else []:
            if not isinstance(field, dict) or not isinstance(field.get("key"), str) or not re.fullmatch(_ANSWER_KEY, field["key"]) \
                    or field.get("type") not in SCRIPT_INSTALL_TYPES or not _plain(field.get("label"), 40):
                continue
            entry = {"key": field["key"], "type": field["type"], "label": field["label"], "optional": field.get("optional") is True}
            if _plain(field.get("placeholder"), 80):
                entry["placeholder"] = field["placeholder"]
            if field["type"] == "enum":
                options = [{"value": o["value"], "label": o["label"]} for o in field.get("options", [])[:10]
                           if isinstance(o, dict) and isinstance(o.get("value"), str) and re.fullmatch(r"[a-z0-9_-]{1,32}", o["value"]) and _plain(o.get("label"), 80)] \
                    if isinstance(field.get("options"), list) else []
                if not options:
                    continue
                entry["options"] = options
                if field.get("default") in [o["value"] for o in options]:
                    entry["default"] = field["default"]
            when = field.get("when")
            if isinstance(when, dict) and when:
                if len(when) > 3 or not all(isinstance(k, str) and re.fullmatch(_ANSWER_KEY, k) and isinstance(v, str) and re.fullmatch(r"[a-z0-9_-]{1,32}", v)
                                            for k, v in when.items()):
                    continue
                entry["when"] = dict(when)
            fields.append(entry)
        if cores and _plain(item.get("name"), 40):
            clean[name] = {"name": item["name"], "cores": cores, "fields": fields}
    return {"version": 1, "protocols": clean} if clean else None


def validate_script_install_task(data, schema=None):
    """Install through the node script's own flow. With the node's schema (panel side) the protocol, core and
    answer keys and types must match it; the script re-validates semantics (ports, domains, conflicts)."""
    if not isinstance(data, dict) or set(data) != {"action", "params"} or data["action"] != "script_install" \
            or not isinstance(data["params"], dict) or set(data["params"]) != {"protocol", "core", "answers"}:
        raise ValueError("安装任务字段无效")
    params = data["params"]
    if not isinstance(params["protocol"], str) or not re.fullmatch(r"[a-z0-9-]{1,32}", params["protocol"]) \
            or params["core"] not in SCRIPT_INSTALL_CORES:
        raise ValueError("协议或内核无效")
    answers = params["answers"]
    if not isinstance(answers, dict) or len(answers) > 20:
        raise ValueError("安装参数无效")
    for key, value in answers.items():
        if not isinstance(key, str) or not re.fullmatch(_ANSWER_KEY, key) or not (
                (type(value) is int and 1 <= value <= 65535) or (isinstance(value, str) and re.fullmatch(_ANSWER_TEXT, value))):
            raise ValueError("安装参数无效：" + str(key)[:40])
    if schema is not None:
        item = (schema or {}).get("protocols", {}).get(params["protocol"])
        if not item or params["core"] not in item["cores"]:
            raise ValueError("该服务器的节点脚本不支持面板安装此协议")
        fields = {f["key"]: f for f in item["fields"]}
        for key, value in answers.items():
            field = fields.get(key)
            if field is None:
                raise ValueError("安装参数无效：" + key)
            if field["type"] == "port" and type(value) is not int:
                raise ValueError(field["label"] + "必须是 1-65535 的整数")
            if field["type"] == "enum" and value not in [o["value"] for o in field["options"]]:
                raise ValueError(field["label"] + "选项无效")
            if field["type"] in ("domain", "host") and (not isinstance(value, str) or not re.fullmatch(DNS_NAME, value)):
                raise ValueError(field["label"] + "格式无效")
    return {"action": "script_install", "params": {"protocol": params["protocol"], "core": params["core"], "answers": dict(answers)}}


FORWARD_FIELDS = ("backend", "remark", "transport", "listen_host", "listen_port", "remote_host", "remote_port", "enabled")
FORWARD_OPS = {"add": {"op", "rule"}, "update": {"op", "id", "base", "rule"}, "delete": {"op", "id", "base"},
               "enable": {"op", "id", "base"}, "disable": {"op", "id", "base"}}
FORWARD_ID = r"(?:[0-9a-f]{12}|nft-[0-9]{1,5})"
DNS_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"


def _ip(value, version=None):
    import ipaddress
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return version is None or address.version == version


def validate_forward_rule(rule):
    """Same constraints as the script's _fwd_validate; returns the rule with exactly FORWARD_FIELDS."""
    if not isinstance(rule, dict) or set(rule) != set(FORWARD_FIELDS):
        raise ValueError("转发规则字段无效")
    if rule["backend"] not in ("realm", "nftables"):
        raise ValueError("转发类型无效")
    if rule["transport"] not in ("tcp", "udp", "tcp+udp"):
        raise ValueError("转发协议无效")
    for key in ("listen_port", "remote_port"):
        port(rule[key])
    if not isinstance(rule["remark"], str) or len(rule["remark"]) > 64 or re.search(r'[\x00-\x1f\x7f"]', rule["remark"]):
        raise ValueError("备注最多 64 个字符，且不能包含引号或控制字符")
    if type(rule["enabled"]) is not bool:
        raise ValueError("启用状态无效")
    listen, remote = rule["listen_host"], rule["remote_host"]
    if not isinstance(listen, str) or not isinstance(remote, str) or not 1 <= len(remote) <= 253:
        raise ValueError("地址无效")
    if rule["backend"] == "nftables":
        if rule["transport"] != "tcp+udp" or listen != "0.0.0.0":
            raise ValueError("nftables 转发固定为 TCP+UDP 并监听所有地址")
        if not _ip(remote, 4):
            raise ValueError("nftables 转发的目标必须是 IPv4 地址")
    else:
        if listen not in ("0.0.0.0", "::") and not _ip(listen):
            raise ValueError("监听地址必须是 IP 地址")
        if not _ip(remote) and not re.fullmatch(DNS_NAME, remote):
            raise ValueError("目标地址必须是 IP 地址或域名")
    return {k: rule[k] for k in FORWARD_FIELDS}


def validate_forward_task(data):
    """One forwarding change per task; mirrors the script's forward_apply contract."""
    if not isinstance(data, dict) or set(data) != {"action", "params"} or data["action"] != "forward_apply":
        raise ValueError("任务字段无效")
    params = data["params"]
    if not isinstance(params, dict) or set(params) != {"ops"} or not isinstance(params["ops"], list) or len(params["ops"]) != 1:
        raise ValueError("转发操作无效")
    op = params["ops"][0]
    if not isinstance(op, dict) or op.get("op") not in FORWARD_OPS or set(op) != FORWARD_OPS[op["op"]]:
        raise ValueError("转发操作无效")
    if "id" in op and (not isinstance(op["id"], str) or not re.fullmatch(FORWARD_ID, op["id"])):
        raise ValueError("转发规则 ID 无效")
    if "base" in op:
        base = op["base"]
        if not isinstance(base, dict) or set(base) - set(FORWARD_FIELDS) - {"id"}:
            raise ValueError("转发规则快照无效")
    if "rule" in op:
        validate_forward_rule(op["rule"])
    return {"action": "forward_apply", "params": {"ops": [dict(op)]}}


def sanitize_forwards(data):
    """Snapshot rules from the node; drop anything malformed rather than trusting it."""
    clean = []
    for item in data if isinstance(data, list) else []:
        if len(clean) >= 500:
            break
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(FORWARD_ID, item["id"]):
            continue
        try:
            rule = validate_forward_rule({k: item.get(k) for k in FORWARD_FIELDS})
        except ValueError:
            continue
        bytes_value = item.get("bytes")
        clean.append({"id": item["id"], **rule, "status": item.get("status") if item.get("status") in ("running", "stopped", "disabled") else "stopped",
                      "bytes": bytes_value if type(bytes_value) is int and 0 <= bytes_value < 10 ** 18 else None})
    return clean


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
