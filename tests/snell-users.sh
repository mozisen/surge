#!/usr/bin/env bash
# No services, firewall rules, or network requests are made by this test.
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
script="$repo/vless-server.sh"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
CFG="$fixture"
DB_FILE="$CFG/db.json"
load_function() {
    local body
    body=$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$script")
    eval "$body"
}
for fn in _is_snell_users_protocol _snell_managed _snell_any_managed _snell_rows _snell_migrate _snell_sync_traffic _snell_prepare_user _snell_user_share _snell_group_service _snell_live_stats _db_apply db_list_users db_get_user_field gen_snell_surge_line db_set_user_tg_binding db_find_user_by_tg_chat; do
    load_function "$fn"
done
_db_lock_acquire() { :; }
_db_lock_release() { :; }
_info() { :; }
_err() { echo "$*" >&2; }
_snell_nft_ready() { :; }
_snell_counter_prepare() { :; }
get_connection_addresses() { echo '203.0.113.1|2001:db8::1'; }
_is_valid_port() { [[ "$1" -gt 0 && "$1" -lt 65536 ]]; }
tg_send_over_quota() { echo quota >> "$CFG/events"; }
send_tg_expired_notice() { echo expired >> "$CFG/events"; }
tg_send_quota_alert() { echo alert >> "$CFG/events"; }
db_get_user_alert_state() { echo 0; }
db_set_user_alert_state() { :; }
db_set_user_enabled() {
    _db_apply --arg p "$2" --arg n "$3" --argjson e "$4" '.xray[$p] |= map(.users |= map(if .name == $n then .enabled=$e else . end))'
}
nft() { printf '%s\n' "$fixture_snapshot"; }
svc() { printf '%s %s\n' "$1" "$2" >> "$CFG/service-events"; }

printf '%s\n' '{"xray":{"snell-v6":{"port":60125,"psk":"originalpsk123456","mode":"unshaped","dns":"1.1.1.1","users":[{"name":"default","uuid":"originalpsk123456","used":70,"quota":0,"enabled":true,"telegram_chat_id":"123"}]}},"meta":{}}' > "$DB_FILE"
printf '[snell-server]\nlisten = 0.0.0.0:60125\npsk = originalpsk123456\nmode = unshaped\ndns = 1.1.1.1\n' > "$CFG/snell-v6.conf"
_snell_migrate snell-v6
id=$(jq -r '.xray["snell-v6"][0].snell_id' "$DB_FILE")
[[ "$id" =~ ^[0-9a-f]{24}$ ]]
jq -e '.xray["snell-v6"][0] | .port == 60125 and .users[0].used == 70 and .users[0].telegram_chat_id == "123" and .users[0].uuid == .psk' "$DB_FILE" >/dev/null
cmp "$CFG/snell-v6.conf" "$CFG/snell-users/$id.conf"
_snell_migrate snell-v6
[[ "$(jq -r '.xray["snell-v6"][0].snell_id' "$DB_FILE")" == "$id" ]]
echo 'PASS migration preserves credentials, configuration, traffic, binding; idempotent'

fixture_snapshot=$(jq -n --arg id "$id" '{nftables:[{counter:{name:("u_"+$id),bytes:100,comment:"generation1"}},{counter:{name:("d_"+$id),bytes:200}}]}')
_snell_sync_traffic
_snell_sync_traffic
[[ "$(jq -r '.xray["snell-v6"][0].users[0].used' "$DB_FILE")" == 370 ]]
fixture_snapshot=$(jq -n --arg id "$id" '{nftables:[{counter:{name:("u_"+$id),bytes:10,comment:"generation2"}},{counter:{name:("d_"+$id),bytes:20}}]}')
_snell_sync_traffic
[[ "$(jq -r '.xray["snell-v6"][0].users[0].used' "$DB_FILE")" == 400 ]]
echo 'PASS counter delta, repeated synchronization, new counter generation'

_db_apply '.xray["snell-v6"][0].users[0].quota=350'
_snell_sync_traffic
[[ "$(jq -r '.xray["snell-v6"][0].users[0].enabled' "$DB_FILE")" == false ]]
[[ "$(cat "$CFG/events")" == quota ]]
if _snell_prepare_user snell-v6 "$id"; then exit 1; fi
_snell_group_service start snell-v6
[[ ! -s "$CFG/service-events" ]]
echo 'PASS quota disables user and group start skips disabled user'

_db_apply '.xray["snell-v6"][0].users[0] |= (.enabled=true | .quota=0 | .expire_date="2000-01-01")'
_snell_sync_traffic
[[ "$(tail -n1 "$CFG/events")" == expired ]]
echo 'PASS expired user disabled during Snell-only synchronization'

link=$(_snell_user_share snell-v6 default 60125)
[[ "$link" == *'60125, psk=originalpsk123456, version=6, mode=unshaped'* ]]
db_set_user_tg_binding xray snell-v6 default 456 alice now
[[ "$(db_find_user_by_tg_chat 456)" == 'xray|snell-v6|default' ]]
echo 'PASS Surge mode/credentials and Telegram user binding'
for protocol in snell snell-v5; do
    case "$protocol" in snell) expected_version=4 ;; *) expected_version=5 ;; esac
    _db_apply --arg p "$protocol" '.xray[$p]={port:60126,psk:"versiontest123456",users:[]}'
    printf '[snell-server]\nlisten = 0.0.0.0:60126\npsk = versiontest123456\nobfs = off\n' > "$CFG/$protocol.conf"
    _snell_migrate "$protocol"
    result=$(_snell_user_share "$protocol" default 60126)
    [[ "$result" == *"version=$expected_version"* ]] || exit 1
    [[ "$result" != *"mode="* ]] || exit 1
done
echo 'PASS v4/v5 migration and protocol-specific Surge output'
echo 'All Snell user regression tests passed'
