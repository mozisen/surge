#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
eval "$(awk 'index($0,"_regenerate_config() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
CFG="$fixture"
DISTRO=debian
_info() { :; }
_ok() { :; }
_err() { echo "err:$*" >> "$fixture/events"; }
_snell_managed() { return 1; }
systemctl() { :; }
rc-service() { :; }
rebuild_and_reload_xray() { echo rebuild >> "$fixture/events"; }
db_get_field() {
    case "$3" in
        users) echo '[{"name":"alice","uuid":"aaaaaaaa-0000-4000-8000-000000000001","enabled":true}]' ;;
        uuid) echo "aaaaaaaa-0000-4000-8000-000000000000" ;;
    esac
}
# Reality(vision) 和 Reality+XHTTP 两个 VLESS 入站，各有自己的用户。
jq -n '{inbounds:[
  {tag:"vless",protocol:"vless",settings:{clients:[{id:"reality-user",email:"default@vless",flow:"xtls-rprx-vision"}]},streamSettings:{network:"raw",security:"reality"}},
  {tag:"vless-xhttp",protocol:"vless",settings:{clients:[{id:"xhttp-user",email:"default@vless-xhttp"}]},streamSettings:{network:"xhttp",security:"reality"}}
],outbounds:[{tag:"direct",protocol:"freedom"}],routing:{rules:[]}}' > "$CFG/config.json"
cp "$CFG/config.json" "$fixture/before.json"

for proto in vless vless-xhttp; do
    : > "$fixture/events"
    _regenerate_config xray "$proto"
    # 增删某个协议的用户不能改写其他 VLESS 入站，也不能给 XHTTP 加 vision flow。
    jq -e '.inbounds[] | select(.tag == "vless-xhttp") | .settings.clients == [{id:"xhttp-user",email:"default@vless-xhttp"}]' "$CFG/config.json" >/dev/null || exit 1
    jq -e '.inbounds[] | select(.tag == "vless") | .settings.clients[0].id == "reality-user"' "$CFG/config.json" >/dev/null || exit 1
    grep -qx rebuild "$fixture/events" || exit 1
done
cmp -s "$fixture/before.json" "$CFG/config.json" || exit 1
echo 'PASS Xray user changes rebuild the full config without overwriting other VLESS inbounds'
