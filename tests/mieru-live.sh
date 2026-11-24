#!/usr/bin/env bash
# 真实 mita / mieru 测试：用脚本生成的配置、导入脚本和 systemd unit 启动 mita，
# 再用脚本生成的分享链接参数配置 mieru 客户端，经 SOCKS5 访问本地 HTTP 服务。
# 需要 root（或免密 sudo）和 systemd；只在提供 MITA_TEST_BIN 和 MIERU_TEST_BIN 时运行。
set -e
if [[ -z "${MITA_TEST_BIN:-}" || -z "${MIERU_TEST_BIN:-}" ]]; then
    [[ -n "${CI:-}" ]] && { echo "FAIL: CI 中必须提供 MITA_TEST_BIN 和 MIERU_TEST_BIN"; exit 1; }
    echo "SKIP mieru live test (MITA_TEST_BIN / MIERU_TEST_BIN not set)"; exit 0
fi
if [[ $EUID -ne 0 ]]; then
    exec sudo -n -E bash "$0" "$@"
fi
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
chmod 755 "$fixture"
CFG="$fixture/cfg"
mkdir -p "$CFG" "$fixture/home"
pids=()
cleanup() {
    HOME="$fixture/home" "$MIERU_TEST_BIN" stop >/dev/null 2>&1 || true
    systemctl stop vless-mieru >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/vless-mieru.service; systemctl daemon-reload || true
    for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
    rm -rf "$fixture" /etc/mita /var/lib/mita /var/run/mita
}
trap cleanup EXIT
fail() {
    echo "FAIL: $*"
    systemctl status vless-mieru --no-pager -l 2>&1 | tail -30 || true
    journalctl -u vless-mieru --no-pager -n 40 2>&1 || true
    exit 1
}
for fn in _ensure_mita_user gen_mieru_server_config gen_mieru_apply_script _write_mieru_service gen_mieru_link urlencode get_ip_suffix; do
    eval "$(awk -v fn="$fn" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"
done
_err() { echo "err: $*" >&2; }
register_protocol() { :; }
build_config() { :; }
_save_join_info() { :; }

install -m 755 "$MITA_TEST_BIN" /usr/local/bin/mita
_ensure_mita_user || fail "创建 mita 用户或目录失败"
id mita >/dev/null || fail "没有 mita 用户"

port=38461 user=ci-user pass='p@ss+word=1'
gen_mieru_server_config "$user" "$pass" "$port" || fail "生成配置失败"
DISTRO=debian _write_mieru_service vless-mieru
systemctl daemon-reload
systemctl start vless-mieru || fail "vless-mieru 启动失败"
[[ "$(systemctl show -p User --value vless-mieru)" == mita ]] || fail "服务没有以 mita 用户运行"
mita_pid=$(systemctl show -p MainPID --value vless-mieru)
[[ "$(ps -o user= -p "$mita_pid" | tr -d ' ')" == mita ]] || fail "mita 进程不是 mita 用户"
/usr/local/bin/mita status 2>&1 | grep -q RUNNING || fail "mita 代理未运行"
ss -ltn | grep -q ":$port " || fail "mita 没有监听 TCP $port"

# 重启服务应重新导入配置并保持运行（开机、升级脚本后 start_services 都会重启）。
systemctl restart vless-mieru || fail "vless-mieru 重启失败"
/usr/local/bin/mita status 2>&1 | grep -q RUNNING || fail "重启后 mita 代理未运行"

# 分享链接能被官方客户端解析，且字段正确。
link=$(gen_mieru_link 127.0.0.1 "$port" "$user" "$pass" CI)
explained=$(HOME="$fixture/home" "$MIERU_TEST_BIN" explain config "$link" 2>&1) || fail "mieru 无法解析分享链接: $explained"
grep -q '"name": *"ci-user"' <<<"$explained" || fail "解析出的用户名不对: $explained"
grep -q '"password": *"p@ss+word=1"' <<<"$explained" || fail "解析出的密码不对: $explained"
grep -q "\"port\": *$port" <<<"$explained" || fail "解析出的端口不对: $explained"

# 客户端经 mita 代理访问本地 HTTP 服务。
echo mieru-ok > "$fixture/ok.txt"
python3 -m http.server 38462 --bind 127.0.0.1 --directory "$fixture" > "$fixture/http.log" 2>&1 &
pids+=("$!")
jq -n --arg u "$user" --arg p "$pass" --argjson port "$port" '{
  profiles: [{profileName: "default", user: {name: $u, password: $p},
    servers: [{ipAddress: "127.0.0.1", portBindings: [{port: $port, protocol: "TCP"}]}],
    mtu: 1400, multiplexing: {level: "MULTIPLEXING_LOW"}}],
  activeProfile: "default", rpcPort: 38463, socks5Port: 38464, loggingLevel: "INFO"}' > "$fixture/client.json"
HOME="$fixture/home" "$MIERU_TEST_BIN" apply config "$fixture/client.json" || fail "客户端配置无效"
HOME="$fixture/home" "$MIERU_TEST_BIN" start || fail "客户端启动失败"
body=""
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    body=$(curl -fsS --max-time 5 --socks5-hostname 127.0.0.1:38464 http://127.0.0.1:38462/ok.txt 2>/dev/null) && break
    sleep 1
done
[[ "$body" == mieru-ok ]] || fail "经 Mieru 代理访问失败"

# 错误密码不能连通。
jq --arg p wrong-password '.profiles[0].user.password = $p' "$fixture/client.json" > "$fixture/bad.json"
HOME="$fixture/home" "$MIERU_TEST_BIN" stop >/dev/null 2>&1 || true
HOME="$fixture/home" "$MIERU_TEST_BIN" apply config "$fixture/bad.json" || fail "客户端配置无效"
HOME="$fixture/home" "$MIERU_TEST_BIN" start || fail "客户端启动失败"
if curl -fsS --max-time 5 --socks5-hostname 127.0.0.1:38464 http://127.0.0.1:38462/ok.txt >/dev/null 2>&1; then
    fail "错误密码仍能连通"
fi
echo 'PASS real mita runs as the mita user from the generated unit and serves a mieru client'
