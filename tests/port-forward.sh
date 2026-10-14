#!/usr/bin/env bash
# 端口转发（Realm + nftables）：规则合并与 nft.sh 兼容、平台写接口的校验/冲突/事务回滚/幂等、启停、状态与流量。函数级隔离测试。
set -e -o pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap '[[ -n "${KEEP:-}" ]] || rm -rf "$fixture"' EXIT
# Bash 3.2 的 set -e 不处理 [[ ]] 失败，断言统一显式失败。
fail() { echo "FAIL line $1"; exit 1; }
CFG="$fixture/cfg"; mkdir -p "$CFG"; DB_FILE="$CFG/db.json"; VERSION=test
REALM_DIR="$CFG/realm"; REALM_RULES_FILE="$REALM_DIR/rules.json"; REALM_CONFIG_FILE="$REALM_DIR/config.toml"
REALM_BIN="$fixture/realm"; REALM_SVC="vless-realm"
load() {
    local body
    body=$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$script")
    [[ -n "$body" ]] || { echo "missing $1"; exit 1; }
    eval "$body"
}
for fn in ensure_realm_dir _fwd_rand_id _fwd_write_store _fwd_nft_conf_rules fwd_rules _fwd_nft_write_conf _fwd_save _fwd_nft_prepare \
    _fwd_nft_reload _fwd_stats_sync _fwd_stats_ensure _fwd_bytes fwd_inventory _fwd_validate _fwd_conflict _fwd_activate _fwd_backup \
    _fwd_restore _fwd_rule_core _fwd_execute _api_forward_apply _api_reply _api_txn_lock _api_txn_unlock _api_sha256 _api_account_store \
    _api_account_result _is_valid_ipv4_literal _is_valid_ipv6_literal _is_valid_dns_name _is_valid_port; do
    load "$fn"
done
# 固定路径改到夹具目录
NFT_FORWARD_CONF="$fixture/nftables.d/port-forward.conf"; NFT_MAIN_CONF="$fixture/nftables.conf"
NFT_SYSCTL_CONF="$fixture/99-nft-forward.conf"; NFT_FORWARD_TABLE=port_forward; FWD_STATS_TABLE=vless_forward_stats
_info() { :; }; _ok() { :; }; _warn() { :; }; _err() { echo "✗ $*"; }
sleep() { :; }
nft_present=true; realm_fail=false; nft_check_fail=false
check_cmd() {
    case "$1" in
        nft) [[ "$nft_present" == true ]] ;;
        realm) [[ -f "$fixture/realm-installed" ]] ;;
        iptables|apt-get|apk|dnf|yum) return 1 ;;
        *) command -v "$1" >/dev/null 2>&1 ;;
    esac
}
nft() {
    echo "nft $*" >> "$fixture/calls"
    case "$*" in
        "-c -f "*) [[ "$nft_check_fail" == true ]] && grep -q "dport 40002" "$3" && return 1; return 0 ;;
        "-f -") cat > "$fixture/stats.nft" ;;
        "-f "*) cp "$2" "$fixture/loaded.conf" ;;
        "list table ip port_forward") [[ -f "$fixture/loaded.conf" ]] && cat "$fixture/loaded.conf" ;;
        "-j list table inet vless_forward_stats") [[ -f "$fixture/stats.json" ]] && cat "$fixture/stats.json" || return 1 ;;
        "delete table inet vless_forward_stats") rm -f "$fixture/stats.nft" ;;
    esac
}
svc() {
    echo "svc $*" >> "$fixture/calls"
    case "$1" in status) [[ -f "$fixture/realm-up" ]] ;; *) return 0 ;; esac
}
sysctl() { case "$1" in -n) echo 0 ;; -w) echo "$2" >> "$fixture/sysctl" ;; esac; }
install_realm_binary() { touch "$fixture/realm-installed"; }
realm_restart_service() {
    local n
    n=$(jq '[.[] | select((.backend // "realm") == "realm" and .enabled != false)] | length' "$REALM_RULES_FILE")
    echo "realm-restart $n" >> "$fixture/calls"
    [[ "$realm_fail" == true ]] && return 1
    if [[ "$n" == 0 ]]; then rm -f "$fixture/realm-up"; else touch "$fixture/realm-up"; fi
}
api() { # api <request_id> <ops json>
    api_id="$1"
    _api_forward_apply "$(jq -nc --arg id "$1" --argjson ops "$2" '{api_version:1,request_id:$id,action:"forward_apply",params:{ops:$ops}}')" || true
}
q() { jq -r "$@" "$REALM_RULES_FILE"; }
echo '{"xray":{"vless":[{"port":443}]},"singbox":{"hy2":{"port":8443}}}' > "$DB_FILE"

# 1. 旧规则补 id；nft.sh 生成的配置被识别为 nftables 规则
mkdir -p "$REALM_DIR" "$(dirname "$NFT_FORWARD_CONF")"
echo '[{"backend":"realm","remark":"old","transport":"tcp","listen_host":"0.0.0.0","listen_port":20001,"remote_host":"example.com","remote_port":80,"enabled":true}]' > "$REALM_RULES_FILE"
cat > "$NFT_FORWARD_CONF" <<'NFT'
#!/usr/sbin/nft -f
define LOCAL_IP = 10.0.0.2
table ip port_forward {
    chain prerouting {
        type nat hook prerouting priority -100; policy accept;
        # 转发: 本机:30001 -> 1.1.1.1:53
        tcp dport 30001 dnat to 1.1.1.1:53
        udp dport 30001 dnat to 1.1.1.1:53
    }
    chain postrouting {
        type nat hook postrouting priority 100; policy accept;
        ip daddr 1.1.1.1 tcp dport 53 ct status dnat snat to $LOCAL_IP
    }
}
NFT
rules=$(fwd_rules)
[[ "$(jq length <<< "$rules")" == 2 ]] || fail $LINENO
realm_id=$(q '.[0].id')
[[ "$realm_id" =~ ^[0-9a-f]{12}$ ]] || fail $LINENO
[[ "$(jq -r '.[1] | "\(.id) \(.backend) \(.transport) \(.remote_host):\(.remote_port)"' <<< "$rules")" == "nft-30001 nftables tcp+udp 1.1.1.1:53" ]] || fail $LINENO
[[ "$(fwd_rules | jq -r '.[0].id')" == "$realm_id" ]] || fail $LINENO
echo 'PASS legacy Realm rules get stable ids; nft.sh rules are read as nftables rules'

# 2. 新增 Realm 规则
out=$(api r1 '[{"op":"add","rule":{"backend":"realm","remark":"web","transport":"tcp+udp","listen_host":"0.0.0.0","listen_port":20002,"remote_host":"10.0.0.9","remote_port":8080,"enabled":true}}]')
[[ "$(jq -r .status <<< "$out")" == succeeded ]] || { echo "$out"; fail $LINENO; }
new_id=$(jq -r .data.rule.id <<< "$out")
[[ "$new_id" =~ ^[0-9a-f]{12}$ && -f "$fixture/realm-up" ]] || fail $LINENO
[[ "$(q '[.[] | select(.backend == "realm")] | length')" == 2 ]] || fail $LINENO
echo 'PASS platform adds a Realm rule and the service runs'

# 3. 校验与冲突
for bad in '{"backend":"nftables","remark":"","transport":"tcp+udp","listen_host":"0.0.0.0","listen_port":40000,"remote_host":"example.com","remote_port":443,"enabled":true}' \
           '{"backend":"realm","remark":"x\ny","transport":"tcp","listen_host":"0.0.0.0","listen_port":40000,"remote_host":"1.2.3.4","remote_port":443,"enabled":true}' \
           '{"backend":"realm","remark":"","transport":"sctp","listen_host":"0.0.0.0","listen_port":40000,"remote_host":"1.2.3.4","remote_port":443,"enabled":true}' \
           '{"backend":"realm","remark":"","transport":"tcp","listen_host":"0.0.0.0","listen_port":70000,"remote_host":"1.2.3.4","remote_port":443,"enabled":true}'; do
    [[ "$(api "bad$RANDOM" "[{\"op\":\"add\",\"rule\":$bad}]" | jq -r .code)" == invalid_request ]] || fail $LINENO
done
[[ "$(api c1 '[{"op":"add","rule":{"backend":"nftables","remark":"","transport":"tcp+udp","listen_host":"0.0.0.0","listen_port":20002,"remote_host":"1.2.3.4","remote_port":443,"enabled":true}}]' | jq -r .code)" == port_conflict ]] || fail $LINENO
[[ "$(api c2 '[{"op":"add","rule":{"backend":"realm","remark":"","transport":"udp","listen_host":"0.0.0.0","listen_port":443,"remote_host":"1.2.3.4","remote_port":443,"enabled":true}}]' | jq -r .code)" == port_conflict ]] || fail $LINENO
[[ "$(api c3 '[{"op":"add","rule":{"backend":"realm","remark":"","transport":"udp","listen_host":"0.0.0.0","listen_port":20001,"remote_host":"1.2.3.4","remote_port":443,"enabled":true}}]' | jq -r .status)" == succeeded ]] || fail $LINENO
echo 'PASS validation (nftables IPv4 only, remark, transport, port) and port conflicts with rules and proxy instances'

# 4. 新增 nftables 规则：保留 nft.sh 原有规则，开启转发并加载
out=$(api n1 '[{"op":"add","rule":{"backend":"nftables","remark":"游戏","transport":"tcp","listen_host":"1.2.3.4","listen_port":40000,"remote_host":"5.6.7.8","remote_port":443,"enabled":true}}]')
[[ "$(jq -r .data.rule.id <<< "$out")" == nft-40000 && "$(jq -r .data.rule.transport <<< "$out")" == tcp+udp ]] || { echo "$out"; fail $LINENO; }
grep -q 'tcp dport 40000 dnat to 5.6.7.8:443' "$NFT_FORWARD_CONF" || fail $LINENO
grep -q 'udp dport 30001 dnat to 1.1.1.1:53' "$NFT_FORWARD_CONF" || fail $LINENO
cmp -s "$NFT_FORWARD_CONF" "$fixture/loaded.conf" || fail $LINENO
grep -q 'include "/etc/nftables.d/\*.conf"' "$NFT_MAIN_CONF" || fail $LINENO
grep -q 'net.ipv4.ip_forward = 1' "$NFT_SYSCTL_CONF" || fail $LINENO
grep -q 'counter comment "fwd:nft-40000"' "$fixture/stats.nft" || fail $LINENO
[[ "$(q '.[] | select(.backend == "nftables" and .listen_port == 40000) | .remark')" == 游戏 ]] || fail $LINENO
# nft.sh 的解析方式仍能读出全部规则
[[ "$(sed -E '/^[[:space:]]*#/d' "$NFT_FORWARD_CONF" | grep -cE 'tcp dport [0-9]+ dnat to [0-9.]+:[0-9]+')" == 2 ]] || fail $LINENO
echo 'PASS nftables rule written in nft.sh format, existing nft.sh rules kept, forwarding enabled, counters built'

# 5. 修改：快照过期拒绝；按快照修改；端口变化 id 随之变化
inv=$(fwd_inventory)
base=$(jq -c '.rules[] | select(.id == "nft-40000")' <<< "$inv")
stale=$(jq -c '.remote_port = 1' <<< "$base")
[[ "$(api u0 "[{\"op\":\"update\",\"id\":\"nft-40000\",\"base\":$stale,\"rule\":$(jq -c '.remote_port = 8443' <<< "$base")}]" | jq -r .code)" == rule_changed ]] || fail $LINENO
out=$(api u1 "[{\"op\":\"update\",\"id\":\"nft-40000\",\"base\":$base,\"rule\":$(jq -c '{backend,remark,transport,listen_host,remote_host,enabled} + {listen_port: 40001, remote_port: 8443}' <<< "$base")}]")
[[ "$(jq -r .data.rule.id <<< "$out")" == nft-40001 ]] || { echo "$out"; fail $LINENO; }
grep -q 'tcp dport 40001 dnat to 5.6.7.8:8443' "$NFT_FORWARD_CONF" && ! grep -q 'dport 40000' "$NFT_FORWARD_CONF" || fail $LINENO
[[ "$(q '[.[] | select(.listen_port == 40000)] | length')" == 0 ]] || fail $LINENO
base=$(fwd_inventory | jq -c --arg id "$new_id" '.rules[] | select(.id == $id)')
out=$(api u2 "[{\"op\":\"update\",\"id\":\"$new_id\",\"base\":$base,\"rule\":$(jq -c '{backend,remark,transport,listen_host,listen_port,remote_host,enabled} + {remote_port: 9090}' <<< "$base")}]")
[[ "$(jq -r .data.rule.id <<< "$out")" == "$new_id" && "$(q --arg id "$new_id" '.[] | select(.id == $id) | .remote_port')" == 9090 ]] || fail $LINENO
echo 'PASS updates reject stale snapshots; Realm keeps its id, nftables id follows the port'

# 6. 停用 / 启用 nftables 规则
base=$(fwd_inventory | jq -c '.rules[] | select(.id == "nft-40001")')
[[ "$(api d1 "[{\"op\":\"disable\",\"id\":\"nft-40001\",\"base\":$base}]" | jq -r .status)" == succeeded ]] || fail $LINENO
! grep -q 'dport 40001' "$NFT_FORWARD_CONF" || fail $LINENO
inv=$(fwd_inventory)
[[ "$(jq -r '.rules[] | select(.id == "nft-40001") | "\(.enabled) \(.status) \(.remark)"' <<< "$inv")" == "false disabled 游戏" ]] || fail $LINENO
[[ "$(jq -r '.rules[] | select(.id == "nft-30001") | .status' <<< "$inv")" == running ]] || fail $LINENO
base=$(jq -c '.rules[] | select(.id == "nft-40001")' <<< "$inv")
[[ "$(api e1 "[{\"op\":\"enable\",\"id\":\"nft-40001\",\"base\":$base}]" | jq -r .status)" == succeeded ]] || fail $LINENO
grep -q 'tcp dport 40001 dnat to 5.6.7.8:8443' "$NFT_FORWARD_CONF" || fail $LINENO
echo 'PASS disabling keeps the rule (metadata) and removes it from nftables; enabling restores it'

# 7. 应用失败回滚：文件与运行状态恢复
before_rules=$(cat "$REALM_RULES_FILE"); before_conf=$(cat "$NFT_FORWARD_CONF")
nft_check_fail=true
out=$(api f1 '[{"op":"add","rule":{"backend":"nftables","remark":"","transport":"tcp+udp","listen_host":"0.0.0.0","listen_port":40002,"remote_host":"9.9.9.9","remote_port":53,"enabled":true}}]')
nft_check_fail=false
[[ "$(jq -r '"\(.status) \(.code) \(.data.rolled_back)"' <<< "$out")" == "failed apply_failed true" ]] || { echo "$out"; fail $LINENO; }
[[ "$(cat "$REALM_RULES_FILE")" == "$before_rules" && "$(cat "$NFT_FORWARD_CONF")" == "$before_conf" ]] || fail $LINENO
echo 'PASS a failed apply restores rules and configuration'

# 8. 幂等：同一请求重放返回原结果；同 ID 不同请求拒绝；结果可查询
[[ "$(api r1 '[{"op":"add","rule":{"backend":"realm","remark":"web","transport":"tcp+udp","listen_host":"0.0.0.0","listen_port":20002,"remote_host":"10.0.0.9","remote_port":8080,"enabled":true}}]' | jq -r .data.rule.id)" == "$new_id" ]] || fail $LINENO
[[ "$(api r1 '[{"op":"delete","id":"nft-30001","base":{}}]' | jq -r .code)" == request_id_conflict ]] || fail $LINENO
api_id=x; [[ "$(_api_account_result '{"params":{"request_id":"f1"}}' | jq -r .code)" == apply_failed ]] || fail $LINENO
echo 'PASS idempotent replay, request id conflicts and result lookup'

# 9. 删除最后的 Realm 规则后停止 Realm；删除 nft.sh 导入的规则
for id in $(fwd_rules | jq -r '.[] | select(.backend == "realm") | .id'); do
    base=$(fwd_inventory | jq -c --arg id "$id" '.rules[] | select(.id == $id)')
    [[ "$(api "del-$id" "[{\"op\":\"delete\",\"id\":\"$id\",\"base\":$base}]" | jq -r .status)" == succeeded ]] || fail $LINENO
done
[[ ! -f "$fixture/realm-up" ]] || fail $LINENO
grep -q 'realm-restart 0' "$fixture/calls" || fail $LINENO
base=$(fwd_inventory | jq -c '.rules[] | select(.id == "nft-30001")')
[[ "$(api del-nft "[{\"op\":\"delete\",\"id\":\"nft-30001\",\"base\":$base}]" | jq -r .status)" == succeeded ]] || fail $LINENO
! grep -q 'dport 30001' "$NFT_FORWARD_CONF" || fail $LINENO
[[ "$(api gone '[{"op":"delete","id":"nft-30001","base":{}}]' | jq -r .code)" == rule_not_found ]] || fail $LINENO
echo 'PASS deleting the last Realm rule stops Realm; nft.sh rules can be deleted from the platform'

# 10. 流量：计数表按规则汇总（两个方向）
echo '{"nftables":[{"rule":{"comment":"fwd:nft-40001","expr":[{"counter":{"bytes":100}}]}},{"rule":{"comment":"fwd:nft-40001","expr":[{"counter":{"bytes":23}}]}}]}' > "$fixture/stats.json"
[[ "$(fwd_inventory | jq -r '.rules[] | select(.id == "nft-40001") | .bytes')" == 123 ]] || fail $LINENO
: > "$fixture/stats.nft"; _fwd_stats_ensure
[[ ! -s "$fixture/stats.nft" ]] || fail $LINENO   # same rule set: counters are not reset
echo '{"nftables":[]}' > "$fixture/stats.json"; _fwd_stats_ensure
grep -q 'fwd:nft-40001' "$fixture/stats.nft" || fail $LINENO
echo 'PASS traffic counters sum both directions and are rebuilt only when the rule set changes'

# 11. 请求格式
for bad in '[]' '[{"op":"add"}]' '[{"op":"drop","id":"nft-1","base":{}}]' '[{"op":"delete","id":"../x","base":{}}]' '[{"op":"update","id":"nft-40001","base":{}}]'; do
    [[ "$(api "fmt$RANDOM" "$bad" | jq -r .code)" == invalid_request ]] || { echo "$bad"; fail $LINENO; }
done
echo 'PASS malformed requests are rejected'
