"""Read-only preview bridge. API capabilities never grant task execution rights."""
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .runtime import ROOT, UPSTREAM_SHA


class ScriptAPI:
    def __init__(self, script=None):
        self.script = Path(script) if script else ROOT / 'vendor/vless-server.sh'
        self.cached = None
        self.checked = 0

    def read(self, action):
        if action not in {'capabilities', 'inventory'}:
            raise ValueError('preview API is read-only')
        if hashlib.sha256(self.script.read_bytes()).hexdigest() != UPSTREAM_SHA:
            raise ValueError('script checksum mismatch')
        identity = str(uuid.uuid4())
        request = {'api_version': 1, 'request_id': identity, 'action': action}
        # Keep stdout bounded in memory; stderr may contain private local paths.
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(['bash', str(self.script), '--api'],
                input=json.dumps(request).encode(), stdout=output, stderr=subprocess.DEVNULL,
                timeout=8, env={**os.environ, 'VLESS_SCRIPT_SOURCE_REF': 'codex/platform-api'})
            output.seek(0)
            raw = output.read(1024 * 1024 + 1)
        if result.returncode or len(raw) > 1024 * 1024:
            raise ValueError('script API unavailable')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('api_version') != 1 or data.get('request_id') != identity or data.get('status') != 'succeeded':
            raise ValueError('invalid API response')
        return data

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
            self.cached = {'status': 'ready', 'version': version, 'stage': 'read_only',
                           'protocol_count': len(protocols), 'instance_count': len(instances)}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError):
            self.cached = {'status': 'unavailable', 'stage': 'read_only'}
        self.checked = now
        return dict(self.cached)
