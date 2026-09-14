#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'command rm -rf "$fixture"' EXIT
CFG="$fixture" DB_FILE="$fixture/db.json" DISTRO=debian
for fn in _snell_uninstall_port _snell_delete_user _snell_rows _snell_managed _is_snell_users_protocol _db_apply db_get_user_field; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_ok() { :; }; _err() { :; }
svc() { echo "$*" >> "$fixture/events"; [[ "${fail_stop:-false}" != true ]]; }
systemctl() { :; }
rm() { echo "rm $*" >> "$fixture/events"; }
nft() {
    echo "nft $*" >> "$fixture/events"
    if [[ "$1" == -j ]]; then echo '{"nftables":[]}'; fi
}
for proto in snell snell-v5 snell-v6; do
    jq -n --arg p "$proto" '{xray:{($p):[
      {port:10001,snell_id:"aaaaaaaaaaaaaaaaaaaaaaaa",users:[{name:"default",id:"aaaaaaaaaaaaaaaaaaaaaaaa",used:42}]},
      {port:10002,snell_id:"bbbbbbbbbbbbbbbbbbbbbbbb",users:[{name:"second",id:"bbbbbbbbbbbbbbbbbbbbbbbb",used:99,telegram_chat_id:"123"}]}]},meta:{snell_users:{($p):true}}}' > "$DB_FILE"
    original=$(jq -c --arg p "$proto" '.xray[$p][1]' "$DB_FILE")
    : > "$fixture/events"
    if _snell_uninstall_port "$proto" 9999; then exit 1; fi
    [[ ! -s "$fixture/events" ]]
    _snell_uninstall_port "$proto" 10001
    [[ "$(jq -c --arg p "$proto" '.xray[$p][0]' "$DB_FILE")" == "$original" ]]
    ! grep -q bbbbbbbbbbbbbbbbbbbbbbbb "$fixture/events"
    grep -q 'stop vless-snellu-aaaaaaaaaaaaaaaaaaaaaaaa' "$fixture/events"
    _snell_uninstall_port "$proto" all
    jq -e --arg p "$proto" '.xray[$p] == null and .meta.snell_users[$p] == null' "$DB_FILE" >/dev/null
done
# Guard that the interactive handler dispatches before whole-group service stops.
awk '/^uninstall_specific_protocol\(\)/,/^}/' "$repo/vless-server.sh" | awk '
 /_snell_uninstall_port/ { scoped=1 }
 /svc stop/ { if (!scoped) exit 1; found=1 }
 END { if (!found) exit 1 }'
echo 'PASS Snell v4/v5/v6 scoped deletion, sibling preservation, missing port, last/all cleanup and menu dispatch'
