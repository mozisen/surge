#!/usr/bin/env bash
# Mieru 安装：菜单第 16 项、mita 配置、导入脚本、服务文件、分享链接和 Clash 订阅。
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
load() { eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$script")"; }
for fn in select_protocol gen_mieru_server_config gen_mieru_apply_script _write_mieru_service \
          gen_mieru_link urlencode get_ip_suffix gen_clash_sub get_protocol_name recommend_port; do
    load "$fn"
done
fail() { echo "FAIL: $*"; exit 1; }
command_not_found_handle() { return 0; }
CFG="$fixture/cfg"
mkdir -p "$CFG"

# 注册表：Mieru 是独立协议，服务名 vless-mieru，进程 mita。
registry=$(grep -E '^(STANDALONE_PROTOCOLS=|PROTO_SVC\[mieru\]|    \[vless-mieru\])' "$script")
grep -q '^STANDALONE_PROTOCOLS=".* mieru' <<<"$registry" || fail "mieru 不在独立协议列表"
grep -q 'PROTO_SVC\[mieru\]="vless-mieru"; PROTO_KIND\[mieru\]="mieru"; PROTO_BIN\[mieru\]="mita"' <<<"$registry" || fail "mieru 服务注册不对"
grep -q '\[vless-mieru\]="mita"' <<<"$registry" || fail "缺少 mita 进程回退"
[[ "$(get_protocol_name mieru)" == Mieru ]] || fail "显示名不对"

# 菜单第 16 项选择 Mieru，提示范围为 0-16。
_line() { :; }
_item() { printf '%s %s\n' "$1" "$2"; }
menu=$(SELECTED_PROTOCOL=""; select_protocol <<<"16" 2>&1; echo "selected=$SELECTED_PROTOCOL")
grep -q '^16 Mieru' <<<"$menu" || fail "菜单缺少第 16 项 Mieru"
grep -q '^selected=mieru$' <<<"$menu" || fail "第 16 项没有选中 mieru"
grep -q 'read -rp "  选择协议 \[0-16\]: "' "$script" || fail "选择提示不是 [0-16]"

# 推荐端口为随机高位端口（mita 只接受 1025-65535）。
gen_port() { echo 34567; }
is_internal_port_occupied() { return 1; }
db_exists() { return 1; }
[[ "$(INSTALL_MODE=new recommend_port mieru)" == 34567 ]] || fail "推荐端口不是随机高位端口"

# 生成 mita 配置：TCP 端口、单用户、权限 600。
registered=""
register_protocol() { registered="$1|$2"; }
build_config() { local a=(); while (($#)); do a+=(--arg "$1" "$2"); shift 2; done; jq -cn "${a[@]}" '$ARGS.named'; }
_save_join_info() { printf '%s\n' "$@" > "$fixture/join-args"; : > "$CFG/mieru.join"; }
gen_mieru_server_config 'alice.01' 'p@ss+word=1' 23456
jq -e '. == {portBindings:[{port:23456,protocol:"TCP"}],users:[{name:"alice.01",password:"p@ss+word=1"}],loggingLevel:"WARN",mtu:1400}' \
    "$CFG/mieru.json" >/dev/null || fail "mita 配置内容不对: $(cat "$CFG/mieru.json")"
[[ "$(stat -c %a "$CFG/mieru.json" 2>/dev/null || stat -f %Lp "$CFG/mieru.json")" == 600 ]] || fail "配置文件权限不是 600"
[[ "${registered%%|*}" == mieru ]] || fail "没有登记 mieru"
jq -e '.username == "alice.01" and .password == "p@ss+word=1" and .port == "23456"' <<<"${registered#*|}" >/dev/null || fail "登记的字段不对"
[[ "$(sed -n 3p "$fixture/join-args")" == gen_mieru_link ]] || fail "JOIN 信息没有使用 gen_mieru_link"
[[ "$(cat "$CFG/role")" == server ]] || fail "没有写入 role"

# 导入脚本：等待守护进程、replace config、stop+start、确认 RUNNING。
apply="$CFG/mieru-apply.sh"
[[ -x "$apply" ]] || fail "导入脚本不可执行"
sh -n "$apply" || fail "导入脚本语法错误"
grep -qx "\$mita replace config \"$CFG/mieru.json\" || exit 1" "$apply" || fail "导入脚本没有 replace config"
grep -qx '$mita start || exit 1' "$apply" || fail "导入脚本没有启动代理"
grep -qx '$mita status 2>&1 | grep -q RUNNING' "$apply" || fail "导入脚本没有检查 RUNNING"
# 用假 mita 走一遍：守护进程第 2 次查询才就绪，最后状态为 RUNNING。
mkdir -p "$fixture/bin"
cat > "$fixture/bin/mita" <<EOF
#!/bin/sh
echo "\$*" >> "$fixture/mita-calls"
if [ "\$1" = status ]; then
    n=\$(cat "$fixture/n" 2>/dev/null || echo 0); n=\$((n + 1)); echo \$n > "$fixture/n"
    [ \$n -ge 2 ] || exit 1
    echo 'mita server status is "RUNNING"'
fi
exit 0
EOF
chmod +x "$fixture/bin/mita"
sed "s#^mita=/usr/local/bin/mita#mita=$fixture/bin/mita#; s#sleep 1#:#" "$apply" > "$fixture/apply-test.sh"
sh "$fixture/apply-test.sh" || fail "导入脚本执行失败"
[[ "$(cat "$fixture/mita-calls")" == "status
status
replace config $CFG/mieru.json
stop
start
status" ]] || fail "导入脚本调用顺序不对: $(cat "$fixture/mita-calls")"

# systemd：以 mita 用户运行，root 准备目录并导入配置。
mkdir -p "$fixture/etc/systemd/system" "$fixture/etc/init.d"
sed "s#/etc/systemd/system/#$fixture/etc/systemd/system/#; s#/etc/init.d/#$fixture/etc/init.d/#g" <<<"$(declare -f _write_mieru_service)" > "$fixture/svc.sh"
. "$fixture/svc.sh"
DISTRO=debian _write_mieru_service vless-mieru
unit="$fixture/etc/systemd/system/vless-mieru.service"
for line in User=mita Group=mita 'ExecStart=/usr/local/bin/mita run' "ExecStartPost=+/bin/sh $CFG/mieru-apply.sh" \
            'ExecStartPre=+/bin/mkdir -p /var/run/mita' 'ExecStartPre=+/bin/chown mita:mita /var/run/mita' \
            Restart=always 'WantedBy=multi-user.target'; do
    grep -qxF "$line" "$unit" || fail "systemd unit 缺少: $line"
done
DISTRO=alpine _write_mieru_service vless-mieru
rc="$fixture/etc/init.d/vless-mieru"
sh -n "$rc" || fail "OpenRC 脚本语法错误"
for line in 'command="/usr/local/bin/mita"' 'command_args="run"' 'command_user="mita:mita"' "start_post() { /bin/sh \"$CFG/mieru-apply.sh\"; }"; do
    grep -qxF "$line" "$rc" || fail "OpenRC 脚本缺少: $line"
done

# 分享链接：用户名密码做 URL 编码，带 profile；IPv6 加方括号。
link=$(gen_mieru_link 203.0.113.7 23456 'alice.01' 'p@ss+word=1' JP)
[[ "$link" == 'mierus://alice.01:p%40ss%2bword%3d1@203.0.113.7?mtu=1400&multiplexing=MULTIPLEXING_LOW&port=23456&profile=JP-Mieru-7&protocol=TCP' ]] || fail "分享链接不对: $link"
link6=$(gen_mieru_link '[2001:db8::1]' 23456 u p)
[[ "$link6" == 'mierus://u:p@[2001:db8::1]?mtu=1400&multiplexing=MULTIPLEXING_LOW&port=23456&profile=Mieru-v6&protocol=TCP' ]] || fail "IPv6 链接不对: $link6"
[[ "$(gen_mieru_link 2001:db8::1 1 u p)" == *'@[2001:db8::1]?'* ]] || fail "未加括号的 IPv6 没有补方括号"

# Clash 订阅：mihomo mieru 节点，用户名密码加引号。
get_installed_protocols() { echo mieru; }
get_connection_addresses() { echo '203.0.113.7|'; }
get_ip_country() { echo JP; }
get_all_external_links() { :; }
_get_master_port() { :; }
db_exists() { [[ "$1" == xray && "$2" == mieru ]]; }
db_get() { jq -n '{username:"alice.01",password:"p@ss+word=1",port:"23456"}'; }
sub=$(gen_clash_sub)
expected='  - name: "JP-Mieru-7"
    type: mieru
    server: "203.0.113.7"
    port: 23456
    transport: TCP
    udp: true
    username: "alice.01"
    password: "p@ss+word=1"
    multiplexing: MULTIPLEXING_LOW'
[[ "$sub" == *"$expected"* ]] || fail "Clash 订阅缺少 Mieru 节点: $sub"
grep -qx '      - "JP-Mieru-7"' <<<"$sub" || fail "Mieru 节点未加入策略组"

# 卸载：单独卸载、重装和完整卸载都清理 mita 配置（含密码）。
[[ $(grep -cF 'mieru) rm -f "$CFG/mieru.json" "$CFG/mieru-apply.sh"; rm -rf /etc/mita /var/lib/mita /var/run/mita ;;' "$script") -eq 2 ]] || fail "协议卸载未清理 mita 配置"
grep -qxF '    rm -rf /etc/mita /var/lib/mita /var/run/mita 2>/dev/null' "$script" || fail "完整卸载未清理 mita 配置"
echo 'PASS Mieru menu item, mita config, apply script, services, share link, Clash subscription and cleanup'
