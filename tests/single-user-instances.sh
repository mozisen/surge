#!/usr/bin/env bash
# 一用户一实例：SOCKS（按入站统计）与 ShadowTLS 组合（每台节点一份，按端口统计）。函数级隔离测试。
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
for fn in _single_user_active _socks_accounts _socks_sync_inbound_stats _is_stls_protocol _stls_counter_id _stls_row _stls_active \
    _stls_apply _stls_sync_traffic _api_sha256 add_xray_inbound_v2 _gen_user_share_link _proto_user_mode _proto_user_available \
    _account_jq_defs _account_valid_id _account_valid_name _account_valid_date _account_new_id _account_proto_supported \
    db_account_get db_account_find db_account_create db_account_set db_account_member_add db_account_member_new _account_assign_single \
    _account_materialize_default db_get_user_port _accounts_user_states _accounts_reload _accounts_reload_or_queue accounts_apply gen_socks_link \
    db_list_users db_get_user_field _db_apply is_standalone_protocol _is_snell_users_protocol; do
    load "$fn"
done
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_err() { echo "ERR $*" >> "$fixture/messages"; }; _warn() { :; }; _info() { :; }; _ok() { :; }
get_protocol_name() { echo "$1"; }; ensure_expire_check_cron() { :; }
gen_uuid() { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; }; gen_password() { echo "pw$RANDOM"; }
_snell_managed() { return 1; }
rebuild_and_reload_xray() { echo xray >> "$fixture/reloads"; }; _regenerate_config() { echo "$1:$2" >> "$fixture/reloads"; }
svc() { echo "$1 $2" >> "$fixture/svc"; }
get_ip_suffix() { :; }
create_service() { echo "create $1" >> "$fixture/svc"; }
_snell_update_counter_port() { echo "counter $1 $2" >> "$fixture/svc"; }
q() { jq -r "$@" "$DB_FILE"; }
today=2026-10-13
date() { case "$1" in +%F|'+%Y-%m-%d') echo "$today" ;; +%s) echo 1760000000 ;; *) command date "$@" ;; esac; }

# 1. SOCKS 账号：旧实例沿用实例账号；有 users 时只开放唯一有效用户，否则随机账号
[[ "$(_socks_accounts '{"username":"u","password":"p"}')" == '[{"user":"u","pass":"p"}]' ]] || fail $LINENO
[[ "$(_socks_accounts '{"username":"u","password":"p","users":[{"name":"alice","uuid":"K"}]}')" == '[{"user":"alice","pass":"K"}]' ]] || fail $LINENO
for bad in '{"name":"a","uuid":"K","enabled":false}' '{"name":"a","uuid":"K","expire_date":"2000-01-01"}' '{"name":"a","uuid":"K","quota":5,"used":5}'; do
    out=$(_socks_accounts "{\"username\":\"u\",\"password\":\"p\",\"users\":[$bad]}")
    [[ "$(jq -r '.[0].user' <<< "$out")" == vaio-disabled && "$out" != *'"K"'* && "$out" != *'"p"'* ]] || fail $LINENO
done
[[ "$(jq -r '.[0].user' <<< "$(_socks_accounts '{"users":[]}')")" == vaio-disabled ]] || fail $LINENO
db_exists() { [[ "$2" == socks ]]; }; db_get() { cat "$fixture/row.json"; }; db_ip_routing_enabled() { return 1; }; _listen_addr() { echo 0.0.0.0; }
echo '{"inbounds":[]}' > "$CFG/config.json"
printf '%s' '{"port":1080,"username":"u","password":"p","users":[{"name":"alice","uuid":"K"}]}' > "$fixture/row.json"
add_xray_inbound_v2 socks || fail $LINENO
[[ "$(jq -c '.inbounds[0] | {tag, accounts: .settings.accounts, auth: .settings.auth}' "$CFG/config.json")" == '{"tag":"socks-1080","accounts":[{"user":"alice","pass":"K"}],"auth":"password"}' ]] || fail $LINENO
[[ "$(grep -c 'system: {statsInboundUplink: true, statsInboundDownlink: true}' "$repo/vless-server.sh")" == 4 ]] || fail $LINENO
echo 'PASS SOCKS single-user accounts, disabled placeholder, legacy compatibility, inbound stats policy'

# 2. SOCKS 归入旧实例、分配空实例、入站计数
cat > "$DB_FILE" <<'JSON'
{"xray":{"socks":[{"port":1080,"username":"olduser","password":"OLDPASS"},{"port":1081,"username":"x","password":"y","users":[]}],
 "snell-shadowtls":{"port":443,"psk":"OLDPSK","sni":"a.example","stls_password":"OLDSTLS","snell_backend_port":10443,"version":"4"},
 "ss2022-shadowtls":{"port":8443,"password":"OLDSS","method":"2022-blake3-aes-128-gcm","sni":"b.example","stls_password":"OLDSTLS2","ss_backend_port":18443}},
 "singbox":{},"meta":{}}
JSON
alice=$(db_account_create alice 0 "" 0)
db_account_member_add "$alice" xray socks 1080 olduser true || fail $LINENO
[[ "$(q '.xray.socks[0].users[0] | "\(.name)|\(.uuid)"')" == "olduser|OLDPASS" ]] || fail $LINENO
bob=$(db_account_create bob 0 "" 0)
db_account_member_new "$bob" xray socks 1081 || fail $LINENO
[[ "$(q '.xray.socks[1] | "\(.users[0].name)|\(.username)|\(.password == .users[0].uuid)|\(.password != "y")"')" == "bob|bob|true|true" ]] || fail $LINENO
if db_account_member_new "$alice" xray socks 1081 2>/dev/null; then fail $LINENO; fi
grep -q '已有用户（一用户一实例）' "$fixture/messages" || fail $LINENO
printf '%s\n' 'inbound>>>socks-1081>>>traffic>>>uplink 100' 'inbound>>>socks-1081>>>traffic>>>downlink 23' 'inbound>>>socks-1080>>>traffic>>>uplink 0' > "$fixture/stats"
_socks_sync_inbound_stats "$fixture/stats" || fail $LINENO
[[ "$(q '[.xray.socks[].users[0].used // 0] | join(",")')" == "0,123" ]] || fail $LINENO
echo 'PASS SOCKS claim keeps the legacy account, assignment rotates it, occupied refused, inbound bytes counted'

# 3. ShadowTLS：旧实例常开；分配后由唯一用户决定启停，凭据与握手密码一并更换
[[ "$(_stls_row snell-shadowtls | jq -r .port)" == 443 ]] || fail $LINENO
_stls_active snell-shadowtls || fail $LINENO
printf '[snell-server]\nlisten = 127.0.0.1:10443\npsk = OLDPSK\nobfs = off\n' > "$CFG/snell-shadowtls.conf"
printf '%s\n' '{"inbounds":[{"port":18443,"protocol":"shadowsocks","settings":{"method":"2022-blake3-aes-128-gcm","password":"OLDSS"}}]}' > "$CFG/ss2022-shadowtls-backend.json"
carol=$(db_account_create carol 0 "" 0)
: > "$fixture/svc"
db_account_member_new "$carol" xray snell-shadowtls 443 || fail $LINENO
psk=$(q '.xray["snell-shadowtls"].psk')
[[ "$psk" != OLDPSK && "$(q '.xray["snell-shadowtls"] | "\(.users[0].name)|\(.users[0].uuid == .psk)|\(.stls_password != "OLDSTLS")"')" == "carol|true|true" ]] || fail $LINENO
grep -qx "psk = $psk" "$CFG/snell-shadowtls.conf" || fail $LINENO
grep -q '^create snell-shadowtls$' "$fixture/svc" && grep -q "^counter $(_stls_counter_id snell-shadowtls) 443$" "$fixture/svc" || fail $LINENO
grep -qx 'restart vless-snell-shadowtls-backend' "$fixture/svc" && grep -qx 'restart vless-snell-shadowtls' "$fixture/svc" || fail $LINENO
dave=$(db_account_create dave 0 "" 0)
db_account_member_new "$dave" xray ss2022-shadowtls 8443 || fail $LINENO
key=$(q '.xray["ss2022-shadowtls"].password')
[[ "$(printf '%s' "$key" | base64 -d | wc -c | tr -d ' ')" == 16 && "$(jq -r '.inbounds[0].settings.password' "$CFG/ss2022-shadowtls-backend.json")" == "$key" ]] || fail $LINENO
echo 'PASS ShadowTLS assignment rewrites backend credentials, rotates the handshake password and restarts both services'

# 4. 停用统一用户：成员派生为停用，前后端服务停止；恢复后重新启动
: > "$fixture/svc"
db_account_set "$carol" enabled false || fail $LINENO
! _stls_active snell-shadowtls || fail $LINENO
grep -qx 'stop vless-snell-shadowtls' "$fixture/svc" && grep -qx 'stop vless-snell-shadowtls-backend' "$fixture/svc" && grep -qx 'disable vless-snell-shadowtls' "$fixture/svc" || fail $LINENO
: > "$fixture/svc"
db_account_set "$carol" enabled true || fail $LINENO
grep -qx 'restart vless-snell-shadowtls' "$fixture/svc" || fail $LINENO
echo 'PASS account state stops and restarts the ShadowTLS services'

# 5. 端口计数（nft 计数器，代际变化时重新计基线）
_snell_nft_ready() { return 0; }
COUNTER_ID=$(_stls_counter_id snell-shadowtls)
nft() { printf '{"nftables":[{"counter":{"name":"u_%s","bytes":%s,"comment":"%s"}},{"counter":{"name":"d_%s","bytes":%s}}]}' "$COUNTER_ID" "$UP" "$GEN" "$COUNTER_ID" "$DOWN"; }
UP=100; DOWN=50; GEN=g1; _stls_sync_traffic || fail $LINENO
UP=130; DOWN=60; _stls_sync_traffic || fail $LINENO
[[ "$(q '.xray["snell-shadowtls"].users[0].used')" == 190 ]] || fail $LINENO
UP=5; DOWN=5; GEN=g2; _stls_sync_traffic || fail $LINENO
[[ "$(q '.xray["snell-shadowtls"].users[0].used')" == 200 ]] || fail $LINENO
echo 'PASS port counters accumulate into the single user across counter generations'

# 6. 分享链接（Surge 格式，包含握手密码）
db_get() { jq -c --arg c "$1" --arg p "$2" '.[$c][$p]' "$DB_FILE"; }
db_exists() { jq -e --arg c "$1" --arg p "$2" '.[$c][$p] != null' "$DB_FILE" >/dev/null; }
VAIO_SHARE_HOST=203.0.113.9
link=$(_gen_user_share_link xray snell-shadowtls "$psk" carol 443)
[[ "$link" == "carol = snell, 203.0.113.9, 443, psk=$psk, version=4, reuse=true, tfo=true, shadow-tls-password=$(q '.xray["snell-shadowtls"].stls_password'), shadow-tls-sni=a.example, shadow-tls-version=3" ]] || { echo "$link"; fail $LINENO; }
link=$(_gen_user_share_link xray ss2022-shadowtls "$key" dave 8443)
[[ "$link" == "dave = ss, 203.0.113.9, 8443, encrypt-method=2022-blake3-aes-128-gcm, password=$key, shadow-tls-password="* ]] || { echo "$link"; fail $LINENO; }
link=$(_gen_user_share_link xray socks "$(q '.xray.socks[1].password')" bob 1081)
[[ "$link" == *"server=203.0.113.9&port=1081&user=bob&pass="* ]] || { echo "$link"; fail $LINENO; }
echo 'PASS share links for ShadowTLS and SOCKS members'
