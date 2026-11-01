#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
CFG="$fixture/cfg"
mkdir -p "$CFG" "$fixture/bin"
eval "$(awk 'index($0,"_singbox_stats_build_version() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
# 核心路径改到 fixture，避免读写真实 /usr/local/bin。
eval "$(awk 'index($0,"_build_singbox_stats_core() (")==1 {on=1} on {print} on && $0==")" {exit}' "$repo/vless-server.sh" | sed "s#/usr/local/bin/#$fixture/bin/#g")"
_info() { :; }
_ok() { echo "ok:$*" >> "$fixture/events"; }
_err() { echo "err:$*" >> "$fixture/events"; }
_map_arch() { echo amd64; }
fake_core() {
    printf '#!/bin/sh\n[ "$1" = version ] && { echo "sing-box version %s"; echo "Tags: with_v2ray_api"; exit 0; }\necho "$*" >> "%s/core-calls"\n' "$2" "$fixture" > "$1"
    chmod 755 "$1"
}
_download_singbox_stats_core() { mkdir -p "$3/bin"; fake_core "$3/bin/sing-box" "$1"; }
install_singbox_stats_client() { echo client >> "$fixture/events"; }
generate_singbox_config() { echo generate >> "$fixture/events"; }
svc() { echo "svc:$*" >> "$fixture/events"; }
get_singbox_protocols() { printf '%s' "$singbox_protocols"; }

# 没有 Sing-box 协议且配置已删除：只替换核心并备份旧核心，不检查配置、不碰服务。
fake_core "$fixture/bin/sing-box" 1.14.3
singbox_protocols=''
_build_singbox_stats_core 1.14.4
"$fixture/bin/sing-box" version | grep -q 'version 1.14.4'
backup=$(echo "$CFG"/singbox-stats-backup.*)
"$backup/sing-box" version | grep -q 'version 1.14.3'
[[ ! -e "$backup/singbox.json" && ! -e "$CFG/singbox.json" ]]
[[ ! -e "$fixture/core-calls" ]]
if grep -q -e '^svc:' -e '^generate' -e '^client' -e '^err:' "$fixture/events"; then exit 1; fi
grep -q '^ok:' "$fixture/events"

# 仍有 Sing-box 协议却缺少配置：拒绝替换，原核心保留。
rm -rf "$CFG"/singbox-stats-backup.* "$fixture/events"
fake_core "$fixture/bin/sing-box" 1.14.3
singbox_protocols='hy2'
if _build_singbox_stats_core 1.14.4; then exit 1; fi
"$fixture/bin/sing-box" version | grep -q 'version 1.14.3'
if ls "$CFG"/singbox-stats-backup.* >/dev/null 2>&1; then exit 1; fi
grep -q '缺少' "$fixture/events"
if grep -q '^svc:' "$fixture/events"; then exit 1; fi
echo 'PASS stats core updates without config when no Sing-box protocols, refuses when protocols lack config'
