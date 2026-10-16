"""Script API bridge. Protocol capabilities never grant task execution rights; only the
unified-account transaction (account_apply), port-forward changes (forward_apply) and installs through
the script's own flow (install) are written through it."""
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from vaio.common import sanitize_forwards, sanitize_install_schema

from .runtime import ROOT, UPSTREAM_SHA


class ScriptAPI:
    def __init__(self, script=None):
        self.script = Path(script) if script else ROOT / 'vendor/vless-server.sh'
        self.cached = None
        self.checked = 0

    def _call(self, request, timeout):
        """Run one --api request; returns (exit status, parsed response)."""
        if hashlib.sha256(self.script.read_bytes()).hexdigest() != UPSTREAM_SHA:
            raise ValueError('script checksum mismatch')
        # Keep stdout bounded in memory; stderr may contain private local paths.
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(['bash', str(self.script), '--api'],
                input=json.dumps(request).encode(), stdout=output, stderr=subprocess.DEVNULL,
                timeout=timeout, env={**os.environ, 'VLESS_SCRIPT_SOURCE_REF': 'codex/platform-api'})
            output.seek(0)
            raw = output.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('script API response too large')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('api_version') != 1 or data.get('request_id') != request['request_id'] \
                or data.get('status') not in ('succeeded', 'failed', 'unknown'):
            raise ValueError('invalid API response')
        return result.returncode, data

    def read(self, action):
        if action not in {'capabilities', 'inventory'}:
            raise ValueError('preview API is read-only')
        code, data = self._call({'api_version': 1, 'request_id': str(uuid.uuid4()), 'action': action}, 8)
        if code or data['status'] != 'succeeded':
            raise ValueError('script API unavailable')
        return data

    @staticmethod
    def _request_id(value):
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError('invalid request id')
        return value

    def write(self, params, request_id):
        """Unified-account transaction. The task ID is the script's idempotency key."""
        request = {'api_version': 1, 'request_id': self._request_id(request_id), 'action': 'account_apply', 'params': params}
        return self._call(request, 300)[1]

    def forward(self, params, request_id):
        """Port-forward transaction (Realm / nftables). The task ID is the script's idempotency key."""
        request = {'api_version': 1, 'request_id': self._request_id(request_id), 'action': 'forward_apply', 'params': params}
        return self._call(request, 300)[1]

    def install(self, params, request_id):
        """Install through the script's menu flow (certificates, Nginx, core downloads): allow up to 20 minutes."""
        request = {'api_version': 1, 'request_id': self._request_id(request_id), 'action': 'install', 'params': params}
        return self._call(request, 1200)[1]

    def share(self, target, name, host, port=None):
        """A member's connection link from the script (read-only; nothing is recorded).
        host/port replace the address in the link (relay entry); credentials stay the landing instance's."""
        request = {'api_version': 1, 'request_id': str(uuid.uuid4()), 'action': 'account_share',
                   'params': {'target': target, 'name': name, **({'host': host} if host else {}), **({'port': port} if port else {})}}
        code, data = self._call(request, 30)
        if data['status'] != 'succeeded' or not isinstance(data.get('data'), dict) or not isinstance(data['data'].get('connection'), str):
            raise ValueError({'user_not_found': '用户不存在', 'unsupported_protocol': '该协议不支持用户管理'}.get(data.get('code'), '节点脚本无法生成连接信息'))
        return data['data']['connection'][:8000]

    def result(self, request_id):
        """Read-only lookup of a previous account_apply; never re-executes it."""
        request = {'api_version': 1, 'request_id': str(uuid.uuid4()), 'action': 'result',
                   'params': {'request_id': self._request_id(request_id)}}
        return self._call(request, 30)[1]

    def invalidate(self):
        """Next status() re-reads inventory (after a forward change)."""
        self.checked = 0

    def status(self):
        now = time.monotonic()
        if self.cached is not None and now - self.checked < 60:
            return dict(self.cached)
        try:
            caps, inv = self.read('capabilities'), self.read('inventory')
            c, i = caps['data'], inv['data']
            if c.get('stage') != 'read_only_foundation' or c.get('write_actions') != []:
                raise ValueError('unsupported capability contract')
            protocols = c.get('protocols')
            instances = i.get('instances')
            if not isinstance(protocols, list) or not isinstance(instances, list) or len(protocols) > 100 or len(instances) > 1000:
                raise ValueError('invalid inventory')
            if any(p.get('write_supported') is not False for p in protocols):
                raise ValueError('unexpected write capability')
            if caps.get('script_version') != inv.get('script_version'):
                raise ValueError('version mismatch')
            version = caps.get('script_version')
            if not isinstance(version, str) or len(version) > 40 or not all(ch.isalnum() or ch in '.-' for ch in version):
                raise ValueError('invalid version')
            # Do not forward arbitrary API fields, users, resources, or revision.
            # Script snapshot revisions include traffic and are not task revisions.
            accounts = c.get('accounts_api')
            # Version 2 adds set_authority, 3 adds account_share and user modes; earlier operations are unchanged.
            accounts_ready = isinstance(accounts, dict) and accounts.get('version') in (1, 2, 3) \
                and isinstance(accounts.get('actions'), list) and 'account_apply' in accounts['actions']
            install = c.get('install_api')
            schema = sanitize_install_schema(install.get('schema')) if isinstance(install, dict) and install.get('version') == 1 else None
            forward = c.get('forward_api')
            forward_ready = isinstance(forward, dict) and forward.get('version') == 1
            self.cached = {'status': 'ready', 'version': version, 'stage': 'read_only',
                           'protocol_count': len(protocols), 'instance_count': len(instances),
                           'accounts_api': 1 if accounts_ready else 0, 'forward_api': 1 if forward_ready else 0,
                           'forwards': sanitize_forwards(i.get('forwards')) if forward_ready else [],
                           **({'install_schema': schema} if schema else {})}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
            self.cached = {'status': 'unavailable', 'stage': 'read_only'}
        self.checked = now
        return dict(self.cached)
