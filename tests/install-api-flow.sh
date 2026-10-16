#!/usr/bin/env bash
# 面板安装接口走真实安装流程：加载整份脚本（数据目录改到临时目录），只把下载、系统服务和网络探测换成桩，
# 通过 --api install 安装 VLESS-Vision（自签证书），并验证提问全部由参数回答、失败时恢复。需要 Bash 4.1+。
set -e -o pipefail
fail() { echo "FAIL line $1"; exit 1; }
repo=$(cd "$(dirname "$0")/.." && pwd)
if (( BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1] < 401 )); then
    echo 'SKIP install API flow (needs Bash 4.1+)'
    [[ "${CI:-}" != true ]] || fail $LINENO
    exit 0
fi
command -v openssl >/dev/null || { echo 'SKIP install API flow (needs openssl)'; [[ "${CI:-}" != true ]] || fail $LINENO; exit 0; }
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
line=$(grep -n '^# 命令行参数处理' "$repo/vless-server.sh" | cut -d: -f1)
head -n $((line - 1)) "$repo/vless-server.sh" | sed 's|^readonly CFG="/etc/vless-reality"$|readonly CFG="$VAIO_TEST_CFG"|' > "$fixture/lib.sh"
grep -q 'VAIO_TEST_CFG' "$fixture/lib.sh" || fail $LINENO
export VAIO_TEST_CFG="$fixture/cfg"
mkdir -p "$VAIO_TEST_CFG"
# shellcheck disable=SC1091
source "$fixture/lib.sh"
set +e
# 桩：不下载、不碰系统服务与网络
check_dependencies() { :; }; install_deps() { :; }; install_xray() { :; }
ensure_dual_stack_listen() { :; }; show_install_network_environment() { :; }
create_server_scripts() { :; }; create_service() { :; }; create_shortcut() { :; }
start_services() { echo start >> "$fixture/svc"; }
svc() { echo "$*" >> "$fixture/svc"; }
show_single_protocol_info() { :; }; _header() { :; }; sync_time() { :; }; _log() { :; }
get_ipv4() { echo 203.0.113.10; }; get_ipv6() { :; }
ss() { :; }; netstat() { :; }
_db_lock_acquire() { :; }; _db_lock_release() { :; }
command -v flock >/dev/null 2>&1 || { _api_txn_lock() { :; }; _api_txn_unlock() { :; }; }
call() { _api_dispatch <<< "$1" > "$fixture/out" 2>"$fixture/err" || true; jq -e . "$fixture/out" >/dev/null || { cat "$fixture/out" "$fixture/err"; fail "$2"; }; }
out() { jq -r "$1" "$fixture/out"; }
install_req() { jq -nc --arg id "$1" --argjson a "$2" '{api_version:1,request_id:$id,action:"install",params:{protocol:"vless-vision",core:"xray",answers:$a}}'; }

call '{"api_version":1,"request_id":"cap","action":"capabilities"}' $LINENO
[[ "$(out '(.data.actions | index("install") != null) and .data.install_api.version == 1 and (.data.install_api.schema.protocols["vless-vision"].cores == ["xray"])')" == true ]] || fail $LINENO
echo 'PASS capabilities declare the install API and its field schema'

# 1. 自签证书 + 自定义 SNI + 指定端口
call "$(install_req v1 '{"port":24443,"sni":"cdn.example.com"}')" $LINENO
[[ "$(out '"\(.status)|\(.data.target.port)"')" == "succeeded|24443" ]] || { cat "$fixture/out"; tail -30 "$CFG/api-backups/v1/log"; fail $LINENO; }
entry=$(jq -c '.xray["vless-vision"] | if type == "array" then .[] else . end | select(.port == 24443)' "$DB_FILE")
[[ "$(jq -r .sni <<< "$entry")" == cdn.example.com ]] || fail $LINENO
[[ -s "$CFG/certs/server.crt" && -s "$CFG/certs/server.key" ]] || fail $LINENO
grep -q 'SNI: cdn.example.com' "$CFG/api-backups/v1/log" || fail $LINENO
! grep -q 'install.confirm\|安装参数无效' "$CFG/api-backups/v1/log" || fail $LINENO
echo 'PASS VLESS-Vision installs through the menu flow with a self-signed certificate, custom SNI and port'

# 2. 第二个实例：默认（随机 SNI，推荐端口），已有自签证书保持不变
cert=$(openssl x509 -in "$CFG/certs/server.crt" -noout -fingerprint)
call "$(install_req v2 '{"port":24444}')" $LINENO
[[ "$(out .status)" == succeeded ]] || { cat "$fixture/out"; tail -30 "$CFG/api-backups/v2/log"; fail $LINENO; }
[[ "$(jq '[.xray["vless-vision"] | if type == "array" then .[] else . end] | length' "$DB_FILE")" == 2 ]] || fail $LINENO
[[ "$(openssl x509 -in "$CFG/certs/server.crt" -noout -fingerprint)" == "$cert" ]] || fail $LINENO
echo 'PASS a second instance is added and keeps the existing certificate'

# 3. 端口已被本协议占用：重复提问即中止，数据恢复原样
before=$(cat "$DB_FILE")
call "$(install_req v3 '{"port":24443}')" $LINENO
[[ "$(out '"\(.status)|\(.code)|\(.data.field)|\(.data.rolled_back)"')" == "failed|invalid_answer|port|true" ]] || { cat "$fixture/out"; tail -30 "$CFG/api-backups/v3/log"; fail $LINENO; }
[[ "$(cat "$DB_FILE")" == "$before" ]] || fail $LINENO
[[ "$(openssl x509 -in "$CFG/certs/server.crt" -noout -fingerprint)" == "$cert" ]] || fail $LINENO
echo 'PASS an occupied port fails without hanging and restores the previous state'

# 4. 已装 Trojan（443 主协议）：默认换端口安装，Trojan 保留
jq '.xray.trojan = [{"port":443,"password":"T_SECRET","sni":"t.example.com","users":[]}]' "$DB_FILE" > "$DB_FILE.t" && mv "$DB_FILE.t" "$DB_FILE"
call "$(install_req v4 '{"port":24445}')" $LINENO
[[ "$(out .status)" == succeeded ]] || { cat "$fixture/out"; tail -30 "$CFG/api-backups/v4/log"; fail $LINENO; }
[[ "$(jq -r '.xray.trojan[0].port' "$DB_FILE")" == 443 ]] || fail $LINENO
echo 'PASS an existing Trojan master is kept by default'
