#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
script="${SCRIPT_UNDER_TEST:-$repo/vless-server.sh}"
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
CFG="$fixture"
load() { eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$script")"; }
for fn in ensure_cron_service_running _start_cron_service _install_cron_daemon setup_tg_user_bot_cron _enable_tg_user_bot; do load "$fn"; done
_info() { :; }; _warn() { :; }; _ok() { :; }; _err() { echo "$*" >> "$fixture/errors"; }
state=inactive; daemon_present=true; mode=systemd
cron_service_is_active() { [[ "$state" == active ]]; }
_cron_daemon_path() { [[ "$daemon_present" == true ]] && echo fake_crond; }
command() {
    if [[ "$1" == -v ]]; then
        case "$2" in
            systemctl) [[ "$mode" == systemd ]] && echo systemctl; return ;;
            rc-service|rc-update) [[ "$mode" == openrc ]] && echo "$2"; return ;;
            service) return 1 ;;
            crontab) echo crontab; return ;;
            dnf) return 1 ;;
        esac
    fi
    builtin command "$@"
}
systemctl() {
    echo "$*" >> "$fixture/systemctl"
    case "$1" in
        show-environment) return 0 ;;
        enable) return 1 ;; # Static/enable failure must not block start.
        start) [[ "$blocked" == true ]] && return 1; state=active ;;
    esac
}
rc-update() { return 0; }
rc-service() {
    echo "$*" >> "$fixture/openrc"
    [[ "$1" == dcron && "$2" == start ]] || return 1
    state=active
}
fake_crond() { state=active; echo started >> "$fixture/raw"; }
blocked=false
ensure_cron_service_running false
[[ "$state" == active ]]
grep -q 'start cron' "$fixture/systemctl"
state=inactive; blocked=true
if ensure_cron_service_running false; then exit 1; fi
[[ ! -e "$fixture/raw" ]] # Never bypass a failed/masked managed service.
grep -q 'cron-service.log' "$fixture/errors"
state=inactive; blocked=false; mode=openrc
ensure_cron_service_running false
grep -q 'dcron start' "$fixture/openrc"
state=inactive; mode=container
ensure_cron_service_running false
[[ -e "$fixture/raw" ]]

# Package selection and partial installs (crontab present, daemon absent).
mode=systemd; state=inactive; daemon_present=false; DISTRO=debian
apt-get() { echo "apt $*" >> "$fixture/packages"; [[ "$1" == install ]] && daemon_present=true; return 0; }
apk() { echo "apk $*" >> "$fixture/packages"; daemon_present=true; }
yum() { echo "yum $*" >> "$fixture/packages"; daemon_present=true; }
if ensure_cron_service_running false; then exit 1; fi
[[ ! -e "$fixture/packages" ]]
ensure_cron_service_running true
grep -q 'apt install -y cron' "$fixture/packages"
DISTRO=alpine; _install_cron_daemon
DISTRO=centos; _install_cron_daemon
grep -q 'apk add --no-cache cronie' "$fixture/packages"
grep -q 'yum install -y cronie' "$fixture/packages"
DISTRO=debian; state=inactive; daemon_present=false
apt-get() { return 1; }
if ensure_cron_service_running true; then exit 1; fi

# Local scheduler must work before writing a new bot rule.
printf '#!/bin/bash\n' > "$fixture/script"
chmod +x "$fixture/script"
readlink() { echo "$fixture/script"; }
get_bash_interpreter() { echo /bin/bash; }
build_cron_command() { echo 'test-command'; }
install_cron_entry() { echo written > "$fixture/rule"; }
ensure_cron_service_running() { return 1; }
if setup_tg_user_bot_cron; then exit 1; fi
[[ ! -e "$fixture/rule" ]]
ensure_cron_service_running() { return 0; }
setup_tg_user_bot_cron
[[ -e "$fixture/rule" ]]

# Test standard enable function without driving an interactive menu or Telegram.
tg_set_config() { echo "$2" > "$fixture/enabled"; }
remove_tg_user_bot_cron() { echo removed > "$fixture/removed"; }
traffic_cron_entry_exists() { return 0; }
tg_bot_api_request() {
    echo "$1" >> "$fixture/api"
    if [[ "$1" == deleteWebhook && "$webhook_fail" == true ]]; then
        echo '{"ok":false}'; return
    fi
    echo '{"ok":true,"result":{"username":"test_bot"}}'
}
webhook_fail=false
setup_tg_user_bot_cron() { return 1; }
if _enable_tg_user_bot; then exit 1; fi
! grep -q deleteWebhook "$fixture/api"
[[ "$(cat "$fixture/enabled")" == false ]]
setup_tg_user_bot_cron() { return 0; }
webhook_fail=true
if _enable_tg_user_bot; then exit 1; fi
[[ "$(cat "$fixture/enabled")" == false && -e "$fixture/removed" ]]
webhook_fail=false
_enable_tg_user_bot
[[ "$(cat "$fixture/enabled")" == true ]]
# Neither menu may interpolate the token into its display line.
! grep 'echo.*Bot Token:' "$script" | grep -q '\$.*bot_token'
echo 'PASS cron partial install, init variants, enable/start separation, managed failure, silent mode, rule ordering, Telegram failure recovery, token masking'
