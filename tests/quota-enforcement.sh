#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
CFG="$fixture"; DB_FILE="$fixture/db.json"
load() { eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"; }
for fn in _singbox_effective_users _ensure_singbox_default_users db_get_users_stats _enforce_user_quotas db_list_users db_list_protocols db_get_user_field db_get_user_alert_state db_set_user_alert_state db_set_user_enabled db_reset_user_traffic _db_apply db_get gen_xray_trojan_clients gen_xray_vmess_clients; do load "$fn"; done
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_snell_managed() { return 1; }
_warn() { :; }
_ok() { :; }; _info() { :; }; _err() { :; }
for proto in vless trojan hy2 tuic anytls; do
    cfg='{"port":10001,"uuid":"original","password":"original","users":[{"name":"default","uuid":"blocked","enabled":false},{"name":"over","uuid":"over-secret","used":100,"quota":100},{"name":"expired","uuid":"expired-secret","expire_date":"2000-01-01"},{"name":"alice","uuid":"valid","enabled":true}]}'
    result=$(_singbox_effective_users "$proto" "$cfg")
    [[ "$(jq length <<< "$result")" == 1 ]]
    [[ "$(jq -r '.[0].name' <<< "$result")" == "$proto-alice" ]]
    cfg=$(jq '.users |= map(.enabled=false)' <<< "$cfg")
    result=$(_singbox_effective_users "$proto" "$cfg")
    [[ "$result" != *original* && "$result" != *blocked* && "$result" != *valid* ]]
    [[ "$(jq -r '.[0].name' <<< "$result")" == quota-disabled ]]
    result=$(_singbox_effective_users "$proto" '{"uuid":"legacy","password":"legacy"}')
    [[ "$result" == *legacy* ]]
done
printf '%s\n' '{"singbox":{"anytls":[{"port":1,"password":"old","users":[]},{"port":2,"password":"legacy"}]},"xray":{"vless":{"port":3,"uuid":"old","users":[{"name":"default","uuid":"old","enabled":false}]}}}' > "$DB_FILE"
_ensure_singbox_default_users
jq -e '.singbox.anytls[0].users == [] and .singbox.anytls[1].users[0].enabled' "$DB_FILE" >/dev/null
[[ "$(db_get_users_stats xray vless)" == *'|false|'* ]]
_db_apply '.xray.trojan={password:"old-secret",users:[{name:"default",uuid:"old-secret",enabled:false}]}'
[[ "$(gen_xray_trojan_clients trojan)" == '[]' ]]
_db_apply '.xray.trojan.users=[]'
[[ "$(gen_xray_trojan_clients trojan)" == '[]' ]]
if grep -q 'clients" == "\[\]"' "$repo/vless-server.sh"; then
    echo 'unsafe Xray default fallback remains'; exit 1
fi
rebuild_and_reload_xray() { echo xray >> "$fixture/reloads"; [[ "$fail" != true ]]; }
_regenerate_config() { echo singbox >> "$fixture/reloads"; [[ "$fail" != true ]]; }
printf '%s\n' '{"singbox":{"anytls":{"users":[{"name":"alice","uuid":"secret","enabled":false,"used":100,"quota":100,"quota_exceeded_notified":true}]}},"xray":{"vless":{"users":[{"name":"bob","uuid":"secret2","enabled":true,"used":200,"quota":100}]}}}' > "$DB_FILE"
fail=true
if _enforce_user_quotas; then echo 'expected reload failure'; exit 1; fi
jq -e '.singbox.anytls.users[0].quota_enforced == false and .xray.vless.users[0].quota_enforced == false' "$DB_FILE" >/dev/null
fail=false
_enforce_user_quotas
jq -e '.singbox.anytls.users[0].quota_enforced and .xray.vless.users[0].quota_enforced and (.xray.vless.users[0].enabled == false)' "$DB_FILE" >/dev/null
count=$(wc -l < "$fixture/reloads")
_enforce_user_quotas
[[ "$(wc -l < "$fixture/reloads")" == "$count" ]]
echo 'PASS per-port eligibility, disabled/default exclusion, migration, Xray false, reload failure retry independent of traffic/notification'

db_reset_user_traffic singbox anytls alice
jq -e '.singbox.anytls.users[0] | .enabled == true and .used == 0 and .quota_enforced == null and .quota_exceeded_notified == null' "$DB_FILE" >/dev/null
_db_apply '.singbox.anytls.users[0] |= (.used=100 | .enabled=false | .disable_reason="manual" | .quota_enforced=true)'
db_reset_user_traffic singbox anytls alice
jq -e '.singbox.anytls.users[0] | .enabled == false and .used == 0' "$DB_FILE" >/dev/null
_db_apply '.singbox.anytls.users[0] |= (.used=100 | .disable_reason="quota" | .expire_date="2000-01-01")'
db_reset_user_traffic singbox anytls alice
jq -e '.singbox.anytls.users[0].enabled == false' "$DB_FILE" >/dev/null
_db_apply '.singbox.anytls.users[0] |= (del(.disable_reason,.expire_date) | .quota_exceeded_notified=true)'
fail=true
if db_reset_user_traffic singbox anytls alice; then exit 1; fi
jq -e '.singbox.anytls.users[0].resume_after_quota_reset == true' "$DB_FILE" >/dev/null
fail=false
db_reset_user_traffic singbox anytls alice
jq -e '.singbox.anytls.users[0] | .enabled and (.resume_after_quota_reset == false)' "$DB_FILE" >/dev/null
db_reset_user_traffic xray vless bob
jq -e '.xray.vless.users[0] | .enabled and .used == 0' "$DB_FILE" >/dev/null
_db_apply '.singbox.anytls=[{port:1,users:[{name:"alice",uuid:"a",enabled:false,disable_reason:"quota",used:9,quota:9}]},{port:2,users:[{name:"sibling",uuid:"b",enabled:false,used:8}]}]'
db_reset_user_traffic singbox anytls alice
jq -e '.singbox.anytls[0].users[0].enabled and (.singbox.anytls[1].users[0].enabled == false) and .singbox.anytls[1].users[0].used == 8' "$DB_FILE" >/dev/null
echo 'PASS quota reset resumes users, manual/expired remain disabled, legacy marker compatibility, failed resume retry, multi-port isolation'

for fn in reset_monthly_user_traffic check_monthly_traffic_reset db_get_user; do load "$fn"; done
TRAFFIC_MONTHLY_RESET_LAST_FILE="$fixture/monthly-last"
get_traffic_monthly_reset_enabled() { echo "$monthly_enabled"; }
get_traffic_monthly_reset_day() { echo 5; }
date() {
    case "$1" in
        +%Y-%m) echo "$test_month" ;;
        +%d) echo "$test_day" ;;
        +%F) echo "$test_month-$test_day" ;;
        *) command date "$@" ;;
    esac
}
monthly_enabled=true; test_month=2026-09; test_day=04
_db_apply '.={xray:{vless:{users:[{name:"x",uuid:"x",used:100,quota:100,enabled:false,disable_reason:"quota"},{name:"manual",uuid:"m",used:12,enabled:false,disable_reason:"manual"},{name:"expired",uuid:"e",used:13,enabled:false,disable_reason:"quota",expire_date:"2000-01-01"}]},
    "snell-v6":[{users:[{name:"s",uuid:"s",used:100,quota:100,enabled:false,disable_reason:"quota"}]}]},
    singbox:{anytls:{users:[{name:"a",uuid:"a",used:100,quota:100,enabled:false,disable_reason:"quota"}]}}}'
check_monthly_traffic_reset
[[ ! -f "$TRAFFIC_MONTHLY_RESET_LAST_FILE" ]]
_snell_managed() { [[ "$1" == snell-v6 ]]; }
_snell_apply_users() { echo snell >> "$fixture/reloads"; }
test_day=05
_regenerate_config() { [[ "$monthly_fail" != true ]]; }
monthly_fail=true
if check_monthly_traffic_reset; then echo 'expected monthly partial failure'; exit 1; fi
[[ ! -f "$TRAFFIC_MONTHLY_RESET_LAST_FILE" ]]
jq -e '.xray.vless.users[0].enabled and .xray["snell-v6"][0].users[0].enabled and
    (.xray.vless.users[1].enabled == false) and (.xray.vless.users[2].enabled == false)' "$DB_FILE" >/dev/null
_db_apply '.xray.vless.users[0].used=23 | .singbox.anytls.users[0].used=7'
monthly_fail=false
check_monthly_traffic_reset
[[ "$(cat "$TRAFFIC_MONTHLY_RESET_LAST_FILE")" == 2026-09 ]]
jq -e '.xray.vless.users[0].used == 23 and .singbox.anytls.users[0].used == 7 and
    .singbox.anytls.users[0].enabled' "$DB_FILE" >/dev/null
check_monthly_traffic_reset
jq -e '.xray.vless.users[0].used == 23' "$DB_FILE" >/dev/null
test_month=2026-10; test_day=09
check_monthly_traffic_reset
jq -e '.xray.vless.users[0].used == 0 and .singbox.anytls.users[0].used == 0' "$DB_FILE" >/dev/null
[[ "$(cat "$TRAFFIC_MONTHLY_RESET_LAST_FILE")" == 2026-10 ]]
test_month=2026-11; monthly_enabled=false
_db_apply '.xray.vless.users[0].used=33'
check_monthly_traffic_reset
jq -e '.xray.vless.users[0].used == 33' "$DB_FILE" >/dev/null
echo 'PASS monthly due date/catch-up, both cores and Snell, partial failure retry without double reset, disabled/expired protection, next month and switch off'
