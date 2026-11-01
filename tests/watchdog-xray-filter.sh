#!/usr/bin/env bash
# 看门狗只在确有核心协议时守护 vless-reality / vless-singbox。
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
export TEST_CFG="$fixture"
# 只加载函数定义：CFG 指向临时目录，去掉末尾的命令行入口。
sed -e 's|^readonly CFG="/etc/vless-reality"$|readonly CFG="$TEST_CFG"|' \
    -e '/^case "\${1:-}" in$/,$d' "$script" > "$fixture/lib.sh"
source "$fixture/lib.sh"
set +e
is_protocol_installed() { return 1; }
create_server_scripts

fail() { echo "FAIL: $*"; exit 1; }
grep -q '__XRAY_PROTOCOLS__\|__SINGBOX_PROTOCOLS__' "$fixture/watchdog.sh" && fail "协议列表占位符未替换"
bash -n "$fixture/watchdog.sh" || fail "watchdog.sh 语法错误"

# 只取出 get_all_services，并让它读取测试数据库。
awk 'index($0, "get_all_services() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$fixture/watchdog.sh" \
    > "$fixture/services.sh"
services() {
    echo "$1" > "$fixture/db.json"
    env CFG="$fixture" bash -c 'source "$1"; get_all_services' _ "$fixture/services.sh"
}

out=$(services '{"xray":{"snell-v6":{"port":1}},"singbox":{"vless":{"port":2}}}')
[[ "$out" != *vless-reality* ]] || fail "只有 snell-v6 时不应守护 vless-reality: $out"
[[ "$out" == *vless-singbox:sing-box* ]] || fail "应守护 vless-singbox: $out"

out=$(services '{"xray":{"snell-v6":{"port":1},"vless":{"port":2}},"singbox":{}}')
[[ "$out" == *vless-reality:xray* ]] || fail "有 vless 时应守护 vless-reality: $out"
[[ "$out" != *vless-singbox* ]] || fail "sing-box 无协议时不应守护: $out"

out=$(services '{"xray":{},"singbox":{}}')
[[ -z "${out// /}" ]] || fail "无协议时不应守护任何服务: $out"
echo "看门狗协议过滤测试通过"
