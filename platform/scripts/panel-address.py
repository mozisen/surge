#!/usr/bin/env python3
"""Panel address helper (root): Nginx site, certificate, VAIO_PUBLIC_URL.

install  --domain D --port P | --ip IP --port P   used by install-panel.sh
apply                                              run by vaio-panel-address.service when the panel writes a request
domain   --domain D [--port P]                     same as a panel request, from the shell (vaio-panel domain)

The panel itself has no root rights: it writes $DATA/address-request.json and reads $DATA/address-status.json.
State lives in /etc/vaio-panel/address.json: {"legacy": {"ip", "port"} | null, "previous": {"name", "port"} | null,
"domain": {"name", "port"} | null}. legacy (HTTP by IP) and previous (the domain before a change) keep serving until
close-legacy, so nodes still using them can receive the new address.
Every change rewrites the whole Nginx site from that state; a failure restores the previous files.
"""
import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PREFIX = Path(os.environ.get("VAIO_ADDRESS_PREFIX", "/"))
ETC = PREFIX / "etc/vaio-panel"
STATE = ETC / "address.json"
ENV = ETC / "panel.env"
DATA = PREFIX / "var/lib/vaio-panel"
REQUEST = DATA / "address-request.json"
STATUS = DATA / "address-status.json"
SITE = PREFIX / "etc/nginx/sites-available/vaio-panel"
ENABLED = PREFIX / "etc/nginx/sites-enabled/vaio-panel"
LIVE = PREFIX / "etc/letsencrypt/live"
BACKEND = "http://127.0.0.1:18080"
DOMAIN = re.compile(r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}")


def run(*command, **kwargs):
    return subprocess.run(list(command), check=True, timeout=kwargs.pop("timeout", 300), **kwargs)


def check_port(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("端口必须是 1–65535 的整数")
    return port


def check_domain(name):
    if not isinstance(name, str) or not DOMAIN.fullmatch(name) or len(name) > 253:
        raise ValueError("域名格式无效，请输入不带 https:// 和路径的域名")
    return name.lower()


def check_ip(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise ValueError("IP 地址无效") from None
    if address.version != 4:
        raise ValueError("请使用 IPv4 地址")
    return str(address)


def public_url(state):
    if state.get("domain"):
        d = state["domain"]
        return "https://" + d["name"] + ("" if d["port"] == 443 else ":%d" % d["port"])
    legacy = state["legacy"]
    return "http://" + legacy["ip"] + ("" if legacy["port"] == 80 else ":%d" % legacy["port"])


def proxy_block():
    return ("    client_max_body_size 1m;\n    location / {\n        proxy_pass %s;\n        proxy_set_header Host $host;\n"
            "        proxy_set_header X-Real-IP $remote_addr;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
            "        proxy_set_header X-Forwarded-Proto $scheme;\n    }\n") % BACKEND


def ssl_block(name, port):
    cert = "/etc/letsencrypt/live/%s" % name
    return ("server {\n    listen %d ssl;\n    listen [::]:%d ssl;\n    server_name %s;\n    ssl_certificate %s/fullchain.pem;\n"
            "    ssl_certificate_key %s/privkey.pem;\n    ssl_protocols TLSv1.2 TLSv1.3;\n%s}\n" % (port, port, name, cert, cert, proxy_block()))


def render(state, acme_only=False):
    """The whole Nginx site for a state. acme_only: just the port-80 block certbot needs to issue the certificate."""
    blocks = []
    legacy, domain, previous = state.get("legacy"), state.get("domain"), state.get("previous")
    if previous and (not domain or previous["name"] != domain["name"]):
        blocks.append(ssl_block(previous["name"], previous["port"]))
    if legacy:
        # Panel without a domain: plain HTTP on the chosen port (kept as the legacy address after binding a domain).
        blocks.append("server {\n    listen %d;\n    listen [::]:%d;\n    server_name %s _;\n%s}\n" % (legacy["port"], legacy["port"], legacy["ip"], proxy_block()))
    if domain:
        name, port = domain["name"], domain["port"]
        if acme_only:
            blocks.append("server {\n    listen 80;\n    listen [::]:80;\n    server_name %s;\n%s}\n" % (name, proxy_block()))
        else:
            target = "https://%s%s$request_uri" % (name, "" if port == 443 else ":%d" % port)
            blocks.append("server {\n    listen 80;\n    listen [::]:80;\n    server_name %s;\n    location /.well-known/acme-challenge/ { root /var/www/html; }\n"
                          "    location / { return 301 %s; }\n}\n" % (name, target))
            blocks.append(ssl_block(name, port))
    return "# 由 vaio-panel 管理（scripts/panel-address.py），请勿手动修改\n" + "\n".join(blocks)


def write_env(state):
    lines = [line for line in (ENV.read_text().splitlines() if ENV.exists() else [])
             if not line.startswith(("VAIO_PUBLIC_URL=", "VAIO_ALLOW_HTTP="))]
    lines.insert(0, "VAIO_PUBLIC_URL=" + public_url(state))
    if state.get("legacy"):
        lines.append("VAIO_ALLOW_HTTP=1")
    ENV.write_text("\n".join(lines) + "\n")
    ENV.chmod(0o600)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    # Installed before 1.1.0: derive the state from the panel address (certbot-managed site on 443).
    url = next((l.split("=", 1)[1] for l in ENV.read_text().splitlines() if l.startswith("VAIO_PUBLIC_URL=")), "") if ENV.exists() else ""
    match = re.fullmatch(r"https://([^/:]+)(?::(\d+))?/?", url)
    if not match:
        raise ValueError("无法识别当前面板地址，请检查 /etc/vaio-panel/panel.env")
    return {"legacy": None, "previous": None, "domain": {"name": match.group(1), "port": int(match.group(2) or 443)}}


def save_state(state):
    STATE.write_text(json.dumps(state))
    STATE.chmod(0o600)


def status(state, action, message, **extra):
    DATA.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({"state": state, "action": action, "message": message, "at": time.time(), **extra}, ensure_ascii=False))
    try:
        shutil.chown(STATUS, "vaio-panel", "vaio-panel")
    except (LookupError, PermissionError, OSError):
        pass


def port_busy(port, own_ports, share_nginx=True):
    """A listener on the port that is not ours. With a domain, Nginx can share a port with other sites (server_name);
    a panel without a domain needs the port to itself."""
    if port in own_ports:
        return False
    try:
        out = subprocess.run(["ss", "-lntpH"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    for line in out.splitlines():
        fields = line.split()
        if len(fields) > 3 and re.search(r"[:.]%d$" % port, fields[3]) and not (share_nginx and '"nginx"' in line):
            return True
    return False


def own_ports(state):
    ports = set()
    if state.get("legacy"):
        ports.add(state["legacy"]["port"])
    if state.get("domain"):
        ports |= {80, state["domain"]["port"]}
    if state.get("previous"):
        ports.add(state["previous"]["port"])
    return ports


def reload_nginx():
    run("nginx", "-t", capture_output=True)
    run("systemctl", "reload", "nginx")


def issue(name):
    if (LIVE / name / "fullchain.pem").exists():
        return
    run("certbot", "certonly", "--nginx", "-d", name, "--agree-tos", "--register-unsafely-without-email", "--non-interactive", capture_output=True, timeout=600)


def transition(old, new, restart=True):
    """Write Nginx, certificate and panel.env for the new state; restore the old files on any failure."""
    saved = {path: path.read_bytes() if path.exists() else None for path in (SITE, ENV, STATE)}
    try:
        if new.get("domain") and not (LIVE / new["domain"]["name"] / "fullchain.pem").exists():
            SITE.write_text(render({**new, "legacy": old.get("legacy") or new.get("legacy")}, acme_only=True))
            if not ENABLED.exists():
                ENABLED.symlink_to(SITE)
            reload_nginx()
            issue(new["domain"]["name"])
        SITE.write_text(render(new))
        if not ENABLED.exists():
            ENABLED.symlink_to(SITE)
        reload_nginx()
        write_env(new)
        save_state(new)
        if restart:
            run("systemctl", "restart", "vaio-panel")
            run("curl", "--fail", "--retry", "10", "--retry-connrefused", "--retry-delay", "1", "--max-time", "10", "-sS",
                "http://127.0.0.1:18080/healthz", capture_output=True)
    except Exception:
        for path, content in saved.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        try:
            reload_nginx()
            if restart:
                run("systemctl", "restart", "vaio-panel")
        except Exception:
            pass
        raise


def set_domain(name, port):
    name, port = check_domain(name), check_port(port)
    state = load_state()
    if port_busy(port, own_ports(state)) or (not state.get("domain") and port_busy(80, own_ports(state))):
        raise ValueError("端口 %d%s 已被其他服务占用" % (port, "" if port == 80 else " 或 80"))
    if state.get("legacy") and state["legacy"]["port"] == port:
        raise ValueError("新端口不能与当前未加密地址的端口 %d 相同" % port)
    old_domain = state.get("domain")
    previous = old_domain if old_domain and old_domain["name"] != name else state.get("previous")
    new = {"legacy": state.get("legacy"), "previous": previous, "domain": {"name": name, "port": port}}
    transition(state, new)
    return public_url(new)


def close_legacy():
    state = load_state()
    if not state.get("domain"):
        raise ValueError("尚未绑定域名，不能关闭当前地址")
    if not state.get("legacy") and not state.get("previous"):
        return public_url(state)
    new = {"legacy": None, "previous": None, "domain": state["domain"]}
    transition(state, new)
    return public_url(new)


def apply():
    """Process the request the panel wrote (one at a time)."""
    if not REQUEST.exists():
        return
    try:
        request = json.loads(REQUEST.read_text())
    except ValueError:
        request = {}
    REQUEST.unlink(missing_ok=True)
    action = request.get("action") if isinstance(request, dict) else None
    if action == "install_update_helper":
        # Panels upgraded by a 1.1.0 updater lack the self-update units; this helper already runs the new code.
        subprocess.run([sys.executable, str(Path(__file__).resolve().with_name("update-panel.py")), "--install-helpers"], check=False, timeout=300)
        return
    status("running", action, "正在处理")
    try:
        if action == "set_domain":
            url = set_domain(request.get("domain"), request.get("port"))
            status("succeeded", action, "已切换到 " + url, url=url)
        elif action == "close_legacy":
            url = close_legacy()
            status("succeeded", action, "已关闭未加密地址，面板地址为 " + url, url=url)
        else:
            raise ValueError("未知的地址操作")
    except subprocess.CalledProcessError as error:
        detail = ((error.stderr or b"").decode(errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or "")).strip().splitlines()
        status("failed", action, "执行失败，已恢复原配置：" + (detail[-1][:200] if detail else " ".join(map(str, error.cmd))[:120]))
    except Exception as error:
        status("failed", action, str(error)[:300] or "执行失败，已恢复原配置")


def install(args):
    if args.domain:
        state = {"legacy": None, "previous": None, "domain": {"name": check_domain(args.domain), "port": check_port(args.port)}}
    else:
        state = {"legacy": {"ip": check_ip(args.ip), "port": check_port(args.port)}, "previous": None, "domain": None}
        if port_busy(state["legacy"]["port"], set(), share_nginx=False):
            raise ValueError("端口 %d 已被占用，请换一个端口" % state["legacy"]["port"])
    if state["domain"] and (port_busy(state["domain"]["port"], set()) or port_busy(80, set())):
        raise ValueError("端口 %d 或 80 已被 Nginx 以外的程序占用" % state["domain"]["port"])
    transition({"legacy": None, "domain": None}, state, restart=False)
    print(public_url(state))


def main():
    parser = argparse.ArgumentParser(description="面板地址（Nginx、证书、VAIO_PUBLIC_URL）")
    parser.add_argument("command", choices=["install", "apply", "domain", "close-legacy", "url"])
    parser.add_argument("--domain")
    parser.add_argument("--ip")
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if os.geteuid() != 0 and PREFIX == Path("/"):
        raise SystemExit("请使用 root 运行")
    try:
        if args.command == "install":
            install(args)
        elif args.command == "apply":
            apply()
        elif args.command == "domain":
            print(set_domain(args.domain, args.port or 443))
        elif args.command == "close-legacy":
            print(close_legacy())
        else:
            print(public_url(load_state()))
    except ValueError as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    main()
