"""Proxy cores (Xray, Sing-box, Snell v5/v6): versions for the panel and one-click updates.
Installs go through the node script's own functions; Sing-box always uses the statistics build
(mozisen/surge branch singbox-stats-binaries), since the official build has no per-user counters."""
import json
import platform
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from .inventory import read_db, rows, service_for

CORES = {
    "xray": {"label": "Xray", "binary": "/usr/local/bin/xray", "version": ["version"]},
    "singbox": {"label": "Sing-box", "binary": "/usr/local/bin/sing-box", "version": ["version"]},
    "snell-v5": {"label": "Snell v5", "binary": "/usr/local/bin/snell-server-v5", "version": ["--version"]},
    "snell-v6": {"label": "Snell v6", "binary": "/usr/local/bin/snell-server-v6", "version": ["--v"]},
}
VERSION = re.compile(r"v?(\d+\.\d+\.\d+)")
STATS_TREE = "https://api.github.com/repos/mozisen/surge/git/trees/singbox-stats-binaries?recursive=1"


def version_key(text):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in match.groups()) if match else None


def read_version(core, run=subprocess.run):
    """(version, has_stats) of the installed binary; ("", False) when absent or unreadable."""
    spec = CORES[core]
    if not Path(spec["binary"]).is_file():
        return "", False
    try:
        output = run([spec["binary"], *spec["version"]], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return "", False
    text = (output.stdout or b"").decode(errors="replace") + (output.stderr or b"").decode(errors="replace")
    match = VERSION.search(text)
    return (match[1] if match else ""), core == "singbox" and "with_v2ray_api" in text


def platform_dir():
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    if not arch:
        return ""
    try:
        text = subprocess.run(["ldd", "--version"], capture_output=True, timeout=10)
        libc = "musl" if b"musl" in (text.stdout + text.stderr) else "glibc"
    except (OSError, subprocess.TimeoutExpired):
        libc = "glibc"
    return "linux-%s-%s" % (arch, libc)


def stats_latest(directory=None, fetch=None):
    """Newest statistics build published for this machine (vX.Y.Z/linux-arch-libc/manifest.json)."""
    directory = directory if directory is not None else platform_dir()
    if not directory:
        return ""
    if fetch is None:
        def fetch():
            request = urllib.request.Request(STATS_TREE, headers={"User-Agent": "Vaio-Agent", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read(4 * 1024 * 1024))
    tree = fetch().get("tree", [])
    versions = {m[1] for m in (re.fullmatch(r"v(\d+\.\d+\.\d+)/" + re.escape(directory) + r"/manifest\.json", str(t.get("path", "")))
                               for t in tree if isinstance(t, dict)) if m}
    return max(versions, key=version_key) if versions else ""


def latest(runtime, core):
    """Latest stable version this node can install; "" when unknown."""
    if core == "singbox":
        return stats_latest()
    if core == "snell-v6":
        output = runtime.upstream_output("_get_snell_v6_stable_version", "true")
    else:
        output = runtime.upstream_output("_get_latest_version", {"xray": "XTLS/Xray-core", "snell-v5": "surge-networks/snell"}[core], "true")
    found = [m[1] for m in (re.fullmatch(r"v?(\d+\.\d+\.\d+)", line.strip()) for line in output.splitlines()) if m]
    return found[-1] if found else ""


def official_singbox(runtime):
    output = runtime.upstream_output("_get_latest_version", "SagerNet/sing-box", "true")
    found = [m[1] for m in (re.fullmatch(r"v?(\d+\.\d+\.\d+)", line.strip()) for line in output.splitlines()) if m]
    return found[-1] if found else ""


def services(db, core):
    """Services running this core's binary, from the node's protocol inventory."""
    names = {"xray": {"vless-reality"}}.get(core, set())
    for c, proto, row in rows(db):
        if core == "xray" and c == "xray" and not proto.startswith("snell"):
            names.add(service_for(c, proto, row))
        elif core in ("snell-v5", "snell-v6") and proto == core:
            names.add(service_for(c, proto, row))
    return sorted(names)


def update(runtime, cfg, state, core, sync=True, wait=2.0):
    """Update one core to the latest stable version; returns {core, from, to, changed}.
    Failures after the binary changed restore it and the services (RuntimeError);
    a failed restore raises the caller's unknown-outcome error (OSError)."""
    if core not in CORES:
        raise ValueError("不支持的内核")
    label = CORES[core]["label"]
    current, stats = read_version(core)
    if not current:
        raise ValueError(label + " 未安装")
    target = latest(runtime, core)
    if not version_key(target):
        raise ValueError("无法获取 " + label + " 的最新稳定版本" + ("（统计版预编译包）" if core == "singbox" else ""))
    if target == current and (core != "singbox" or stats):
        return {"core": core, "from": current, "to": current, "changed": False}
    if sync:
        try:
            runtime.sync_traffic()          # record usage before the core restarts and its counters reset
        except (OSError, RuntimeError):
            pass
    if core == "singbox":
        # The script's statistics path downloads and verifies, backs up, swaps and checks, and restores on failure.
        runtime.upstream("_update_singbox_preserving_stats", "stable", target)
        now, stats = read_version(core)
        if now != target or not stats:
            raise RuntimeError("Sing-box 更新后版本校验失败（当前 %s），请在节点检查" % (now or "未知"))
        return {"core": core, "from": current, "to": target, "changed": True}
    binary = Path(CORES[core]["binary"])
    backup_dir = Path(state) / "core-backups"
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = backup_dir / ("%s-%s-%d" % (binary.name, current, time.time_ns()))
    shutil.copy2(binary, backup)
    paused = set((read_db(cfg).get("meta") or {}).get("panel_paused_services") or [])
    running = [s for s in services(read_db(cfg), core) if s not in paused and runtime.is_running(s)]
    try:
        for service in running:
            runtime.service(service, "stop")
        if core == "snell-v6":
            runtime.upstream("install_snell_v6", target)
        else:
            runtime.upstream({"xray": "install_xray", "snell-v5": "install_snell_v5"}[core], "stable", "true", target)
        now, _ = read_version(core)
        if now != target:
            raise RuntimeError("安装后版本为 %s，不是 %s" % (now or "未知", target))
        for service in running:
            runtime.service(service, "start")
        time.sleep(wait)
        down = [s for s in running if not runtime.is_running(s)]
        if down:
            raise RuntimeError("新版本启动失败：" + "、".join(down))
    except Exception as error:
        restore(runtime, binary, backup, running)
        raise RuntimeError("%s 更新失败，已恢复 %s：%s" % (label, current, str(error)[:200] or type(error).__name__)) from None
    for old in sorted(backup_dir.glob(binary.name + "-*"))[:-3]:
        old.unlink(missing_ok=True)
    return {"core": core, "from": current, "to": target, "changed": True}


class RestoreFailed(Exception):
    """The old core could not be put back: the node state is uncertain."""


def restore(runtime, binary, backup, running):
    try:
        _restore(runtime, binary, backup, running)
    except Exception as error:
        raise RestoreFailed("内核更新失败且恢复旧版本失败，请在节点核对 %s（备份 %s）：%s" % (binary, backup, error)) from None


def _restore(runtime, binary, backup, running):
    temp = binary.with_name("." + binary.name + ".vaio-restore")
    shutil.copy2(backup, temp)
    temp.replace(binary)
    for service in running:
        runtime.service(service, "start")


def snapshot(current, latest_found, official=""):
    """Snapshot field: installed cores only."""
    cores = {}
    for core, (version, stats) in current.items():
        if not version:
            continue
        item = {"current": version, "latest": latest_found.get(core, "")}
        if core == "singbox":
            item.update(stats=stats, official=official)
        cores[core] = item
    return cores
