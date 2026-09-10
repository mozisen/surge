#!/usr/bin/env bash
# Offline regression: no services or network access.
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
DB_FILE="$fixture/db.json"
load_function() {
    eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"
}
for fn in _select_user_socks5_routing _select_user_routing _is_valid_domain_or_ip _is_valid_port db_chain_node_exists db_add_chain_node db_get_chain_node gen_xray_chain_outbound gen_singbox_chain_outbound db_set_user_routing db_get_user_routing; do
    load_function "$fn"
done
_db_apply() { jq "$@" "$DB_FILE" > "$fixture/new.json" && mv "$fixture/new.json" "$DB_FILE"; }
_line() { :; }
_ok() { :; }
_err() { echo "$*" >&2; }
warp_status() { return 0; }
rebuild_and_reload_xray() { echo xray > "$fixture/reloaded"; }
rebuild_and_reload_singbox() { echo singbox > "$fixture/reloaded"; }
printf '%s\n' '{"singbox":{"anytls":{"users":[{"name":"mm"},{"name":"default"}]}},"chain_proxy":{"nodes":[],"active":"unchanged"}}' > "$DB_FILE"
# WARP present: explicit SOCKS5 entry is number 4. Create authenticated IPv6 node.
_select_user_routing <<'INPUT'
4
n
exit6
[2001:db8::1]
01080
alice
p"a\ss
INPUT
[[ "$SELECTED_ROUTING" == chain:exit6 ]]
jq -e '.chain_proxy.active == "unchanged" and (.chain_proxy.nodes[0] | .server == "2001:db8::1" and .port == 1080 and .password == "p\"a\\ss")' "$DB_FILE" >/dev/null
db_set_user_routing singbox anytls mm "$SELECTED_ROUTING"
[[ "$(db_get_user_routing singbox anytls mm)" == chain:exit6 ]]
[[ "$(cat "$fixture/reloaded")" == singbox ]]
jq -e '.singbox.anytls.users[1].routing == null' "$DB_FILE" >/dev/null
gen_xray_chain_outbound exit6 test | jq -e '.protocol == "socks" and .settings.servers[0].users[0].user == "alice"' >/dev/null
gen_singbox_chain_outbound exit6 test | jq -e '.type == "socks" and .username == "alice" and .server_port == 1080' >/dev/null
_select_user_socks5_routing <<< '1'
[[ "$SELECTED_ROUTING" == chain:exit6 ]]
_select_user_socks5_routing <<'INPUT'
n
exit4
proxy.example.com
1080

INPUT
gen_xray_chain_outbound exit4 test | jq -e '.settings.servers[0].users == null' >/dev/null
gen_singbox_chain_outbound exit4 test | jq -e '.username == null and .password == null' >/dev/null
before=$(jq -c . "$DB_FILE")
if _select_user_socks5_routing <<< '0'; then exit 1; fi
if _select_user_socks5_routing <<< $'n\nexit4'; then exit 1; fi
if _select_user_socks5_routing <<< $'n\nbad\n\n1080'; then exit 1; fi
if _select_user_socks5_routing <<< $'n\nbad\nlocalhost\n65536'; then exit 1; fi
[[ "$(jq -c . "$DB_FILE")" == "$before" ]]
echo 'PASS SOCKS5 menu, selection, authenticated/anonymous outbounds, IPv6, validation, per-user storage and core reload dispatch'
