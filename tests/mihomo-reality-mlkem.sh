#!/usr/bin/env bash
# mihomo 连 Xray >= 26.9.9 的 REALITY 节点必须开启 ML-KEM 密钥交换。
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
CFG="$fixture"
load() { eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$script")"; }
for fn in gen_clash_sub external_link_to_clash; do load "$fn"; done
get_installed_protocols() { echo "vless vless-xhttp"; }
get_connection_addresses() { echo "203.0.113.7|"; }
get_ip_suffix() { echo 7; }
get_ip_country() { echo US; }
get_all_external_links() { :; }
get_protocol_name() { echo "$1"; }
_get_master_port() { :; }
db_exists() { [[ "$1" == xray ]]; }
db_get() {
    jq -n --arg p "$2" '{uuid:"u-1", port:443, sni:"www.example.com", short_id:"ab", public_key:"PK", path:"/x"}'
}
parse_share_link() {
    jq -nc '{type:"vless", name:"ext", server:"198.51.100.2", port:8443, uuid:"u-2", security:"reality",
             transport:"tcp", sni:"www.example.com", pbk:"PK2", sid:"cd", flow:"xtls-rprx-vision"}'
}

fail() { echo "FAIL: $*"; exit 1; }
check_block() {
    local out="$1" label="$2"
    [[ $(grep -c 'support-x25519mlkem768: true' <<<"$out") -ge "$3" ]] || fail "$label 缺少 support-x25519mlkem768"
    [[ $(grep -c 'client-fingerprint: chrome' <<<"$out") -ge "$3" ]] || fail "$label 缺少 client-fingerprint: chrome"
    # 开关必须位于 reality-opts 之下（6 空格缩进）
    grep -q '^      support-x25519mlkem768: true$' <<<"$out" || fail "$label 开关缩进不在 reality-opts 下"
}

local_out=$(gen_clash_sub)
check_block "$local_out" "本机节点" 2
external_out=$(external_link_to_clash "vless://placeholder")
check_block "$external_out" "外部节点" 1
echo "mihomo REALITY ML-KEM 输出测试通过"
