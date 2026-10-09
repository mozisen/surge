#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
DB_FILE="$fixture/db.json"
TRAFFIC_MONTHLY_RESET_LAST_FILE="$fixture/last"
for fn in reset_monthly_user_traffic _db_apply db_list_protocols db_list_users db_get_user_field db_reset_user_traffic; do
    eval "$(awk -v fn="$fn" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"
done
_db_lock_acquire() { :; }
_db_lock_release() { :; }
_ok() { :; }
_info() { :; }
_err() { :; }
# 本用例不涉及超额恢复；若被调用说明面板计费用户或手动停用用户被错误恢复。
db_set_user_enabled() { exit 1; }
db_set_user_alert_state() { exit 1; }
printf '%s\n' '{"xray":{"vless":[{"users":[{"name":"managed","used":500,"enabled":false,"panel_quota":1000,"panel_used":500},{"name":"legacy","used":500,"enabled":true}]}]},"singbox":{"hy2":{"users":[{"name":"managed","used":300,"enabled":true,"panel_quota":0,"panel_used":300},{"name":"legacy","used":300,"enabled":false}]}}}' > "$DB_FILE"
reset_monthly_user_traffic
jq -e '.xray.vless[0].users[0] | .enabled == false and .used == 500 and .panel_used == 500' "$DB_FILE" >/dev/null
jq -e '.xray.vless[0].users[1].used == 0' "$DB_FILE" >/dev/null
jq -e '.singbox.hy2.users[0] | .used == 300 and .panel_used == 300' "$DB_FILE" >/dev/null
jq -e '.singbox.hy2.users[1] | .used == 0 and .enabled == false' "$DB_FILE" >/dev/null
[[ -s "$TRAFFIC_MONTHLY_RESET_LAST_FILE" ]]
rm "$TRAFFIC_MONTHLY_RESET_LAST_FILE"
_db_apply() { return 1; }
if reset_monthly_user_traffic; then exit 1; fi
[[ ! -e "$TRAFFIC_MONTHLY_RESET_LAST_FILE" ]]
echo 'PASS monthly CLI reset isolates panel billing users on both cores, keeps manual suspension, marks success only after commit'
