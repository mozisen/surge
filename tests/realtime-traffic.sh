#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
DB_FILE="$fixture/db.json"
for fn in get_all_traffic_stats db_list_protocols db_list_users _singbox_stat_key_for_user _is_snell_users_protocol _snell_managed _snell_rows; do
    eval "$(awk -v fn="$fn" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"
done
printf '%s\n' '{"xray":{"vless":{"users":[{"name":"default"}]},"snell-v6":[{"snell_id":"abc","users":[{"name":"default"}]}]},"singbox":{"vless":{"users":[{"name":"default"}]},"trojan":{"users":[{"name":"default"}]},"anytls":{"users":[{"name":"default"}]},"ss2022":{"password":"test"}},"meta":{"snell_users_v1":true}}' > "$DB_FILE"
_snell_managed() { return 0; }
_pgrep() { [[ "$offline" != true ]]; }
singbox_stats_available() { return 0; }
xray_api_query() { [[ "$1" == 'user>>>' && "$2" == false ]] || exit 1; printf '%s\n' "$xr"; }
singbox_api_query() { [[ "$2" == false ]] || exit 1; [[ "$fail_sb" != true ]] || return 1; printf '%s\n' "$sb"; }
nft() { printf '%s\n' "$nftdata"; }
xr='{"stat":[]}'
sb=$'user>>>vless-default>>>traffic>>>uplink 12\nuser>>>trojan-default>>>traffic>>>downlink 34'
nftdata='{"nftables":[{"counter":{"name":"u_abc","bytes":0}},{"counter":{"name":"d_abc","bytes":0}}]}'
out=$(get_all_traffic_stats)
[[ $(printf '%s\n' "$out" | wc -l | tr -d ' ') == 6 ]]
[[ "$out" == *'vless|default|0|0|0|ok'* ]]
[[ "$out" == *'vless|default|12|0|12|ok'* ]]
[[ "$out" == *'trojan|default|0|34|34|ok'* ]]
[[ "$out" == *'anytls|default|0|0|0|ok'* ]]
[[ "$out" == *'snell-v6|default|0|0|0|ok'* ]]
[[ "$out" == *'ss2022|default||||统计不可用（未接入用户计数）'* ]]
echo 'PASS mixed cores, zero traffic, VLESS/Trojan coverage, unsupported protocol visibility, no duplicate Snell'
xr='invalid'; fail_sb=true; nftdata='{"nftables":[]}'
out=$(get_all_traffic_stats)
[[ $(printf '%s\n' "$out" | grep -c '统计不可用') == 6 ]]
offline=true
out=$(get_all_traffic_stats)
[[ $(printf '%s\n' "$out" | wc -l | tr -d ' ') == 6 ]]
echo 'PASS malformed API, failed API, missing nft counters and stopped cores retain users as unavailable'
offline=false; fail_sb=false; xr='{}'; sb=''; nftdata='{}'
out=$(get_all_traffic_stats)
[[ "$out" == *'anytls|default|0|0|0|ok'* ]]
echo 'PASS successful empty API after reset displays zero'
