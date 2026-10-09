#!/usr/bin/env bash
set -e
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
trap 'rm -rf "$fixture"' EXIT
DB_FILE="$fixture/db.json" VERSION=3.7.2
XRAY_PROTOCOLS='vless trojan'
SINGBOX_PROTOCOLS='hy2 anytls'
STANDALONE_PROTOCOLS='snell snell-v5 snell-v6'
for fn in _api_reply _api_inventory _api_dispatch; do
    eval "$(awk -v fn="$fn" 'index($0,fn"() {")==1 {on=1} on {print} on && $0=="}" {exit}' "$repo/vless-server.sh")"
done
printf '%s' '{"xray":{"vless":[{"port":10001,"uuid":"SECRET_UUID","private_key":"SECRET_KEY","users":[{"name":"one","uuid":"SECRET_USER","used":123,"telegram_chat_id":"SECRET_CHAT"}]},{"port":10002,"uuid":"SECRET_OTHER"}],"snell-v6":[{"port":20001,"snell_id":"aaaaaaaaaaaaaaaaaaaaaaaa","psk":"SECRET_PSK","users":[]}]},"singbox":{"hy2":{"port":30001,"password":"SECRET_PASSWORD"}}}' > "$DB_FILE"
before=$(cat "$DB_FILE")
call_api() { _api_dispatch <<< "$1" > "$fixture/out" || true; jq -e . "$fixture/out" >/dev/null; }
call_api '{"api_version":1,"request_id":"cap","action":"capabilities"}'
jq -e '.status=="succeeded" and .data.write_actions==[]' "$fixture/out" >/dev/null
call_api '{"api_version":1,"request_id":"inv","action":"inventory"}'
! grep -q SECRET "$fixture/out"
jq -e '.data.instances|length==4' "$fixture/out" >/dev/null
jq -e '.data.instances[]|select(.target.protocol=="snell-v6")|.target.core=="standalone" and .instance_id=="aaaaaaaaaaaaaaaaaaaaaaaa"' "$fixture/out" >/dev/null
revision=$(jq -r .data.revision "$fixture/out")
call_api "$(jq -nc --arg r "$revision" '{api_version:1,request_id:"plan",action:"plan",expected_revision:$r,target:{core:"xray",protocol:"vless",port:10001},params:{action:"delete"}}')"
jq -e '.code=="unsupported_operation" and .data.executable==false' "$fixture/out" >/dev/null
call_api '{"api_version":1,"request_id":"plan","action":"plan","expected_revision":"stale"}'
jq -e '.code=="revision_conflict"' "$fixture/out" >/dev/null
for action in install update delete start stop restart user_add user_update user_delete share migrate shell; do
    call_api "$(jq -nc --arg a "$action" '{api_version:1,request_id:"write",action:$a,params:{command:"touch /tmp/should-not-execute"}}')"
    jq -e '.code=="unsupported_operation"' "$fixture/out" >/dev/null
done
call_api '{"api_version":1,"request_id":"old-task","action":"result"}'
jq -e '.status=="unknown" and .data.replay_allowed==false' "$fixture/out" >/dev/null
call_api '{} {}'
jq -e '.code=="invalid_json"' "$fixture/out" >/dev/null
[[ "$(cat "$DB_FILE")" == "$before" ]]
duplicate=$(jq -c '.xray.vless += [.xray.vless[0]]' "$DB_FILE")
printf '%s' "$duplicate" > "$DB_FILE"
call_api '{"api_version":1,"request_id":"inv","action":"inventory"}'
revision=$(jq -r .data.revision "$fixture/out")
call_api "$(jq -nc --arg r "$revision" '{api_version:1,request_id:"dup",action:"plan",expected_revision:$r,target:{core:"xray",protocol:"vless",port:10001},params:{action:"delete"}}')"
jq -e '.code=="ambiguous_target"' "$fixture/out" >/dev/null
call_api "$(jq -nc --arg r "$revision" '{api_version:1,request_id:"missing",action:"plan",expected_revision:$r,target:{core:"xray",protocol:"vless",port:65535},params:{action:"delete"}}')"
jq -e '.code=="target_not_found"' "$fixture/out" >/dev/null
printf '%s' '{broken' > "$DB_FILE"
call_api '{"api_version":1,"request_id":"inv","action":"inventory"}'
jq -e '.code=="invalid_database"' "$fixture/out" >/dev/null
echo 'PASS API framing, redaction, inventory, revision checks, no writes and no replay'
