import copy
import fcntl
import json
import os
import re
import secrets
import socket
import uuid
import hashlib
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlencode

from vaio.common import MUTATIONS, config_revision, validate_task
from .inventory import mutable, read_db, rows, service_for, users_for
from .runtime import Runtime, active_users, atomic_write


class TransactionUnknown(RuntimeError):
    """The task must be inspected on the node, never automatically replayed."""


class TransactionRolledBack(RuntimeError):
    """Runtime and database restoration completed."""


class Bridge:
    def __init__(self, cfg="/etc/vless-reality", state="/var/lib/vaio-agent", runtime=None):
        self.cfg, self.state = Path(cfg), Path(state)
        self.runtime = runtime or Runtime(self.cfg, self.state)

    @contextmanager
    def locked(self):
        self.cfg.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(self.cfg / ".db.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def write(self, db):
        atomic_write(self.cfg / "db.json", json.dumps(db, ensure_ascii=False, indent=2))

    @staticmethod
    def find(db, core, proto, port):
        found = [r for c, p, r in rows(db) if (c, p, r["port"]) == (core, proto, port)]
        if len(found) != 1:
            raise ValueError("无法唯一定位协议实例，请刷新节点")
        return found[0]

    @staticmethod
    def save_row(db, core, proto, before, after):
        value = db.setdefault(core, {}).get(proto, [])
        items = value if isinstance(value, list) else [value]
        new_items = [after if r is before else r for r in items] if before else items + [after]
        new_items = [r for r in new_items if r is not None]
        if not new_items:
            db[core].pop(proto, None)
        else:
            db[core][proto] = new_items if isinstance(value, list) or len(new_items) > 1 else new_items[0]

    @staticmethod
    def check_port(db, port):
        if port in (10085, 10086) or any(row["port"] == port for _, _, row in rows(db)):
            raise ValueError("端口已被使用或为统计接口保留端口")
        # Probe both transports, then release immediately; the service's final bind is authoritative.
        for family, address in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
            for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                with socket.socket(family, kind) as sock:
                    try:
                        sock.bind((address, port))
                    except OSError as error:
                        if family == socket.AF_INET6 and error.errno in (97, 99):
                            continue
                        raise ValueError("目标端口已被系统占用")

    def execute(self, task):
        identity = task.get("id", str(uuid.uuid4()))
        if not isinstance(identity, str) or str(uuid.UUID(identity)) != identity:
            raise ValueError("任务 ID 无效")
        validated = validate_task({k: v for k, v in task.items() if k != "id"})
        if validated["action"] not in MUTATIONS:
            return self._execute({**validated, "id": identity})
        fingerprint = hashlib.sha256(json.dumps(validated, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        directory = self.state / "transactions"
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        record = directory / (identity + ".json")
        # Bridge remains safe even when invoked without the Agent process lock.
        with open(directory / ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if record.exists():
                prior = json.loads(record.read_text())
                if prior.get("fingerprint") != fingerprint:
                    raise ValueError("任务 ID 已用于不同请求，已拒绝执行")
                if prior.get("status") == "succeeded":
                    return prior["result"]
                if prior.get("status") == "failed":
                    raise RuntimeError(prior["message"])
                raise TransactionUnknown("任务结果待核对，禁止重放；节点记录 " + str(record))
            intent = {"fingerprint": fingerprint, "status": "running"}
            atomic_write(record, json.dumps(intent))
            try:
                result = self._execute({**validated, "id": identity})
            except TransactionUnknown:
                atomic_write(record, json.dumps({**intent, "status": "unknown"}))
                raise
            except TransactionRolledBack:
                atomic_write(record, json.dumps({**intent, "status": "failed", "message": "应用失败且配置已回滚；原请求不重放，请刷新后重新提交"}))
                raise
            except ValueError:
                atomic_write(record, json.dumps({**intent, "status": "failed", "message": "参数或配置检查失败，原请求不得重放"}))
                raise
            except Exception:
                # Includes interruption after a filesystem change or unsuccessful
                # restore. Never present an uncertain result as a clean failure.
                atomic_write(record, json.dumps({**intent, "status": "unknown"}))
                raise TransactionUnknown("事务未确认完成，请在节点核对备份；记录 " + str(record))
            atomic_write(record, json.dumps({**intent, "status": "succeeded", "result": result}))
            return result

    def _execute(self, task):
        task_id = task.get("id", str(uuid.uuid4()))
        if not isinstance(task_id, str) or str(uuid.UUID(task_id)) != task_id:
            raise ValueError("任务 ID 无效")
        task = validate_task({k: v for k, v in task.items() if k != "id"})
        core, proto, action = task["core"], task["protocol"], task["action"]
        with self.locked():
            db = read_db(self.cfg)
            if action in MUTATIONS and task["revision"] != config_revision(db):
                raise ValueError("节点配置已变化，已拒绝过期任务；请刷新后重新操作")
            before = None if action == "install" else self.find(db, core, proto, task["port"])
            if before and not mutable(core, proto, before):
                raise ValueError("该实例首版仅支持查看")
            if before and proto.startswith("snell") and before.get("snell_id") and not re.fullmatch(r"[0-9a-f]{24}", str(before["snell_id"])):
                raise ValueError("Snell 实例 ID 无效")
            if before and proto.startswith("snell") and not before.get("snell_id"):
                if len([r for c, p, r in rows(db) if p == proto]) > 1:
                    raise ValueError("旧版多端口 Snell 无法安全定位配置，请先在原脚本完成迁移")
            if action == "inspect":
                return {"steps": ["已读取数据库并验证目标实例"], "affected": [service_for(core, proto, before)]}
            if action == "share":
                return {"connection": self.share(proto, before, task["params"])}
            if action.startswith("user_") and proto.startswith("snell") and action != "user_update":
                raise ValueError("Snell 一用户一端口，请通过新增或卸载协议实例管理")
            original = copy.deepcopy(db)
            params = task["params"]
            after = copy.deepcopy(before)
            if action == "install":
                self.check_port(db, task["port"])
                # Do not mix legacy and independently managed Snell layouts without migration.
                if proto.startswith("snell") and any(p == proto and not r.get("snell_id") for _, p, r in rows(db)):
                    raise ValueError("已有旧版 Snell，请先用原脚本迁移多用户后再添加实例")
                self.runtime.install(proto, core) if proto in ("trojan", "anytls") or (proto == "vless" and core == "singbox") else self.runtime.install(proto)
                name = params.get("name", "default") if proto.startswith("snell") else "default"
                if not proto.startswith("snell") and any(u.get("name") == name for c, p, r in rows(db) if (c, p) == (core, proto) for u in users_for(r)):
                    name = "u" + str(task["port"])
                    if any(u.get("name") == name for c, p, r in rows(db) if (c, p) == (core, proto) for u in users_for(r)):
                        raise ValueError("自动生成的用户名已存在，请选择其他端口")
                credential = str(uuid.uuid4()) if proto == "vless" else secrets.token_hex(16)
                after = {"port": task["port"], "instance_id": str(uuid.uuid4()), "panel_managed": True, "users": [
                    {"name": name, "uuid": credential, "enabled": True, "used": 0, "quota": 0, "expire_date": ""}]}
                if proto == "vless":
                    private, public = self.runtime.keys(core) if core == "singbox" else self.runtime.keys()
                    after.update(uuid=credential, private_key=private, public_key=public, short_id=secrets.token_hex(4),
                                 sni=params["sni"], security_mode="reality")
                elif proto in ("hy2", "trojan", "anytls"):
                    after.update(password=credential, sni=params["sni"], hop_enable="0")
                    self.runtime.certificate(after)
                else:
                    if any(u.get("name") == name for c, p, r in rows(db) if p == proto for u in users_for(r)):
                        raise ValueError("同协议 Snell 用户名已存在")
                    snell_id = secrets.token_hex(12)
                    after.update(psk=credential, snell_id=snell_id, version={"snell": "4", "snell-v5": "5", "snell-v6": "6"}[proto])
                    after["users"][0]["id"] = snell_id
                    db.setdefault("meta", {}).setdefault("snell_users", {})[proto] = True
            elif action == "delete":
                after = None
            elif action == "update":
                if params["port"] != before["port"]:
                    self.check_port(db, params["port"])
                after["port"] = params["port"]
            elif action.startswith("user_"):
                after["users"] = copy.deepcopy(users_for(before))
                users = after["users"]
                found = [u for u in users if u.get("name") == params["name"]]
                if action == "user_add":
                    # Upstream traffic identities are protocol-wide, not per-port.
                    if any(u.get("name") == params["name"] for c, p, row in rows(db) if c == core and p == proto for u in users_for(row)):
                        raise ValueError("同协议用户名已存在")
                    user = {"name": params["name"], "uuid": str(uuid.uuid4()) if proto == "vless" else secrets.token_hex(16), "enabled": True, "used": 0}
                    users.append(user)
                else:
                    if len(found) != 1:
                        raise ValueError("用户不存在或不唯一")
                    user = found[0]
                if action == "user_delete":
                    if params["name"] == "default":
                        raise ValueError("默认用户请禁用；保留记录以兼容原脚本")
                    users.remove(user)
                else:
                    if params.get("quota_gb", 0) > 0:
                        raise ValueError("首版配额为只读：请在原脚本配置并确认统计接口；面板支持用户启停与到期日期")
                    if "expire_date" in params:
                        user["expire_date"] = params["expire_date"]
                    if "enabled" in params:
                        user["enabled"] = params["enabled"]
                    if params.get("reset_credentials"):
                        old_credential = user.get("uuid")
                        user["uuid"] = str(uuid.uuid4()) if proto == "vless" else secrets.token_hex(16)
                        for field in ("uuid", "password", "psk"):
                            if old_credential is not None and after.get(field) == old_credential:
                                after[field] = user["uuid"]
            if after:
                after["panel_managed"] = True
            target = after or before
            service = service_for(core, proto, target)
            paused = db.setdefault("meta", {}).setdefault("panel_paused_services", [])
            if action == "stop":
                if service not in paused:
                    paused.append(service)
            elif action in ("start", "restart"):
                if service in paused:
                    paused.remove(service)
            elif service in paused:
                raise ValueError("该共享服务已暂停，请先启动服务再修改配置")
            # Backups contain credentials; never leave the node or use public file modes.
            backup = self.state / "backups" / task_id
            backup.mkdir(parents=True, mode=0o700)
            atomic_write(backup / "db.json", json.dumps(original, indent=2))
            files = {str(p): p.read_bytes() if p.exists() else None for p in self.runtime.paths(core, proto, target)}
            for number, (path, content) in enumerate(files.items()):
                if content is not None:
                    atomic_write(backup / str(number), content)
            atomic_write(backup / "manifest.json", json.dumps(list(files)))
            running = self.runtime.is_running(service)
            enabled = self.runtime.is_enabled(service)
            atomic_write(backup / "recovery.json", json.dumps({
                "core": core, "protocol": proto, "port": task["port"], "service": service,
                "running": running, "enabled": enabled, "revision": config_revision(original),
                "files": [{"path": path, "backup": str(number) if content is not None else None}
                          for number, (path, content) in enumerate(files.items())]}))
            self.save_row(db, core, proto, before, after)
            try:
                self.write(db)
                if action == "stop":
                    self.runtime.service(service, "stop")
                    self.runtime.service(service, "disable")
                    if self.runtime.is_running(service):
                        raise RuntimeError("服务未成功停止")
                else:
                    self.runtime.apply(core, proto, before, after, db)
            except Exception as error:
                self.write(original)
                try:
                    self.runtime.restore(service, files, running, enabled)
                except Exception:
                    raise TransactionUnknown("应用失败且服务未完全恢复，请在节点检查备份 " + str(backup)) from error
                raise TransactionRolledBack("应用失败：" + str(error) + "；配置已回滚；节点备份 " + str(backup)) from error
            return {"backup": str(backup), "affected": [service],
                    "steps": ["检查配置版本与目标实例", "保存节点本地备份", "更新指定实例", "校验并应用运行配置", "验证服务状态"]}

    @staticmethod
    def share(proto, row, params):
        users = [u for u in users_for(row) if u.get("name") == params["name"]]
        if len(users) != 1:
            raise ValueError("用户不存在")
        credential = users[0]["uuid"]
        host = params["host"]
        host = "[" + host + "]" if ":" in host else host
        address = host + ":" + str(row["port"])
        if proto == "vless":
            query = urlencode({"encryption": "none", "security": "reality", "type": "tcp", "flow": "xtls-rprx-vision",
                               "sni": row["sni"], "fp": "chrome", "pbk": row["public_key"], "sid": row["short_id"]})
            return "vless://" + quote(credential, safe="") + "@" + address + "?" + query + "#" + quote(params["name"])
        if proto == "hy2":
            return "hysteria2://" + quote(credential, safe="") + "@" + address + "?" + urlencode({"sni": row["sni"], "insecure": "1"})
        if proto in ("trojan", "anytls"):
            options = {"sni": row.get("sni", ""), "security": "tls"}
            if row.get("panel_cert"):
                options["allowInsecure"] = "1"
            return proto + "://" + quote(credential, safe="") + "@" + address + "?" + urlencode(options) + "#" + quote(params["name"])
        version = {"snell": 4, "snell-v5": 5, "snell-v6": 6}[proto]
        return f'{params["name"]} = snell, {host}, {row["port"]}, psk={credential}, version={version}, reuse=true'

    def reconcile(self):
        """Locally enforce expiry / externally collected quotas even if the panel is offline."""
        with self.locked():
            db = read_db(self.cfg)
            statepath = self.state / "enforcement.json"
            state = json.loads(statepath.read_text()) if statepath.exists() else {}
            for core, proto, row in rows(db):
                if not row.get("panel_managed") or not mutable(core, proto, row):
                    continue
                if service_for(core, proto, row) in db.get("meta", {}).get("panel_paused_services", []):
                    continue
                key = f'{core}:{proto}:{row["port"]}'
                allowed = [u["name"] for u in active_users(row)]
                if state.get(key) != allowed:
                    service = service_for(core, proto, row)
                    files = {str(p): p.read_bytes() if p.exists() else None for p in self.runtime.paths(core, proto, row)}
                    running, enabled = self.runtime.is_running(service), self.runtime.is_enabled(service)
                    try:
                        self.runtime.apply(core, proto, row, row, db)
                    except Exception:
                        self.runtime.restore(service, files, running, enabled)
                        raise
                    state[key] = allowed
            atomic_write(statepath, json.dumps(state))
