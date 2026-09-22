"""Strict installation options; no shell fragments or filesystem paths in requests."""
import base64
import ipaddress
import re
import uuid

TLS_PROTOCOLS = {"hy2", "trojan", "anytls"}
ADVANCED_INSTALL_FIELDS = {"credential", "certificate_mode", "acme_email",
                           "mode", "dns", "dns_ip_preference", "tfo", "private_key", "short_id"}

REALITY_INSTALL_FIELDS = {"private_key", "short_id"}


def validate_install_options(proto, params):
    allowed = {"name", "credential"}
    if proto == "vless" or proto in TLS_PROTOCOLS:
        allowed.add("sni")
    if proto == "vless":
        allowed |= REALITY_INSTALL_FIELDS
    if proto in TLS_PROTOCOLS:
        allowed |= {"certificate_mode", "acme_email"}
    if proto == "snell-v6":
        allowed |= {"mode", "dns", "dns_ip_preference", "tfo"}
    if set(params) - allowed:
        raise ValueError("该协议不具备所提交的安装参数")
    if "private_key" in params:
        value = params["private_key"]
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
            raise ValueError("Reality 私钥必须为 32 字节 Base64URL 编码")
        raw = base64.urlsafe_b64decode(value + "=")
        if base64.urlsafe_b64encode(raw).decode().rstrip("=") != value:
            raise ValueError("Reality 私钥编码无效")
    if "short_id" in params and (not isinstance(params["short_id"], str) or
                                 not re.fullmatch(r"(?:[0-9a-fA-F]{2}){1,8}", params["short_id"])):
        raise ValueError("Short ID 必须为 2–16 位偶数长度十六进制字符")
    if "credential" in params:
        value = params["credential"]
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+=./-]{8,128}", value):
            raise ValueError("凭据必须为 8–128 位安全字符；留空请省略该字段以自动生成")
        if proto == "vless":
            try:
                uuid.UUID(value)
            except ValueError:
                raise ValueError("VLESS 凭据必须为 UUID")
    mode = params.get("certificate_mode", "self")
    if mode not in {"self", "existing", "acme"}:
        raise ValueError("证书模式无效")
    if "acme_email" in params:
        if mode != "acme" or not isinstance(params["acme_email"], str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", params["acme_email"]) or len(params["acme_email"]) > 254:
            raise ValueError("ACME 联系邮箱无效")
    if mode == "acme" and not params.get("acme_email"):
        raise ValueError("申请证书需要联系邮箱")
    if mode in {"existing", "acme"}:
        domain = params.get("sni", "")
        if not isinstance(domain, str) or not re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}", domain):
            raise ValueError("真实证书需要有效域名")
    if params.get("mode", "default") not in {"default", "unshaped", "unsafe-raw"}:
        raise ValueError("Snell 模式无效")
    if params.get("dns_ip_preference", "default") not in {"default", "prefer-ipv4", "prefer-ipv6", "ipv4-only", "ipv6-only"}:
        raise ValueError("DNS IP 偏好无效")
    if "tfo" in params and type(params["tfo"]) is not bool:
        raise ValueError("TFO 必须为布尔值")
    if "dns" in params:
        value = params["dns"]
        if not isinstance(value, str) or len(value) > 512:
            raise ValueError("DNS 列表无效")
        for address in value.split(",") if value else []:
            try:
                ipaddress.ip_address(address.strip())
            except ValueError:
                raise ValueError("DNS 服务器必须为逗号分隔的 IP 地址")
