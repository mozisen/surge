import copy
import unittest
from unittest.mock import patch
from agent.script_api import ScriptAPI
from agent.inventory import sanitize_snapshot


class ScriptAPITest(unittest.TestCase):
    def replies(self):
        return [dict(script_version='3.7.3-preview.1',data=dict(stage='read_only_foundation',write_actions=[],protocols=[dict(write_supported=False)])),
                dict(script_version='3.7.3-preview.1',data=dict(instances=[{'password':'SECRET'}],revision='not-a-task-revision'))]

    def test_summary_is_redacted_cached_and_not_a_write_permission(self):
        api=ScriptAPI()
        with patch.object(api,'read',side_effect=self.replies()) as read:
            result=api.status()
            self.assertEqual(result['status'],'ready')
            self.assertEqual(result['protocol_count'],1)
            self.assertEqual(result['instance_count'],1)
            self.assertNotIn('SECRET',str(result))
            self.assertNotIn('revision',result)
            self.assertEqual(api.status(),result)
            self.assertEqual(read.call_count,2)
        clean=sanitize_snapshot({'script_api':{**result,'token':'SECRET'},'instances':[]})
        self.assertNotIn('SECRET',str(clean))

    def test_changed_or_malformed_contract_fails_closed(self):
        for mutation in ('writes','stage','malformed','version'):
            replies=copy.deepcopy(self.replies())
            if mutation=='writes':replies[0]['data']['write_actions']=['delete']
            elif mutation=='stage':replies[0]['data']['stage']='write_ready'
            elif mutation=='version':replies[1]['script_version']='other'
            else:replies[0]['data']['protocols']=[None]
            with patch.object(ScriptAPI,'read',side_effect=replies):
                self.assertEqual(ScriptAPI().status()['status'],'unavailable')

    def test_mutations_rejected_before_process_start(self):
        with patch('agent.script_api.subprocess.run') as run:
            for action in ('install','update','delete','share','shell'):
                with self.assertRaises(ValueError):ScriptAPI().read(action)
            run.assert_not_called()

    def test_checksum_mismatch_rejected_before_process_start(self):
        with patch('agent.script_api.Path.read_bytes',return_value=b'changed'),patch('agent.script_api.subprocess.run') as run:
            with self.assertRaises(ValueError):ScriptAPI().read('inventory')
            run.assert_not_called()

    def test_failure_does_not_leak_exception(self):
        with patch.object(ScriptAPI,'read',side_effect=ValueError('SECRET')):
            result=ScriptAPI().status()
        self.assertEqual(result,{'status':'unavailable','stage':'read_only'})
