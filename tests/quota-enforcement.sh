#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
CFG="$fixture"; DB_FILE="$fixture/db.json"
load() { eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"; }
for fn in _singbox_effective_users _ensure_singbox_default_users db_get_users_stats _enforce_user_quotas db_list_users db_list_protocols db_get_user_field db_get_user_alert_state db_set_user_alert_state db_set_user_enabled _db_apply db_get gen_xray_trojan_clients gen_xray_vmess_clients; do load "$fn"; done
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_snell_managed() { return 1; }
_warn() { :; }
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
