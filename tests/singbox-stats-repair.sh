#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
CFG="$fixture"
eval "$(awk 'index($0,"_prepare_singbox_stats_interactive() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
_pgrep() { return 0; }
_warn() { echo "$*"; }
_info() { echo "$*"; }
_ok() { echo "$*"; }
_err() { echo "$*"; }
singbox_stats_available() { [[ -f "$CFG/ready" ]]; }
_singbox_stats_config_ready() { [[ -f "$CFG/ready" ]]; }
singbox_api_query() { [[ -f "$CFG/ready" ]]; }
_repair_singbox_stats_interactive() {
    echo attempt >> "$CFG/attempts"
    echo 'fixture build failure'
    [[ "$succeed" == true ]] || return 1
    touch "$CFG/ready"
}
if _prepare_singbox_stats_interactive; then exit 1; fi
[[ "$(cat "$CFG/singbox-stats-repair.state")" == failed_or_cancelled ]]
if _prepare_singbox_stats_interactive; then exit 1; fi
[[ "$(wc -l < "$CFG/attempts" | tr -d ' ')" == 1 ]]
# A new invocation only relies on disk state; successful retry requires real health.
succeed=true
_prepare_singbox_stats_interactive true
[[ "$(cat "$CFG/singbox-stats-repair.state")" == ready ]]
_prepare_singbox_stats_interactive
[[ "$(wc -l < "$CFG/attempts" | tr -d ' ')" == 2 ]]
rm "$CFG/ready"
if _prepare_singbox_stats_interactive; then exit 1; fi
[[ "$(wc -l < "$CFG/attempts" | tr -d ' ')" == 2 ]]
echo 'PASS persistent failure suppresses repeated prompts, explicit retry works, live API overrides saved status'
