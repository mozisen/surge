import json
import time
import unittest
from agent.config_details import config_details
from vaio.common import PROTOCOL_CORES
import test_panel as panel


class DetailsTest(unittest.TestCase):
    def test_script_templates_and_selected_user(self):
        row = dict(port=24443, uuid='wrong-default', password='wrong-default', private_key='NEVER_EXPORT_PRIVATE',
                   public_key='public', short_id='abcd', sni='example.com', method='aes-256-gcm',
                   users=[dict(name='alice', uuid='chosen-secret')])
        for proto, cores in PROTOCOL_CORES.items():
            for core in cores:
                text = config_details(core, proto, row, dict(name='alice',host='2001:db8::1'))
                self.assertIn('chosen-secret', text, proto)
                self.assertIn('[2001:db8::1]', text, proto)
                self.assertNotIn('wrong-default', text)
                self.assertNotIn('NEVER_EXPORT_PRIVATE', text)
                if proto == 'vless':
                    self.assertIn('Loon 配置:', text)
                    self.assertIn('public-key="public", short-id=abcd', text)
                if proto == 'snell-v6':
                    self.assertIn('version=6, mode=default', text)
        with self.assertRaises(ValueError):
            config_details('xray','vless',row,dict(name='missing',host='example.com'))


class DetailAccessTest(unittest.TestCase):
    setUp = panel.PanelTest.setUp
    tearDown = panel.PanelTest.tearDown
    add = panel.PanelTest.add
    registered = panel.PanelTest.registered
    task = panel.PanelTest.task

    def test_qr_auth_expiry_and_result_allowlist(self):
        node, token, snap = self.registered()
        task = self.task(node).json['id']
        self.client.post('/api/agent/'+node+'/poll',json={'snapshot':snap,'ready':True},headers=token)
        result = dict(connection='vless://secret@example.com:443',config_details='UUID: secret')
        self.client.post('/api/agent/'+node+'/tasks/'+task+'/result',json={'status':'succeeded','message':'完成','result':result},headers=token)
        with self.store.connect() as db:
            self.assertNotIn('config_details',json.loads(db.execute('SELECT result FROM tasks WHERE id=?',(task,)).fetchone()['result']))
            db.execute("UPDATE tasks SET action='share',status='succeeded',finished=?,result=? WHERE id=?",(time.time(),json.dumps(result),task))
        url='/api/tasks/'+task+'/qr'
        self.assertEqual(self.app.test_client().get(url).status_code,401)
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'<svg',response.data)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        with self.store.connect() as db:
            db.execute('UPDATE tasks SET finished=? WHERE id=?',(time.time()-601,task))
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.get('/api/tasks').json['tasks'][0]['result'],{})
