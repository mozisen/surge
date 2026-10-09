#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
load() { eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"; }
load _db_apply
load _sync_ss_inbound_traffic
_db_lock_acquire() { :; }
_db_lock_release() { :; }
CFG="$fixture"; DB_FILE="$fixture/db.json"
mock_epoch=one
_ss_stats_generation() { echo "$mock_epoch"; }
singbox_api_query() { [[ "$1" == 'inbound>>>' && "$2" == false ]]; cat "$fixture/stats"; }
cat > "$DB_FILE" <<'JSON'
{"singbox":{"ss-legacy":[{"port":1001,"users":[{"name":"default","used":7}]},{"port":1002,"users":[{"name":"default","used":0}]}],"ss2022":{"port":1003,"users":[{"name":"default","used":0}]}}}
JSON
jq -n '{inbounds:[range(1001;1004)|{type:"shadowsocks",listen_port:.,tag:("ss-"+tostring)}],experimental:{v2ray_api:{stats:{enabled:true,inbounds:[range(1001;1004)|"ss-"+tostring]}}}}' > "$CFG/singbox.json"
for port in 1001 1002 1003; do
 printf 'inbound>>>ss-%s>>>traffic>>>uplink %s\ninbound>>>ss-%s>>>traffic>>>downlink 3\n' "$port" "$port" "$port"
done > "$fixture/stats"
_sync_ss_inbound_traffic
jq -e '.singbox["ss-legacy"][0].users[0].used == 1011 and .singbox["ss-legacy"][1].users[0].used == 1005 and .singbox.ss2022.users[0].used == 1006' "$DB_FILE" >/dev/null
_sync_ss_inbound_traffic
jq -e '.singbox.ss2022.users[0].used == 1006' "$DB_FILE" >/dev/null
mock_epoch=two
_sync_ss_inbound_traffic
jq -e '.singbox.ss2022.users[0].used == 2012' "$DB_FILE" >/dev/null
printf 'inbound>>>ss-1003>>>traffic>>>uplink 2\ninbound>>>ss-1003>>>traffic>>>downlink 1\n' > "$fixture/stats"
_sync_ss_inbound_traffic
jq -e '.singbox.ss2022.users[0].used == 2015' "$DB_FILE" >/dev/null
before=$(jq '.singbox' "$DB_FILE")
: > "$fixture/stats"
_sync_ss_inbound_traffic
[[ "$before" == "$(jq '.singbox' "$DB_FILE")" ]]
# Multi-user or ambiguous runtime inputs must not inherit a single-user counter.
jq '.inbounds += [.inbounds[2]]' "$CFG/singbox.json" > "$fixture/new"
mv "$fixture/new" "$CFG/singbox.json"
printf 'inbound>>>ss-1003>>>traffic>>>uplink 99999\ninbound>>>ss-1003>>>traffic>>>downlink 99999\n' > "$fixture/stats"
_sync_ss_inbound_traffic
[[ "$before" == "$(jq '.singbox' "$DB_FILE")" ]]
echo 'PASS SS/SS2022 exact port ownership, repeat reads, restart/reset, missing counters, ambiguous config'
