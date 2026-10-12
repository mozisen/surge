#!/usr/bin/env bash
# 统一用户（节点级，一人多协议）：数据层、结算与成员派生。函数级隔离测试。
set -e -o pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
# Bash 3.2 的 set -e 不处理 [[ ]] 失败，断言统一显式失败。
fail() { echo "FAIL line $1"; exit 1; }
CFG="$fixture"; DB_FILE="$fixture/db.json"
STANDALONE_PROTOCOLS="snell snell-v5 snell-v6 snell-shadowtls snell-v5-shadowtls ss2022-shadowtls naive"
# 支持单行函数（以 "; }" 结尾）与多行函数（以独立的 "}" 结尾）。
load() {
    local body
    body=$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1; if ($0 ~ /; }$/) {print; exit}} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")
    [[ -n "$body" ]] || { echo "missing $1"; exit 1; }
    eval "$body"
}
for fn in _account_jq_defs _account_valid_id _account_valid_name _account_valid_date _account_new_id \
    _account_proto_supported db_account_list db_account_get db_account_find db_account_members db_user_account_id \
    _accounts_user_states _accounts_reload _accounts_reload_or_queue accounts_apply db_account_create db_account_set _account_materialize_default \
    db_account_member_add db_account_member_new db_get_user_port db_account_member_remove db_account_delete \
    db_account_reset_usage db_account_unlink_platform db_account_reset_credentials _account_merge_candidates \
    _account_member_guard _account_ask_expire _account_instances _account_claimable_users _account_reason_text \
    _account_show_list _account_select _account_show_detail _account_create_interactive _account_edit_interactive \
    _account_add_protocol_interactive _account_claim_interactive _account_pick_member _account_remove_member_interactive \
    _account_member_share _account_share_interactive _account_merge_interactive manage_accounts format_bytes \
    _db_apply db_get_user_field db_list_users is_standalone_protocol _is_snell_users_protocol reset_monthly_user_traffic; do
    load "$fn"
done
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_err() { echo "ERR: $*" >> "$fixture/errors"; }; _ok() { :; }; _info() { :; }; _warn() { :; }
get_protocol_name() { echo "$1"; }
ensure_expire_check_cron() { :; }
gen_uuid() { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; }
gen_password() { echo "pw$RANDOM$RANDOM"; }
_snell_managed() { [[ "$1" == snell-v5 ]]; }
rebuild_and_reload_xray() { echo xray >> "$fixture/reloads"; [[ "${fail:-}" != true ]]; }
_regenerate_config() { echo "$1:$2" >> "$fixture/reloads"; [[ "${fail:-}" != true ]]; }
_snell_apply_users() { echo "snell:$1" >> "$fixture/reloads"; }
_snell_add_user() {
    [[ "$3" == account ]] || return 1
    _db_apply --arg n "$2" '.xray["snell-v5"] += [{port: 9001, psk: "oldpsk", snell_id: "aaaaaaaaaaaaaaaaaaaaaaaa", users: [{id: "aaaaaaaaaaaaaaaaaaaaaaaa", name: $n, uuid: "oldpsk", used: 0, quota: 0, enabled: true, expire_date: ""}]}]'
}
_snell_delete_user() { _db_apply --arg n "$2" '.xray["snell-v5"] |= map(select(.users[0].name != $n))'; }
today=2026-10-12; now=1760000000
date() {
    case "$1" in
        +%F) echo "$today" ;;
        +%s) echo "$now" ;;
        *) command date "$@" ;;
    esac
}
reloads() { local r; r=$(sort -u "$fixture/reloads" 2>/dev/null | tr '\n' ' '); : > "$fixture/reloads"; echo "$r"; }
q() { jq -r "$@" "$DB_FILE"; }
user() { jq -c --arg c "$1" --arg p "$2" --arg n "$3" '[.[$c][$p] | if type == "array" then .[] else . end | .users[]? | select(.name == $n)][0]' "$DB_FILE"; }

cat > "$DB_FILE" <<'JSON'
{"xray":{"vless":{"port":443,"uuid":"row-secret","sni":"a.example"},
 "trojan":[{"port":1,"password":"t1","users":[{"name":"bob","uuid":"bob-secret","used":30,"quota":500,"enabled":true,"panel_quota":9,"panel_used":3}]},
           {"port":2,"password":"t2","users":[{"name":"carol","uuid":"c","used":5,"enabled":true}]}],
 "snell-v5":[]},
 "singbox":{"hy2":{"port":8443,"password":"hy","users":[]}},"meta":{}}
JSON

# 1. 创建与校验
id=$(db_account_create alice 100 2026-12-31 5 "测试")
_account_valid_id "$id"
[[ "$(q --arg id "$id" '.accounts[$id] | "\(.rev)|\(.cycle)|\(.cycle_used)|\(.mtime.quota)"')" == "1|2026-10-05|0|$now" ]] || fail $LINENO
if db_account_create ALICE 0 "" 0 2>/dev/null; then echo 'duplicate name accepted'; exit 1; fi
if db_account_create 'bad name' 0 "" 0; then exit 1; fi
if db_account_create x 0 2026/1/1 0; then exit 1; fi
if db_account_create x 0 "" 29; then exit 1; fi
[[ "$(db_account_find Alice)" == "$id" ]] || fail $LINENO
echo 'PASS create, validation, case-insensitive uniqueness'

# 2. 新建成员：旧单用户实例补 default，新成员凭据独立，派生到期与配额
db_account_member_new "$id" xray vless 443
db_account_member_new "$id" singbox hy2 8443
[[ "$(q '.xray.vless.users | map(.name) | join(",")')" == "default,alice" ]] || fail $LINENO
[[ "$(q '.xray.vless.users[0].uuid')" == row-secret ]] || fail $LINENO
a=$(user xray vless alice)
[[ "$(jq -r '.account_id' <<< "$a")" == "$id" && "$(jq -r '.expire_date' <<< "$a")" == 2026-12-31 && "$(jq -r '.quota' <<< "$a")" == 0 ]] || fail $LINENO
[[ "$(jq -r '.uuid' <<< "$a")" != "$(jq -r '.uuid' <<< "$(user singbox hy2 alice)")" ]] || fail $LINENO
[[ "$(reloads)" == *xray* ]] || fail $LINENO
[[ "$(q --arg id "$id" '.accounts[$id].members | length')" == 2 ]] || fail $LINENO
if db_account_member_new "$id" xray vless 443 2>/dev/null; then echo 'duplicate member name accepted'; exit 1; fi
if db_account_member_new "$id" xray socks 1080 2>/dev/null; then exit 1; fi
echo 'PASS member creation, default materialization, independent credentials, derived fields'

# 3. 跨协议合计与超额停用全部成员
_db_apply '.xray.vless.users[1].used = 60 | .singbox.hy2.users[0].used = 50'
accounts_apply
[[ "$(q --arg id "$id" '.accounts[$id].cycle_used')" == 110 ]] || fail $LINENO
[[ "$(jq -r '"\(.enabled)|\(.disable_reason)"' <<< "$(user xray vless alice)")" == "false|quota" ]] || fail $LINENO
[[ "$(jq -r '.enabled' <<< "$(user singbox hy2 alice)")" == false ]] || fail $LINENO
r=$(reloads); [[ "$r" == *xray* && "$r" == *singbox:hy2* ]] || fail $LINENO
accounts_apply
[[ -z "$(reloads)" ]] || fail $LINENO
# 重建失败：保留待重建记录，下次结算重试并清除
fail=true
if db_account_set "$id" quota 1000; then fail $LINENO; fi
[[ "$(q '.meta.accounts_reload_pending | join(",")')" == *"singbox|hy2"* ]] || fail $LINENO
fail=false; : > "$fixture/reloads"
accounts_apply || fail $LINENO
[[ "$(reloads)" == *singbox:hy2* && "$(q '.meta.accounts_reload_pending')" == null ]] || fail $LINENO
db_account_set "$id" quota 100
reloads >/dev/null
echo 'PASS aggregate quota disables every member, idempotent settle does not reload, failed reload retried'

# 4. 调高配额恢复；计数归零按新计数计入
rev0=$(q --arg id "$id" '.accounts[$id].rev'); now=1760000100
db_account_set "$id" quota 200
[[ "$(jq -r '.enabled' <<< "$(user xray vless alice)")" == true ]] || fail $LINENO
[[ "$(q --arg id "$id" '.accounts[$id] | "\(.rev)|\(.mtime.quota)"')" == "$((rev0 + 1))|$now" ]] || fail $LINENO
_db_apply '.xray.vless.users[1].used = 10'
accounts_apply
[[ "$(q --arg id "$id" '.accounts[$id].cycle_used')" == 120 ]] || fail $LINENO
db_account_set "$id" quota 200
[[ "$(q --arg id "$id" '.accounts[$id].rev')" == "$((rev0 + 1))" ]] || fail $LINENO
echo 'PASS raising quota resumes, counter reset counted once, unchanged value keeps rev'

# 5. 周期切换清零并恢复超额；手动停用不被恢复
db_account_set "$id" quota 100
_db_apply '.xray.vless.users[1].used = 10'
accounts_apply
[[ "$(jq -r '.disable_reason' <<< "$(user xray vless alice)")" == quota ]] || fail $LINENO
today=2026-11-05; accounts_apply
[[ "$(q --arg id "$id" '.accounts[$id] | "\(.cycle)|\(.cycle_used)"')" == "2026-11-05|0" ]] || fail $LINENO
[[ "$(jq -r '.enabled' <<< "$(user xray vless alice)")" == true ]] || fail $LINENO
db_account_set "$id" enabled false
[[ "$(jq -r '"\(.enabled)|\(.disable_reason)"' <<< "$(user singbox hy2 alice)")" == "false|manual" ]] || fail $LINENO
today=2026-12-05; accounts_apply
[[ "$(jq -r '.enabled' <<< "$(user singbox hy2 alice)")" == false ]] || fail $LINENO
db_account_set "$id" enabled true
echo 'PASS monthly rollover clears usage and resumes, manual disable survives rollover'

# 6. 到期停用、延长恢复；重置日修改保留用量
today=2027-01-01; accounts_apply
[[ "$(jq -r '"\(.enabled)|\(.disable_reason)"' <<< "$(user xray vless alice)")" == "false|expired" ]] || fail $LINENO
db_account_set "$id" expire_date 2027-06-30
[[ "$(jq -r '"\(.enabled)|\(.expire_date)"' <<< "$(user xray vless alice)")" == "true|2027-06-30" ]] || fail $LINENO
_db_apply --arg id "$id" '.accounts[$id].cycle_used = 42'
db_account_set "$id" reset_day 0
[[ "$(q --arg id "$id" '.accounts[$id] | "\(.cycle)|\(.cycle_used)"')" == "total|42" ]] || fail $LINENO
today=2027-02-10; accounts_apply
[[ "$(q --arg id "$id" '.accounts[$id].cycle_used')" == 42 ]] || fail $LINENO
db_account_set "$id" reset_day 1
[[ "$(q --arg id "$id" '.accounts[$id] | "\(.cycle)|\(.cycle_used)"')" == "2027-02-01|42" ]] || fail $LINENO
echo 'PASS expiry and extension, reset-day change keeps usage'

# 7. 归入已有用户：保留凭据、计入已用、清除旧计费字段；不可重复归属
db_account_member_add "$id" xray trojan 1 bob true
b=$(user xray trojan bob)
[[ "$(jq -r '"\(.uuid)|\(.account_id)|\(.quota)|\(.panel_quota)"' <<< "$b")" == "bob-secret|$id|0|null" ]] || fail $LINENO
[[ "$(q --arg id "$id" '.accounts[$id].cycle_used')" == 72 ]] || fail $LINENO
id2=$(db_account_create dave 0 "" 0)
if db_account_member_add "$id2" xray trojan 1 bob 2>/dev/null; then echo 'double ownership accepted'; exit 1; fi
db_account_member_add "$id2" xray trojan 2 carol false
[[ "$(q --arg id "$id2" '.accounts[$id].cycle_used')" == 0 ]] || fail $LINENO
echo 'PASS claim keeps credentials and usage, strips panel billing, prevents double ownership'

# 8. platform_block、解除平台关联
_db_apply --arg id "$id" '.accounts[$id].platform_user_id = "11111111-2222-4333-8444-555555555555" | .accounts[$id].platform_block = "quota"'
accounts_apply
[[ "$(jq -r '"\(.enabled)|\(.disable_reason)"' <<< "$(user xray trojan bob)")" == "false|platform_quota" ]] || fail $LINENO
db_account_unlink_platform "$id"
[[ "$(jq -r '.enabled' <<< "$(user xray trojan bob)")" == true ]] || fail $LINENO
[[ "$(q --arg id "$id" '.accounts[$id].platform_user_id')" == null ]] || fail $LINENO
echo 'PASS platform block and unlink'

# 9. 重置凭据：单个成员与全部；实例级同值凭据同步
_db_apply '.singbox.hy2.password = .singbox.hy2.users[0].uuid'
old_v=$(jq -r .uuid <<< "$(user xray vless alice)"); old_h=$(jq -r .uuid <<< "$(user singbox hy2 alice)")
db_account_reset_credentials "$id" singbox hy2 8443 alice
[[ "$(jq -r .uuid <<< "$(user xray vless alice)")" == "$old_v" ]] || fail $LINENO
new_h=$(jq -r .uuid <<< "$(user singbox hy2 alice)")
[[ "$new_h" != "$old_h" && "$(q .singbox.hy2.password)" == "$new_h" ]] || fail $LINENO
db_account_reset_credentials "$id"
[[ "$(jq -r .uuid <<< "$(user xray vless alice)")" != "$old_v" && "$(q '.xray.vless.users[0].uuid')" == row-secret ]] || fail $LINENO
echo 'PASS credential reset for one member or all, row credential kept in sync'

# 10. Snell 成员（独立实例）
db_account_member_new "$id" xray snell-v5 0
[[ "$(jq -r '"\(.account_id)|\(.expire_date)"' <<< "$(user xray snell-v5 alice)")" == "$id|2027-06-30" ]] || fail $LINENO
[[ "$(q --arg id "$id" '[.accounts[$id].members[] | select(.protocol == "snell-v5") | .port][0]')" == 9001 ]] || fail $LINENO
echo 'PASS Snell member via dedicated instance'

# 11. 外部删除协议用户：成员自动移除且 rev 增加；移除成员保留或删除
rev=$(q --arg id "$id" '.accounts[$id].rev')
_db_apply '.xray.trojan[0].users = []'
accounts_apply
[[ "$(q --arg id "$id" '[.accounts[$id].members[] | select(.protocol == "trojan")] | length')" == 0 ]] || fail $LINENO
(( $(q --arg id "$id" '.accounts[$id].rev') == rev + 1 )) || fail $LINENO
db_account_member_remove "$id" singbox hy2 8443 alice release
[[ "$(jq -r '.account_id' <<< "$(user singbox hy2 alice)")" == null ]] || fail $LINENO
db_account_member_remove "$id" xray snell-v5 9001 alice delete
[[ "$(q '.xray["snell-v5"] | length')" == 0 ]] || fail $LINENO
if db_account_member_remove "$id" xray vless 443 default delete; then exit 1; fi
echo 'PASS external deletion detected, release keeps user, delete removes user'

# 12. 批量归并候选：同名协议用户（排除 default 与已归属）
_db_apply '.singbox.hy2.users += [{"name":"erin","uuid":"e1","used":1,"enabled":true,"expire_date":"2027-01-01"}] | .xray.trojan[1].users += [{"name":"erin","uuid":"e2","used":2,"enabled":true,"expire_date":"2027-03-01"}]'
[[ "$(_account_merge_candidates | grep '^erin|' | cut -d'|' -f2)" == "2027-03-01" ]] || fail $LINENO
[[ "$(_account_merge_candidates | grep -c '^erin|')" == 1 ]] || fail $LINENO
! _account_merge_candidates | grep -Eq '^(default|alice|carol)\|' || fail $LINENO
_db_apply '.singbox.hy2.users |= map(if .name == "erin" then .expire_date = "" else . end)'
[[ "$(_account_merge_candidates | grep '^erin|' | cut -d'|' -f2)" == "" ]] || fail $LINENO
echo 'PASS merge candidates by name with latest-or-none expiry'

# 13. 删除统一用户（保留成员）与全局月重置跳过成员
db_account_delete "$id" release
[[ "$(q --arg id "$id" '.accounts[$id]')" == null && "$(jq -r .account_id <<< "$(user xray vless alice)")" == null ]] || fail $LINENO
db_list_protocols() { [[ "$1" == xray ]] && echo trojan; }
db_reset_user_traffic() { echo "$3" >> "$fixture/reset"; }
TRAFFIC_MONTHLY_RESET_LAST_FILE="$fixture/monthly"
reset_monthly_user_traffic >/dev/null
grep -qx erin "$fixture/reset" || fail $LINENO
! grep -qx carol "$fixture/reset" || fail $LINENO
echo 'PASS delete keeps members as plain users, global monthly reset skips account members'

# 14. 菜单辅助：成员保护、到期输入、可选实例与可归入用户
id3=$(db_account_create frank 0 "" 0)
db_account_member_add "$id3" xray trojan 2 erin true
if _account_member_guard xray trojan 2>/dev/null erin; then fail $LINENO; fi
_account_member_guard singbox hy2 erin || fail $LINENO
[[ "$(_account_ask_expire 2027-01-01 <<< '' 2>/dev/null)" == 2027-01-01 ]] || fail $LINENO
[[ "$(_account_ask_expire 2027-01-01 <<< 0 2>/dev/null)" == "" ]] || fail $LINENO
[[ "$(_account_ask_expire '' <<< 2028-02-03 2>/dev/null)" == 2028-02-03 ]] || fail $LINENO
if _account_ask_expire '' <<< 'tomorrow' >/dev/null 2>&1; then fail $LINENO; fi
inst=$(_account_instances)
grep -qx 'xray|vless|443' <<< "$inst" || fail $LINENO
grep -qx 'singbox|hy2|8443' <<< "$inst" || fail $LINENO
claim=$(_account_claimable_users)
grep -q '^singbox|hy2|8443|erin|' <<< "$claim" || fail $LINENO
! grep -q '|trojan|2|erin|' <<< "$claim" || fail $LINENO
[[ "$(_account_reason_text platform_quota)" == 平台总流量已用尽 ]] || fail $LINENO
echo 'PASS menu helpers: member guard, expiry input, instance and claimable listings'

# 15. 菜单流程冒烟：新建→添加协议→修改配额→查看分享→批量归并→删除
_header() { :; }; _line() { :; }; _dline() { :; }; _item() { :; }; _pause() { read -r _ || true; }
traffic_cron_entry_exists() { return 0; }
_gen_user_share_link() { echo "LINK $2 $5 $4" >> "$fixture/links"; }
D=; C=; W=; G=; R=; Y=; NC=
# 现有统一用户按名称排序为 dave、frank，新建的 grace 排第 3。
printf '%s\n' 1 grace 5 30 1 "" y 1 "" "" 2 3 2 50 "" 0 6 3 "" 0 | manage_accounts >/dev/null 2>&1 || true
gid=$(db_account_find grace)
[[ -n "$gid" ]] || fail $LINENO
[[ "$(q --arg id "$gid" '.accounts[$id] | "\(.quota)|\(.reset_day)|\(.members | length)"')" == "53687091200|1|1" ]] || fail $LINENO
grep -q '^LINK ' "$fixture/links" || fail $LINENO
printf '%s\n' m y "" 0 | manage_accounts >/dev/null 2>&1 || true
[[ "$(q --arg id "$(db_account_find alice)" '.accounts[$id].members | length')" == 2 ]] || fail $LINENO
gidx=$(db_account_list | awk -F'|' '$2 == "grace" {print NR}')
printf '%s\n' 9 "$gidx" 2 y "" 0 | manage_accounts >/dev/null 2>&1 || true
[[ -z "$(db_account_find grace)" ]] || fail $LINENO
[[ "$(q '[.xray.vless.users[].name] | index("grace")')" == null ]] || fail $LINENO
echo 'PASS interactive menu smoke: create, add protocol, edit quota, share, merge, delete'
