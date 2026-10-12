#!/usr/bin/env bash
# 完整 CLI 进程联调：以 root 运行真实脚本的 --api account_apply，并由 Agent 的 ScriptAPI 调用。
# 只在 Bash 4.1+、root、且 /etc/vless-reality 不存在（隔离的 CI 环境）时执行，其余环境跳过。
set -e -o pipefail
fail() { echo "FAIL line $1"; exit 1; }
repo=$(cd "$(dirname "$0")/.." && pwd)
if (( BASH_VERSINFO[0] * 100 + BASH_VERSINFO[1] < 401 )) || [[ $EUID -ne 0 ]] || [[ -e /etc/vless-reality ]]; then
    echo 'SKIP accounts CLI integration (needs root, Bash 4.1+ and an unused /etc/vless-reality)'
    # GitHub Actions must really run it; a silent skip there would hide a broken setup.
    [[ "${CI:-}" != true ]] || fail $LINENO
    exit 0
fi
command -v flock >/dev/null || { echo 'SKIP accounts CLI integration (needs flock)'; [[ "${CI:-}" != true ]] || fail $LINENO; exit 0; }
trap 'rm -rf /etc/vless-reality' EXIT
mkdir -p /etc/vless-reality
cat > /etc/vless-reality/db.json <<'JSON'
{"version":"4.0.0","xray":{"vless":{"port":443,"uuid":"ROW_SECRET","sni":"a.example","users":[
  {"name":"default","uuid":"ROW_SECRET","enabled":true,"used":0,"quota":0,"expire_date":""},
  {"name":"bob","uuid":"BOB_SECRET","enabled":true,"used":7,"quota":0,"expire_date":""}]}},"singbox":{},"meta":{"user_authority":"platform"}}
JSON
call() { printf '%s' "$1" | bash "$repo/vless-server.sh" --api 2>/dev/null || true; }
A=11111111-1111-4111-8111-111111111111
B=33333333-3333-4333-8333-333333333333
P=22222222-2222-4222-8222-222222222222

out=$(call '{"api_version":1,"request_id":"cap","action":"capabilities"}')
[[ "$(jq -r '"\(.data.accounts_api.version)|\(.data.user_authority)"' <<< "$out")" == "3|platform" ]] || fail $LINENO

req=$(jq -nc --arg a "$A" --arg p "$P" '{api_version:1,request_id:"cli-create",action:"account_apply",params:{ops:[
  {op:"create",account_id:$a,platform_user_id:$p,fields:{name:"bob",reset_day:1}},
  {op:"member_claim",account_id:$a,target:{core:"xray",protocol:"vless",port:443},name:"bob"}]}}')
out=$(call "$req")
[[ "$(jq -r .status <<< "$out")" == succeeded ]] || { echo "$out"; fail $LINENO; }
rev=$(jq -r ".data.accounts[\"$A\"].rev" <<< "$out")
[[ "$(call "$req" | jq -r ".data.accounts[\"$A\"].rev")" == "$rev" ]] || fail $LINENO
[[ "$(jq -r '.xray.vless.users[1] | "\(.account_id)|\(.uuid)"' /etc/vless-reality/db.json)" == "$A|BOB_SECRET" ]] || fail $LINENO
[[ "$(stat -c %a /etc/vless-reality/api-results)" == 700 && "$(stat -c %a "/etc/vless-reality/api-results/cli-create.json")" == 600 ]] || fail $LINENO

# 并发：两个请求在真实 flock 下串行执行，各自成功，版本号连续
one=$(jq -nc --arg a "$A" --argjson r "$rev" '{api_version:1,request_id:"cli-u1",action:"account_apply",params:{ops:[{op:"update",account_id:$a,base_rev:$r,fields:{note:"one"}}]}}')
two=$(jq -nc --arg b "$B" '{api_version:1,request_id:"cli-u2",action:"account_apply",params:{ops:[{op:"create",account_id:$b,fields:{name:"carol"}}]}}')
call "$one" > /tmp/vaio-cli-one & call "$two" > /tmp/vaio-cli-two & wait
[[ "$(jq -r .status /tmp/vaio-cli-one)|$(jq -r .status /tmp/vaio-cli-two)" == "succeeded|succeeded" ]] || { cat /tmp/vaio-cli-one /tmp/vaio-cli-two; fail $LINENO; }
[[ "$(jq -r --arg a "$A" '.accounts[$a].rev' /etc/vless-reality/db.json)" == "$((rev + 1))" ]] || fail $LINENO
out=$(call "$one")
[[ "$(jq -r .status <<< "$out")" == succeeded ]] || fail $LINENO
out=$(call "$(jq -c '.request_id = "cli-u3"' <<< "$one")")
[[ "$(jq -r '"\(.code)|\(.data.rev)"' <<< "$out")" == "rev_conflict|$((rev + 1))" ]] || fail $LINENO

out=$(call '{"api_version":1,"request_id":"inv","action":"inventory"}')
! grep -q SECRET <<< "$out" || fail $LINENO
[[ "$(jq -r ".data.accounts[\"$A\"] | \"\(.note)|\(.platform_user_id)|\(.members[0].used)\"" <<< "$out")" == "one|$P|7" ]] || fail $LINENO
echo 'PASS real CLI process: capabilities, transaction, idempotency, file modes, concurrent flock, rev conflict, redacted inventory'

# Agent ScriptAPI 直接调用真实（vendor）脚本：任务 ID 即幂等键，结果可查询
cd "$repo/platform"
python3 - "$A" <<'PY'
import sys, uuid
from agent.script_api import ScriptAPI
account = sys.argv[1]
api = ScriptAPI()
status = api.status()
assert status['status'] == 'ready' and status['accounts_api'] >= 1, status
db = __import__('json').load(open('/etc/vless-reality/db.json'))
task = str(uuid.uuid4())
reply = api.write({'ops': [{'op': 'update', 'account_id': account, 'base_rev': db['accounts'][account]['rev'], 'fields': {'note': 'agent'}}]}, task)
assert reply['status'] == 'succeeded', reply
assert api.result(task)['status'] == 'succeeded'
assert api.result(str(uuid.uuid4()))['code'] == 'result_not_found'
link = api.share({'core': 'xray', 'protocol': 'vless', 'port': 443}, 'bob', '203.0.113.5')
assert link.startswith('vless://') and '203.0.113.5:443' in link and 'BOB_SECRET' in link, link
try:
    api.share({'core': 'xray', 'protocol': 'vless', 'port': 443}, 'nobody', '203.0.113.5')
    raise AssertionError('unknown member shared')
except ValueError:
    pass
PY
[[ "$(jq -r --arg a "$A" '.accounts[$a].note' /etc/vless-reality/db.json)" == agent ]] || fail $LINENO
echo 'PASS agent ScriptAPI against the vendored script'

# 切换用户管理方式：脚本模式拒绝写用户；接管时清空用户与凭据（真实进程）
out=$(call '{"api_version":1,"request_id":"cli-to-script","action":"account_apply","params":{"ops":[{"op":"set_authority","mode":"script"}]}}')
[[ "$(jq -r '"\(.status)|\(.data.user_authority)"' <<< "$out")" == "succeeded|script" ]] || { echo "$out"; fail $LINENO; }
out=$(call "$(jq -nc --arg a "$A" '{api_version:1,request_id:"cli-denied",action:"account_apply",params:{ops:[{op:"reset_usage",account_id:$a}]}}')")
[[ "$(jq -r .code <<< "$out")" == authority_script ]] || fail $LINENO
out=$(call '{"api_version":1,"request_id":"cli-takeover","action":"account_apply","params":{"ops":[{"op":"set_authority","mode":"platform"}]}}')
[[ "$(jq -r '"\(.status)|\(.data.user_authority)"' <<< "$out")" == "succeeded|platform" ]] || { echo "$out"; fail $LINENO; }
[[ "$(jq -r '"\(.xray.vless.users | length)|\(.accounts)"' /etc/vless-reality/db.json)" == "0|null" ]] || fail $LINENO
! grep -q SECRET /etc/vless-reality/db.json || fail $LINENO
echo 'PASS real CLI process: authority switch, script-mode rejection, takeover clears users and credentials'
