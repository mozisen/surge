#!/usr/bin/env bash
# 统一用户（节点级，一人多协议）：数据层、结算与成员派生。函数级隔离测试。
set -e -o pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
# Bash 3.2 的 set -e 不处理 [[ ]] 失败，断言统一显式失败。
fail() { echo "FAIL line $1"; exit 1; }
CFG="$fixture"; DB_FILE="$fixture/db.json"
STANDALONE_PROTOCOLS="snell snell-v5 snell-v6 snell-shadowtls snell-v5-shadowtls ss2022-shadowtls naive"
# 支持单行函数（以 "; }" 结尾）与多行函数（以独立的 "}" 结尾）。
load() {
    local body
    body=$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1; if ($0 ~ /; }$/) {print; exit}} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")
    [[ -n "$body" ]] || { echo "missing $1"; exit 1; }
    eval "$body"
}
for fn in _account_jq_defs _account_valid_id _account_valid_name _account_valid_date _account_new_id \
    _account_proto_supported db_account_list db_account_get db_account_find db_account_members db_user_account_id \
    _accounts_user_states _accounts_reload _accounts_reload_or_queue accounts_apply db_account_create db_account_set _account_materialize_default \
    db_account_member_add db_account_member_new db_get_user_port db_account_member_remove db_account_delete \
    db_account_reset_usage db_account_unlink_platform db_account_reset_credentials _account_merge_candidates \
    _account_member_guard _account_ask_expire _account_instances _account_claimable_users _account_reason_text \
    _account_show_list _account_select _account_show_detail _account_create_interactive _account_edit_interactive \
    _account_add_protocol_interactive _account_claim_interactive _account_pick_member _account_remove_member_interactive \
    _account_member_share _account_share_interactive _account_merge_interactive manage_accounts format_bytes db_authority_get _authority_guard \
    _db_apply db_get_user_field db_list_users is_standalone_protocol _is_snell_users_protocol reset_monthly_user_traffic; do
    load "$fn"
done
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_err() { echo "ERR: $*" >> "$fixture/errors"; }; _ok() { :; }; _info() { :; }; _warn() { :; }
get_protocol_name() { echo "$1"; }
ensure_expire_check_cron() { :; }
gen_uuid() { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; }
gen_password() { echo "pw$RANDOM$RANDOM"; }
_snell_managed() { [[ "$1" == snell-v5 ]]; }
rebuild_and_reload_xray() { echo xray >> "$fixture/reloads"; [[ "${fail:-}" != true ]]; }
_regenerate_config() { echo "$1:$2" >> "$fixture/reloads"; [[ "${fail:-}" != true ]]; }
_snell_apply_users() { echo "snell:$1" >> "$fixture/reloads"; }
_snell_add_user() {
    [[ "$3" == account ]] || return 1
    _db_apply --arg n "$2" '.xray["snell-v5"] += [{port: 9001, psk: "oldpsk", snell_id: "aaaaaaaaaaaaaaaaaaaaaaaa", users: [{id: "aaaaaaaaaaaaaaaaaaaaaaaa", name: $n, uuid: "oldpsk", used: 0, quota: 0, enabled: true, expire_date: ""}]}]'
}
_snell_delete_user() { _db_apply --arg n "$2" '.xray["snell-v5"] |= map(select(.users[0].name != $n))'; }
today=2026-10-12; now=1760000000
date() {
    case "$1" in
        +%F) echo "$today" ;;
        +%s) echo "$now" ;;
        *) command date "$@" ;;
    esac
}
reloads() { local r; r=$(sort -u "$fixture/reloads" 2>/dev/null | tr '\n' ' '); : > "$fixture/reloads"; echo "$r"; }
q() { jq -r "$@" "$DB_FILE"; }
user() { jq -c --arg c "$1" --arg p "$2" --arg n "$3" '[.[$c][$p] | if type == "array" then .[] else . end | .users[]? | select(.name == $n)][0]' "$DB_FILE"; }

_proto_user_mode() { echo multi; }
_is_stls_protocol() { return 1; }
K16=$(head -c 16 /dev/urandom | base64 | tr -d '\n')
cat > "$DB_FILE" <<JSON
{"xray":{},"singbox":{
 "ss2022":[{"port":7001,"method":"2022-blake3-chacha20-poly1305","users":[{"name":"u7001","uuid":"FIRSTKEY","used":0,"enabled":true}]},
           {"port":7002,"method":"2022-blake3-aes-128-gcm","password":"SERVER","users":[{"name":"u7002","uuid":"SERVER","used":0,"enabled":true}]}]},
 "meta":{}}
JSON
id=$(db_account_create alice 0 "" 0)
# Panel-installed instance (no instance key): the first user's key becomes the server key before the second user joins.
db_account_member_new "$id" singbox ss2022 7001
[[ "$(q '.singbox.ss2022[0].password')" == FIRSTKEY ]] || fail $LINENO
[[ "$(q '.singbox.ss2022[0].users | map(.name) | join(",")')" == "u7001,alice" ]] || fail $LINENO
# chacha20-poly1305 takes a 32-byte key; aes-128-gcm a 16-byte one; an existing server key is kept.
[[ "$(q '.singbox.ss2022[0].users[1].uuid' | base64 -d | wc -c | tr -d ' ')" == 32 ]] || fail $LINENO
bob=$(db_account_create bob 0 "" 0)
db_account_member_new "$bob" singbox ss2022 7002
[[ "$(q '.singbox.ss2022[1].password')" == SERVER ]] || fail $LINENO
[[ "$(q '.singbox.ss2022[1].users[1].uuid' | base64 -d | wc -c | tr -d ' ')" == 16 ]] || fail $LINENO
echo 'PASS SS2022 second user records the server key; key length follows the method'
