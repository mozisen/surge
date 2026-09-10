#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
load() { eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"; }
for fn in singbox_api_query _singbox_stats_proto _sync_all_user_traffic_unlocked _get_singbox_stat_user_mappings db_exists db_get_user_field db_list_protocols _singbox_stats_config_ready; do load "$fn"; done
SINGBOX_V2RAY_API_PORT=10086
grpcurl() {
    printf '%s\n' "$*" > "$fixture/args"
    [[ "$fail" != true ]] || return 1
    printf '%s\n' "$mock_response"
}
mock_response='{"stat":[{"name":"user>>>vless-default>>>traffic>>>uplink","value":"123"}]}'
[[ "$(singbox_api_query 'user>>>' false)" == 'user>>>vless-default>>>traffic>>>uplink 123' ]]
grep -q 'v2ray.core.app.stats.command.StatsService/QueryStats' "$fixture/args"
grep -q '"reset":false' "$fixture/args"
singbox_api_query 'user>>>' true >/dev/null
grep -q '"reset":true' "$fixture/args"
singbox_api_query 'user>>>' reset >/dev/null
grep -q '"reset":true' "$fixture/args"
mock_response='{}'; [[ -z "$(singbox_api_query 'user>>>')" ]]
fail=true
if singbox_api_query 'user>>>'; then exit 1; fi
fail=false
echo 'PASS wire service name, JSON int64 conversion, reset flags, empty mock_response, query failure'
DB_FILE="$fixture/db.json"
jq -n '{singbox:(["vless","trojan","hy2","tuic","anytls"] | map({key:.,value:{users:[{name:"default",uuid:"secret",quota:0,used:0}]}}) | from_entries)}' > "$DB_FILE"
CFG="$fixture"
printf '%s\n' '{"experimental":{"v2ray_api":{"listen":"127.0.0.1:10086","stats":{"enabled":true,"users":["anytls-default"]}}}}' > "$CFG/singbox.json"
if _singbox_stats_config_ready; then exit 1; fi
jq '.experimental.v2ray_api.stats.users=["vless-default","trojan-default","hy2-default","tuic-default","anytls-default"]' "$CFG/singbox.json" > "$fixture/config.new"
mv "$fixture/config.new" "$CFG/singbox.json"
_singbox_stats_config_ready
echo 'PASS detects omitted VLESS/Trojan stats users in existing configuration'
_ensure_singbox_default_users() { :; }
check_monthly_traffic_reset() { :; }
_snell_sync_traffic() { :; }
check_daily_report() { :; }
_pgrep() { [[ "$1" == sing-box ]]; }
singbox_stats_available() { return 0; }
tg_get_config() { echo 80; }
mark_traffic_sync_result() { echo "$1" > "$fixture/result"; }
_warn() { :; }
db_update_user_traffic() { jq --arg p "$2" --arg n "$3" --argjson v "$4" '.singbox[$p].users |= map(if .name == $n then .used += $v else . end)' "$DB_FILE" > "$fixture/new" && mv "$fixture/new" "$DB_FILE"; }
mock_response=$(jq -n '{stat:(["vless","trojan","hy2","tuic","anytls"] | map({name:("user>>>"+.+"-default>>>traffic>>>uplink"),value:"123"}))}')
_sync_all_user_traffic_unlocked true
jq -e '[.singbox[].users[0].used] | all(. == 123)' "$DB_FILE" >/dev/null
[[ "$(cat "$fixture/result")" == ok ]]
mock_response='{}'
_sync_all_user_traffic_unlocked true
jq -e '[.singbox[].users[0].used] | all(. == 123)' "$DB_FILE" >/dev/null
fail=true
if _sync_all_user_traffic_unlocked true; then exit 1; fi
[[ "$(cat "$fixture/result")" == singbox_error ]]
echo 'PASS VLESS/Trojan/HY2/TUIC/AnyTLS sync to database, empty post-reset sync, failed query not reported as success'
