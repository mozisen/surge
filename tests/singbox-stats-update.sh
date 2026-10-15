#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
for fn in _singbox_stats_build_version _update_singbox_preserving_stats _update_core_to_version update_singbox_core install_singbox; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
_info() { :; }
_err() { echo "$*" >> "$fixture/errors"; }
_warn() { echo "$*" >> "$fixture/errors"; }
_ok() { :; }
_check_core_update_deps() { :; }
_confirm_core_update_version() { :; }
_confirm_core_update() { :; }
installed=true; platform=true
check_cmd() { [[ "$1" != sing-box || "$installed" == true ]]; }
_singbox_stats_platform() { [[ "$platform" == true ]] && echo linux-amd64-glibc; }
_singbox_stats_has_version() { [[ " ${published:-1.15.0 1.16.0} " == *" ${1#v} "* ]]; }
_get_singbox_stats_latest() { echo 1.15.0; }
_get_latest_version() { echo 9.9.9; }                 # official: must never be the target
svc() {
    echo "$1" >> "$fixture/events"
    if [[ "$1" == status ]]; then [[ "$running" == true ]]; else return 0; fi
}
_build_singbox_stats_core() {
    echo "build:$1" >> "$fixture/events"
    [[ "$build_failed" != true ]]
}
_install_singbox_stats_fresh() { echo "fresh:${1:-latest}" >> "$fixture/events"; }
_map_arch() { echo amd64; }
_install_binary() { echo "official:$2" >> "$fixture/events"; }
install_singbox_stats_client() { :; }
DISTRO=debian
running=true
_update_core_to_version Sing-box stable 1.15.0 vless-singbox install_singbox
[[ "$(cat "$fixture/events")" == 'build:1.15.0' ]]
: > "$fixture/events"
update_singbox_core stable
[[ "$(cat "$fixture/events")" == 'build:1.15.0' ]]       # latest statistics build, not the official 9.9.9
: > "$fixture/events"
install_singbox stable true 1.16.0
[[ "$(cat "$fixture/events")" == 'build:1.16.0' ]]
: > "$fixture/events"
build_failed=true
if _update_singbox_preserving_stats stable 1.15.0; then exit 1; fi
[[ "$(cat "$fixture/events")" == 'build:1.15.0' ]]
running=false; build_failed=false
: > "$fixture/events"
_update_singbox_preserving_stats stable 1.15.0
[[ "$(cat "$fixture/events")" == 'build:1.15.0' ]]
: > "$fixture/events"
if _update_singbox_preserving_stats prerelease; then exit 1; fi
[[ ! -s "$fixture/events" ]]
# A version without a statistics build is refused before anything is downloaded or stopped.
if _update_singbox_preserving_stats stable 1.14.3; then exit 1; fi
[[ ! -s "$fixture/events" ]]
grep -q '没有本机可用的统计版预编译包' "$fixture/errors"
# Already installed and not forced: nothing changes.
install_singbox
[[ ! -s "$fixture/events" ]]
# Fresh install uses the statistics build; only an unsupported machine falls back to the official core.
installed=false
install_singbox
[[ "$(cat "$fixture/events")" == 'fresh:latest' ]]
: > "$fixture/events"
install_singbox stable true 1.16.0
[[ "$(cat "$fixture/events")" == 'fresh:1.16.0' ]]
: > "$fixture/events"; platform=false
install_singbox
[[ "$(cat "$fixture/events")" == 'official:SagerNet/sing-box' ]]
grep -q '不含用户流量统计' "$fixture/errors"
echo 'PASS every Sing-box install and update uses published statistics builds only; unpublished versions refused; official core only where no build exists'
