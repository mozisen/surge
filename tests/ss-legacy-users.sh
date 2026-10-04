#!/usr/bin/env bash
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
CFG="$fixture"; DB_FILE="$fixture/db.json"; listen_addr=0.0.0.0
load() { eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$script")"; }
for fn in _ss_legacy_active_users _ss_legacy_xray_settings _ss_legacy_singbox_inbound add_xray_inbound_v2 db_add_user _regenerate_config _gen_user_share_link gen_ss_legacy_link; do load "$fn"; done
_err() { echo "$*" >&2; }
db_ip_routing_enabled() { return 1; }
_is_snell_users_protocol() { return 1; }
is_standalone_protocol() { return 1; }
_listen_addr() { echo 0.0.0.0; }
_has_ipv6() { return 1; }
db_exists() { [[ "$2" == ss-legacy* || "$2" == ss2022 ]]; }
db_get() { jq -c --arg c "$1" --arg p "${2%%_port_*}" --arg port "${2##*_port_}" '.[$c][$p] | if type=="array" then .[] | select((.port|tostring)==$port) else . end' "$DB_FILE"; }
get_connection_addresses() { echo '192.0.2.1|'; }
get_ip_country() { echo TEST; }
get_ip_suffix() { echo test; }
rebuild_and_reload_xray() { echo reload >> "$fixture/reloads"; }
rebuild_and_reload_singbox() { echo reload >> "$fixture/singbox-reloads"; }
_db_apply() { jq "$@" "$DB_FILE" > "$fixture/new.json" && mv "$fixture/new.json" "$DB_FILE"; }

for method in aes-128-gcm aes-256-gcm chacha20-ietf-poly1305; do
    jq -n --arg m "$method" '{xray:{"ss-legacy":[{port:31001,method:$m,password:"original",users:[{name:"default",uuid:"original"},{name:"alice",uuid:"alice-password"},{name:"blocked",uuid:"blocked",enabled:false},{name:"spent",uuid:"spent",quota:1,used:1},{name:"expired",uuid:"expired",expire_date:"2000-01-01"}]},{port:31002,method:$m,password:"second"}]}}' > "$DB_FILE"
    echo '{"inbounds":[{"tag":"untouched","protocol":"vless","settings":{"clients":[{"id":"keep"}]}}]}' > "$CFG/config.json"
    add_xray_inbound_v2 ss-legacy_port_31001
    add_xray_inbound_v2 ss-legacy_port_31002
    jq -e --arg m "$method" '
        .inbounds[0].settings.clients[0].id == "keep" and
        ([.inbounds[1].settings.clients[].password] == ["original","alice-password"]) and
        ([.inbounds[1].settings.clients[].method]|all(.==$m)) and
        .inbounds[1].settings.clients[1].email == "alice@ss-legacy" and
        .inbounds[2].settings.clients[0].password == "second"
    ' "$CFG/config.json" >/dev/null
    inbound=$(_ss_legacy_singbox_inbound "$(db_get xray ss-legacy_port_31001)" 0.0.0.0)
    jq -e --arg m "$method" '
        .method==$m and .listen_port==31001 and
        [.users[].password]==["original","alice-password"] and
        .users[1].name=="ss-legacy-alice" and (has("password")|not)
    ' <<< "$inbound" >/dev/null
    _db_apply '.singbox=.xray'
    # Share credentials must match exactly what both servers accept.
    db_get() { jq -c --arg c "$1" --arg p "$2" '.[$c][$p]' "$DB_FILE"; }
    link=$(_gen_user_share_link xray ss-legacy alice-password alice 31001)
    auth=$(printf '%s' "$method:alice-password" | base64 | tr -d '\n')
    [[ "$link" == "ss://$auth@192.0.2.1:31001"* ]]
    [[ "$(_gen_user_share_link singbox ss-legacy alice-password alice 31001)" == "$link" ]]
    # Restore the port-scoped generator adapter.
    db_get() { jq -c --arg c "$1" --arg p "${2%%_port_*}" --arg port "${2##*_port_}" '.[$c][$p] | if type=="array" then .[] | select((.port|tostring)==$port) else . end' "$DB_FILE"; }
done

settings=$(_ss_legacy_xray_settings '{"method":"aes-128-gcm","password":"old","users":[]}')
[[ "$settings" != *'"old"'* ]]
jq -e '.clients|length==1' <<< "$settings" >/dev/null
settings=$(_ss_legacy_xray_settings '{"method":"aes-128-gcm","password":"old"}')
jq -e '.clients[0].password=="old"' <<< "$settings" >/dev/null
settings=$(_ss_legacy_xray_settings '{"method":"aes-128-gcm","password":"old","users":[{"name":"default","uuid":"old","enabled":false}]}')
[[ "$settings" != *'"old"'* ]]
echo '{"xray":{"ss-legacy":[{"port":1,"method":"aes-128-gcm","password":"old"},{"port":2,"password":"other"}]}}' > "$DB_FILE"
db_add_user xray ss-legacy alice secret 0
jq -e '.xray["ss-legacy"][0].users[0].uuid=="old" and .xray["ss-legacy"][0].users[1].uuid=="secret" and (.xray["ss-legacy"][1]|has("users")|not)' "$DB_FILE" >/dev/null
_db_apply '.singbox={"ss-legacy":{port:3,method:"aes-128-gcm",password:"sing-default"}}'
db_add_user singbox ss-legacy bob sing-secret 0
jq -e '.singbox["ss-legacy"].users[0].uuid=="sing-default" and .singbox["ss-legacy"].users[1].uuid=="sing-secret"' "$DB_FILE" >/dev/null
_regenerate_config xray ss-legacy
[[ "$(wc -l < "$fixture/reloads" | tr -d ' ')" == 2 ]]
echo '{"xray":{"ss2022":{"port":31003,"method":"2022-blake3-aes-128-gcm","password":"server-key"}}}' > "$DB_FILE"
echo '{"inbounds":[]}' > "$CFG/config.json"
add_xray_inbound_v2 ss2022
jq -e '.inbounds[0].settings.password=="server-key" and (.inbounds[0].settings|has("clients")|not)' "$CFG/config.json" >/dev/null
! grep -q 'ask_password 16 "SS2022密码"' "$script"
echo 'PASS SS prompt, all AEAD methods, Xray/Sing-box inbound/share consistency, per-port isolation, disabled/quota/expiry filtering, default migration, SS2022 isolation'
