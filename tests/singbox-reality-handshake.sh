#!/usr/bin/env bash
# sing-box 接管 VLESS Reality 时，握手目标必须与 Xray 的 Reality dest 一致。
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
_info() { :; }; _warn() { :; }; _ok() { :; }; _err() { echo "$*" >&2; }
_listen_addr() { echo "::"; }
_ensure_nginx_https_for_reality() { echo "$1" > "$fixture/nginx_called"; }
real_cert=false
_is_real_cert() { [[ "$real_cert" == true ]]; }

cat > "$fixture/db.json" <<'JSON'
{"xray":{},"singbox":{"vless":{"port":29541,"uuid":"11111111-1111-1111-1111-111111111111",
 "private_key":"PRIV","public_key":"PUB","short_id":"ab","sni":"node.example.com","security_mode":"reality"}},
 "routing_rules":[]}
JSON

fail() { echo "FAIL: $*"; exit 1; }
handshake() { jq -c '.inbounds[] | select(.type=="vless") | .tls.reality.handshake' "$fixture/singbox.json"; }

# 非真实证书：握手到 sni:443
echo "node.example.com" > "$fixture/cert_domain"
generate_singbox_config >/dev/null 2>"$fixture/err" || { cat "$fixture/err"; fail "生成失败（自签名）"; }
[[ "$(handshake)" == '{"server":"node.example.com","server_port":443}' ]] || fail "自签名模式握手目标错误: $(handshake)"
[[ ! -f "$fixture/nginx_called" ]] || fail "自签名模式不应配置 Nginx"

# 真实证书且 sni 等于证书域名：握手到本机 Nginx
real_cert=true
generate_singbox_config >/dev/null 2>"$fixture/err" || { cat "$fixture/err"; fail "生成失败（真实证书）"; }
[[ "$(handshake)" == '{"server":"127.0.0.1","server_port":8443}' ]] || fail "真实证书模式握手目标错误: $(handshake)"
[[ "$(cat "$fixture/nginx_called")" == node.example.com ]] || fail "真实证书模式未确保 Nginx HTTPS 监听"

# 真实证书但 sni 是别的站点：仍握手到 sni:443
rm -f "$fixture/nginx_called"
echo "other.example.com" > "$fixture/cert_domain"
generate_singbox_config >/dev/null 2>"$fixture/err" || { cat "$fixture/err"; fail "生成失败（sni 不同）"; }
[[ "$(handshake)" == '{"server":"node.example.com","server_port":443}' ]] || fail "sni 不同时握手目标错误: $(handshake)"
echo "sing-box Reality 握手目标测试通过"
