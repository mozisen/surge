#!/usr/bin/env bash
# Optional real-core test: supply SINGBOX_TEST_BIN and GRPCURL_TEST_BIN.
set -e
: "${SINGBOX_TEST_BIN:?Supply a verified sing-box binary}"
: "${GRPCURL_TEST_BIN:?Supply a verified grpcurl binary}"
repo=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d)
pids=()
cleanup() { for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done; rm -rf "$fixture"; }
trap cleanup EXIT
for fn in singbox_api_query _singbox_stats_proto; do
    eval "$(awk -v fn="$fn" 'index($0, fn "() {") == 1 {on=1} on {print} on && $0 == "}" {exit}' "$repo/vless-server.sh")"
done
grpcurl() { "$GRPCURL_TEST_BIN" "$@"; }
SINGBOX_V2RAY_API_PORT=39886
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$fixture/key.pem" -out "$fixture/cert.pem" -days 1 -subj /CN=localhost >/dev/null 2>&1
python3 -m http.server 39880 --bind 127.0.0.1 --directory "$fixture" > "$fixture/http.log" 2>&1 &
pids+=("$!")
uuid=3b57c991-27ae-4ccc-a94f-043536883301
jq -n --arg cert "$fixture/cert.pem" --arg key "$fixture/key.pem" --arg uuid "$uuid" '{
 inbounds:[
 {type:"vless",tag:"vless",listen:"127.0.0.1",listen_port:39881,users:[{name:"vless-default",uuid:$uuid}]},
 {type:"anytls",tag:"anytls",listen:"127.0.0.1",listen_port:39882,users:[{name:"anytls-default",password:"test-password"}],tls:{enabled:true,certificate_path:$cert,key_path:$key}},
 {type:"trojan",tag:"trojan",listen:"127.0.0.1",listen_port:39883,users:[{name:"trojan-default",password:"test-password"}],tls:{enabled:true,certificate_path:$cert,key_path:$key}}
 ],outbounds:[{type:"direct",tag:"direct"}],experimental:{v2ray_api:{listen:"127.0.0.1:39886",stats:{enabled:true,users:["vless-default","anytls-default","trojan-default"]}}}
}' > "$fixture/server.json"
"$SINGBOX_TEST_BIN" run -c "$fixture/server.json" > "$fixture/server.log" 2>&1 &
pids+=("$!")
for attempt in 1 2 3 4 5; do singbox_api_query 'user>>>' false >/dev/null && break; sleep 1; done
for proto in vless anytls trojan; do
    case "$proto" in vless) port=39881 ;; anytls) port=39882 ;; trojan) port=39883 ;; esac
    jq -n --arg type "$proto" --argjson port "$port" --arg uuid "$uuid" '{
      inbounds:[{type:"mixed",listen:"127.0.0.1",listen_port:39884}],
      outbounds:[({type:$type,server:"127.0.0.1",server_port:$port} +
        if $type == "vless" then {uuid:$uuid} else {password:"test-password",tls:{enabled:true,insecure:true,server_name:"localhost"}} end)]
    }' > "$fixture/client.json"
    "$SINGBOX_TEST_BIN" run -c "$fixture/client.json" > "$fixture/client.log" 2>&1 &
    client_pid=$!; pids+=("$client_pid")
    success=false
    for attempt in 1 2 3 4 5; do
        if curl --noproxy '' --socks5-hostname 127.0.0.1:39884 -fsS --max-time 5 http://127.0.0.1:39880/cert.pem -o /dev/null 2>/dev/null; then success=true; break; fi
        sleep 1
    done
    [[ "$success" == true ]] || { cat "$fixture/server.log" "$fixture/client.log"; exit 1; }
    stats=$(singbox_api_query 'user>>>' false)
    printf '%s\n' "$stats" | awk -v key="user>>>$proto-default>>>traffic>>>downlink" '$1==key && $2>0 {ok=1} END {exit !ok}'
    kill "$client_pid"; wait "$client_pid" 2>/dev/null || true
    echo "PASS real $proto traffic produces named-user counters"
done
singbox_api_query 'user>>>' true >/dev/null
singbox_api_query 'user>>>' false | awk 'NF && $2!=0 {bad=1} END {exit bad}'
echo 'PASS real gRPC reset leaves zero counters'
