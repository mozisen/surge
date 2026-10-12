#!/usr/bin/env bash
# 用户管理方式（脚本 / 平台）：平台接管清空用户、守卫、回滚、切回、菜单。函数级隔离测试。
set -e -o pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
# Bash 3.2 的 set -e 不处理 [[ ]] 失败，断言统一显式失败。
fail() { echo "FAIL line $1"; exit 1; }
CFG="$fixture"; DB_FILE="$fixture/db.json"
STANDALONE_PROTOCOLS="snell snell-v5 snell-v6 snell-shadowtls snell-v5-shadowtls ss2022-shadowtls naive"
load() {
    local body
    body=$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1; if ($0 ~ /; }$/) {print; exit}} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")
    [[ -n "$body" ]] || { echo "missing $1"; exit 1; }
    eval "$body"
}
for fn in db_authority_get _authority_guard _authority_rows _authority_user_counts _authority_new_secret _authority_apply \
    db_authority_set _authority_menu _account_jq_defs _accounts_user_states _accounts_reload _accounts_reload_or_queue accounts_apply \
    _api_account_backup_files _api_account_restore _api_sha256 _db_apply is_standalone_protocol _is_snell_users_protocol \
    _add_user _delete_user _set_user_quota _toggle_user _set_user_expire_date _set_user_routing _tg_unbind_user _snell_edit_user; do
    load "$fn"
done
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_err() { echo "ERR $*" >> "$fixture/messages"; }; _warn() { echo "WARN $*" >> "$fixture/messages"; }
_ok() { :; }; _info() { :; }; _line() { :; }; get_protocol_name() { echo "$1"; }
gen_uuid() { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; }
_snell_managed() { [[ "$1" == snell-v5 ]]; }
failures=0
reload() {
    echo "$1" >> "$fixture/reloads"
    echo "{\"rebuilt\":$RANDOM}" > "$CFG/config.json"
    if (( failures > 0 )); then failures=$((failures - 1)); return 1; fi
}
rebuild_and_reload_xray() { reload xray; }
_regenerate_config() { reload "$1:$2"; }
_snell_apply_users() { reload "snell:$1"; }
q() { jq -r "$@" "$DB_FILE"; }
echo '{"seed":1}' > "$CFG/config.json"
cat > "$DB_FILE" <<'JSON'
{"xray":{
  "vless":[{"port":443,"uuid":"ROW_SECRET","sni":"a","users":[{"name":"default","uuid":"ROW_SECRET"},
           {"name":"alice","uuid":"ALICE_SECRET","telegram_chat_id":"CHAT_SECRET","routing":"warp","quota":9,"expire_date":"2099-01-01","account_id":"a1"}]},
           {"port":444,"uuid":"LEGACY_SECRET"}],
  "snell-v5":[{"port":9001,"psk":"SNELL_SECRET","snell_id":"aaaaaaaaaaaaaaaaaaaaaaaa","users":[{"id":"aaaaaaaaaaaaaaaaaaaaaaaa","name":"sam","uuid":"SNELL_SECRET"}]}],
  "snell":{"port":7000,"psk":"STANDALONE_PSK"}},
 "singbox":{"ss2022":{"port":8388,"method":"2022-blake3-aes-128-gcm","password":"SS_SECRET","panel_managed":true,"users":[{"name":"default","uuid":"SS_SECRET"}]},
            "hy2":{"port":8443,"password":"HY_SECRET","users":[{"name":"bob","uuid":"BOB_SECRET"}]}},
 "accounts":{"a1":{"name":"alice","members":[{"core":"xray","protocol":"vless","port":443,"name":"alice"}],"platform_user_id":"p1"}},
 "meta":{"snell_users":{"snell-v5":true},"accounts_reload_pending":["xray|vless"]}}
JSON

# 1. 缺省为脚本模式，守卫放行；统计将删除的用户
[[ "$(db_authority_get)" == script ]] || fail $LINENO
_authority_guard || fail $LINENO
counts=$(_authority_user_counts)
grep -qx 'xray|vless|443|2' <<< "$counts" || fail $LINENO
grep -qx 'xray|vless|444|1' <<< "$counts" || fail $LINENO
grep -qx 'singbox|ss2022|8388|1' <<< "$counts" || fail $LINENO
grep -qx 'xray|snell-v5|9001|1' <<< "$counts" || fail $LINENO
! grep -q '|snell|7000|' <<< "$counts" || fail $LINENO
echo 'PASS default script mode and per-instance user counts (standalone Snell excluded)'

# 2. 重建失败：整体回滚数据库与配置
before=$(cat "$DB_FILE"); cfg_before=$(cat "$CFG/config.json")
failures=1
if db_authority_set platform; then fail $LINENO; fi
[[ "$(cat "$DB_FILE")" == "$before" ]] || fail $LINENO
grep -q '切换失败，已恢复原用户数据' "$fixture/messages" || fail $LINENO
failures=0; : > "$fixture/reloads"
echo 'PASS takeover failure restores the database and configuration'

# 3. 平台接管：清空全部受管实例的用户与凭据，独立协议不受影响
db_authority_set platform || fail $LINENO
[[ "$(db_authority_get)" == platform ]] || fail $LINENO
[[ "$(q '[.xray.vless[].users, .xray["snell-v5"][0].users, .singbox.ss2022.users, .singbox.hy2.users] | map(length) | add')" == 0 ]] || fail $LINENO
[[ "$(q '.xray.vless[1].users | type')" == array ]] || fail $LINENO
for secret in ROW_SECRET ALICE_SECRET LEGACY_SECRET SNELL_SECRET SS_SECRET HY_SECRET BOB_SECRET CHAT_SECRET; do
    ! grep -q "$secret" "$DB_FILE" || { echo "$secret remains"; fail $LINENO; }
done
[[ "$(q .xray.snell.psk)" == STANDALONE_PSK ]] || fail $LINENO
[[ "$(q '.xray.vless[0].uuid')" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || fail $LINENO
[[ "$(q .singbox.ss2022.password | base64 -d 2>/dev/null | wc -c | tr -d ' ')" == 16 ]] || fail $LINENO
[[ "$(q '.xray["snell-v5"][0].psk')" =~ ^[0-9a-f]{32}$ ]] || fail $LINENO
[[ "$(q '"\(.accounts)|\(.meta.accounts_reload_pending)|\(.meta.snell_users["snell-v5"])"')" == "null|null|true" ]] || fail $LINENO
r=$(sort -u "$fixture/reloads" | tr '\n' ' ')
[[ "$r" == *xray* && "$r" == *singbox:* && "$r" == *snell:snell-v5* ]] || fail $LINENO
echo 'PASS takeover clears users, credentials, accounts and TG/routing data; keeps standalone protocols'

# 4. 平台模式下菜单写操作全部被拒绝
: > "$fixture/messages"
for fn in _add_user _delete_user _set_user_quota _toggle_user _set_user_expire_date _set_user_routing _tg_unbind_user _snell_edit_user; do
    if "$fn" xray vless >/dev/null 2>&1; then echo "$fn allowed"; fail $LINENO; fi
done
[[ "$(grep -c 'Vaio 平台管理' "$fixture/messages")" == 8 ]] || fail $LINENO
echo 'PASS platform mode blocks every local user write'

# 5. 切回脚本：用户与凭据保留，统一用户解除平台关联
_db_apply '.singbox.hy2.users = [{"name":"carol","uuid":"CAROL"}] | .accounts = {"a2":{"name":"carol","members":[],"platform_user_id":"p2","platform_block":"quota"}}'
db_authority_set script || fail $LINENO
[[ "$(db_authority_get)" == script ]] || fail $LINENO
[[ "$(q '"\(.singbox.hy2.users[0].uuid)|\(.accounts.a2.platform_user_id)|\(.accounts.a2.platform_block)"')" == "CAROL|null|null" ]] || fail $LINENO
_authority_guard || fail $LINENO
echo 'PASS switching back keeps users and unlinks accounts'

# 6. 菜单：未输入 CLEAR 不切换；输入 CLEAR 切换；平台模式下确认切回
: > "$fixture/messages"
_authority_menu <<< 'clear' >/dev/null 2>&1
[[ "$(db_authority_get)" == script ]] || fail $LINENO
_authority_menu <<< 'CLEAR' >/dev/null 2>&1
[[ "$(db_authority_get)" == platform && "$(q '.singbox.hy2.users | length')" == 0 ]] || fail $LINENO
_authority_menu <<< 'n' >/dev/null 2>&1
[[ "$(db_authority_get)" == platform ]] || fail $LINENO
_authority_menu <<< 'y' >/dev/null 2>&1
[[ "$(db_authority_get)" == script ]] || fail $LINENO
echo 'PASS menu requires CLEAR to take over and confirmation to switch back'
