"""Allowlisted OS operations. Existing routing and unrelated inbounds are preserved."""
import copy
import datetime
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from .inventory import read_db, rows, service_for, users_for

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_SHA = "fc38833fc12d9f1bff8adfa4f12ac1f3aca41aee5978059af68fb27222044c32"


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".vaio-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content.encode() if isinstance(content, str) else content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        # Persist the rename as well as the contents before applying mutations.
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def active_users(row):
    today = datetime.date.today().isoformat()
    return [u for u in users_for(row) if u.get("enabled", True)
            and (not u.get("expire_date") or u["expire_date"] >= today)
            and (not u.get("quota") or u.get("used", 0) < u["quota"])]


def render_inbound(proto, row, previous=None):
    inbound = copy.deepcopy(previous) if previous else {}
    users = active_users(row)
    if proto == "vless":
        inbound.update(port=row["port"])
        if not previous:
            inbound.update(tag="vless-" + str(row["port"]), listen="0.0.0.0", protocol="vless",
                           settings={"decryption": "none"}, streamSettings={"network": "tcp", "security": "reality",
                           "realitySettings": {"show": False, "dest": row["sni"] + ":443", "serverNames": [row["sni"]],
                                               "privateKey": row["private_key"], "shortIds": [row["short_id"]]}})
        inbound.setdefault("settings", {})["clients"] = [{"id": u["uuid"], "email": u["name"] + "@vless", "flow": "xtls-rprx-vision"} for u in users]
        # Empty clients intentionally deny all users; never restore a disabled default credential.
    elif proto == "hy2":
        inbound.update(listen_port=row["port"])
        if not previous:
            inbound.update(type="hysteria2", tag="hy2-in-" + str(row["port"]), listen="0.0.0.0",
                           tls={"enabled": True, "certificate_path": row["panel_cert"], "key_path": row["panel_key"]})
        inbound["users"] = [{"name": "hy2-" + u["name"], "password": u["uuid"]} for u in users]
        if not users:
            # Some core versions require at least one authentication record. A fresh,
            # undisclosed credential keeps all real users disabled without falling back.
            inbound["users"] = [{"name": "vaio-disabled", "password": secrets.token_urlsafe(48)}]
    return inbound


class Runtime:
    def __init__(self, cfg, state):
        self.cfg, self.state = Path(cfg), Path(state)
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log = self.state / "runtime.log"

    def command(self, argv, timeout=120, capture=False):
        # Output may contain credentials: keep only on the node, never in task messages.
        with open(self.log, "ab") as log:
            os.chmod(self.log, 0o600)
            if self.log.stat().st_size > 5 * 1024 * 1024:
                log.truncate(0)
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture else log,
                                    stderr=log, start_new_session=True,
                                    env={**os.environ, "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                                         "ENABLE_DEPRECATED_LEGACY_DOMAIN_STRATEGY_OPTIONS": "true"})
            try:
                output, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                raise RuntimeError("执行 " + Path(argv[0]).name + " 超时；请查看节点 runtime.log")
            if proc.returncode:
                raise RuntimeError("执行 " + Path(argv[0]).name + " 失败（退出码 " + str(proc.returncode) + "）；请查看节点 runtime.log")
            return output.decode().strip() if capture else ""

    def upstream(self, operation, *args):
        allowed = {"install_xray", "install_singbox", "install_snell", "install_snell_v5", "install_snell_v6", "_snell_update_counter_port"}
        if operation not in allowed:
            raise ValueError("未授权的脚本操作")
        source = (ROOT / "vendor/vless-server.sh").read_bytes()
        if hashlib.sha256(source).hexdigest() != UPSTREAM_SHA:
            raise RuntimeError("脚本完整性校验失败")
        library = self.state / "upstream-library.sh"
        atomic_write(library, source.decode().split("# 命令行参数处理\n", 1)[0])
        runner = 'source "$1"; shift; "$@"'
        self.command(["bash", "-c", runner, "vaio", str(library), operation, *args], timeout=1200)

    def install(self, proto):
        operation = {"vless": "install_xray", "hy2": "install_singbox", "snell": "install_snell",
                     "snell-v5": "install_snell_v5", "snell-v6": "install_snell_v6"}[proto]
        self.upstream(operation)

    def keys(self):
        output = self.command(["/usr/local/bin/xray", "x25519"], capture=True)
        private = re.search(r"PrivateKey:\s*(\S+)", output)
        public = re.search(r"(?:Password(?: \(PublicKey\))?|PublicKey):\s*(\S+)", output)
        if not private or not public:
            raise RuntimeError("无法读取 Xray Reality 密钥")
        return private[1], public[1]

    def certificate(self, row):
        certdir = self.cfg / "certs" / "hy2"
        certdir.mkdir(parents=True, mode=0o700, exist_ok=True)
        cert, key = certdir / "server.crt", certdir / "server.key"
        if not cert.exists() and not key.exists():
            self.command(["openssl", "req", "-x509", "-nodes", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                          "-keyout", str(key), "-out", str(cert), "-subj", "/CN=" + row["sni"], "-days", "3650"])
        if not cert.exists() or not key.exists():
            raise ValueError("Hysteria2 证书文件不完整，请先修复")
        key.chmod(0o600)
        row.update(panel_cert=str(cert), panel_key=str(key))

    def is_running(self, service):
        command = ["rc-service", service, "status"] if Path("/sbin/openrc").exists() else ["systemctl", "is-active", service]
        try:
            return subprocess.run(command, capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def service(self, name, action):
        if not re.fullmatch(r"vless-[a-z0-9-]+", name) or action not in {"restart", "start", "stop", "enable", "disable"}:
            raise ValueError("服务操作无效")
        if Path("/sbin/openrc").exists():
            argv = ["rc-update", "add" if action == "enable" else "del", name, "default"] if action in ("enable", "disable") else ["rc-service", name, action]
        else:
            argv = ["systemctl", action, name]
        self.command(argv)

    def is_enabled(self, name):
        if Path("/sbin/openrc").exists():
            return (Path("/etc/runlevels/default") / name).exists()
        try:
            return subprocess.run(["systemctl", "is-enabled", name], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def unit_path(self, service):
        return Path("/etc/init.d") / service if Path("/sbin/openrc").exists() else Path("/etc/systemd/system") / (service + ".service")

    def ensure_unit(self, service, binary, arguments):
        path = self.unit_path(service)
        if path.exists():
            return
        prepare = ""
        if service.startswith("vless-snellu-"):
            prepare = "/usr/bin/python3 -m agent prepare --instance " + service.removeprefix("vless-snellu-")
        if Path("/sbin/openrc").exists():
            content = f'#!/sbin/openrc-run\nname="{service}"\nsupervisor="supervise-daemon"\ndirectory="{ROOT}"\ncommand="{binary}"\ncommand_args="{arguments}"\nrespawn_delay=3\ndepend() {{ need net; }}\n'
            if prepare:
                content += f'start_pre() {{ cd "{ROOT}" && {prepare}; }}\n'
        else:
            content = f"[Unit]\nDescription=Vaio managed {service}\nAfter=network-online.target\n[Service]\nWorkingDirectory={ROOT}\n"
            if prepare:
                content += f"ExecStartPre={prepare}\n"
            content += f"ExecStart={binary} {arguments}\nRestart=on-failure\nRestartSec=3\nLimitNOFILE=51200\n[Install]\nWantedBy=multi-user.target\n"
        atomic_write(path, content)
        path.chmod(0o755 if Path("/sbin/openrc").exists() else 0o644)
        if not Path("/sbin/openrc").exists():
            self.command(["systemctl", "daemon-reload"])

    def config_path(self, core, proto, row):
        if proto.startswith("snell"):
            return self.cfg / "snell-users" / (row["snell_id"] + ".conf") if row.get("snell_id") else self.cfg / (proto + ".conf")
        return self.cfg / ("singbox.json" if core == "singbox" else "config.json")

    def paths(self, core, proto, row):
        return [self.config_path(core, proto, row), self.unit_path(service_for(core, proto, row))]

    def remove_counters(self, identity):
        if not re.fullmatch(r"[0-9a-f]{24}", identity):
            raise ValueError("Snell 实例 ID 无效")
        changes = []
        for chain in ("input", "output"):
            try:
                data = json.loads(self.command(["nft", "-j", "list", "chain", "inet", "vless_snell_users", chain], capture=True))
            except (RuntimeError, FileNotFoundError):
                continue
            for item in data.get("nftables", []):
                rule = item.get("rule", {})
                if rule.get("comment") == identity and type(rule.get("handle")) is int:
                    changes.append(f'delete rule inet vless_snell_users {chain} handle {rule["handle"]}')
        if changes:
            changes += [f'delete counter inet vless_snell_users {prefix}_{identity}' for prefix in ('u', 'd')]
            plan = self.state / "snell-counters.nft"
            atomic_write(plan, '\n'.join(changes) + '\n')
            self.command(["nft", "-f", str(plan)])

    def apply(self, core, proto, before, after, db):
        row = after or before
        service = service_for(core, proto, row)
        path = self.config_path(core, proto, row)
        if proto.startswith("snell"):
            if after is None:
                self.service(service, "stop")
                self.service(service, "disable")
                if before.get("snell_id"):
                    self.remove_counters(before["snell_id"])
                path.unlink(missing_ok=True)
                self.unit_path(service).unlink(missing_ok=True)
                if not Path("/sbin/openrc").exists():
                    self.command(["systemctl", "daemon-reload"])
                return
            old_text = path.read_text() if path.exists() else "[snell-server]\nlisten = 0.0.0.0:0\npsk = pending\n"
            text = re.sub(r"(?m)^(\s*listen\s*=\s*.+:)\d+\s*$", lambda m: m[1] + str(after["port"]), old_text)
            text = re.sub(r"(?m)^\s*psk\s*=.*$", "psk = " + after["psk"], text)
            atomic_write(path, text)
            binary = "/usr/local/bin/" + {"snell": "snell-server", "snell-v5": "snell-server-v5", "snell-v6": "snell-server-v6"}[proto]
            self.ensure_unit(service, binary, "-c " + str(path))
            if after.get("snell_id"):
                self.upstream("_snell_update_counter_port", after["snell_id"], str(after["port"]))
            if not active_users(after):
                self.service(service, "stop")
                self.service(service, "disable")
                return
        else:
            if path.exists():
                config = json.loads(path.read_text())
            elif before:
                raise ValueError("缺少运行配置，拒绝覆盖；请先修复原节点")
            elif core == "xray":
                config = {"log": {"loglevel": "warning"}, "inbounds": [], "outbounds": [{"protocol": "freedom", "tag": "direct"}]}
            else:
                config = {"log": {"level": "warn"}, "inbounds": [], "outbounds": [{"type": "direct", "tag": "direct"}]}
            key = "listen_port" if core == "singbox" else "port"
            matches = [i for i, inbound in enumerate(config.get("inbounds", [])) if before and inbound.get(key) == before["port"]]
            if before and len(matches) != 1:
                raise ValueError("运行配置与数据库不一致，无法唯一定位端口")
            old = config["inbounds"][matches[0]] if matches else None
            if old:
                if (proto == "vless" and (old.get("protocol") != "vless" or old.get("streamSettings", {}).get("security") != "reality")) or (proto == "hy2" and old.get("type") != "hysteria2"):
                    raise ValueError("运行协议与数据库不一致")
            if matches:
                if after:
                    config["inbounds"][matches[0]] = render_inbound(proto, after, old)
                else:
                    config["inbounds"].pop(matches[0])
            else:
                config.setdefault("inbounds", []).append(render_inbound(proto, after))
            if not [i for i in config["inbounds"] if i.get("tag") != "api"]:
                self.service(service, "stop")
                self.service(service, "disable")
                atomic_write(path, json.dumps(config, indent=2))
                return
            atomic_write(path, json.dumps(config, indent=2))
            binary = "/usr/local/bin/sing-box" if core == "singbox" else "/usr/local/bin/xray"
            check = [binary, "check", "-c", str(path)] if core == "singbox" else [binary, "run", "-test", "-config", str(path)]
            self.command(check)
            self.ensure_unit(service, binary, "run -c " + str(path))
        self.service(service, "enable")
        self.service(service, "restart")
        time.sleep(1)
        if not self.is_running(service):
            raise RuntimeError("服务启动后未保持运行")

    def restore(self, service, files, running, enabled):
        # Stop the new process before restoring files, then return to the previous state.
        try:
            self.service(service, "stop")
        except RuntimeError:
            pass
        try:
            self.service(service, "disable")
        except RuntimeError:
            pass
        for path, content in files.items():
            if content is None:
                Path(path).unlink(missing_ok=True)
            else:
                atomic_write(path, content)
                if str(path).startswith("/etc/init.d/"):
                    Path(path).chmod(0o755)
        if not Path("/sbin/openrc").exists():
            self.command(["systemctl", "daemon-reload"])
        if service.startswith("vless-snellu-"):
            identity = service.removeprefix("vless-snellu-")
            original = next((r for _, _, r in rows(read_db(self.cfg)) if r.get("snell_id") == identity), None)
            if original:
                self.upstream("_snell_update_counter_port", identity, str(original["port"]))
            else:
                self.remove_counters(identity)
        if enabled:
            self.service(service, "enable")
        if running:
            self.service(service, "start")
            if not self.is_running(service):
                raise RuntimeError("回滚后服务仍未恢复")
