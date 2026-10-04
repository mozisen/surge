#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
DB_FILE="$fixture/db.json"
TRAFFIC_MONTHLY_RESET_LAST_FILE="$fixture/last"
for fn in reset_monthly_user_traffic _db_apply; do
    eval "$(awk -v fn="$fn" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"
done
_db_lock_acquire() { :; }
_db_lock_release() { :; }
_ok() { :; }
printf '%s\n' '{"xray":{"vless":[{"users":[{"name":"managed","used":500,"enabled":false,"panel_quota":1000,"panel_used":500},{"name":"legacy","used":500,"enabled":true}]}]}}' > "$DB_FILE"
reset_monthly_user_traffic
jq -e '.xray.vless[0].users[0] | .enabled == false and .used == 500 and .panel_used == 500' "$DB_FILE" >/dev/null
jq -e '.xray.vless[0].users[1].used == 0' "$DB_FILE" >/dev/null
[[ -s "$TRAFFIC_MONTHLY_RESET_LAST_FILE" ]]
rm "$TRAFFIC_MONTHLY_RESET_LAST_FILE"
_db_apply() { return 1; }
if reset_monthly_user_traffic; then exit 1; fi
[[ ! -e "$TRAFFIC_MONTHLY_RESET_LAST_FILE" ]]
echo 'PASS monthly CLI reset isolates panel billing users and marks success only after commit'
