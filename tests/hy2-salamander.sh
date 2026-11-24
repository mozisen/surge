#!/usr/bin/env bash
# Hysteria2 Salamander 混淆：写入 sing-box 入站、分享链接、节点信息和订阅。
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
get_ipv4() { echo 203.0.113.7; }
get_ipv6() { :; }
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

# 3. sing-box 入站：有混淆密码时写入 salamander，没有时不写。
mkdir -p "$fixture/certs/hy2" "$fixture/certs/tuic"
openssl req -x509 -nodes -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -keyout "$fixture/certs/hy2/server.key" \
    -out "$fixture/certs/hy2/server.crt" -subj /CN=www.example.com -days 1 >/dev/null 2>&1
cp "$fixture/certs/hy2/server."* "$fixture/certs/tuic/"
generate_singbox_config >/dev/null 2>"$fixture/err" || { cat "$fixture/err"; fail "sing-box 配置生成失败"; }
jq -e '.inbounds[] | select(.type=="hysteria2") | .obfs == {type:"salamander",password:"obfs-secret"}' "$fixture/singbox.json" >/dev/null \
    || fail "sing-box 入站缺少 salamander: $(jq -c '.inbounds[] | select(.type=="hysteria2")' "$fixture/singbox.json")"
if [[ -n "${SINGBOX_TEST_BIN:-}" ]]; then
    "$SINGBOX_TEST_BIN" check -c "$fixture/singbox.json" || fail "sing-box 不接受生成的混淆配置"
fi
jq '.singbox.hy2 |= del(.obfs_password)' "$fixture/db.json" > "$fixture/next" && mv "$fixture/next" "$fixture/db.json"
generate_singbox_config >/dev/null 2>&1 || fail "sing-box 配置生成失败（无混淆）"
jq -e '.inbounds[] | select(.type=="hysteria2") | has("obfs") | not' "$fixture/singbox.json" >/dev/null || fail "未启用混淆时不应写 obfs"
jq '.singbox.hy2.obfs_password = "obfs-secret"' "$fixture/db.json" > "$fixture/next" && mv "$fixture/next" "$fixture/db.json"

# 4. 分享链接。
[[ "$(gen_hy2_link 203.0.113.7 7000 hy2pass www.example.com JP)" == 'hysteria2://hy2pass@203.0.113.7:7000?sni=www.example.com&insecure=1#JP-Hysteria2-7' ]] || fail "无混淆链接变了"
[[ "$(gen_hy2_link 203.0.113.7 7000 hy2pass www.example.com JP 'ob@fs')" == 'hysteria2://hy2pass@203.0.113.7:7000?sni=www.example.com&insecure=1&obfs=salamander&obfs-password=ob%40fs#JP-Hysteria2-7' ]] || fail "混淆链接不对"

# 5. 节点信息：Surge / Loon / Clash Meta 都带混淆参数。
info=$(show_single_protocol_info hy2 false 2>/dev/null </dev/null | sed 's/\x1b\[[0-9;]*m//g')
grep -q 'hysteria2://hy2pass@203.0.113.7:7000?sni=www.example.com&insecure=1&obfs=salamander&obfs-password=obfs-secret#' <<<"$info" || fail "节点信息链接缺少混淆: $(grep -i 'hysteria2' <<<"$info")"
grep -q '= hysteria2, 203.0.113.7, 7000, password=hy2pass, sni=www.example.com, skip-cert-verify=true, salamander-password=obfs-secret$' <<<"$info" || fail "Surge 配置缺少 salamander-password"
grep -q '= Hysteria2, 203.0.113.7, 7000, "hy2pass", udp=true, sni=www.example.com, skip-cert-verify=true, salamander-password=obfs-secret$' <<<"$info" || fail "Loon 配置缺少 salamander-password"
grep -q '^ *obfs: salamander$' <<<"$info" || fail "Clash 配置缺少 obfs"
grep -q '^ *obfs-password: "obfs-secret"$' <<<"$info" || fail "Clash 配置缺少 obfs-password"

# 6. 订阅。
surge=$(gen_surge_sub)
grep -q '= hysteria2, 203.0.113.7, 7000, password=hy2pass, sni=www.example.com, skip-cert-verify=true, salamander-password=obfs-secret$' <<<"$surge" || fail "Surge 订阅缺少混淆"
clash=$(gen_clash_sub)
grep -A8 'type: hysteria2' <<<"$clash" | grep -q '^    obfs: salamander$' || fail "Clash 订阅缺少 obfs"
grep -A9 'type: hysteria2' <<<"$clash" | grep -q '^    obfs-password: "obfs-secret"$' || fail "Clash 订阅缺少 obfs-password"
v2=$(gen_v2ray_sub | base64 -d 2>/dev/null || gen_v2ray_sub | base64 -D)
grep -q '&obfs=salamander&obfs-password=obfs-secret#' <<<"$v2" || fail "通用订阅缺少混淆"
# 未启用混淆的节点各处都不带混淆参数。
jq '.singbox.hy2 |= del(.obfs_password)' "$fixture/db.json" > "$fixture/next" && mv "$fixture/next" "$fixture/db.json"
grep -q salamander <<<"$(gen_surge_sub; gen_clash_sub; show_single_protocol_info hy2 false 2>/dev/null </dev/null)" && fail "未启用混淆时不应输出混淆参数"
echo 'PASS Salamander obfuscation reaches sing-box, share links, node info and all subscriptions; absent when disabled'
