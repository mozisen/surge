#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
for fn in gen_vless_surge_line show_single_protocol_info gen_surge_sub; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
# 只关心配置文本，其余依赖一律当作空操作。
command_not_found_handle() { return 0; }
CFG="$fixture"
db_exists() { [[ "$1" == xray && -f "$fixture/$2.json" ]]; }
db_get() { cat "$fixture/$2.json"; }
get_ip_country() { echo JP; }
get_protocol_name() { echo "$1"; }
get_installed_protocols() { printf '%s\n' vless vless-xhttp vless-xhttp-cdn; }
get_connection_addresses() { echo '1.2.3.4|'; }
get_all_external_links() { :; }
uuid=2cae91b3-f85c-433b-88ee-a002b9ed6d61
pbk=dwrjY6KiAMPxKdlF7T4AWFXXBtsxeHCXtBQYeCOdZV4
write_cfg() {
    jq -n --arg u "$uuid" --arg k "$pbk" --arg sid "$2" --arg v4 "$3" --arg v6 "$4" --arg path "$5" \
        '{uuid:$u,port:443,sni:"www.microsoft.com",public_key:$k,short_id:$sid,ipv4:$v4,ipv6:$v6,path:$path,domain:"cdn.example.com"}' > "$fixture/$1.json"
}
show() { show_single_protocol_info "$1" false 2>/dev/null </dev/null | sed 's/\x1b\[[0-9;]*m//g'; }
surge_line() { grep -A1 'Surge 配置' <<<"$1" | tail -1 | sed 's/^ *//'; }

write_cfg vless 0123456789abcdef 1.2.3.4 '' ''
out=$(show vless)
[[ "$(surge_line "$out")" == "JP-Vless-Reality = vless, 1.2.3.4, 443, username=$uuid, flow=xtls-rprx-vision, sni=www.microsoft.com, reality-public-key=$pbk, reality-short-id=0123456789abcdef" ]] || exit 1
# Surge 在 Loon 之前。
surge_at=$(grep -n 'Surge 配置' <<<"$out" | cut -d: -f1)
loon_at=$(grep -n 'Loon 配置' <<<"$out" | cut -d: -f1)
[[ -n "$surge_at" && -n "$loon_at" && "$surge_at" -lt "$loon_at" ]] || exit 1

# 空 ShortID 不输出该参数；纯 IPv6 使用方括号地址，与其他 Surge 行一致。
write_cfg vless '' '' 2001:db8::1 ''
[[ "$(surge_line "$(show vless)")" == "JP-Vless-Reality = vless, [2001:db8::1], 443, username=$uuid, flow=xtls-rprx-vision, sni=www.microsoft.com, reality-public-key=$pbk" ]] || exit 1

# XHTTP + REALITY：不带 vision flow，提示不再说 Surge 不支持。
write_cfg vless-xhttp 0123456789abcdef 1.2.3.4 '' /xh
out=$(show vless-xhttp)
[[ "$(surge_line "$out")" == "JP-Vless-XHTTP = vless, 1.2.3.4, 443, username=$uuid, sni=www.microsoft.com, reality-public-key=$pbk, reality-short-id=0123456789abcdef, xhttp=true, xhttp-path=/xh" ]] || exit 1
grep -q 'Loon/Surge 暂不支持' <<<"$out" && exit 1

# XHTTP + TLS + CDN：域名、443、tls=true。
write_cfg vless-xhttp-cdn '' 1.2.3.4 '' /cdn
out=$(show vless-xhttp-cdn)
[[ "$(surge_line "$out")" == "JP-Vless-XHTTP-CDN = vless, cdn.example.com, 443, username=$uuid, sni=cdn.example.com, tls=true, xhttp=true, xhttp-path=/cdn" ]] || exit 1
grep -q 'Loon/Surge 暂不支持' <<<"$out" && exit 1

# Surge 订阅包含三种 VLESS 节点，并列入策略组；Encryption 模式的 VLESS 不生成。
write_cfg vless 0123456789abcdef 1.2.3.4 '' ''
sub=$(gen_surge_sub)
grep -qx "JP-vless-4 = vless, 1.2.3.4, 443, username=$uuid, flow=xtls-rprx-vision, sni=www.microsoft.com, reality-public-key=$pbk, reality-short-id=0123456789abcdef" <<<"$sub" || exit 1
grep -qx "JP-vless-xhttp-4 = vless, 1.2.3.4, 443, username=$uuid, sni=www.microsoft.com, reality-public-key=$pbk, reality-short-id=0123456789abcdef, xhttp=true, xhttp-path=/xh" <<<"$sub" || exit 1
grep -qx "JP-vless-xhttp-cdn-4 = vless, cdn.example.com, 443, username=$uuid, sni=cdn.example.com, tls=true, xhttp=true, xhttp-path=/cdn" <<<"$sub" || exit 1
grep -qx 'Proxy = select, JP-vless-4, JP-vless-xhttp-4, JP-vless-xhttp-cdn-4' <<<"$sub" || exit 1
jq '.security_mode="encryption"' "$fixture/vless.json" > "$fixture/next" && mv "$fixture/next" "$fixture/vless.json"
grep -q '^JP-vless-4 =' <<<"$(gen_surge_sub)" && exit 1
echo 'PASS Surge lines for VLESS REALITY, XHTTP and XHTTP-CDN in node info and the Surge subscription'
