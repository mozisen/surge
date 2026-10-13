#!/usr/bin/env bash
# 以平台为准时 TG 通知由平台管理：清除本机配置与机器人轮询、发送函数静默、菜单只读；脚本模式不变。函数级隔离测试。
set -e -o pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
# Bash 3.2 的 set -e 不处理 [[ ]] 失败，断言统一显式失败。
fail() { echo "FAIL line $1"; exit 1; }
CFG="$fixture"; DB_FILE="$fixture/db.json"
TG_CONFIG_FILE="$fixture/telegram.json"; TG_CONFIG_LOCK_DIR="$fixture/.telegram.lock"
eval "$(grep -m1 '^readonly TG_CONFIG_DEFAULTS=' "$script" | sed 's/^readonly //')"
[[ -n "$TG_CONFIG_DEFAULTS" ]] || fail $LINENO
load() {
    local body
    body=$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$script")
    [[ -n "$body" ]] || { echo "missing $1"; exit 1; }
    eval "$body"
}
for fn in db_authority_get _tg_config_lock_acquire _tg_config_lock_release init_tg_config tg_get_config tg_set_config \
    _tg_platform_mode _tg_platform_cleanup tg_send_message send_tg_message tg_send_bound_user_message check_daily_report \
    tg_poll_user_bot _configure_tg_notify _db_apply tg_send_chat_message; do
    load "$fn"
done
_db_lock_acquire() { :; }; _db_lock_release() { :; }
_warn() { echo "WARN $*" >> "$fixture/messages"; }; _err() { echo "ERR $*" >> "$fixture/messages"; }
_ok() { :; }; _info() { :; }; _line() { :; }; _dline() { :; }; _header() { :; }; _pause() { :; }
W=''; NC=''; D=''; G=''; R=''; Y=''
cron=true
tg_user_bot_cron_entry_exists() { [[ "$cron" == true ]]; }
remove_tg_user_bot_cron() { cron=false; echo removed >> "$fixture/cron"; }
curl() { echo "curl $*" >> "$fixture/curl"; echo '{"ok":true,"result":[]}'; }
db_get_user_field() { echo 12345; }
# 本地 Bash 3.2 没有 mapfile；CI 的 Bash 5 使用内置命令。
type mapfile >/dev/null 2>&1 || mapfile() { local line; eval "$2=()"; while IFS= read -r line; do eval "$2+=(\"\$line\")"; done; }
tg_bot_api_request() { echo "api $1" >> "$fixture/curl"; echo '{"ok":true,"result":[]}'; }
db_get_tg_config() { jq -r --arg f "$1" '.telegram[$f] // ""' "$DB_FILE"; }
configured='{"enabled":true,"bot_token":"123456:SECRET_TOKEN_SECRET_TOKEN_1","chat_id":"999","notify_quota_percent":70,"notify_daily":true,"server_name":"hk","user_bot_enabled":true,"user_bot_update_offset":5,"daily_report_hour":9}'

# 1. 脚本模式：配置保留，发送照常，机器人照常轮询
echo '{"meta":{},"telegram":{"bot_token":"OLD","chat_id":"1"}}' > "$DB_FILE"
printf '%s\n' "$configured" > "$TG_CONFIG_FILE"
_tg_platform_mode && fail $LINENO
_tg_platform_cleanup || fail $LINENO
[[ "$(jq -r .bot_token "$TG_CONFIG_FILE")" == 123456:SECRET_TOKEN_SECRET_TOKEN_1 ]] || fail $LINENO
[[ "$cron" == true && "$(jq -r .telegram.bot_token "$DB_FILE")" == OLD ]] || fail $LINENO
tg_send_message "hello"
grep -q 'sendMessage' "$fixture/curl" || fail $LINENO
tg_send_bound_user_message xray vless alice "hi"
grep -q 'api sendMessage' "$fixture/curl" || fail $LINENO
: > "$fixture/curl"
tg_poll_user_bot
grep -q 'api getUpdates' "$fixture/curl" || fail $LINENO
echo 'PASS script mode keeps TG configuration, alerts and the user bot'

# 2. 平台模式：清空本机 TG 配置、旧数据库配置和机器人轮询；文件保持 600
echo '{"meta":{"user_authority":"platform"},"telegram":{"bot_token":"OLD","chat_id":"1"}}' > "$DB_FILE"
_tg_platform_mode || fail $LINENO
_tg_platform_cleanup || fail $LINENO
jq -e --argjson d "$TG_CONFIG_DEFAULTS" '. == $d' "$TG_CONFIG_FILE" >/dev/null || fail $LINENO
! grep -q SECRET "$TG_CONFIG_FILE" || fail $LINENO
[[ "$(jq 'has("telegram")' "$DB_FILE")" == false ]] || fail $LINENO
[[ "$cron" == false ]] || fail $LINENO
mode=$(stat -f '%Lp' "$TG_CONFIG_FILE" 2>/dev/null || stat -c '%a' "$TG_CONFIG_FILE")
[[ "$mode" == 600 ]] || fail $LINENO
echo 'PASS platform mode clears TG configuration, legacy database settings and the bot cron'

# 3. 幂等：已是默认配置时不重写文件
before=$(ls -li "$TG_CONFIG_FILE" | awk '{print $1}')
_tg_platform_cleanup || fail $LINENO
[[ "$(ls -li "$TG_CONFIG_FILE" | awk '{print $1}')" == "$before" ]] || fail $LINENO
[[ "$(wc -l < "$fixture/cron" | tr -d ' ')" == 1 ]] || fail $LINENO
echo 'PASS cleanup is idempotent'

# 4. 平台模式下即使配置被手动写回，也不发送任何消息；机器人轮询先清理再退出
printf '%s\n' "$configured" > "$TG_CONFIG_FILE"; cron=true
echo '{"meta":{"user_authority":"platform"},"telegram":{"bot_token":"OLD","chat_id":"1"}}' > "$DB_FILE"
: > "$fixture/curl"
tg_send_message "x"; send_tg_message "x"; tg_send_bound_user_message xray vless alice "x"; check_daily_report
[[ ! -s "$fixture/curl" ]] || fail $LINENO
tg_poll_user_bot || fail $LINENO
[[ ! -s "$fixture/curl" ]] || fail $LINENO
jq -e --argjson d "$TG_CONFIG_DEFAULTS" '. == $d' "$TG_CONFIG_FILE" >/dev/null || fail $LINENO
[[ "$cron" == false ]] || fail $LINENO
echo 'PASS platform mode sends nothing and the bot poll cleans up and exits'

# 5. 菜单只读：提示由平台管理，不进入配置循环
printf '%s\n' "$configured" > "$TG_CONFIG_FILE"
out=$(_configure_tg_notify < /dev/null)
grep -q 'TG 通知由 Vaio 平台管理' <<< "$out" || fail $LINENO
! grep -q '设置 Bot Token' <<< "$out" || fail $LINENO
jq -e --argjson d "$TG_CONFIG_DEFAULTS" '. == $d' "$TG_CONFIG_FILE" >/dev/null || fail $LINENO
echo 'PASS platform mode TG menu is read-only'

# 6. 切到平台：_authority_apply 在写入平台模式后调用清理
grep -q '_tg_platform_cleanup || _warn "本机 TG 配置清理失败' "$script" || fail $LINENO
awk '/^_authority_apply\(\) \{/{on=1} on&&/_tg_platform_cleanup/{print "found"; exit} on&&/^}/{exit}' "$script" | grep -q found || fail $LINENO
awk '/^sync_all_user_traffic\(\) \{/{on=1} on&&/_tg_platform_cleanup/{print "found"; exit} on&&/^}/{exit}' "$script" | grep -q found || fail $LINENO
echo 'PASS takeover and traffic sync call the cleanup'
