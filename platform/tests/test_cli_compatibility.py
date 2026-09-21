import json
import re
import subprocess
import unittest
from pathlib import Path

from agent.runtime import ROOT, render_inbound


class CLICompatibility(unittest.TestCase):
    def cli(self, core, proto, row, previous):
        source = (ROOT / 'vendor/vless-server.sh').read_text()
        functions = '\n'.join(re.search(r'^' + name + r'\(\) \{\n.*?^\}', source, re.M | re.S)[0]
                              for name in ('_platform_render_inbound', '_platform_cli_inbound'))
        result = subprocess.run(['bash', '-c', functions + '\n_platform_cli_inbound "$@"', 'test',
                                 core, proto, json.dumps(row), json.dumps(previous)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_cli_and_agent_generate_same_inbound_for_every_shared_combination(self):
        for core, proto in [('xray', 'vless'), ('xray', 'trojan'), ('singbox', 'vless'),
                            ('singbox', 'trojan'), ('singbox', 'anytls'), ('singbox', 'hy2')]:
            with self.subTest(core=core, protocol=proto):
                row = dict(port=24443, panel_managed=True, panel_cert='/unique/cert', panel_key='/unique/key',
                           sni='example.com', private_key='private', short_id='abcd', users=[
                               dict(name='custom', uuid='custom-secret', enabled=True, used=10),
                               dict(name='disabled', uuid='disabled-secret', enabled=False)])
                generated = render_inbound(proto, row, core=core)
                self.assertEqual(self.cli(core, proto, row, {}), generated)
                row['runtime_tag'] = generated['tag']
                row['port'] = 24444
                generated['custom'] = {'preserve': True}
                actual = self.cli(core, proto, row, {'inbounds': [generated]})
                self.assertEqual(actual, render_inbound(proto, row, generated, core))
                self.assertNotIn('disabled-secret', json.dumps(actual))
                self.assertEqual(actual['tag'], generated['tag'])
                self.assertEqual(actual['custom'], {'preserve': True})

    def test_disabled_or_expired_users_never_regain_default_access(self):
        row = dict(port=12345, password='default-secret', users=[
            dict(name='default', uuid='default-secret', enabled=False),
            dict(name='expired', uuid='expired-secret', expire_date='2000-01-01')],
            panel_cert='/cert', panel_key='/key')
        result = self.cli('singbox', 'anytls', row, {})
        self.assertEqual(result['users'][0]['name'], 'vaio-disabled')
        self.assertNotIn('default-secret', json.dumps(result))
        self.assertNotIn('expired-secret', json.dumps(result))

    def test_vendor_matches_standalone_source_when_monorepo_available(self):
        source = ROOT.parent / 'vless-server.sh'
        if not source.exists():
            self.skipTest('standalone source not included in installed platform bundle')
        self.assertEqual(source.read_bytes(), (ROOT / 'vendor/vless-server.sh').read_bytes())


if __name__ == '__main__':
    unittest.main()
