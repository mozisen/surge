import fcntl
import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent.__main__ import Agent
from agent.bridge import Bridge, TransactionRolledBack, TransactionUnknown
from agent.inventory import inventory, read_db, sanitize_snapshot
from agent.runtime import atomic_write
from agent.script_api import ScriptAPI
from vaio.common import config_revision, validate_platform_task
from test_agent import FakeRuntime

ACCOUNT = '11111111-1111-4111-8111-111111111111'
PLATFORM = '22222222-2222-4222-8222-222222222222'


def account_db():
    return {"version": "4.0.0", "xray": {"vless": [
        {"port": 443, "uuid": "ROW_SECRET", "sni": "a.example", "users": [
            {"name": "default", "uuid": "ROW_SECRET", "enabled": True, "used": 1},
            {"name": "alice", "uuid": "ALICE_SECRET", "enabled": False, "used": 70, "account_id": ACCOUNT,
             "expire_date": "2099-01-01", "quota": 0, "disable_reason": "quota"}]}]},
        "singbox": {}, "meta": {},
        "accounts": {ACCOUNT: {"name": "alice", "note": "n", "enabled": True, "expire_date": "2099-01-01", "quota": 50,
                               "reset_day": 1, "cycle": "2026-10-01", "cycle_used": 70, "rev": 4,
                               "mtime": {"quota": 1760000000}, "platform_user_id": PLATFORM, "platform_block": "",
                               "members": [{"core": "xray", "protocol": "vless", "port": 443, "name": "alice", "last_raw": 70}]}}}


def op(**extra):
    return {"op": "update", "account_id": ACCOUNT, "base_rev": 4, "fields": {"expire_date": "2099-02-01"}, **extra}


class FakeScriptAPI:
    def __init__(self, cfg, replies=None, results=None):
        self.cfg, self.replies, self.results = Path(cfg), list(replies or []), list(results or [])
        self.writes, self.lookups = [], []

    def write(self, params, request_id):
        # The Agent must not hold the shared transaction lock while the script runs.
        with open(self.cfg / '.txn.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.writes.append((params, request_id))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def result(self, request_id):
        self.lookups.append(request_id)
        reply = self.results.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class PlatformTaskValidation(unittest.TestCase):
    def test_valid_operations(self):
        ops = [{"op": "create", "account_id": ACCOUNT, "platform_user_id": PLATFORM,
                "fields": {"name": "alice", "quota": 0, "expire_date": "", "reset_day": 1, "note": "", "enabled": True},
                "members": [{"target": {"core": "xray", "protocol": "vless", "port": 443}, "name": "alice"}]},
               op(), {"op": "link", "account_id": ACCOUNT, "platform_user_id": PLATFORM},
               {"op": "unlink", "account_id": ACCOUNT}, {"op": "block", "account_id": ACCOUNT, "platform_block": "quota"},
               {"op": "member_add", "account_id": ACCOUNT, "target": {"core": "singbox", "protocol": "hy2", "port": 8443}},
               {"op": "member_claim", "account_id": ACCOUNT, "target": {"core": "xray", "protocol": "vless", "port": 443}, "name": "bob", "count_existing": False},
               {"op": "member_remove", "account_id": ACCOUNT, "target": {"core": "xray", "protocol": "vless", "port": 443}, "name": "bob", "mode": "delete"},
               {"op": "reset_credentials", "account_id": ACCOUNT, "member": {"core": "xray", "protocol": "vless", "port": 443, "name": "alice"}},
               {"op": "reset_usage", "account_id": ACCOUNT}, {"op": "delete", "account_id": ACCOUNT, "mode": "release"}]
        self.assertEqual(validate_platform_task({"action": "platform_apply", "params": {"ops": ops}})["params"]["ops"], ops)

    def test_invalid_requests_rejected(self):
        bad = [
            {"action": "platform_apply", "params": {"ops": []}},
            {"action": "platform_apply", "params": {"ops": [op()] * 201}},
            {"action": "platform_apply", "params": {"ops": [op()]}, "revision": "x"},
            {"action": "platform_apply", "params": {"ops": [op(account_id="ALICE")]}},
            {"action": "platform_apply", "params": {"ops": [op(shell="rm -rf /")]}},
            {"action": "platform_apply", "params": {"ops": [op(fields={"password": "x"})]}},
            {"action": "platform_apply", "params": {"ops": [op(fields={"note": "a\nb"})]}},
            {"action": "platform_apply", "params": {"ops": [op(fields={"reset_day": 29})]}},
            {"action": "platform_apply", "params": {"ops": [op(base_rev=True)]}},
            {"action": "platform_apply", "params": {"ops": [{"op": "block", "account_id": ACCOUNT, "platform_block": "manual"}]}},
            {"action": "platform_apply", "params": {"ops": [{"op": "member_add", "account_id": ACCOUNT, "target": {"core": "xray", "protocol": "vless", "port": 70000}}]}},
            {"action": "platform_apply", "params": {"ops": [{"op": "create", "account_id": ACCOUNT, "fields": {"quota": 1}}]}},
            {"action": "install", "params": {"ops": [op()]}},
        ]
        for data in bad:
            with self.assertRaises(ValueError, msg=str(data)[:80]):
                validate_platform_task(data)


class ScriptAPIAccounts(unittest.TestCase):
    def caps(self, accounts):
        data = dict(stage='read_only_foundation', write_actions=[], protocols=[dict(write_supported=False)])
        if accounts is not None:
            data['accounts_api'] = accounts
        return [dict(script_version='v', data=data), dict(script_version='v', data=dict(instances=[]))]

    def test_accounts_capability_parsed_and_fails_closed(self):
        for accounts, expected in (({'version': 1, 'actions': ['account_apply', 'result']}, 1), (None, 0),
                                   ({'version': 2, 'actions': ['account_apply']}, 1), ({'version': 3, 'actions': ['account_apply']}, 1), ({'version': 4, 'actions': ['account_apply']}, 0), ({'version': 1, 'actions': 'x'}, 0)):
            with patch.object(ScriptAPI, 'read', side_effect=self.caps(accounts)):
                result = ScriptAPI().status()
            self.assertEqual((result['status'], result['accounts_api']), ('ready', expected))

    def test_write_and_result_requests(self):
        api, sent = ScriptAPI(), []
        def call(request, timeout):
            sent.append((request, timeout))
            return 0, {'api_version': 1, 'request_id': request['request_id'], 'status': 'succeeded', 'data': {}}
        task = str(uuid.uuid4())
        with patch.object(api, '_call', side_effect=call):
            api.write({'ops': [op()]}, task)
            api.result(task)
        self.assertEqual((sent[0][0]['action'], sent[0][0]['request_id'], sent[0][1]), ('account_apply', task, 300))
        self.assertEqual((sent[1][0]['action'], sent[1][0]['params']), ('result', {'request_id': task}))
        self.assertNotEqual(sent[1][0]['request_id'], task)
        with self.assertRaises(ValueError):
            api.write({'ops': []}, '../../etc')

    def test_response_framing_checked(self):
        api = ScriptAPI()
        def run(response):
            def fake(argv, input, stdout, **kwargs):
                stdout.write(json.dumps(response).encode())
                return subprocess.CompletedProcess(argv, 1)
            return fake
        task = str(uuid.uuid4())
        with patch('agent.script_api.subprocess.run', side_effect=run({'api_version': 1, 'request_id': task, 'status': 'failed', 'code': 'rev_conflict'})):
            self.assertEqual(api.write({'ops': [op()]}, task)['code'], 'rev_conflict')
        for bad in ({'api_version': 1, 'request_id': 'other', 'status': 'failed'}, {'api_version': 1, 'request_id': task, 'status': 'done'}, []):
            with patch('agent.script_api.subprocess.run', side_effect=run(bad)), self.assertRaises(ValueError):
                api.write({'ops': [op()]}, task)


class BridgePlatformApply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / 'cfg'; self.cfg.mkdir()
        self.state = Path(self.tmp.name) / 'state'
        atomic_write(self.cfg / 'db.json', json.dumps(account_db()))
        self.runtime = FakeRuntime(self.cfg / 'config.json'); self.runtime.path.write_text('original')

    def tearDown(self):
        self.tmp.cleanup()

    def bridge(self, replies=None, results=None):
        self.api = FakeScriptAPI(self.cfg, replies, results)
        return Bridge(self.cfg, self.state, self.runtime, script_api=self.api)

    @staticmethod
    def task():
        return {"id": str(uuid.uuid4()), "action": "platform_apply", "params": {"ops": [op()]}}

    def test_success_is_journaled_and_not_replayed(self):
        bridge, task = self.bridge([{'status': 'succeeded', 'data': {'accounts': {ACCOUNT: {'rev': 5, 'exists': True, 'secret': 'x'}}}}]), self.task()
        result = bridge.execute(task)
        self.assertEqual(result['accounts'], {ACCOUNT: {'rev': 5, 'exists': True}})
        self.assertEqual(self.api.writes[0], (task['params'], task['id']))
        self.assertEqual(bridge.execute(task), result)
        self.assertEqual(len(self.api.writes), 1)

    def test_rev_conflict_and_rolled_back_failures(self):
        bridge, task = self.bridge([{'status': 'failed', 'code': 'rev_conflict', 'data': {'account_id': ACCOUNT, 'rev': 9}}]), self.task()
        with self.assertRaisesRegex(ValueError, '节点版本 9'):
            bridge.execute(task)
        with self.assertRaises(RuntimeError):
            bridge.execute(task)
        self.assertEqual(len(self.api.writes), 1)
        bridge = self.bridge([{'status': 'failed', 'code': 'apply_failed', 'data': {'message': 'Sing-box 配置校验失败', 'rolled_back': True}}])
        with self.assertRaisesRegex(TransactionRolledBack, 'Sing-box 配置校验失败'):
            bridge.execute(self.task())

    def test_uncertain_outcome_is_looked_up_never_rerun(self):
        bridge = self.bridge([subprocess.TimeoutExpired('bash', 300)], [{'status': 'succeeded', 'data': {'accounts': {}}}])
        task = self.task()
        bridge.execute(task)
        self.assertEqual(self.api.lookups, [task['id']])
        bridge = self.bridge([{'status': 'unknown', 'code': 'result_unknown'}], [{'status': 'unknown'}])
        task = self.task()
        with self.assertRaises(TransactionUnknown):
            bridge.execute(task)
        with self.assertRaises(TransactionUnknown):
            bridge.execute(task)
        self.assertEqual(len(self.api.writes), 1)

    def test_unavailable_api_and_pending_enforcement(self):
        with self.assertRaisesRegex(ValueError, '脚本接口不可用'):
            Bridge(self.cfg, self.state, self.runtime).execute(self.task())
        bridge = self.bridge([{'status': 'succeeded', 'data': {}}])
        self.state.mkdir(exist_ok=True); (self.state / 'enforcement-pending.json').write_text('{}')
        with self.assertRaises(TransactionUnknown):
            bridge.execute(self.task())
        self.assertEqual(self.api.writes, [])

    def test_instance_transactions_hold_shared_lock(self):
        bridge = self.bridge()
        with bridge.locked(), open(self.cfg / '.txn.lock', 'a') as other:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def instance_task(self, action, params):
        return {"id": str(uuid.uuid4()), "action": action, "protocol": "vless", "core": "xray", "port": 443,
                "params": params, "revision": config_revision(read_db(self.cfg))}

    def test_member_policy_fields_rejected_on_instance_tasks(self):
        bridge = self.bridge()
        for action, params in (('user_update', {'name': 'alice', 'enabled': True}), ('user_update', {'name': 'alice', 'quota_gb': 1}),
                               ('user_update', {'name': 'alice', 'expire_date': '2100-01-01'}), ('user_delete', {'name': 'alice'})):
            with self.assertRaisesRegex(ValueError, '统一用户'):
                bridge.execute(self.instance_task(action, params))
        bridge.execute(self.instance_task('user_update', {'name': 'alice', 'reset_credentials': True}))
        user = read_db(self.cfg)['xray']['vless'][0]['users'][1]
        self.assertNotEqual(user['uuid'], 'ALICE_SECRET')
        self.assertEqual((user['account_id'], user['enabled']), (ACCOUNT, False))

    def test_settlement_runs_through_script_and_failure_does_not_block(self):
        calls = []
        self.runtime.upstream = lambda operation, *args: calls.append(operation)
        bridge = self.bridge()
        bridge.reconcile()
        self.assertEqual(calls, ['accounts_apply'])
        def broken(*args):
            raise RuntimeError('boom')
        self.runtime.upstream = broken
        with self.assertLogs(level='ERROR'):
            bridge.reconcile()


class AccountSnapshot(unittest.TestCase):
    def test_inventory_reports_accounts_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            atomic_write(Path(tmp) / 'db.json', json.dumps(account_db()))
            data = sanitize_snapshot({**inventory(tmp, status=lambda _: 'running'), 'accounts_version': 1})
        text = json.dumps(data)
        for secret in ('ROW_SECRET', 'ALICE_SECRET'):
            self.assertNotIn(secret, text)
        account = data['accounts'][ACCOUNT]
        self.assertEqual((account['rev'], account['state'], account['platform_user_id'], data['accounts_version']), (4, 'quota', PLATFORM, 1))
        self.assertEqual(account['members'][0], {'core': 'xray', 'protocol': 'vless', 'port': 443, 'name': 'alice',
                                                 'used': 70, 'enabled': False, 'disable_reason': 'quota'})
        users = data['instances'][0]['users']
        self.assertEqual([u['account_id'] for u in users], ['', ACCOUNT])

    def test_sanitizer_rejects_or_clamps_untrusted_accounts(self):
        good = {ACCOUNT: {'name': 'x' * 40, 'note': 'a\nb', 'quota': -1, 'state': 'evil', 'platform_user_id': 'no', 'members': []}}
        clean = sanitize_snapshot({'instances': [], 'accounts': good, 'accounts_version': 2})['accounts'][ACCOUNT]
        self.assertEqual((clean['name'], clean['note'], clean['quota'], clean['state'], clean['platform_user_id']), ('', 'ab', 0, '', None))
        self.assertEqual(sanitize_snapshot({'instances': [], 'accounts_version': 2})['accounts_version'], 0)
        for bad in ({'not-a-uuid': {}}, {ACCOUNT: {'members': [{}] * 51}}, {ACCOUNT: {'members': [{'core': 'shell', 'port': 1}]}},
                    {str(uuid.uuid4()): {} for _ in range(1001)}):
            with self.assertRaises(ValueError):
                sanitize_snapshot({'instances': [], 'accounts': bad})

    def test_agent_declares_accounts_version_from_script_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent = Agent({'url': 'https://panel.example', 'node_id': 'n', 'token': 't'}, Path(tmp) / 'state', cfg=Path(tmp))
            sent = []
            for accounts_api, expected in ((1, 1), (0, 0)):
                agent.script_api = type('API', (), {'status': lambda self, v=accounts_api: {'status': 'ready', 'accounts_api': v}})()
                agent.snapshot_cache = None
                with patch.object(agent, 'api', side_effect=lambda suffix, payload: sent.append(payload) or {}):
                    agent.cycle(None, None)
                self.assertEqual(sent[-1]['snapshot']['accounts_version'], expected)


if __name__ == '__main__':
    unittest.main()
