#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
DB_FILE="$fixture/db.json"
printf '{}\n' > "$DB_FILE"
eval "$(awk 'index($0,"_sync_traffic_now() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
_header() { :; }
_line() { :; }
_dline() { :; }
_info() { :; }
_ok() { :; }
_warn() { :; }
_err() { echo "$*"; }
_prepare_singbox_stats_interactive() { return 0; }
_pgrep() { [[ "$1" == "$running_core" ]]; }
_snell_any_managed() { return 0; }
sync_all_user_traffic() { return 0; }
db_list_protocols() {
    if [[ "$1" == xray ]]; then printf 'snell\nsnell-v5\nsnell-v6\n'; else printf 'anytls\nvless\n'; fi
}
db_get_users_stats() { printf 'default|secret|123|0|true|12345|\n'; }
get_protocol_name() { echo "$1"; }
format_bytes() { echo "$1 B"; }
for running_core in sing-box xray none; do
    output=$(_sync_traffic_now)
    for proto in snell snell-v5 snell-v6 anytls vless; do
        [[ $(printf '%s\n' "$output" | grep -c "^  $proto$") == 1 ]]
    done
    [[ $(printf '%s\n' "$output" | grep -c 'default: 123 B') == 5 ]]
done
echo 'PASS Snell v4/v5/v6 and saved protocol usage appear once regardless of running Xray/Sing-box'
