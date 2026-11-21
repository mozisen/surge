#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
eval "$(awk 'index($0,"show_single_protocol_info() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
# 只关心配置文本，其余依赖一律当作空操作。
command_not_found_handle() { return 0; }
CFG="$fixture"
db_exists() { [[ "$1" == xray && "$2" == vless ]]; }
db_get() { cat "$fixture/cfg.json"; }
get_ip_country() { echo JP; }
uuid=2cae91b3-f85c-433b-88ee-a002b9ed6d61
pbk=dwrjY6KiAMPxKdlF7T4AWFXXBtsxeHCXtBQYeCOdZV4
show() {
    jq -n --arg u "$uuid" --arg k "$pbk" --arg sid "$1" --arg v4 "$2" --arg v6 "$3" \
        '{uuid:$u,port:443,sni:"www.microsoft.com",public_key:$k,short_id:$sid,ipv4:$v4,ipv6:$v6}' > "$fixture/cfg.json"
    show_single_protocol_info vless false 2>/dev/null </dev/null | sed 's/\x1b\[[0-9;]*m//g'
}
surge_line() { grep -A1 'Surge 配置' <<<"$1" | tail -1 | sed 's/^ *//'; }

out=$(show 0123456789abcdef 1.2.3.4 '')
[[ "$(surge_line "$out")" == "JP-Vless-Reality = vless, 1.2.3.4, 443, username=$uuid, flow=xtls-rprx-vision, sni=www.microsoft.com, reality-public-key=$pbk, reality-short-id=0123456789abcdef" ]] || exit 1
# Surge 在 Loon 之前。
surge_at=$(grep -n 'Surge 配置' <<<"$out" | cut -d: -f1)
loon_at=$(grep -n 'Loon 配置' <<<"$out" | cut -d: -f1)
[[ -n "$surge_at" && -n "$loon_at" && "$surge_at" -lt "$loon_at" ]] || exit 1

# 空 ShortID 不输出该参数；纯 IPv6 使用方括号地址，与其他 Surge 行一致。
out=$(show '' '' 2001:db8::1)
[[ "$(surge_line "$out")" == "JP-Vless-Reality = vless, [2001:db8::1], 443, username=$uuid, flow=xtls-rprx-vision, sni=www.microsoft.com, reality-public-key=$pbk" ]] || exit 1
echo 'PASS VLESS REALITY shows a Surge line before Loon, omitting an empty short ID'
