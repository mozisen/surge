"""One flock-elected worker per database, durable incident transitions, no task replay."""
import datetime
import fcntl
import json
import logging
import os
import re
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from . import backups

SCHEMA = '''
CREATE TABLE IF NOT EXISTS samples(node_id TEXT NOT NULL, bucket INTEGER NOT NULL, metrics TEXT NOT NULL, PRIMARY KEY(node_id,bucket));
CREATE TABLE IF NOT EXISTS incidents(key TEXT PRIMARY KEY, active INTEGER NOT NULL, at REAL NOT NULL, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, at REAL NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
'''


def settings(store, private=False):
    data = json.loads(store.setting('notifications') or '{}')
    if private:
        return data
    return {**{k: v for k, v in data.items() if k != 'telegram_token'}, 'telegram_configured': bool(data.get('telegram_token'))}


def save_settings(store, data):
    if set(data) - {'enabled', 'telegram_token', 'telegram_chat', 'webhook', 'clear_telegram'}:
        raise ValueError('通知字段无效')
    old = settings(store, True)
    if type(data.get('enabled')) is not bool:
        raise ValueError('通知开关无效')
    token = data.get('telegram_token', '')
    chat = data.get('telegram_chat', '')
    webhook = data.get('webhook', '')
    if not isinstance(token, str) or (token and not re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{20,100}', token)):
        raise ValueError('Telegram 令牌格式无效')
    if not isinstance(chat, str) or (chat and not re.fullmatch(r'(?:-?[0-9]{1,24}|@[A-Za-z0-9_]{5,32})', chat)):
        raise ValueError('Telegram 接收地址无效')
    if not isinstance(webhook, str) or len(webhook) > 2048:
        raise ValueError('Webhook 地址无效')
    if webhook:
        url = urlsplit(webhook)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('Webhook 必须使用不含登录信息的 HTTPS 地址')
    token = '' if data.get('clear_telegram') is True else token or old.get('telegram_token', '')
    if bool(token) != bool(chat):
        raise ValueError('请同时设置 Telegram 令牌和接收地址')
    if data['enabled'] and not (token or webhook):
        raise ValueError('请至少配置一个通知渠道')
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES('notifications',?)", (json.dumps(dict(enabled=data['enabled'], telegram_token=token, telegram_chat=chat, webhook=webhook)),))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('通知渠道不允许重定向')


def deliver(config, title):
    targets = []
    if config.get('telegram_token'):
        targets.append(('https://api.telegram.org/bot' + config['telegram_token'] + '/sendMessage', {'chat_id': config['telegram_chat'], 'text': title}, True))
    if config.get('webhook'):
        targets.append((config['webhook'], {'title': title, 'source': 'Vaio Panel'}, False))
    if not targets:
        return 'unconfigured'
    outcomes = []
    for url, payload, telegram in targets:
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=10) as response:
                ok = 200 <= response.status < 300
                if telegram:
                    ok = ok and json.loads(response.read(65536)).get('ok') is True
                outcomes.append(ok)
        except Exception:
            # URLs may contain secrets; never persist exception text.
            outcomes.append(False)
    return 'sent' if all(outcomes) else 'failed'


def transition(db, key, title, active, now, enabled):
    old = db.execute('SELECT * FROM incidents WHERE key=?', (key,)).fetchone()
    if (old is None and not active) or (old and bool(old['active']) == active):
        return
    db.execute('INSERT OR REPLACE INTO incidents VALUES(?,?,?,?)', (key, int(active), now, title))
    message = title if active else '已恢复：' + title
    db.execute('INSERT INTO notifications(at,title,status) VALUES(?,?,?)', (now, message, 'pending' if enabled else 'disabled'))


def scan(store, now=None):
    now = time.time() if now is None else now
    config = settings(store, True)
    enabled = config.get('enabled') is True
    today = datetime.datetime.fromtimestamp(now).date()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE tasks SET status='unknown',finished=?,message='执行超时且结果未知，请核对节点' WHERE status='running' AND started<?", (now, now-2100))
        for node in db.execute('SELECT * FROM nodes WHERE deleted IS NULL AND revoked=0 AND last_seen IS NOT NULL').fetchall():
            if node['maintenance']:
                continue
            offline = now - node['last_seen'] > 120
            transition(db, 'offline:' + node['id'], node['name'] + ' · 节点离线', offline, now, enabled)
            if offline:
                continue
            snap = json.loads(node['snapshot'])
            if snap.get('error'):
                continue
            for item in snap.get('instances', []):
                for user in item.get('users', []):
                    prefix = node['id'] + ':' + item['core'] + ':' + item['protocol'] + ':' + str(item['port']) + ':' + user['name']
                    label = node['name'] + ' · ' + item['protocol'] + ':' + str(item['port']) + ' · ' + user['name']
                    if item.get('traffic_state') == 'ready':
                        quota = user.get('quota', 0)
                        transition(db, 'quota:' + prefix, label + ' · 流量已达配额的 80%', bool(quota and user.get('used', 0) >= quota * .8), now, enabled)
                        transition(db, 'overquota:' + prefix, label + ' · 流量已用尽', bool(quota and user.get('used', 0) >= quota), now, enabled)
                    try:
                        days = (datetime.date.fromisoformat(user.get('expire_date', '')) - today).days
                    except ValueError:
                        days = 9999
                    transition(db, 'expiry:' + prefix, label + ' · 已到期或将在 3 天内到期', days <= 3, now, enabled)
        for task in db.execute("SELECT tasks.*, nodes.name FROM tasks JOIN nodes ON nodes.id=tasks.node_id WHERE tasks.status IN ('failed','unknown') AND finished>?", (now - 3600,)).fetchall():
            transition(db, 'task:' + task['id'], task['name'] + ' · 任务失败或结果未知：' + {'install':'安装协议','update':'修改实例','delete':'删除实例','user_add':'新增用户','user_update':'修改用户','user_delete':'删除用户','start':'启动服务','stop':'停止服务','restart':'重启服务','share':'导出连接','inspect':'检查配置'}.get(task['action'], '节点操作') + '（' + task['id'][:8] + '）', True, now, enabled)
        db.execute('DELETE FROM samples WHERE bucket<?', (int(now//60)-7*1440,))
        db.execute('DELETE FROM notifications WHERE at<?', (now-30*86400,))
        db.execute("DELETE FROM incidents WHERE key LIKE 'task:%' AND at<?", (now-2*86400,))
        db.execute("INSERT OR REPLACE INTO settings VALUES('monitor_heartbeat',?)", (str(now),))


def send_pending(store):
    config = settings(store, True)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # A process died during delivery. Do not resend a possibly delivered message.
        db.execute("UPDATE notifications SET status='unknown' WHERE status='sending'")
        pending = db.execute("SELECT * FROM notifications WHERE status='pending' ORDER BY id LIMIT 10").fetchall()
        for row in pending:
            db.execute("UPDATE notifications SET status='sending' WHERE id=?", (row['id'],))
    for row in pending:
        status = deliver(config, row['title']) if config.get('enabled') else 'disabled'
        with store.connect() as db:
            db.execute('UPDATE notifications SET status=? WHERE id=?', (status, row['id']))


def worker(store):
    with open(store.path + '.monitor.lock', 'a') as lock:
        os.chmod(store.path + '.monitor.lock', 0o600)
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(30)
        while True:
            try:
                scan(store)
                send_pending(store)
                day = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
                if store.setting('backup_day') != day:
                    backups.create(store)
                    with store.connect() as db:
                        db.execute("INSERT OR REPLACE INTO settings VALUES('backup_day',?)", (day,))
            except Exception:
                logging.error('监控或备份检查失败，请检查数据库权限和可用空间')
            time.sleep(30)


def start(store):
    threading.Thread(target=worker, args=(store,), daemon=True, name='vaio-monitor').start()
