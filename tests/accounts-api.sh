#!/usr/bin/env bash
# 统一用户写接口（--api account_apply / result / inventory）。函数级隔离测试。
set -e -o pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
# Bash 3.2 的 set -e 不处理 [[ ]] 失败，断言统一显式失败。
fail() { echo "FAIL line $1"; exit 1; }
CFG="$fixture"; DB_FILE="$fixture/db.json"; VERSION=test
XRAY_PROTOCOLS='vless trojan'; SINGBOX_PROTOCOLS='hy2'
STANDALONE_PROTOCOLS="snell snell-v5 snell-v6 snell-shadowtls snell-v5-shadowtls ss2022-shadowtls naive"
load() {
    local body
    body=$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1; if ($0 ~ /; }$/) {print; exit}} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")
    [[ -n "$body" ]] || { echo "missing $1"; exit 1; }
    eval "$body"
}
for fn in _account_jq_defs _account_valid_id _account_valid_name _account_valid_date _account_new_id \
    _account_proto_supported db_account_get db_account_find db_account_members db_user_account_id \
    _accounts_user_states _accounts_reload _accounts_reload_or_queue accounts_apply db_account_create db_account_set \
    _account_materialize_default db_account_member_add db_account_member_new db_get_user_port db_account_member_remove \
    db_account_delete db_account_reset_usage db_account_unlink_platform db_account_reset_credentials \
    _db_apply db_get_user_field db_list_users is_standalone_protocol _is_snell_users_protocol \
    _api_reply _api_inventory _api_dispatch _api_sha256 _api_account_validate _api_account_precheck _api_account_execute \
    _api_account_backup_files _api_account_restore _api_account_store _api_account_apply _api_account_result \
    _api_txn_lock _api_txn_unlock db_authority_get _authority_rows _authority_new_secret _authority_apply; do
    load "$fn"
done
API_ACCOUNT_OPS=$(sed -n 's/^API_ACCOUNT_OPS="\(.*\)"$/\1/p' "$repo/vless-server.sh")
# Bash 4.1+ 且有 flock 时使用真实互斥锁，否则（macOS Bash 3.2）替换为空操作。
if (( BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1] < 401 )) || ! command -v flock >/dev/null 2>&1; then
    _api_txn_lock() { :; }; _api_txn_unlock() { :; }
fi
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_err() { echo "  ✗ $*" >&2; }; _ok() { echo "  ✓ $*" >&2; }; _info() { :; }; _warn() { :; }
get_protocol_name() { echo "$1"; }
ensure_expire_check_cron() { :; }
gen_uuid() { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; }
gen_password() { echo "pw$RANDOM$RANDOM"; }
_snell_managed() { [[ "$1" == snell-v5 ]]; }
_snell_apply_users() { :; }
# 重建桩：记录次数并修改配置文件，failures 次数内返回失败
failures=0
reload() {
    echo "$1" >> "$fixture/reloads"
    echo "{\"rebuilt\":$RANDOM}" > "$CFG/config.json"
    if (( failures > 0 )); then failures=$((failures - 1)); return 1; fi
}
rebuild_and_reload_xray() { reload xray; }
_regenerate_config() { reload "$1:$2"; }
call() { _api_dispatch <<< "$1" > "$fixture/out" 2>"$fixture/err" || true; [[ "$(wc -l < "$fixture/out" | tr -d ' ')" == 1 ]] || fail "$2"; jq -e . "$fixture/out" >/dev/null || fail "$2"; }
out() { jq -r "$1" "$fixture/out"; }
q() { jq -r "$@" "$DB_FILE"; }
user() { jq -c --arg c "$1" --arg p "$2" --arg n "$3" '[.[$c][$p] | if type == "array" then .[] else . end | .users[]? | select(.name == $n)][0]' "$DB_FILE"; }
A=11111111-1111-4111-8111-111111111111
P=22222222-2222-4222-8222-222222222222
echo '{"seed":1}' > "$CFG/config.json"
cat > "$DB_FILE" <<'JSON'
{"xray":{"vless":{"port":443,"uuid":"ROW_SECRET","users":[{"name":"default","uuid":"ROW_SECRET","enabled":true,"used":0}]},
 "trojan":[{"port":1,"password":"T_SECRET","users":[{"name":"bob","uuid":"BOB_SECRET","used":30,"enabled":true}]}],
 "snell-v5":[{"port":9001,"psk":"S_SECRET","snell_id":"aaaaaaaaaaaaaaaaaaaaaaaa","users":[{"id":"aaaaaaaaaaaaaaaaaaaaaaaa","name":"sam","uuid":"S_SECRET","used":5,"enabled":true}]}]},
 "singbox":{"hy2":{"port":8443,"password":"HY_SECRET","users":[]}},"meta":{"user_authority":"platform"}}
JSON

# 1. 能力声明：协议级写入仍关闭，统一用户接口单独声明
call '{"api_version":1,"request_id":"cap","action":"capabilities"}' $LINENO
[[ "$(out '.data.write_actions == [] and .data.stage == "read_only_foundation" and .data.accounts_api.version == 2')" == true ]] || fail $LINENO
[[ "$(out '.data.accounts_api.ops | index("member_claim") != null and index("set_authority") != null')" == true ]] || fail $LINENO
[[ "$(out '"\(.data.accounts_api.version)|\(.data.user_authority)"')" == "2|platform" ]] || fail $LINENO
echo 'PASS capabilities keep protocol writes closed and declare accounts API'

# 2. 创建（带成员与平台关联），结果与 inventory
req=$(jq -nc --arg a "$A" --arg p "$P" '{api_version:1,request_id:"create-1",action:"account_apply",params:{ops:[
  {op:"create",account_id:$a,platform_user_id:$p,fields:{name:"alice",quota:100,expire_date:"2099-01-01",reset_day:1,note:"n"},
   members:[{target:{core:"xray",protocol:"vless",port:443}},{target:{core:"singbox",protocol:"hy2",port:8443}}]}]}}')
call "$req" $LINENO
[[ "$(out .status)" == succeeded ]] || { cat "$fixture/out"; fail $LINENO; }
rev=$(out ".data.accounts[\"$A\"].rev")
[[ "$rev" -ge 3 ]] || fail $LINENO
[[ "$(q --arg a "$A" '.accounts[$a] | "\(.name)|\(.platform_user_id)|\(.members | length)"')" == "alice|$P|2" ]] || fail $LINENO
[[ "$(wc -l < "$fixture/reloads" | tr -d ' ')" == 2 ]] || fail $LINENO
call '{"api_version":1,"request_id":"inv","action":"inventory"}' $LINENO
! grep -q SECRET "$fixture/out" || fail $LINENO
[[ "$(out "[.data.instances[].users[] | select(.account_id == \"$A\")] | length")" == 2 ]] || fail $LINENO
[[ "$(out ".data.accounts[\"$A\"] | \"\(.rev)|\(.platform_user_id)|\(.members | length)|\(.members[0].enabled)\"")" == "$rev|$P|2|true" ]] || fail $LINENO
! out ".data.accounts[\"$A\"].members[0]" | grep -q uuid || fail $LINENO
echo 'PASS create with members and platform link, one reload per core, redacted inventory'

# 3. 幂等：同 request_id 同内容返回已存结果且不重复执行；不同内容拒绝
reloads_before=$(wc -l < "$fixture/reloads")
call "$req" $LINENO
[[ "$(out .status)" == succeeded && "$(out ".data.accounts[\"$A\"].rev")" == "$rev" ]] || fail $LINENO
[[ "$(wc -l < "$fixture/reloads")" == "$reloads_before" ]] || fail $LINENO
call "$(jq -c '.params.ops[0].fields.name = "other"' <<< "$req")" $LINENO
[[ "$(out .code)" == request_id_conflict ]] || fail $LINENO
echo 'PASS idempotent replay and request id conflict'

# 4. 乐观并发：过期 base_rev 拒绝且不写入；正确 base_rev 生效
before=$(cat "$DB_FILE")
call "$(jq -nc --arg a "$A" --argjson r "$((rev - 1))" '{api_version:1,request_id:"upd-stale",action:"account_apply",params:{ops:[{op:"update",account_id:$a,base_rev:$r,fields:{expire_date:"2099-02-01"}}]}}')" $LINENO
[[ "$(out '"\(.status)|\(.code)|\(.data.rev)"')" == "failed|rev_conflict|$rev" ]] || fail $LINENO
[[ "$(cat "$DB_FILE")" == "$before" ]] || fail $LINENO
call "$(jq -nc --arg a "$A" --argjson r "$rev" '{api_version:1,request_id:"upd-1",action:"account_apply",params:{ops:[{op:"update",account_id:$a,base_rev:$r,fields:{expire_date:"2099-02-01",quota:0,enabled:true}}]}}')" $LINENO
[[ "$(out .status)" == succeeded ]] || fail $LINENO
[[ "$(out ".data.accounts[\"$A\"].rev")" == "$((rev + 2))" ]] || fail $LINENO
[[ "$(jq -r .expire_date <<< "$(user xray vless alice)")" == 2099-02-01 ]] || fail $LINENO
echo 'PASS stale base_rev rejected without writes, changed fields bump rev'

# 5. 格式校验：未知字段、错误日期、超量操作、非 uuid
for bad in \
  '{"api_version":1,"request_id":"b1","action":"account_apply","params":{"ops":[{"op":"update","account_id":"'$A'","base_rev":1,"fields":{"password":"x"}}]}}' \
  '{"api_version":1,"request_id":"b2","action":"account_apply","params":{"ops":[{"op":"update","account_id":"'$A'","base_rev":1,"fields":{"expire_date":"2099/1/1"}}]}}' \
  '{"api_version":1,"request_id":"b3","action":"account_apply","params":{"ops":[{"op":"link","account_id":"nope","platform_user_id":"'$P'"}]}}' \
  '{"api_version":1,"request_id":"b4","action":"account_apply","params":{"ops":[{"op":"shell","account_id":"'$A'"}]}}' \
  '{"api_version":1,"request_id":"b5","action":"account_apply","params":{"ops":[]}}' \
  '{"api_version":1,"request_id":"b6","action":"account_apply","params":{"ops":[{"op":"update","account_id":"'$A'","base_rev":1,"fields":{"note":"a\nb"}}]}}'; do
    before=$(cat "$DB_FILE")
    call "$bad" $LINENO
    [[ "$(out .code)" == invalid_request ]] || fail $LINENO
    [[ "$(cat "$DB_FILE")" == "$before" ]] || fail $LINENO
done
many=$(jq -nc --arg a "$A" '{api_version:1,request_id:"b7",action:"account_apply",params:{ops:[range(201) | {op:"reset_usage",account_id:$a}]}}')
call "$many" $LINENO
[[ "$(out .code)" == invalid_request ]] || fail $LINENO
echo 'PASS strict request validation rejects without writes'

# 6. 事务回滚：第二个操作失败时第一个操作也撤销，数据库与配置恢复原样
before=$(cat "$DB_FILE"); cfg_before=$(cat "$CFG/config.json")
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"tx-1",action:"account_apply",params:{ops:[
  {op:"member_claim",account_id:$a,target:{core:"xray",protocol:"trojan",port:1},name:"bob"},
  {op:"member_claim",account_id:$a,target:{core:"xray",protocol:"trojan",port:1},name:"ghost"}]}}')" $LINENO
[[ "$(out '"\(.status)|\(.code)|\(.data.rolled_back)"')" == "failed|apply_failed|true" ]] || fail $LINENO
[[ "$(out .data.message)" == *协议用户不存在* ]] || fail $LINENO
[[ "$(cat "$DB_FILE")" == "$before" && "$(cat "$CFG/config.json")" == "$cfg_before" ]] || fail $LINENO
call '{"api_version":1,"request_id":"q1","action":"result","params":{"request_id":"tx-1"}}' $LINENO
[[ "$(out '"\(.status)|\(.code)"')" == "failed|apply_failed" ]] || fail $LINENO
echo 'PASS multi-op transaction rolls back database and config, result is queryable'

# 7. 统一重建失败：回滚并重建原配置；回滚重建也失败时为 unknown
before=$(cat "$DB_FILE")
failures=1
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"tx-2",action:"account_apply",params:{ops:[{op:"member_claim",account_id:$a,target:{core:"xray",protocol:"trojan",port:1},name:"bob"}]}}')" $LINENO
[[ "$(out '"\(.status)|\(.code)"')" == "failed|apply_failed" ]] || fail $LINENO
[[ "$(cat "$DB_FILE")" == "$before" ]] || fail $LINENO
failures=5
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"tx-3",action:"account_apply",params:{ops:[{op:"member_claim",account_id:$a,target:{core:"xray",protocol:"trojan",port:1},name:"bob"}]}}')" $LINENO
[[ "$(out '"\(.status)|\(.code)|\(.data.replay_allowed)"')" == "unknown|result_unknown|false" ]] || fail $LINENO
failures=0
cp "$fixture/api-backups/tx-3/db.json" "$DB_FILE"
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"tx-3",action:"account_apply",params:{ops:[{op:"member_claim",account_id:$a,target:{core:"xray",protocol:"trojan",port:1},name:"bob"}]}}')" $LINENO
[[ "$(out .status)" == unknown ]] || fail $LINENO
echo 'PASS reload failure rolls back, failed restore is unknown and never replayed'

# 8. 中断遗留的 running 记录：重放与查询都返回 unknown
printf '%s\n' "{\"fingerprint\":\"$(jq -cS '{action, params}' <<< '{"action":"account_apply","params":{"ops":[{"op":"reset_usage","account_id":"'$A'"}]}}' | _api_sha256)\",\"status\":\"running\"}" > "$fixture/api-results/crash.json"
call '{"api_version":1,"request_id":"crash","action":"account_apply","params":{"ops":[{"op":"reset_usage","account_id":"'$A'"}]}}' $LINENO
[[ "$(out '"\(.status)|\(.data.replay_allowed)"')" == "unknown|false" ]] || fail $LINENO
call '{"api_version":1,"request_id":"q2","action":"result","params":{"request_id":"crash"}}' $LINENO
[[ "$(out .status)" == unknown ]] || fail $LINENO
call '{"api_version":1,"request_id":"q3","action":"result","params":{"request_id":"never"}}' $LINENO
[[ "$(out .code)" == result_not_found ]] || fail $LINENO
call '{"api_version":1,"request_id":"q4","action":"result","params":{"request_id":"create-1"}}' $LINENO
[[ "$(out .status)" == succeeded ]] || fail $LINENO
echo 'PASS interrupted intent is unknown, results are read-only'

# 9. 归入、平台停用与解除、凭据重置、Snell 限制、删除
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"claim",action:"account_apply",params:{ops:[
  {op:"member_claim",account_id:$a,target:{core:"xray",protocol:"trojan",port:1},name:"bob",count_existing:false},
  {op:"member_claim",account_id:$a,target:{core:"xray",protocol:"snell-v5",port:9001},name:"sam"},
  {op:"block",account_id:$a,platform_block:"quota"}]}}')" $LINENO
[[ "$(out .status)" == succeeded ]] || { cat "$fixture/out" "$fixture/err"; fail $LINENO; }
[[ "$(jq -r '"\(.uuid)|\(.enabled)|\(.disable_reason)"' <<< "$(user xray trojan bob)")" == "BOB_SECRET|false|platform_quota" ]] || fail $LINENO
old=$(jq -r .uuid <<< "$(user singbox hy2 alice)")
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"unblock",action:"account_apply",params:{ops:[
  {op:"block",account_id:$a,platform_block:""},{op:"reset_credentials",account_id:$a,member:{core:"singbox",protocol:"hy2",port:8443,name:"alice"}}]}}')" $LINENO
[[ "$(out .status)" == succeeded ]] || fail $LINENO
[[ "$(jq -r .enabled <<< "$(user xray trojan bob)")" == true && "$(jq -r .uuid <<< "$(user singbox hy2 alice)")" != "$old" ]] || fail $LINENO
before=$(cat "$DB_FILE")
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"snell-add",action:"account_apply",params:{ops:[{op:"member_add",account_id:$a,target:{core:"xray",protocol:"snell-v5",port:9001}}]}}')" $LINENO
[[ "$(out .code)" == unsupported_snell_operation && "$(cat "$DB_FILE")" == "$before" ]] || fail $LINENO
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"del-bad",action:"account_apply",params:{ops:[{op:"delete",account_id:$a,mode:"delete"}]}}')" $LINENO
[[ "$(out .code)" == unsupported_snell_operation ]] || fail $LINENO
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"del",action:"account_apply",params:{ops:[{op:"unlink",account_id:$a},{op:"delete",account_id:$a}]}}')" $LINENO
[[ "$(out "\"\(.status)|\(.data.accounts[\"$A\"].exists)\"")" == "succeeded|false" ]] || fail $LINENO
[[ "$(jq -r .account_id <<< "$(user xray trojan bob)")" == null && "$(jq -r .uuid <<< "$(user xray trojan bob)")" == BOB_SECRET ]] || fail $LINENO
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"gone",action:"account_apply",params:{ops:[{op:"reset_usage",account_id:$a}]}}')" $LINENO
[[ "$(out .code)" == account_not_found ]] || fail $LINENO
echo 'PASS claim, platform block, credential reset, Snell limits, delete keeps members'

# 10. 以脚本为准时拒绝写用户，只允许切换方式；切换必须单独成请求
_db_apply '.meta.user_authority = "script"'
before=$(cat "$DB_FILE")
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"in-script",action:"account_apply",params:{ops:[{op:"reset_usage",account_id:$a}]}}')" $LINENO
[[ "$(out .code)" == authority_script && "$(cat "$DB_FILE")" == "$before" ]] || fail $LINENO
call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"mixed",action:"account_apply",params:{ops:[{op:"set_authority",mode:"platform"},{op:"reset_usage",account_id:$a}]}}')" $LINENO
[[ "$(out .code)" == invalid_request ]] || fail $LINENO
call '{"api_version":1,"request_id":"take","action":"account_apply","params":{"ops":[{"op":"set_authority","mode":"platform"}]}}' $LINENO
[[ "$(out '"\(.status)|\(.data.user_authority)"')" == "succeeded|platform" ]] || { cat "$fixture/out"; fail $LINENO; }
[[ "$(q '[.xray.trojan[0].users, .singbox.hy2.users] | map(length) | add')" == 0 && "$(q .xray.trojan[0].password)" != T_SECRET ]] || fail $LINENO
! grep -q '_SECRET' "$DB_FILE" || fail $LINENO
call '{"api_version":1,"request_id":"inv2","action":"inventory"}' $LINENO
[[ "$(out .data.user_authority)" == platform ]] || fail $LINENO
call '{"api_version":1,"request_id":"back","action":"account_apply","params":{"ops":[{"op":"set_authority","mode":"script"}]}}' $LINENO
[[ "$(out '"\(.status)|\(.data.user_authority)"')" == "succeeded|script" ]] || fail $LINENO
echo 'PASS set_authority: script mode rejects user writes, takeover clears credentials, switch back'
