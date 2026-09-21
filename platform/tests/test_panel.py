import concurrent.futures
import hashlib
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash
from vaio.server import create_app, agent_archive


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE": self.tmp.name + "/panel.sqlite"})
        self.store = self.app.extensions["store"]
        with self.store.connect() as db:
            db.execute("INSERT INTO settings VALUES('password',?)", (generate_password_hash("a-long-test-password", method="pbkdf2:sha256:1000"),))
        self.client = self.app.test_client()
        response = self.client.post('/api/login', json={"username":"admin", "password": "a-long-test-password"})
        self.csrf = response.json['csrf']
        self.headers = {"X-CSRF-Token": self.csrf}

    def tearDown(self):
        self.tmp.cleanup()

    def add(self):
        result = self.client.post('/api/nodes', json={"name": "test node"}, headers=self.headers)
        self.assertEqual(result.status_code, 201)
        script = result.json['script']
        enrollment = json.loads(script.split("<<'VAIO_ENROLLMENT'\n")[1].split('\nVAIO_ENROLLMENT')[0])
        return result.json['node_id'], enrollment

    def registered(self):
        node, enrollment = self.add()
        result = self.client.post('/api/enroll', json=enrollment)
        self.assertEqual(result.status_code, 200)
        token = {"Authorization": "Bearer " + result.json['token']}
        snap = {"revision": "a"*64, "instances": [], "metrics": {"load": 1}, "private_key": "NO_LEAK"}
        self.client.post('/api/agent/'+node+'/poll', json={"snapshot":snap,"ready":True}, headers=token)
        self.client.post('/api/nodes/'+node+'/adopt', json={"revision":"a"*64}, headers=self.headers)
        return node, token, snap

    def task(self, node, key='task1'):
        return self.client.post('/api/nodes/'+node+'/tasks', headers={**self.headers,"Idempotency-Key":key},
                                json={"action":"install","protocol":"vless","core":"xray","port":24443,"params":{"sni":"example.com"},"revision":"a"*64})

    def test_auth_csrf_cookie_and_no_login_csrf(self):
        client = self.app.test_client()
        self.assertEqual(client.get('/api/nodes').status_code,401)
        self.assertEqual(self.client.post('/api/nodes',json={"name":"bad"}).status_code,403)
        self.assertEqual(client.post('/api/login',json={"username":"admin", "password":"a-long-test-password"},headers={"Origin":"https://evil.test"}).status_code,403)
        response = client.post('/api/login',json={"username":"admin", "password":"a-long-test-password"})
        self.assertIn('HttpOnly',response.headers['Set-Cookie'])
        self.assertIn('SameSite=Strict',response.headers['Set-Cookie'])

    def test_enrollment_single_use_and_expiration(self):
        node, enrollment = self.add()
        self.assertEqual(self.client.post('/api/enroll',json=enrollment).status_code,200)
        self.assertEqual(self.client.post('/api/enroll',json=enrollment).status_code,401)
        node2, expired = self.add()
        with self.store.connect() as db:
            db.execute('UPDATE nodes SET enroll_expires=? WHERE id=?',(time.time()-1,node2))
        self.assertEqual(self.client.post('/api/enroll',json=expired).status_code,401)

    def test_parallel_enrollment_consumes_once(self):
        node, enrollment = self.add()
        def enroll():
            return self.app.test_client().post('/api/enroll',json=enrollment).status_code
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            self.assertEqual(sorted(executor.map(lambda _:enroll(),range(2))),[200,401])

    def test_task_idempotency_claim_once_result_ownership(self):
        node, token, snap = self.registered()
        first=self.task(node)
        self.assertEqual(first.status_code,201)
        self.assertEqual(self.task(node).json['id'],first.json['id'])
        self.assertEqual(self.task(node,'different').status_code,409)
        poll=lambda:self.client.post('/api/agent/'+node+'/poll',json={"snapshot":snap,"ready":True},headers=token).json
        self.assertEqual(poll()['task']['id'],first.json['id'])
        self.assertIsNone(poll()['task'])
        node2, token2, _ = self.registered()
        self.assertEqual(self.client.post('/api/agent/'+node2+'/tasks/'+first.json['id']+'/result',headers=token2,json={"status":"succeeded","message":"ok"}).status_code,404)
        for _ in range(2):
            self.assertEqual(self.client.post('/api/agent/'+node+'/tasks/'+first.json['id']+'/result',headers=token,json={"status":"succeeded","message":"ok","result":{"private_key":"DROP","steps":["done"]}}).status_code,200)
        result=self.client.get('/api/tasks').json['tasks'][0]
        self.assertEqual(result['result'],{'steps':['done']})

    def test_revoke_cancels_queue_and_rejects_identity(self):
        node, token, snap=self.registered()
        self.task(node)
        self.client.post('/api/nodes/'+node+'/revoke',headers=self.headers)
        self.assertEqual(self.client.post('/api/agent/'+node+'/poll',headers=token,json={"snapshot":snap}).status_code,401)
        self.assertEqual(self.client.get('/api/tasks').json['tasks'][0]['status'],'cancelled')

    def test_state_and_capability_validation(self):
        node,token,snap=self.registered()
        with self.store.connect() as db:
            db.execute('UPDATE nodes SET adopted=0 WHERE id=?',(node,))
        self.assertEqual(self.task(node).status_code,409)
        response=self.client.post('/api/nodes/'+node+'/tasks',headers={**self.headers,'Idempotency-Key':'bad'},json={"action":"shell","command":"id"})
        self.assertEqual(response.status_code,400)
        self.assertNotIn('NO_LEAK',self.client.get('/api/nodes').text)

    def test_new_protocol_requires_node_declared_capability(self):
        node, token, snap = self.registered()
        task = dict(action='install', protocol='anytls', core='singbox', port=30001,
                    params={'sni': 'example.com'}, revision='a'*64)
        send = lambda: self.client.post('/api/nodes/'+node+'/tasks', json=task,
                                        headers={**self.headers, 'Idempotency-Key': 'new-protocol'})
        self.assertEqual(send().status_code, 409)
        snap.update(task_api_version=2, write_capabilities=[{'protocol': 'anytls', 'core': 'singbox'}])
        self.client.post('/api/agent/'+node+'/poll', json={'snapshot': snap, 'ready': True}, headers=token)
        self.assertEqual(send().status_code, 201)

    def test_old_node_rejects_reset_and_unknown_blocks_new_writes(self):
        node, token, snap = self.registered()
        task = dict(action='user_update', protocol='vless', core='xray', port=30001,
                    params={'name': 'default', 'reset_credentials': True}, revision='a'*64)
        send = lambda: self.client.post('/api/nodes/'+node+'/tasks', json=task,
                                        headers={**self.headers, 'Idempotency-Key': 'reset-user'})
        self.assertEqual(send().status_code, 409)
        snap['task_api_version'] = 2
        self.client.post('/api/agent/'+node+'/poll', json={'snapshot': snap, 'ready': True}, headers=token)
        self.assertEqual(send().status_code, 201)
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET status='unknown' WHERE node_id=?", (node,))
        self.assertEqual(self.task(node, 'another-write').status_code, 409)

    def test_timeout_is_unknown_never_requeued(self):
        node,token,snap=self.registered()
        self.task(node)
        self.client.post('/api/agent/'+node+'/poll',headers=token,json={"snapshot":snap,"ready":True})
        with self.store.connect() as db:
            db.execute('UPDATE tasks SET started=?',(time.time()-2200,))
        self.assertEqual(self.client.get('/api/tasks').json['tasks'][0]['status'],'unknown')
        self.assertIsNone(self.client.post('/api/agent/'+node+'/poll',headers=token,json={"snapshot":snap,"ready":True}).json['task'])

    def test_login_rate_limit(self):
        client=self.app.test_client()
        for _ in range(8):
            self.assertEqual(client.post('/api/login',json={"username":"admin", "password":"bad"}).status_code,401)
        self.assertEqual(client.post('/api/login',json={"username":"admin", "password":"bad"}).status_code,429)

    def test_agent_bundle_deterministic_and_checksum(self):
        one=agent_archive()
        time.sleep(1.01)
        self.assertEqual(one,agent_archive())
        payload=self.client.get('/downloads/agent.tar.gz').data
        checksum=self.client.get('/downloads/agent.sha256').text.split()[0]
        self.assertEqual(hashlib.sha256(payload).hexdigest(),checksum)

    def test_account_change_requires_password_csrf_and_revokes_all_sessions(self):
        other = self.app.test_client()
        other.post('/api/login', json={"username":"admin", "password":"a-long-test-password"})
        data = dict(username="owner", current_password="a-long-test-password",
                    new_password="another-long-password", confirm_password="another-long-password")
        self.assertEqual(self.client.post('/api/account', json=data).status_code, 403)
        self.assertEqual(self.client.post('/api/account', json={**data, "current_password":"wrong"}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/account', json=data, headers=self.headers).status_code, 200)
        self.assertEqual(other.get('/api/session').status_code, 401)
        self.assertEqual(self.client.get('/api/session').status_code, 401)
        for username, password in [("admin", "another-long-password"), ("owner", "a-long-test-password")]:
            self.assertEqual(self.client.post('/api/login', json=dict(username=username,password=password)).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json=dict(username="owner",password="another-long-password")).status_code, 200)
        self.assertEqual(self.client.get('/api/session').json['username'], 'owner')
        with self.store.connect() as db:
            audit = str([tuple(r) for r in db.execute('SELECT * FROM audit')])
        self.assertNotIn('another-long-password', audit)
        self.assertNotEqual(self.store.setting('password'), 'another-long-password')

    def test_account_username_only_and_validation(self):
        data = dict(username="owner", current_password="a-long-test-password", new_password="", confirm_password="")
        for patch in [dict(username="x"), dict(username="a b"), dict(new_password="short"),
                      dict(new_password="long-enough-password",confirm_password="different")]:
            self.assertEqual(self.client.post('/api/account', json={**data, **patch}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.post('/api/account',json=data,headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/login',json=dict(username="owner",password="a-long-test-password")).status_code,200)

    def test_account_current_password_rate_limit(self):
        data = dict(username="owner", current_password="wrong")
        for _ in range(8):
            self.assertEqual(self.client.post('/api/account', json=data, headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/account', json=data, headers=self.headers).status_code,429)
        self.assertIsNone(self.store.setting('username'))

    def test_login_requires_username_even_on_legacy_database(self):
        client = self.app.test_client()
        self.assertEqual(client.post('/api/login',json=dict(password="a-long-test-password")).status_code,401)
        self.assertEqual(client.post('/api/login',json=dict(username="wrong",password="a-long-test-password")).status_code,401)
        self.assertEqual(client.post('/api/login',json=dict(username="admin",password="a-long-test-password")).status_code,200)

    def test_install_download_uses_header_and_expires_after_enrollment(self):
        node, enrollment = self.add()
        path = '/api/install/' + node
        headers = {'Authorization':'Bearer ' + enrollment['enroll_token']}
        self.assertEqual(self.client.get(path).status_code,401)
        response = self.client.get(path,headers=headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertIn('VAIO_ENROLLMENT',response.text)
        self.client.post('/api/enroll',json=enrollment)
        self.assertEqual(self.client.get(path,headers=headers).status_code,401)
        renewed = self.client.post('/api/nodes/'+node+'/enrollment',headers=self.headers).json
        self.assertEqual(self.client.get(path,headers=headers).status_code,401)
        self.assertIn('command', renewed)

    def test_install_download_expiry_and_revocation(self):
        node, data = self.add()
        headers = {'Authorization':'Bearer ' + data['enroll_token']}
        with self.store.connect() as db:
            db.execute('UPDATE nodes SET enroll_expires=? WHERE id=?',(time.time()-1,node))
        self.assertEqual(self.client.get('/api/install/'+node,headers=headers).status_code,401)
        node, data = self.add()
        self.client.post('/api/nodes/'+node+'/revoke',headers=self.headers)
        self.assertEqual(self.client.get('/api/install/'+node,headers={'Authorization':'Bearer '+data['enroll_token']}).status_code,401)

    def test_install_command_execution_and_failure_cleanup(self):
        data = self.client.post('/api/nodes', json={'name':'command'}, headers=self.headers).json
        command = data['command']
        root = Path(self.tmp.name)
        bindir = root/'bin'
        bindir.mkdir()
        temp = root/'downloads'
        temp.mkdir()
        fake = bindir/'curl'
        fake.write_text("#!/bin/sh\nread -r header\ncase \"$header\" in 'header = '*Authorization:*) ;; *) exit 9;; esac\nwhile [ \"$#\" -gt 0 ]; do if [ \"$1\" = -o ]; then shift; printf 'printf installed' > \"$1\"; fi; shift; done\n")
        fake.chmod(0o755)
        env = {**os.environ,'PATH':str(bindir)+':'+os.environ['PATH'],'TMPDIR':str(temp)}
        result = subprocess.run(['sh','-c',command],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout,'installed')
        self.assertEqual(list(temp.iterdir()),[])
        fake.write_text('#!/bin/sh\nexit 22\n')
        result = subprocess.run(['sh','-c',command],env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertEqual(list(temp.iterdir()),[])

    def test_node_settings_delete_restore_preserves_history(self):
        node, token, snap = self.registered()
        settings = dict(name="new name", group_name="test", notes="line 1\nline 2")
        self.assertEqual(self.client.post('/api/nodes/'+node+'/settings',json=settings,headers=self.headers).status_code,200)
        detail = self.client.get('/api/nodes/'+node).json
        self.assertEqual(detail['notes'],settings['notes'])
        task = self.task(node).json['id']
        self.assertEqual(self.client.post('/api/nodes/'+node+'/delete',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/nodes').json['nodes'],[])
        self.assertEqual(self.client.get('/api/nodes/'+node).status_code,404)
        self.assertEqual(self.client.get('/api/nodes?deleted=1').json['nodes'][0]['id'],node)
        self.assertEqual(self.client.get('/api/tasks').json['tasks'][0]['id'],task)
        self.assertEqual(self.client.get('/api/tasks').json['tasks'][0]['status'],'cancelled')
        self.assertEqual(self.client.post('/api/agent/'+node+'/poll',json={'snapshot':snap},headers=token).status_code,401)
        self.assertEqual(self.client.post('/api/nodes/'+node+'/restore',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/nodes').json['nodes'][0]['status'],'revoked')
        self.assertEqual(self.client.post('/api/agent/'+node+'/poll',json={'snapshot':snap},headers=token).status_code,401)

    def test_maintenance_blocks_dispatch_and_new_tasks(self):
        node, token, snap = self.registered()
        endpoint='/api/agent/'+node+'/maintenance'
        self.assertEqual(self.client.post(endpoint,json={'enabled':True},headers=token).status_code,200)
        self.assertEqual(self.task(node).status_code,409)
        self.assertEqual(self.client.post('/api/nodes/'+node+'/delete',headers=self.headers).status_code,409)
        self.assertEqual(self.client.post('/api/nodes/'+node+'/revoke',headers=self.headers).status_code,409)
        self.assertEqual(self.client.post('/api/nodes/'+node+'/enrollment',headers=self.headers).status_code,404)
        self.assertIsNone(self.client.post('/api/agent/'+node+'/poll',json={'ready':True,'snapshot':snap},headers=token).json['task'])
        self.assertTrue(self.client.get('/api/agent/'+node+'/status',headers=token).json['maintenance'])
        self.assertEqual(self.client.post(endpoint,json={'enabled':False},headers=token).status_code,200)
        self.assertEqual(self.task(node).status_code,201)
        self.assertEqual(self.client.post(endpoint,json={'enabled':True},headers=token).status_code,409)

    def test_unknown_requires_explicit_resolution_before_upgrade_or_delete(self):
        node, token, snap=self.registered()
        task=self.task(node).json['id']
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET status='unknown' WHERE id=?",(task,))
        self.assertEqual(self.client.post('/api/agent/'+node+'/maintenance',json={'enabled':True},headers=token).status_code,409)
        self.assertEqual(self.client.post('/api/nodes/'+node+'/delete',headers=self.headers).status_code,409)
        self.assertEqual(self.client.post('/api/tasks/'+task+'/resolve',json={'note':'已核对服务与备份'},headers=self.headers).status_code,200)
        self.assertEqual(self.client.post('/api/agent/'+node+'/tasks/'+task+'/result',json={'status':'unknown','message':'restart'},headers=token).status_code,200)
        self.assertEqual(self.client.get('/api/tasks').json['tasks'][0]['status'],'resolved')
        self.assertEqual(self.client.post('/api/agent/'+node+'/maintenance',json={'enabled':True},headers=token).status_code,200)

    def test_migration_is_idempotent_and_preserves_credentials(self):
        from vaio.store import Store
        before = self.store.setting('password')
        Store(self.store.path)
        Store(self.store.path)
        self.assertEqual(self.store.setting('password'),before)
        node, _ = self.add()
        self.assertEqual(self.client.get('/api/nodes/'+node).json['notes'],'')

    def test_connection_diagnostics_expiration_version_and_offline(self):
        node, token, snap=self.registered()
        snap['agent_version']='0.1.0'
        self.client.post('/api/agent/'+node+'/poll',json={'snapshot':snap},headers=token)
        detail=self.client.get('/api/nodes/'+node).json
        self.assertTrue(detail['upgrade_available'])
        self.assertEqual(detail['panel_version'], __import__('vaio').__version__)
        with self.store.connect() as db:
            db.execute('UPDATE nodes SET last_seen=? WHERE id=?',(time.time()-60,node))
        self.assertIn('vaio-agent logs',self.client.get('/api/nodes/'+node).json['connection_hint'])
        node, _ = self.add()
        with self.store.connect() as db:
            db.execute('UPDATE nodes SET enroll_expires=? WHERE id=?',(time.time()-1,node))
        self.assertIn('过期',self.client.get('/api/nodes/'+node).json['connection_hint'])

    def test_public_url_requires_tls(self):
        with self.assertRaises(ValueError):
            create_app({"DATABASE":self.tmp.name+'/invalid.sqlite',"PUBLIC_URL":"http://public.example.com"})


if __name__=='__main__':
    unittest.main()
