#!/usr/bin/env bash
# Hysteria2 使用 UDP，可与只用 TCP 的协议共用同一端口号；UDP 之间仍互斥。
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
export TEST_CFG="$fixture"
sed -e 's|^readonly CFG="/etc/vless-reality"$|readonly CFG="$TEST_CFG"|' \
    -e '/^case "\${1:-}" in$/,$d' "$script" > "$fixture/lib.sh"
source "$fixture/lib.sh"
set +e
fail() { echo "FAIL: $*"; exit 1; }
_info() { :; }; _ok() { :; }; _line() { :; }
_warn() { echo "warn: $*" >&2; }; _err() { echo "err: $*" >&2; }
_listen_addr() { echo "::"; }
get_connection_addresses() { echo '203.0.113.7|'; }
get_ip_country() { echo JP; }
get_all_external_links() { :; }
netstat() { :; }
# 系统上 TCP 5555 被其他程序占用，UDP 没有占用。
ss() { case "$1" in -tln|-tuln) echo 'LISTEN 0 4096 0.0.0.0:5555 0.0.0.0:*' ;; esac; }

cat > "$fixture/db.json" <<'JSON'
{"xray":{"vless":{"port":443,"uuid":"11111111-1111-1111-1111-111111111111","sni":"www.example.com","public_key":"PUB","short_id":"ab"},
         "ss2022":{"port":8388,"method":"2022-blake3-aes-128-gcm","password":"c3NzcGFzc3dvcmQxMjM0NQ=="}},
 "singbox":{"tuic":{"port":9000,"uuid":"22222222-2222-2222-2222-222222222222","password":"tuicpass","sni":"www.example.com"},
            "hy2":{"port":7000,"password":"hy2pass","sni":"www.example.com","obfs_password":"obfs-secret"}},
 "routing_rules":[]}
JSON

# 1. 端口冲突只看传输层是否重叠。
check_port_conflict 443 hy2 singbox >/dev/null || fail "Hysteria2(UDP) 不应与 VLESS(TCP) 端口冲突"
check_port_conflict 9000 hy2 singbox >/dev/null && fail "Hysteria2 与 TUIC 都用 UDP，应冲突"
check_port_conflict 8388 hy2 singbox >/dev/null && fail "SS2022 同时用 TCP/UDP，应与 Hysteria2 冲突"
check_port_conflict 7000 anytls singbox >/dev/null || fail "AnyTLS(TCP) 不应与 Hysteria2(UDP) 冲突"
check_port_conflict 7000 vless-vision xray >/dev/null || fail "VLESS-Vision(TCP) 不应与 Hysteria2(UDP) 冲突"
check_port_conflict 443 trojan xray >/dev/null && fail "Trojan 与 VLESS 都用 TCP，应冲突"
check_port_conflict 7000 socks xray >/dev/null && fail "SOCKS5 含 UDP，应与 Hysteria2 冲突"
is_internal_port_occupied 443 hy2 >/dev/null && fail "带协议检查时 443 不应算作 Hysteria2 的占用"
[[ "$(is_internal_port_occupied 443)" == vless ]] || fail "不带协议时仍按原逻辑报告占用"
[[ "$(is_internal_port_occupied 9000 hy2)" == tuic ]] || fail "UDP 协议之间仍应报告占用"

# 2. 安装时输入端口：Hysteria2 只检查 UDP 占用，TCP 协议仍检查 TCP。
recommend_port() { echo 12345; }
out=$(INSTALL_MODE=new ask_port hy2 <<<"443" 2>"$fixture/err") || fail "Hysteria2 选 443 被拒绝: $(cat "$fixture/err")"
[[ "$out" == 443 ]] || fail "Hysteria2 端口返回值不对: $out"
out=$(INSTALL_MODE=new ask_port hy2 <<<"5555" 2>"$fixture/err") || fail "Hysteria2 选 TCP 已占用的 5555 被拒绝"
[[ "$out" == 5555 ]] || fail "Hysteria2 不应因 TCP 占用而提示"
grep -q '系统占用' "$fixture/err" && fail "Hysteria2 不应提示系统占用"
out=$(INSTALL_MODE=new ask_port trojan <<<$'5555\nn\nq' 2>"$fixture/err")
grep -q '端口 5555 系统占用中' "$fixture/err" || fail "TCP 协议仍应检查 TCP 占用"
out=$(INSTALL_MODE=new ask_port hy2 <<<$'9000\nq' 2>&1)
grep -q '已被协议 tuic 占用' <<<"$out" || fail "Hysteria2 与 TUIC 同端口仍应拒绝"

echo 'PASS Hysteria2 (UDP) shares port numbers with TCP-only protocols; UDP and TCP+UDP protocols still conflict'
