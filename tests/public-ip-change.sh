#!/usr/bin/env bash
# 公网 IP 变化后，数据库、JOIN 文件和订阅文件都应更新；探测异常时不得改动。
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
export TEST_CFG="$fixture/cfg"
mkdir -p "$TEST_CFG"
# 只加载函数定义：CFG 指向临时目录，去掉末尾的命令行入口。
sed -e 's|^readonly CFG="/etc/vless-reality"$|readonly CFG="$TEST_CFG"|' \
    -e '/^case "\${1:-}" in$/,$d' "$script" > "$fixture/lib.sh"
source "$fixture/lib.sh"
set +e
eval "real$(declare -f _probe_public_ip_from)"
_info() { :; }; _warn() { :; }; _ok() { :; }; _err() { echo "$*" >&2; }
_log() { echo "$*" >> "$fixture/log"; }
generate_sub_files() { echo regenerated >> "$fixture/sub_regen"; }

OLD=203.0.113.7
NEW=198.51.100.9
# 探测结果：probe[族,站点序号]，空值表示探测失败
declare -A probe
_probe_public_ip_from() {
    local idx=0 e
    for e in $PUBLIC_IP_ENDPOINTS; do [[ "$e" == "$2" ]] && break; idx=$((idx + 1)); done
    local v="${probe[$1,$idx]}"
    [[ -n "$v" ]] || return 1
    printf '%s\n' "$v"
}
set_probe() { probe[4,0]="$1"; probe[4,1]="$2"; probe[6,0]=""; probe[6,1]=""; _CACHED_IPV4=""; _CACHED_IPV6=""; }

fail() { echo "FAIL: $*"; exit 1; }
reset_fixture() {
    rm -rf "$CFG"; mkdir -p "$CFG"
    cat > "$CFG/db.json" <<JSON
{"version":"4.0.0","meta":{},
 "xray":{"vless":{"port":443,"ipv4":"$OLD","ipv6":""},
         "vless-ws":[{"port":8080,"ipv4":"$OLD"},{"port":8081,"ipv4":"11.2.3.4"}]},
 "singbox":{"hy2":{"port":8443,"ipv4":"$OLD"}}}
JSON
    local data="REALITY|$OLD|443|uuid|pk|sid|www.example.com"
    {
        echo "# IPv4"
        echo "JOIN_V4=$(printf '%s' "$data" | base64 | tr -d '\n')"
        echo "VLESS_V4=vless://uuid@$OLD:443?security=reality#node"
        echo "NOTE=keep 2$OLD and ${OLD}5"
    } > "$CFG/vless.join"
    cp "$CFG/vless.join" "$CFG/join.txt"
    printf 'sub_uuid=0123456789abcdef0123\nsub_port=8443\nsub_domain=\nsub_https=false\n' > "$CFG/sub.info"
    rm -f "$fixture/sub_regen"
}
db_ips() { jq -r '[(.xray,.singbox)|..|objects|.ipv4? // empty]|join(",")' "$CFG/db.json"; }
join_v4() { grep '^JOIN_V4=' "$CFG/vless.join" | cut -d= -f2- | base64 -d; }

# 1. 两个探测站一致：确认变更
reset_fixture
set_probe "$NEW" "$NEW"
out=$(check_public_ip_change) || fail "检测失败"
[[ "$out" == *"$OLD -> $NEW"* ]] || fail "未报告变更: $out"
[[ "$(db_ips)" == "$NEW,$NEW,11.2.3.4,$NEW" ]] || fail "数据库地址错误: $(db_ips)"
[[ "$(join_v4)" == "REALITY|$NEW|443|uuid|pk|sid|www.example.com" ]] || fail "JOIN_V4 未更新: $(join_v4)"
grep -q "vless://uuid@$NEW:443" "$CFG/vless.join" || fail "分享链接未更新"
grep -q "NOTE=keep 2$OLD and ${OLD}5" "$CFG/vless.join" || fail "误替换了相邻地址"
grep -q "vless://uuid@$NEW:443" "$CFG/join.txt" || fail "join.txt 未更新"
[[ -f "$fixture/sub_regen" ]] || fail "订阅文件未重新生成"
[[ "$(cat "$CFG/public_ip")" == "$NEW|" ]] || fail "基准地址未更新"
grep -q "http://$NEW:8443/sub/0123456789abcdef0123/clash" "$CFG/ip-changed.notice" || fail "未提示新的订阅链接"
[[ "$(stat -c %a "$CFG/vless.join" 2>/dev/null || stat -f %Lp "$CFG/vless.join")" == 600 ]] || fail "JOIN 文件权限应为 600"

# 2. 再次检测，地址未变：不重复处理
rm -f "$fixture/sub_regen"
out=$(check_public_ip_change)
[[ -z "$out" && ! -f "$fixture/sub_regen" ]] || fail "地址未变时不应处理: $out"

# 3. 探测失败：不改任何东西
reset_fixture
printf '%s|\n' "$OLD" > "$CFG/public_ip"
set_probe "" ""
check_public_ip_change >/dev/null
[[ "$(db_ips)" == "$OLD,$OLD,11.2.3.4,$OLD" ]] || fail "探测失败时改动了数据库"
[[ "$(join_v4)" == *"|$OLD|"* ]] || fail "探测失败时改动了 JOIN"
[[ ! -f "$fixture/sub_regen" && ! -f "$CFG/ip-changed.notice" ]] || fail "探测失败时不应刷新订阅或提示"

# 4. 两个探测站不一致：第一次只记候选，第二次相同才确认
set_probe "$NEW" "192.0.2.50"
check_public_ip_change >/dev/null
[[ "$(db_ips)" == "$OLD,$OLD,11.2.3.4,$OLD" ]] || fail "未确认时改动了数据库"
[[ "$(cat "$CFG/public_ip.pending")" == "4|$NEW" ]] || fail "未记录候选地址"
set_probe "" "$NEW"
check_public_ip_change >/dev/null
[[ "$(db_ips)" == "$NEW,$NEW,11.2.3.4,$NEW" ]] || fail "第二次一致后应确认变更"
[[ ! -f "$CFG/public_ip.pending" ]] || fail "确认后应清除候选地址"

# 5. 自动检测关闭：不改任何东西
reset_fixture
touch "$CFG/ip-check.disabled"
set_probe "$NEW" "$NEW"
check_public_ip_change >/dev/null
[[ "$(db_ips)" == "$OLD,$OLD,11.2.3.4,$OLD" ]] || fail "关闭检测后仍改动了数据库"

# 6. 探测站返回无效值时视为探测失败
curl() { printf '%s\n' "<html>blocked</html>"; }
real_probe_public_ip_from 4 https://ip.sb >/dev/null && fail "无效探测值未被拒绝"
curl() { printf '%s\n' "[$NEW]"; }
[[ "$(real_probe_public_ip_from 4 https://ip.sb)" == "$NEW" ]] || fail "合法探测值被拒绝"
unset -f curl

# 7. 定时任务每 30 分钟执行 --check-ip，带 check-ip 标签
get_bash_interpreter() { echo /bin/bash; }
cmd=$(build_cron_command "*/30 * * * *" /usr/local/bin/vless-server.sh "--check-ip" "$CFG/ip-check.log")
[[ "$cmd" == "*/30 * * * * "*"--check-ip >> "* ]] || fail "定时任务命令错误: $cmd"
grep -q 'remove_cron_entry "check-ip"' "$script" || fail "卸载时未移除 check-ip 定时任务"
echo "公网 IP 变更检测测试通过"
