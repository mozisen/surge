#!/usr/bin/env python3
"""Local systemd deployment with a staged environment and automatic code rollback."""
import argparse
import fcntl
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import time
import urllib.request
from urllib.parse import quote
from pathlib import Path


def download(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Vaio-Panel-Updater"}), timeout=60) as response:
        data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise ValueError("更新包过大")
        return data


def extract(payload, target):
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        total = 0
        members = archive.getmembers()
        for item in members:
            path = Path(item.name)
            total += item.size
            if path.is_absolute() or ".." in path.parts or not (item.isfile() or item.isdir()) or total > 64*1024*1024:
                raise ValueError("更新包路径或大小无效")
        # mozisen/vaio-panel: the repository root is the panel; mozisen/surge (previews): the platform/ directory.
        if any(Path(item.name).parts[1:] == ('requirements.txt',) for item in members):
            prefix = ()
        elif any(Path(item.name).parts[1:] == ('platform', 'requirements.txt') for item in members):
            prefix = ('platform',)
        else:
            raise ValueError("更新包缺少 requirements.txt（vaio-panel 根目录或 surge 的 platform/）")
        for item in members:
            parts = Path(item.name).parts[1:]
            if not parts or parts[:len(prefix)] != prefix:
                continue
            parts = parts[len(prefix):]
            if not parts:
                continue
            path = target.joinpath(*parts)
            if item.isdir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile(item).read())
                path.chmod(0o755 if item.mode & 0o111 else 0o644)


HELPER_UNITS = {
    "vaio-panel-address.service": "[Unit]\nDescription=Vaio Panel address change\n[Service]\nType=oneshot\n"
                                  "ExecStart=/usr/bin/python3 /opt/vaio-panel/scripts/panel-address.py apply\n",
    "vaio-panel-address.path": "[Unit]\nDescription=Vaio Panel address change requests\n[Path]\n"
                               "PathExists=/var/lib/vaio-panel/address-request.json\n[Install]\nWantedBy=multi-user.target\n",
    "vaio-panel-update.service": "[Unit]\nDescription=Vaio Panel update from the panel\n[Service]\nType=oneshot\nTimeoutStartSec=1800\n"
                                 "ExecStart=/usr/bin/python3 /opt/vaio-panel/scripts/update-panel.py --from-request /var/lib/vaio-panel/panel-update-request.json\n",
    "vaio-panel-update.path": "[Unit]\nDescription=Vaio Panel update requests\n[Path]\n"
                              "PathExists=/var/lib/vaio-panel/panel-update-request.json\n[Install]\nWantedBy=multi-user.target\n",
}


def ensure_address_helper(units=Path("/etc/systemd/system")):
    """Root helpers the panel triggers through request files (address change, self-update); added to older installs once."""
    if all((units / name).exists() for name in HELPER_UNITS):
        return False
    for name, content in HELPER_UNITS.items():
        (units / name).write_text(content)
    subprocess.run(['systemctl', 'daemon-reload'], check=False, timeout=60)
    for path_unit in ('vaio-panel-address.path', 'vaio-panel-update.path'):
        subprocess.run(['systemctl', 'enable', '--now', path_unit], check=False, timeout=60)
    return True


def update_status(path, state, message, **extra):
    path.write_text(json.dumps({"state": state, "message": message, "at": time.time(), **extra}, ensure_ascii=False))
    try:
        shutil.chown(path, "vaio-panel", "vaio-panel")
    except (LookupError, PermissionError, OSError):
        pass


def from_request(request_path):
    """Update requested from the panel: read and remove the request, run the normal update, report the outcome."""
    request_path = Path(request_path)
    status_path = request_path.with_name("panel-update-status.json")
    try:
        ref = json.loads(request_path.read_text()).get("ref", "")
    except (OSError, ValueError):
        ref = ""
    request_path.unlink(missing_ok=True)
    if not re.fullmatch(r"v\d+\.\d+\.\d+", ref or ""):
        update_status(status_path, "failed", "更新请求无效")
        return 1
    update_status(status_path, "running", "正在更新到 " + ref + "（下载、测试、切换，期间面板会重启）", ref=ref)
    try:
        run_update("mozisen/vaio-panel", ref, None)
    except BaseException as error:
        update_status(status_path, "failed", "更新失败，已保留或恢复原版本：" + (str(error) or type(error).__name__)[:300], ref=ref)
        return 1
    update_status(status_path, "succeeded", "已更新到 " + ref, ref=ref)
    return 0


def main():
    parser = argparse.ArgumentParser(description="升级面板，保留数据并自动检查恢复")
    parser.add_argument("--repo", default="mozisen/vaio-panel", help="GitHub 仓库：mozisen/vaio-panel（正式版）或 mozisen/surge（预览版）")
    parser.add_argument("--ref", default="main", help="分支、提交 SHA 或版本标签，例如 main、v1.0.0")
    parser.add_argument("--archive", help="管理员提供的本地 GitHub 格式源码包，用于离线部署")
    parser.add_argument("--from-request", help=argparse.SUPPRESS)
    parser.add_argument("--install-helpers", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("请使用 root 运行")
    if args.install_helpers:
        ensure_address_helper()
        return
    if args.from_request:
        raise SystemExit(from_request(args.from_request))
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,120}", args.ref):
        raise SystemExit("版本标识无效")
    if args.repo not in ("mozisen/vaio-panel", "mozisen/surge"):
        raise SystemExit("仓库只能是 mozisen/vaio-panel 或 mozisen/surge")
    run_update(args.repo, args.ref, args.archive)


def run_update(repo, ref, archive):
    os.umask(0o022)
    root = Path("/opt/vaio-panel")
    if not root.exists() or not Path("/etc/vaio-panel/panel.env").exists():
        raise SystemExit("未找到直接安装版；容器部署请使用 Docker Compose 更新")
    env = {}
    for line in Path('/etc/vaio-panel/panel.env').read_text().splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            env[key] = value
    database = Path(env["VAIO_DATABASE"])
    backup_root = Path("/var/backups/vaio-panel")
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(backup_root / '.upgrade.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with sqlite3.connect(database) as db:
            if db.execute("SELECT 1 FROM tasks WHERE status IN ('queued','running') LIMIT 1").fetchone():
                raise RuntimeError("有待执行或运行中任务，请完成后再升级")
        api = "https://api.github.com/repos/" + repo
        sha = ref if archive else json.loads(download(api + "/commits/" + quote(ref, safe='')))["sha"]
        payload = Path(archive).read_bytes() if archive else download(api + "/tarball/" + sha)
        identity = str(time.time_ns())
        stage = Path('/opt/vaio-panel-releases') / identity
        stage.mkdir(parents=True)
        backup = backup_root / identity
        backup.mkdir(mode=0o700)
        switched = stopped = False
        old_link = root.resolve() if root.is_symlink() else None
        old_directory = Path('/opt/vaio-panel-before-' + identity)
        try:
            extract(payload, stage)
            subprocess.run(['python3','-m','venv',str(stage/'.venv')],check=True)
            subprocess.run([str(stage/'.venv/bin/pip'),'install','-q','-r',str(stage/'requirements.txt')],check=True,timeout=300)
            subprocess.run([str(stage/'.venv/bin/python'),'-m','unittest','discover','-s','tests','-q'],cwd=stage,check=True,timeout=180,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            (stage/'REVISION').write_text(sha+'\n')
            # Stop incoming requests, then recheck tasks before touching the live tree.
            subprocess.run(['systemctl','stop','vaio-panel'],check=True,timeout=60)
            stopped = True
            with sqlite3.connect(database) as db:
                if db.execute("SELECT 1 FROM tasks WHERE status IN ('queued','running') LIMIT 1").fetchone():
                    raise RuntimeError("检查期间出现新任务，已取消升级")
                with sqlite3.connect(backup/'panel.sqlite') as out:
                    db.backup(out)
            shutil.copy2('/etc/vaio-panel/panel.env',backup/'panel.env')
            if old_link:
                root.unlink()
            else:
                root.rename(old_directory)
            switched = True
            root.symlink_to(stage, target_is_directory=True)
            subprocess.run(['systemctl','start','vaio-panel'],check=True,timeout=60)
            expected = subprocess.check_output([str(stage/'.venv/bin/python'),'-c','from vaio import __version__;print(__version__)'],cwd=stage,text=True).strip()
            for _ in range(15):
                try:
                    if json.loads(download('http://127.0.0.1:18080/healthz')).get('version') == expected:
                        break
                except Exception:
                    pass
                time.sleep(2)
            else:
                raise RuntimeError('升级后健康检查失败')
            shutil.copy2(stage/'scripts/vaio-panel','/usr/local/bin/vaio-panel')
            Path('/usr/local/bin/vaio-panel').chmod(0o755)
            (backup/'previous-code').write_text(str(old_link or old_directory)+'\n')
            ensure_address_helper()
            print('升级完成，版本 '+expected+'；备份 '+str(backup))
        except BaseException:
            if switched:
                subprocess.run(['systemctl','stop','vaio-panel'],check=False,timeout=60)
                if root.is_symlink():
                    root.unlink()
                if old_link:
                    root.symlink_to(old_link, target_is_directory=True)
                else:
                    old_directory.rename(root)
                # Retain the live DB to preserve any newly accepted requests.
                # These additive migrations remain backwards compatible.
                print('已恢复旧程序；数据库保持最新，升级前快照位于 '+str(backup))
            if stopped:
                subprocess.run(['systemctl','start','vaio-panel'],check=True,timeout=60)
            raise


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('面板升级失败：'+str(error))
        raise SystemExit(1)
