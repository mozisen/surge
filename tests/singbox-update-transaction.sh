#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
export TEST_FIXTURE="$fixture"
CFG="$fixture/cfg"; DB_FILE="$CFG/db.json"
mkdir -p "$fixture/bin"
load() { eval "$(awk -v fn="$1" 'index($0,fn "() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$script")"; }
for fn in _sha256_file _singbox_stats_build_version; do load "$fn"; done
definition=$(awk '/^_build_singbox_stats_core\(\) \(/ {on=1} on {print} on && $0==")" {exit}' "$script")
# Only the binary destination is redirected; production transaction is exercised unchanged.
definition=${definition//\/usr\/local\/bin\//$fixture\/bin\/}
eval "$definition"
_err() { echo "$*" >> "$fixture/errors"; }
_ok() { echo "$*" >> "$fixture/ok"; }
_map_arch() { echo amd64; }
_pgrep() { [[ -e "$fixture/unmanaged" ]]; }
sleep() { :; }
sing-box() { echo 'sing-box version 1.14.2'; echo 'Tags: with_v2ray_api'; }
install() {
    [[ ! -e "$fixture/install-fail" || "$*" != *'.sing-box-update.'* ]] || return 1
    command install "$@"
}
svc() {
    echo "$1" >> "$fixture/events"
    case "$1" in
        status) [[ -e "$fixture/running" ]] ;;
        restart)
            if [[ -e "$fixture/restart-fail" ]]; then rm "$fixture/restart-fail"; return 1; fi
            touch "$fixture/running"
            ;;
        *) echo 'unexpected service mutation' >&2; return 1 ;;
    esac
}
install_singbox_stats_client() { echo grpcurl >> "$fixture/events"; }
singbox_api_query() { [[ ! -e "$fixture/api-fail" ]]; }
generate_singbox_config() { return 1; }
_download_singbox_stats_core() {
    echo download >> "$fixture/events"
    [[ ! -e "$fixture/download-fail" ]] || return 1
    mkdir -p "$3/bin"
    cp "$fixture/new-core" "$3/bin/sing-box"
    chmod +x "$3/bin/sing-box"
    [[ ! -e "$fixture/change-config" ]] || echo '{"changed":true}' > "$CFG/singbox.json"
    return 0
}
cat > "$fixture/new-core" <<'CORE'
#!/usr/bin/env bash
case "$1" in
 version) echo 'sing-box version 1.14.2'; echo 'Tags: with_v2ray_api' ;;
 check)
  [[ -f "$3" && ! -e "$TEST_FIXTURE/check-fail" ]] && jq -e . "$3" >/dev/null
  ;;
 *) exit 1 ;;
esac
CORE
cat > "$fixture/old-core" <<'CORE'
#!/usr/bin/env bash
echo 'sing-box version 1.14.0'
echo 'Tags: with_v2ray_api'
CORE
reset_case() {
    rm -rf "$CFG"
    mkdir "$CFG"
    rm -f "$fixture/running" "$fixture/unmanaged" "$fixture/download-fail" "$fixture/check-fail" "$fixture/api-fail" "$fixture/restart-fail" "$fixture/change-config"
    : > "$fixture/events"; : > "$fixture/errors"
    rm -f "$fixture/install-fail"
    cp "$fixture/old-core" "$fixture/bin/sing-box"
    chmod +x "$fixture/bin/sing-box"
    echo '{"singbox":{}}' > "$DB_FILE"
}
configured() {
    echo '{"singbox":{"vless":{"port":10001}}}' > "$DB_FILE"
    echo '{"inbounds":[],"outbounds":[{"type":"direct"}]}' > "$CFG/singbox.json"
    cp "$CFG/singbox.json" "$fixture/original-config"
}
unchanged() {
    cmp "$fixture/old-core" "$fixture/bin/sing-box"
    ! grep -Eq '^(restart|stop|start)$' "$fixture/events"
}
reset_case
_build_singbox_stats_core 1.14.2
cmp "$fixture/new-core" "$fixture/bin/sing-box"
[[ ! -f "$CFG/singbox.json" ]]
! grep -Eq '^(restart|stop|start|grpcurl)$' "$fixture/events"

reset_case; configured; rm "$CFG/singbox.json"
if _build_singbox_stats_core 1.14.2; then exit 1; fi
unchanged
grep -q '配置.*缺失' "$fixture/errors"
! grep -q download "$fixture/events"
reset_case; echo invalid > "$DB_FILE"
if _build_singbox_stats_core 1.14.2; then exit 1; fi
unchanged
reset_case; touch "$fixture/unmanaged"
if _build_singbox_stats_core 1.14.2; then exit 1; fi
unchanged

for state in stopped running; do
 for fail in download-fail check-fail; do
    reset_case; configured
    [[ "$state" != running ]] || touch "$fixture/running"
    touch "$fixture/$fail"
    if _build_singbox_stats_core 1.14.2; then exit 1; fi
    unchanged
    [[ ! -d "$CFG/.singbox-stats-update.lock" ]]
 done
done
reset_case; configured
_build_singbox_stats_core 1.14.2
cmp "$fixture/new-core" "$fixture/bin/sing-box"
! grep -Eq '^(restart|stop|start)$' "$fixture/events"

reset_case; configured; touch "$fixture/running"
_build_singbox_stats_core 1.14.2
cmp "$fixture/new-core" "$fixture/bin/sing-box"
[[ "$(grep -c restart "$fixture/events")" == 1 ]]
for fail in api-fail restart-fail; do
 reset_case; configured; touch "$fixture/running" "$fixture/$fail"
 if _build_singbox_stats_core 1.14.2; then exit 1; fi
 cmp "$fixture/old-core" "$fixture/bin/sing-box"
 cmp "$fixture/original-config" "$CFG/singbox.json"
 [[ "$(grep -c restart "$fixture/events")" == 2 && -f "$fixture/running" ]]
 grep -q '已恢复原核心' "$fixture/errors"
done
reset_case; configured; touch "$fixture/change-config"
touch "$fixture/install-fail"
if _build_singbox_stats_core 1.14.2; then exit 1; fi
unchanged
reset_case; configured; touch "$fixture/install-fail"
if _build_singbox_stats_core 1.14.2; then exit 1; fi
unchanged
# Manual repair configuration regeneration failure must also restore the binary.
reset_case; configured
if _build_singbox_stats_core; then exit 1; fi
unchanged
cmp "$fixture/original-config" "$CFG/singbox.json"
reset_case; configured; touch "$fixture/change-config"
if _build_singbox_stats_core 1.14.2; then exit 1; fi
unchanged
grep -q '配置已变化' "$fixture/errors"
jq -e '.changed==true' "$CFG/singbox.json" >/dev/null
reset_case; configured; mkdir "$CFG/.singbox-stats-update.lock"
if _build_singbox_stats_core 1.14.2; then exit 1; fi
unchanged
echo 'PASS core-only, missing/invalid inventory/config, unmanaged process, early failure no service mutation, stopped preservation, running update, rollback, concurrent changes and update lock'
