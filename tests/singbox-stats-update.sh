#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
for fn in _singbox_stats_build_version _update_singbox_preserving_stats _update_core_to_version update_singbox_core install_singbox; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
_info() { :; }
_err() { :; }
_check_core_update_deps() { :; }
_confirm_core_update_version() { :; }
_confirm_core_update() { :; }
_singbox_stats_enabled() { return 0; }
_get_latest_version() { echo 1.15.0; }
svc() {
    echo "$1" >> "$fixture/events"
    if [[ "$1" == status ]]; then [[ "$running" == true ]]; else return 0; fi
}
_build_singbox_stats_core() {
    echo "build:$1" >> "$fixture/events"
    [[ "$build_failed" != true ]]
}
running=true
_update_core_to_version Sing-box stable 1.15.0 vless-singbox install_singbox
[[ "$(cat "$fixture/events")" == $'status\nbuild:1.15.0' ]]
: > "$fixture/events"
update_singbox_core stable
[[ "$(cat "$fixture/events")" == $'status\nbuild:1.15.0' ]]
: > "$fixture/events"
install_singbox stable true 1.16.0
[[ "$(cat "$fixture/events")" == $'status\nbuild:1.16.0' ]]
: > "$fixture/events"
build_failed=true
if _update_singbox_preserving_stats stable 1.15.0; then exit 1; fi
[[ "$(cat "$fixture/events")" == $'status\nbuild:1.15.0' ]]
running=false; build_failed=false
: > "$fixture/events"
_update_singbox_preserving_stats stable 1.15.0
[[ "$(cat "$fixture/events")" == $'status\nbuild:1.15.0\nstop' ]]
: > "$fixture/events"
if _update_singbox_preserving_stats prerelease; then exit 1; fi
[[ ! -s "$fixture/events" ]]
echo 'PASS all update entries preserve stats, no stop before build, failures propagate, stopped state restored, preview rejected'
