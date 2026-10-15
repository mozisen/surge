#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
load() { eval "$(awk -v fn="$1" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"; }
load _get_singbox_stat_user_mappings
load _singbox_stats_config_ready
CFG="$fixture"; DB_FILE="$fixture/db.json"
cat > "$DB_FILE" <<'JSON'
{"singbox":{"ss2022":{"port":2001,"password":"server","users":[{"name":"alice","uuid":"a"},{"name":"bob","uuid":"b"}]},
            "ss-legacy":[{"port":2002,"users":[{"name":"carol","uuid":"c"},{"name":"dave","uuid":"d"}]}]}}
JSON
[[ "$(_get_singbox_stat_user_mappings ss2022 | tr '\n' ' ')" == 'alice|ss2022-alice bob|ss2022-bob ' ]]
# The repair check requires the multi-user SS2022 names in the statistics users.
jq -n '{inbounds:[{type:"shadowsocks",listen_port:2001,tag:"a",users:[{name:"ss2022-alice"},{name:"ss2022-bob"}]},
                  {type:"shadowsocks",listen_port:2002,tag:"b",users:[{name:"ss-legacy-carol"},{name:"ss-legacy-dave"}]}],
        experimental:{v2ray_api:{listen:"127.0.0.1:1",stats:{enabled:true,users:["ss-legacy-carol","ss-legacy-dave"],inbounds:[]}}}}' > "$CFG/singbox.json"
if _singbox_stats_config_ready; then exit 1; fi
jq '.experimental.v2ray_api.stats.users += ["ss2022-alice","ss2022-bob"]' "$CFG/singbox.json" > "$fixture/next" && mv "$fixture/next" "$CFG/singbox.json"
_singbox_stats_config_ready
# The per-user sync loop counts SS2022 named users as well.
grep -q 'for proto in vless trojan hy2 tuic anytls ss-legacy ss2022; do' <(awk 'index($0,"_sync_all_user_traffic_unlocked() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")
echo 'PASS multi-user SS2022 statistics keys, repair check and per-user sync'
