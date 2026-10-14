#!/usr/bin/env python3
"""Identity-preserving agent upgrade: run by the administrator, or detached by the agent
for a panel upgrade task (--task). The node's main script is upgraded with the agent."""
import argparse
import ast
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("下载地址发生重定向，已停止")


def extract_bundle(payload, destination):
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        total = 0
        for item in archive.getmembers():
            path = Path(item.name)
            total += item.size
            if (path.is_absolute() or ".." in path.parts or not path.parts or
                    path.parts[0] not in ("agent", "vaio", "vendor", "scripts") or
                    not (item.isfile() or item.isdir()) or total > 32 * 1024 * 1024):
                raise ValueError("安装包路径或大小无效")
        for item in archive.getmembers():
            target = destination / item.name
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(item).read())
    source = ast.parse((destination / "vaio/__init__.py").read_text())
    version = next(ast.literal_eval(n.value) for n in source.body
                   if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets))
    if not isinstance(version, str):
        raise ValueError("版本无效")
    return version


MAIN_SCRIPT = Path("/usr/local/bin/vless-server.sh")
RESULT = Path("/var/lib/vaio-agent/last-upgrade.json")


def bundle_script(stage):
    """The vendored script of the new bundle, verified against the bundle's own pin."""
    script = stage / "vendor/vless-server.sh"
    pin = re.search(r'^UPSTREAM_SHA = "([0-9a-f]{64})"', (stage / "agent/runtime.py").read_text(), re.M)
    if not pin or hashlib.sha256(script.read_bytes()).hexdigest() != pin[1]:
        raise RuntimeError("新安装包中的节点脚本校验失败")
    return script


def script_version(path):
    try:
        match = re.search(r'^readonly VERSION="([^"]+)"', Path(path).read_text(errors="replace"), re.M)
    except OSError:
        return ""
    return match[1] if match else ""


def replace_main_script(stage, target=MAIN_SCRIPT):
    """Atomically install the bundle's script; returns the backup path (None when unchanged)."""
    source = bundle_script(stage)
    target = Path(target)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise RuntimeError("主脚本路径不是普通文件，未覆盖")
    content = source.read_bytes()
    if target.exists() and target.read_bytes() == content:
        return None
    backup = target.with_name(target.name + ".vaio-backup-" + str(time.time_ns())) if target.exists() else None
    if backup:
        shutil.copy2(target, backup)
    fd, temp = tempfile.mkstemp(dir=str(target.parent), prefix=".vaio-script-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.chmod(temp, 0o755)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return backup or "installed"


def restore_main_script(backup, target=MAIN_SCRIPT):
    if backup == "installed":
        Path(target).unlink(missing_ok=True)
    elif backup:
        os.replace(backup, target)


def wait_reported(journal_path, task_id, timeout=120, pause=2):
    """The panel refuses maintenance while the triggering task is unreported."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        journal = json.loads(Path(journal_path).read_text()) if Path(journal_path).exists() else {}
        item = journal.get(task_id)
        if item and item.get("status") != "running" and item.get("sent"):
            return
        time.sleep(pause)
    raise RuntimeError("升级任务结果未能上报，已停止升级")


def write_result(data, path=RESULT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".last-upgrade-")
    with os.fdopen(fd, "w") as handle:
        json.dump({**data, "message": str(data.get("message", ""))[:300]}, handle)
    os.replace(temp, path)


def main():
    parser = argparse.ArgumentParser(description="升级节点程序，保留身份和代理配置")
    parser.add_argument("--resume", action="store_true", help="核对升级结果后解除维护模式")
    parser.add_argument("--task", help="由面板升级任务触发时的任务 ID")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("请使用 root 运行")
    os.umask(0o077)
    config = json.loads(Path("/etc/vaio-agent/config.json").read_text())
    base = config["url"].rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in ("https", "http") or (parsed.scheme == "http" and config.get("allow_http") is not True) \
            or not parsed.hostname or parsed.username or parsed.query or parsed.fragment or parsed.path:
        raise SystemExit("公网节点升级需要 HTTPS 面板根地址（未绑定域名的面板除外）")
    opener = urllib.request.build_opener(NoRedirect())

    def api(path, data=None, private=False):
        headers = {"Content-Type": "application/json"}
        if private:
            headers["Authorization"] = "Bearer " + config["token"]
        req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
        with opener.open(req, timeout=60) as response:
            payload = response.read(32 * 1024 * 1024 + 1)
            if len(payload) > 32 * 1024 * 1024:
                raise RuntimeError("下载文件过大")
            return payload

    endpoint = "/api/agent/" + config["node_id"]
    manager = ["rc-service", "vaio-agent"] if Path("/sbin/openrc").exists() else ["systemctl"]

    def service(action):
        subprocess.run(manager + ([action] if manager[0] == "rc-service" else [action, "vaio-agent"]), check=True, timeout=45)

    with open("/var/lib/vaio-agent/.upgrade.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.resume:
            service("status" if manager[0] == "rc-service" else "is-active")
            api(endpoint + "/maintenance", {"enabled": False}, True)
            print("维护模式已解除")
            return
        if args.task:
            wait_reported("/var/lib/vaio-agent/journal.json", args.task)
        from_version = ""
        try:
            from_version = ast.literal_eval(next(n.value for n in ast.parse(Path("/opt/vaio-agent/vaio/__init__.py").read_text()).body
                                                 if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "__version__" for t in n.targets)))
        except Exception:
            pass
        report = {"task": args.task or "", "at": time.time(), "from": from_version, "script_from": script_version(MAIN_SCRIPT)}
        print("正在下载并校验节点程序…", flush=True)
        payload = api("/downloads/agent.tar.gz")
        checksum = api("/downloads/agent.sha256").decode().split()[0]
        if hashlib.sha256(payload).hexdigest() != checksum:
            raise RuntimeError("安装包校验失败，请稍后重试")
        root = Path("/opt/vaio-agent")
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError("节点程序目录无效")
        stage = Path(tempfile.mkdtemp(prefix=".vaio-agent-stage-", dir="/opt"))
        backup = Path("/opt/vaio-agent-backup-" + str(time.time_ns()))
        maintenance = False
        moved = False
        stopped = False
        script_backup = None
        version = ""
        try:
            version = extract_bundle(payload, stage)
            bundle_script(stage)
            subprocess.run([sys.executable, "-m", "agent", "--help"], cwd=stage, check=True, stdout=subprocess.DEVNULL)
            api(endpoint + "/maintenance", {"enabled": True}, True)
            maintenance = True
            journal_path = Path("/var/lib/vaio-agent/journal.json")
            journal = json.loads(journal_path.read_text()) if journal_path.exists() else {}
            if any(v["status"] == "running" or not v.get("sent") for v in journal.values()):
                raise RuntimeError("本机有运行中、待核对或未上报任务，已停止升级")
            cfg = Path("/etc/vless-reality")
            cfg.mkdir(parents=True, exist_ok=True)
            with open(cfg / ".db.lock", "a") as db_lock:
                fcntl.flock(db_lock, fcntl.LOCK_EX)
                service("stop")
            stopped = True
            root.rename(backup)
            moved = True
            stage.rename(root)
            script_backup = replace_main_script(root)
            started = time.time()
            service("start")
            for _ in range(18):
                status = json.loads(api(endpoint + "/status", private=True))
                if (status.get("last_seen") or 0) >= started and status.get("version") == version:
                    break
                time.sleep(5)
            else:
                raise RuntimeError("新版未按时上线")
            if (root / "scripts/vaio-agent").exists():
                shutil.copy2(root / "scripts/vaio-agent", "/usr/local/bin/vaio-agent")
                os.chmod("/usr/local/bin/vaio-agent", 0o755)
            print("升级完成，版本 " + version + "；旧程序保留于 " + str(backup), flush=True)
            write_result({**report, "to": version, "script_to": script_version(MAIN_SCRIPT), "status": "succeeded",
                          "message": "节点程序 " + version + "，节点脚本 " + script_version(MAIN_SCRIPT)})
        except BaseException as error:
            rolled_back = moved
            try:
                restore_main_script(script_backup)
            except Exception:
                print("主脚本恢复失败，请检查 " + str(MAIN_SCRIPT), file=sys.stderr)
            write_result({**report, "to": version, "script_to": script_version(MAIN_SCRIPT),
                          "status": "rolled_back" if rolled_back else "failed", "message": str(error) or type(error).__name__})
            if moved:
                service("stop")
                if root.exists():
                    shutil.rmtree(root)
                backup.rename(root)
                service("start")
                print("升级失败，已恢复旧程序", file=sys.stderr)
            elif stopped:
                service("start")
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            if maintenance:
                try:
                    api(endpoint + "/maintenance", {"enabled": False}, True)
                except Exception:
                    print("无法解除维护，请核对后执行 vaio-agent resume", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("升级失败：" + str(error), file=sys.stderr)
        sys.exit(1)
