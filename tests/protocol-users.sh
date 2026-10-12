#!/usr/bin/env bash
# 协议用户能力表、SS2022 多用户、一用户一实例分配、成员连接信息、平台模式空实例。函数级隔离测试。
set -e -o pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
# Bash 3.2 的 set -e 不处理 [[ ]] 失败，断言统一显式失败。
fail() { echo "FAIL line $1"; exit 1; }
CFG="$fixture"; DB_FILE="$fixture/db.json"; VERSION=test
XRAY_PROTOCOLS="vless vless-xhttp vless-xhttp-cdn vless-ws vless-ws-notls vmess-ws vless-vision trojan trojan-ws socks ss2022 ss-legacy"
SINGBOX_PROTOCOLS="vless trojan ss2022 ss-legacy hy2 tuic anytls"
STANDALONE_PROTOCOLS="snell snell-v5 snell-v6 snell-shadowtls snell-v5-shadowtls ss2022-shadowtls naive"
load() {
    local body
    body=$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1; if ($0 ~ /; }$/) {print; exit}} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")
    [[ -n "$body" ]] || { echo "missing $1"; exit 1; }
    eval "$body"
}
for fn in _proto_user_mode _proto_user_stats _proto_user_available _proto_user_modes_json _proto_user_hint \
    _ss2022_is_multi _ss2022_active_users _platform_render_inbound add_xray_inbound_v2 \
    _account_jq_defs _account_valid_id _account_valid_name _account_valid_date _account_new_id _account_proto_supported \
    db_account_get db_account_find db_account_create db_account_member_add db_account_member_new _account_assign_single \
    _account_materialize_default db_get_user_port _accounts_user_states _accounts_reload _accounts_reload_or_queue accounts_apply \
    db_list_users db_get_user_field _db_apply is_standalone_protocol _is_snell_users_protocol \
    _api_reply _api_account_share register_protocol db_authority_get; do
    load "$fn"
done
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_err() { echo "ERR $*" >> "$fixture/messages"; }; _warn() { echo "WARN $*" >> "$fixture/messages"; }
_info() { echo "INFO $*" >> "$fixture/messages"; }; _ok() { :; }
get_protocol_name() { echo "$1"; }; ensure_expire_check_cron() { :; }
gen_uuid() { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; }; gen_password() { echo "pw$RANDOM"; }
_snell_managed() { [[ "$1" == snell-v5 ]]; }
_snell_apply_users() { echo "snell:$1" >> "$fixture/reloads"; }
rebuild_and_reload_xray() { echo xray >> "$fixture/reloads"; }; _regenerate_config() { echo "$1:$2" >> "$fixture/reloads"; }
q() { jq -r "$@" "$DB_FILE"; }

# 1. 能力表覆盖全部协议标识
declare_modes="vless:multi:user vless-vision:multi:user vless-ws:multi:user vless-ws-notls:multi:user vless-xhttp:multi:user
vless-xhttp-cdn:multi:user vmess-ws:multi:user trojan:multi:user trojan-ws:multi:user ss-legacy:multi:user ss2022:multi:user
hy2:multi:user tuic:multi:user anytls:multi:user socks:single:inbound snell:single:port snell-v5:single:port snell-v6:single:port
snell-shadowtls:single:port snell-v5-shadowtls:single:port ss2022-shadowtls:single:port naive:none:none"
for item in $declare_modes; do
    IFS=':' read -r proto mode stats <<< "$item"
    [[ "$(_proto_user_mode "$proto"):$(_proto_user_stats "$proto")" == "$mode:$stats" ]] || { echo "$proto"; fail $LINENO; }
done
[[ "$(_proto_user_mode socks '{"auth_mode":"noauth"}')" == none ]] || fail $LINENO
echo '{"xray":{},"singbox":{},"meta":{}}' > "$DB_FILE"
modes=$(_proto_user_modes_json)
[[ "$(jq 'keys | length' <<< "$modes")" == 22 ]] || fail $LINENO
[[ "$(jq -r '"\(.vless.available)|\(.socks.available)|\(.naive.mode)|\(."snell-v5".available)|\(.snell.available)"' <<< "$modes")" == "true|false|none|true|false" ]] || fail $LINENO
: > "$fixture/messages"
_proto_user_hint naive; _proto_user_hint snell-v5; _proto_user_hint socks; _proto_user_hint vless
grep -q '该协议不支持用户管理' "$fixture/messages" || fail $LINENO
grep -q '一用户一实例' "$fixture/messages" || fail $LINENO
grep -q '暂未接入用户管理' "$fixture/messages" || fail $LINENO
[[ "$(wc -l < "$fixture/messages" | tr -d ' ')" == 3 ]] || fail $LINENO
echo 'PASS capability table covers all 22 protocols, socks noauth is none, install hints'

# 2. SS2022：旧单密码兼容，多用户按服务端密钥 + 用户密钥
legacy='{"port":8388,"method":"2022-blake3-aes-128-gcm","password":"S","users":[{"name":"default","uuid":"S"}]}'
! _ss2022_is_multi "$legacy" || fail $LINENO
! _ss2022_is_multi '{"password":"S"}' || fail $LINENO
multi='{"port":8388,"method":"2022-blake3-aes-128-gcm","password":"SERVER","users":[{"name":"a","uuid":"KA"},{"name":"b","uuid":"KB","enabled":false},{"name":"c","uuid":"KC","expire_date":"2000-01-01"}]}'
_ss2022_is_multi "$multi" || fail $LINENO
_ss2022_is_multi '{"password":"S","users":[]}' || fail $LINENO
[[ "$(_ss2022_active_users "$multi" | jq -c .)" == '[{"name":"a","password":"KA"}]' ]] || fail $LINENO
[[ "$(_ss2022_active_users '{"method":"2022-blake3-aes-128-gcm","password":"S","users":[]}' | jq -r '.[0].password' | base64 -d | wc -c | tr -d ' ')" == 16 ]] || fail $LINENO
db_exists() { [[ "$2" == ss2022 ]]; }; db_get() { cat "$fixture/row.json"; }; db_ip_routing_enabled() { return 1; }; _listen_addr() { echo 0.0.0.0; }
echo '{"inbounds":[]}' > "$CFG/config.json"
printf '%s' "$multi" > "$fixture/row.json"
add_xray_inbound_v2 ss2022 || fail $LINENO
[[ "$(jq -c '.inbounds[0].settings | {password, clients}' "$CFG/config.json")" == '{"password":"SERVER","clients":[{"password":"KA","email":"a@ss2022"}]}' ]] || fail $LINENO
echo '{"inbounds":[]}' > "$CFG/config.json"
printf '%s' "$legacy" > "$fixture/row.json"
add_xray_inbound_v2 ss2022 || fail $LINENO
[[ "$(jq -c '.inbounds[0].settings | {password, clients}' "$CFG/config.json")" == '{"password":"S","clients":null}' ]] || fail $LINENO
echo 'PASS SS2022 multi-user (server key + user keys) with legacy single-password compatibility on Xray'

# 3. 共享渲染器（面板管理的 Sing-box SS）
render() { jq -nc --argjson row "$1" '{row: $row}' | _platform_render_inbound singbox "$2"; }
[[ "$(render "$legacy" ss2022 | jq -r '"\(.password)|\(.users)"')" == "S|null" ]] || fail $LINENO
[[ "$(render "$multi" ss2022 | jq -c '{password, users}')" == '{"password":"SERVER","users":[{"name":"ss2022-a","password":"KA"}]}' ]] || fail $LINENO
[[ "$(render '{"port":1,"method":"2022-blake3-aes-128-gcm","password":"SERVER","users":[]}' ss2022 | jq -r '.users[0].name')" == vaio-disabled ]] || fail $LINENO
legacy_ss='{"port":2,"method":"aes-256-gcm","password":"P","users":[{"name":"a","uuid":"PA"},{"name":"b","uuid":"PB"}]}'
[[ "$(render "$legacy_ss" ss-legacy | jq -c '{password, users}')" == '{"password":null,"users":[{"name":"ss-legacy-a","password":"PA"},{"name":"ss-legacy-b","password":"PB"}]}' ]] || fail $LINENO
[[ "$(render '{"port":2,"method":"aes-256-gcm","password":"P","users":[{"name":"a","uuid":"P"}]}' ss-legacy | jq -r .password)" == P ]] || fail $LINENO
echo 'PASS shared renderer: SS2022 multi-user and legacy, SS legacy multi-user, disabled placeholder'

# 4. 一用户一实例分配（Snell）：空实例分配新凭据，已占用拒绝
cat > "$DB_FILE" <<'JSON'
{"xray":{"snell-v5":[{"port":9001,"psk":"OLD","snell_id":"aaaaaaaaaaaaaaaaaaaaaaaa","users":[]},
                     {"port":9002,"psk":"BUSY","snell_id":"bbbbbbbbbbbbbbbbbbbbbbbb","users":[{"id":"bbbbbbbbbbbbbbbbbbbbbbbb","name":"other","uuid":"BUSY"}]}]},
 "singbox":{},"meta":{"snell_users":{"snell-v5":true}}}
JSON
id=$(db_account_create alice 0 "" 0)
db_account_member_new "$id" xray snell-v5 9001 || fail $LINENO
[[ "$(q '.xray["snell-v5"][0] | "\(.users[0].name)|\(.users[0].account_id)|\(.users[0].id)|\(.psk == .users[0].uuid)|\(.psk != "OLD")"')" == "alice|$id|aaaaaaaaaaaaaaaaaaaaaaaa|true|true" ]] || fail $LINENO
grep -q 'snell:snell-v5' "$fixture/reloads" || fail $LINENO
id2=$(db_account_create bob 0 "" 0)
if db_account_member_new "$id2" xray snell-v5 9002 2>/dev/null; then fail $LINENO; fi
grep -q '已有用户（一用户一实例）' "$fixture/messages" || fail $LINENO
echo 'PASS single-user instance assignment rotates the credential and refuses occupied instances'

# 5. 成员连接信息：指定地址，不探测公网；未知用户与不支持的协议被拒绝
_gen_user_share_link() { printf '\033[32mLINK %s %s %s %s %s host=%s\033[0m\n' "$@" "$VAIO_SHARE_HOST"; }
api_id=s1
out=$(_api_account_share '{"api_version":1,"request_id":"s1","action":"account_share","params":{"target":{"core":"xray","protocol":"snell-v5","port":9001},"name":"alice","host":"203.0.113.5"}}' || true)
[[ "$(jq -r .data.connection <<< "$out")" == "LINK xray snell-v5 $(q '.xray["snell-v5"][0].psk') alice 9001 host=203.0.113.5" ]] || { echo "$out"; fail $LINENO; }
out=$(_api_account_share '{"api_version":1,"request_id":"s1","action":"account_share","params":{"target":{"core":"xray","protocol":"snell-v5","port":9001},"name":"nobody"}}' || true)
[[ "$(jq -r .code <<< "$out")" == user_not_found ]] || fail $LINENO
out=$(_api_account_share '{"api_version":1,"request_id":"s1","action":"account_share","params":{"target":{"core":"xray","protocol":"naive","port":443},"name":"alice"}}' || true)
[[ "$(jq -r .code <<< "$out")" == unsupported_protocol ]] || fail $LINENO
out=$(_api_account_share '{"api_version":1,"request_id":"s1","action":"account_share","params":{"target":{"core":"xray","protocol":"snell-v5","port":9001},"name":"alice","host":"a;rm -rf /"}}' || true)
[[ "$(jq -r .code <<< "$out")" == invalid_request ]] || fail $LINENO
echo 'PASS member connection info with explicit host, validation and refusals'

# 6. 平台模式安装空实例；脚本模式保持 default
get_protocol_default_core() { echo xray; }; protocol_supports_core() { return 0; }; is_protocol_installed() { return 1; }
db_add() { _db_apply --arg c "$1" --arg p "$2" --argjson v "$3" '.[$c][$p] = $v'; }
register_protocol vless-ws '{"port":2083,"uuid":"U1"}' xray
[[ "$(q '.xray["vless-ws"].users')" == null ]] || fail $LINENO
_db_apply '.meta.user_authority = "platform"'
register_protocol trojan-ws '{"port":2087,"password":"P1"}' xray
[[ "$(q '.xray["trojan-ws"].users | length')" == 0 ]] || fail $LINENO
register_protocol naive '{"port":443,"username":"u","password":"p"}' xray
[[ "$(q '.xray.naive.users')" == null ]] || fail $LINENO
echo 'PASS platform-mode installs empty multi-user instances; script mode and unsupported protocols unchanged'
