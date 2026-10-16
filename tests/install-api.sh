#!/usr/bin/env bash
# 面板安装接口（--api install）与提问层 _ask：函数级隔离测试，安装流程本身用桩替代（真实流程见 install-api-flow.sh）。
set -e -o pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
fail() { echo "FAIL line $1"; exit 1; }
CFG="$fixture/cfg"; DB_FILE="$CFG/db.json"; VERSION=test
mkdir -p "$CFG/certs"
load() {
    local body
    body=$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1; if ($0 ~ /; }$/) {print; exit}} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")
    [[ -n "$body" ]] || { echo "missing $1"; exit 1; }
    eval "$body"
}
for fn in _ask _install_api_abort _api_reply _api_sha256 _api_account_store _api_txn_lock _api_txn_unlock \
    _api_install_schema _api_install_answers _api_install_paths _api_install_restore _api_install; do
    load "$fn"
done
if (( BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1] < 401 )) || ! command -v flock >/dev/null 2>&1; then
    _api_txn_lock() { :; }; _api_txn_unlock() { :; }
fi
_err() { echo "  ✗ $*" >&2; }
init_db() { echo '{"xray":{},"singbox":{}}' > "$DB_FILE"; }
db_list_ports() { jq -r --arg c "$1" --arg p "$2" '.[$c][$p] // empty | if type == "array" then .[] else . end | .port' "$DB_FILE"; }
svc() { echo "$*" >> "$fixture/svc"; }

# 1. 提问层：菜单模式等同 read；接口模式按 KEY 取答案、映射语义值、缺省为空、无效或重复提问即中止
_ask v port "prompt: " <<< "8443" 2>/dev/null
[[ "$v" == 8443 ]] || fail $LINENO
export VAIO_INSTALL_API=1 VAIO_INSTALL_ERROR="$fixture/error"
VAIO_ANSWERS='{"port":"2053","cert.mode":"self"}'
_VAIO_ASKED=""
_ask v port "prompt: " < /dev/null 2>/dev/null; [[ "$v" == 2053 ]] || fail $LINENO
_ask v cert.mode "prompt: " "acme=1 self=2" 2>/dev/null; [[ "$v" == 2 ]] || fail $LINENO
_ask v sni "prompt: " 2>/dev/null; [[ -z "$v" ]] || fail $LINENO
( _ask v port "again: " ) 2>/dev/null && fail $LINENO
[[ "$(cat "$fixture/error")" == "invalid_answer|port" ]] || fail $LINENO
rm -f "$fixture/error"
( VAIO_ANSWERS='{"cert.mode":"other"}'; _VAIO_ASKED=""; _ask v cert.mode "p: " "acme=1 self=2" ) 2>/dev/null && fail $LINENO
[[ "$(cat "$fixture/error")" == "invalid_answer|cert.mode" ]] || fail $LINENO
( VAIO_ANSWERS='{"cert.mode":"other"}'; _VAIO_ASKED=""; _ask v cert.mode "p: " "acme=1 self=2" ) 2>/dev/null || [[ $? == 97 ]] || fail $LINENO
unset VAIO_INSTALL_API VAIO_INSTALL_ERROR VAIO_ANSWERS
echo 'PASS _ask: menu read, mapped answers, empty default, invalid or repeated question aborts with exit 97'

# 2. 字段清单与答案校验
schema=$(_api_install_schema)
[[ "$(jq -c '.protocols["vless-vision"] | [.cores, [.fields[].key]]' <<< "$schema")" == '[["xray"],["port","cert.mode","cert.domain","sni","install.master_conflict"]]' ]] || fail $LINENO
check() { _api_install_answers "{\"params\":$1}" "$schema"; }
[[ "$(check '{"protocol":"vless-vision","core":"xray"}' | jq -c '.answers | [."cert.mode", ."sni.mode", ."cert.existing_self", ."install.confirm", has("port")]')" == '["self","random","keep","yes",false]' ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"xray","answers":{"port":8443,"sni":"a.example.com"}}' | jq -c '.answers | [.port, ."sni.mode", .sni]')" == '["8443","custom","a.example.com"]' ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"xray","answers":{"cert.mode":"acme","cert.domain":"x.example.com","sni":"ignored.example.com"}}' | jq -c '.answers | [."cert.existing_self", ."cert.domain", has("sni")]')" == '["replace","x.example.com",false]' ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"xray","answers":{"cert.mode":"acme"}}' | jq -c .)" == '{"error":"missing_answer","field":"cert.domain"}' ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"xray","answers":{"port":"443"}}' | jq -r .field)" == port ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"xray","answers":{"port":70000}}' | jq -r .field)" == port ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"xray","answers":{"sni":"a..b"}}' | jq -r .field)" == sni ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"xray","answers":{"sni":"a.b;reboot"}}' | jq -r .field)" == sni ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"xray","answers":{"x":1}}' | jq -r .field)" == x ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"singbox"}' | jq -r .error)" == unsupported_core ]] || fail $LINENO
[[ "$(check '{"protocol":"hy2","core":"singbox"}' | jq -r .error)" == unsupported_protocol ]] || fail $LINENO
[[ "$(check '{"protocol":"vless-vision","core":"xray","extra":1}' | jq -r .error)" == invalid_request ]] || fail $LINENO
echo 'PASS install schema and answer validation: defaults, mapping, conditional fields, unknown or invalid values'

# 3. 接口事务：桩安装流程，按 MODE 成功、失败或中止
MODE=ok
do_install_server() {
    [[ "$VAIO_INSTALL_API" == 1 && "$VAIO_INSTALL_PROTOCOL" == vless-vision && "$VAIO_INSTALL_CORE" == xray ]] || return 1
    read -r _ && return 1                      # 标准输入必须为空
    echo "$VAIO_ANSWERS" > "$fixture/answers"
    echo '{"new":1}' > "$CFG/config.json"
    echo new-cert > "$CFG/certs/server.crt"
    echo leftover > "$CFG/vless-vision.join"
    jq '.xray["vless-vision"] = [{"port":2053}]' "$DB_FILE" > "$DB_FILE.t" && mv "$DB_FILE.t" "$DB_FILE"
    case "$MODE" in
        ok) printf 'ok|vless-vision|2053\n' > "$VAIO_INSTALL_RESULT" ;;
        abort) _install_api_abort invalid_answer port ;;
        fake) printf 'ok|vless-vision|9999\n' > "$VAIO_INSTALL_RESULT" ;;
        *) _err "Xray 安装失败"; return 0 ;;
    esac
}
reset_cfg() {
    rm -rf "$CFG"; mkdir -p "$CFG/certs"
    echo '{"xray":{"trojan":[{"port":443}]},"singbox":{}}' > "$DB_FILE"
    echo '{"old":1}' > "$CFG/config.json"
    echo old-cert > "$CFG/certs/server.crt"
    : > "$fixture/svc"
}
run() { api_id="$1"; _api_install "$(jq -nc --argjson a "$2" '{action:"install",params:{protocol:"vless-vision",core:"xray",answers:$a}}')" > "$fixture/out" 2>/dev/null || true; }
out() { jq -r "$1" "$fixture/out"; }

reset_cfg
run ok-1 '{"port":2053}'
[[ "$(out '"\(.status)|\(.data.target.port)|\(.data.target.protocol)"')" == "succeeded|2053|vless-vision" ]] || { cat "$fixture/out"; fail $LINENO; }
[[ "$(jq -r '.port' "$fixture/answers")" == 2053 ]] || fail $LINENO
[[ "$(cat "$CFG/config.json")" == '{"new":1}' ]] || fail $LINENO
[[ "$(stat -c %a "$CFG/api-results/ok-1.json" 2>/dev/null || stat -f %Lp "$CFG/api-results/ok-1.json")" == 600 ]] || fail $LINENO
# 重放同一请求不再执行，换参数复用请求号被拒
MODE=fail
run ok-1 '{"port":2053}'
[[ "$(out .status)" == succeeded ]] || fail $LINENO
run ok-1 '{"port":2054}'
[[ "$(out .code)" == request_id_conflict ]] || fail $LINENO
echo 'PASS install transaction succeeds, records the new instance and replays idempotently'

for mode in fail abort fake; do
    MODE=$mode; reset_cfg
    before=$(cat "$DB_FILE")
    run "bad-$mode" '{}'
    case $mode in
        fail) [[ "$(out '"\(.status)|\(.code)|\(.data.message)|\(.data.rolled_back)"')" == "failed|install_failed|Xray 安装失败|true" ]] || { cat "$fixture/out"; fail $LINENO; } ;;
        abort) [[ "$(out '"\(.code)|\(.data.field)"')" == "invalid_answer|port" ]] || fail $LINENO ;;
        fake) [[ "$(out .code)" == install_failed ]] || fail $LINENO ;;
    esac
    [[ "$(cat "$DB_FILE")" == "$before" && "$(cat "$CFG/config.json")" == '{"old":1}' && "$(cat "$CFG/certs/server.crt")" == old-cert ]] || fail $LINENO
    [[ ! -e "$CFG/vless-vision.join" ]] || fail $LINENO
    grep -qx 'restart vless-reality' "$fixture/svc" || fail $LINENO
    [[ "$(jq -r .status "$CFG/api-results/bad-$mode.json")" == failed ]] || fail $LINENO
done
# 原本没有 Xray 配置：恢复后停止 Xray 而不是重启
MODE=fail; reset_cfg; rm -f "$CFG/config.json"
run bad-fresh '{}'
[[ ! -e "$CFG/config.json" ]] && grep -qx 'stop vless-reality' "$fixture/svc" || fail $LINENO
# 校验失败在落盘之前返回
reset_cfg
run bad-arg '{"port":"x"}'
[[ "$(out '"\(.code)|\(.data.field)"')" == "invalid_answer|port" && ! -e "$CFG/api-results/bad-arg.json" ]] || fail $LINENO
echo 'PASS failed, aborted or unverified installs restore data, certificates and config, remove new files and restart the core'
