"""One flock-elected worker per database: incident transitions, Telegram delivery, the user bot and backups.

Notifications are a send queue only: a row is deleted once delivered (or when its outcome is unknown),
never replayed and never kept as history.
"""
import datetime
import fcntl
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.request

from . import backups, platform_users

SCHEMA = '''
CREATE TABLE IF NOT EXISTS samples(node_id TEXT NOT NULL, bucket INTEGER NOT NULL, metrics TEXT NOT NULL, PRIMARY KEY(node_id,bucket));
CREATE TABLE IF NOT EXISTS incidents(key TEXT PRIMARY KEY, active INTEGER NOT NULL, at REAL NOT NULL, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, at REAL NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', chat_id TEXT);
CREATE TABLE IF NOT EXISTS platform_tg(user_id TEXT PRIMARY KEY REFERENCES platform_users(id) ON DELETE CASCADE,
 chat_id TEXT, username TEXT NOT NULL DEFAULT '', bound_at REAL, code_hash TEXT, code_expires REAL);
CREATE UNIQUE INDEX IF NOT EXISTS platform_tg_chat ON platform_tg(chat_id) WHERE chat_id IS NOT NULL;
'''

DEFAULTS = dict(enabled=False, bot_token='', chat_id='', quota_percent=80, daily_enabled=False, daily_time='09:00',
                bot_enabled=False, bot_offset=0, bot_username='')
TOKEN = re.compile(r'[0-9]{5,20}:[A-Za-z0-9_-]{20,100}')
CHAT = re.compile(r'(?:-?[0-9]{1,24}|@[A-Za-z0-9_]{5,32})')
CODE = re.compile(r'[A-F0-9]{12}')
CODE_TTL = 86400
TICK = 10
COMMANDS = [dict(command='traffic', description='查询个人流量'), dict(command='status', description='查询账号状态'),
            dict(command='bind', description='绑定账号'), dict(command='unbind', description='解除绑定'),
            dict(command='help', description='查看帮助')]
HELP = '''可用命令：
/bind 绑定码  绑定您的账号
/traffic      查询流量与配额
/status       查询账号状态和到期时间
/unbind       解除当前 Telegram 绑定
/help         显示帮助

绑定码由管理员在面板生成，24 小时内有效，只能在私聊中使用。'''


def migrate(db):
    if 'chat_id' not in {row[1] for row in db.execute('PRAGMA table_info(notifications)')}:
        db.execute('ALTER TABLE notifications ADD COLUMN chat_id TEXT')


# ---------------------------------------------------------------- settings

def normalize(raw):
    data = dict(DEFAULTS)
    if 'bot_token' not in raw:
        # 0.3.0-preview.18 and earlier: telegram_token / telegram_chat, plus a webhook that is no longer supported.
        raw = {**raw, 'bot_token': raw.get('telegram_token', ''), 'chat_id': raw.get('telegram_chat', '')}
    for key, default in DEFAULTS.items():
        if type(raw.get(key)) is type(default):
            data[key] = raw[key]
    if not (data['bot_token'] and data['chat_id']):
        data['enabled'] = False
    if not data['bot_token']:
        data['bot_enabled'] = False
    return data


def settings(store, private=False):
    data = normalize(json.loads(store.setting('notifications') or '{}'))
    if private:
        return data
    return {**{k: v for k, v in data.items() if k not in ('bot_token', 'bot_offset')}, 'token_configured': bool(data['bot_token'])}


def write(db, data):
    # telegram_token / telegram_chat keep administrator alerts working after a rollback to an older panel.
    db.execute("INSERT OR REPLACE INTO settings VALUES('notifications',?)",
               (json.dumps({**data, 'telegram_token': data['bot_token'], 'telegram_chat': data['chat_id'], 'webhook': ''}),))


def update(store, **changes):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM settings WHERE key='notifications'").fetchone()
        write(db, {**normalize(json.loads(row[0] if row else '{}')), **changes})


def save_settings(store, data):
    if set(data) - {'enabled', 'bot_token', 'chat_id', 'quota_percent', 'daily_enabled', 'daily_time', 'clear_token'}:
        raise ValueError('通知字段无效')
    old = settings(store, True)
    new = dict(old)
    if type(data.get('enabled')) is not bool:
        raise ValueError('通知开关无效')
    new['enabled'] = data['enabled']
    token = data.get('bot_token', '')
    if not isinstance(token, str) or (token and not TOKEN.fullmatch(token)):
        raise ValueError('Bot Token 格式无效')
    chat = data.get('chat_id', old['chat_id'])
    if not isinstance(chat, str) or (chat and not CHAT.fullmatch(chat)):
        raise ValueError('Chat ID 格式无效')
    new['chat_id'] = chat
    percent = data.get('quota_percent', old['quota_percent'])
    if type(percent) is not int or not 50 <= percent <= 99:
        raise ValueError('流量告警阈值必须为 50–99 的整数')
    new['quota_percent'] = percent
    daily = data.get('daily_enabled', old['daily_enabled'])
    at = data.get('daily_time', old['daily_time'])
    if type(daily) is not bool or not isinstance(at, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', at):
        raise ValueError('每日报告时间无效')
    new['daily_enabled'], new['daily_time'] = daily, at
    if data.get('clear_token') is True:
        token = ''
        new['bot_token'] = ''
    elif token and token != old['bot_token']:
        new['bot_token'] = token
    if new['bot_token'] != old['bot_token']:
        # A different bot must be enabled again: webhook removal, commands and the update offset belong to the old one.
        new['bot_enabled'], new['bot_offset'], new['bot_username'] = False, 0, ''
    if new['enabled'] and not (new['bot_token'] and new['chat_id']):
        raise ValueError('请先设置 Bot Token 和 Chat ID')
    with store.connect() as db:
        write(db, new)


# ---------------------------------------------------------------- Telegram

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise ValueError('Telegram 请求不允许重定向')


def tg_call(token, method, params, timeout=10):
    """POST a Bot API method; raise RuntimeError without the URL (it contains the token)."""
    try:
        req = urllib.request.Request('https://api.telegram.org/bot' + token + '/' + method, data=json.dumps(params).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            data = json.loads(response.read(1 << 20))
    except Exception:
        raise RuntimeError('Telegram 请求失败') from None
    if not isinstance(data, dict) or data.get('ok') is not True:
        raise RuntimeError('Telegram 返回失败')
    return data.get('result')


def deliver(token, chat, text):
    try:
        tg_call(token, 'sendMessage', {'chat_id': chat, 'text': text[:4096]})
        return True
    except RuntimeError:
        return False


def enable_bot(store, enabled):
    config = settings(store, True)
    if not enabled:
        update(store, bot_enabled=False)
        return {}
    if not config['bot_token']:
        raise ValueError('请先设置 Bot Token')
    try:
        me = tg_call(config['bot_token'], 'getMe', {})
        tg_call(config['bot_token'], 'deleteWebhook', {'drop_pending_updates': False})
    except RuntimeError:
        raise ValueError('Bot Token 验证失败或无法连接 Telegram，用户机器人未启用') from None
    try:
        tg_call(config['bot_token'], 'setMyCommands', {'commands': COMMANDS})
    except RuntimeError:
        pass  # The menu is a convenience; commands work without it.
    username = str((me or {}).get('username', ''))[:64]
    update(store, bot_enabled=True, bot_username=username)
    return {'username': username}


def bot_info(store):
    """For the user page: the enabled bot's @name. Bots enabled before 1.3.0 have none saved; look it up once."""
    config = settings(store, True)
    if not config['bot_enabled']:
        return {'enabled': False, 'username': ''}
    if not config['bot_username']:
        try:
            username = str((tg_call(config['bot_token'], 'getMe', {}) or {}).get('username', ''))[:64]
        except RuntimeError:
            username = ''
        if username:
            update(store, bot_username=username)
        config['bot_username'] = username
    return {'enabled': True, 'username': config['bot_username']}


# ---------------------------------------------------------------- bind codes and the user bot

def code_hash(code):
    return hashlib.sha256(code.encode()).hexdigest()


def new_code(db, user_id, now=None):
    now = time.time() if now is None else now
    user = db.execute('SELECT deleting FROM platform_users WHERE id=?', (user_id,)).fetchone()
    if not user or user['deleting']:
        raise ValueError('用户不存在')
    code = secrets.token_hex(6).upper()
    db.execute('INSERT INTO platform_tg(user_id,code_hash,code_expires) VALUES(?,?,?) '
               'ON CONFLICT(user_id) DO UPDATE SET code_hash=excluded.code_hash,code_expires=excluded.code_expires',
               (user_id, code_hash(code), now + CODE_TTL))
    return code, now + CODE_TTL


def unbind(db, user_id):
    if not db.execute('SELECT 1 FROM platform_users WHERE id=?', (user_id,)).fetchone():
        raise ValueError('用户不存在')
    db.execute("UPDATE platform_tg SET chat_id=NULL,username='',bound_at=NULL WHERE user_id=?", (user_id,))


def bindings(db, now=None):
    now = time.time() if now is None else now
    rows = db.execute('SELECT platform_users.id,platform_users.name,platform_users.note,platform_tg.chat_id,platform_tg.username,'
                      'platform_tg.bound_at,platform_tg.code_expires FROM platform_users LEFT JOIN platform_tg ON platform_tg.user_id=platform_users.id '
                      'WHERE platform_users.deleting IS NULL ORDER BY platform_users.name').fetchall()
    return [{'id': r['id'], 'name': r['name'], 'note': r['note'], 'bound': r['chat_id'] is not None, 'username': r['username'] or '',
             'bound_at': r['bound_at'], 'code_pending': bool(r['code_expires'] and r['code_expires'] > now)} for r in rows]


def size(n):
    n = float(n or 0)
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if n < 1024 or unit == 'GiB':
            return ('%d %s' % (n, unit)) if unit == 'B' else ('%.1f %s' % (n, unit))
        n /= 1024
    return ''


def user_report(db, user, now):
    used = platform_users.usage(db, user['id'])
    state = platform_users.state_of(user, used, datetime.date.fromtimestamp(now))
    lines = ['流量查询', '用户：' + user['name'], '已使用：' + size(used)]
    if user['quota']:
        lines += ['总配额：' + size(user['quota']), '剩余流量：' + size(max(user['quota'] - used, 0)),
                  '使用率：%d%%' % (used * 100 // user['quota'])]
    else:
        lines += ['总配额：无限制', '剩余流量：无限制']
    lines += ['到期时间：' + (user['expire_date'] or '永不过期'), '账号状态：' + platform_users.STATE_TEXT.get(state, state)]
    links = db.execute('SELECT platform_links.cycle_used,nodes.name FROM platform_links JOIN nodes ON nodes.id=platform_links.node_id '
                       'WHERE platform_links.user_id=? AND platform_links.removing IS NULL ORDER BY nodes.name', (user['id'],)).fetchall()
    if links:
        lines.append('各节点用量：')
        lines += ['· %s：%s' % (link['name'], size(link['cycle_used'])) for link in links]
    return '\n'.join(lines)


def handle_update(store, update, now=None):
    """Return the reply text for one Telegram update, or None to stay silent."""
    now = time.time() if now is None else now
    message = update.get('message') if isinstance(update, dict) else None
    if not isinstance(message, dict) or (message.get('chat') or {}).get('type') != 'private':
        return None
    chat = str((message.get('chat') or {}).get('id', ''))
    text = message.get('text')
    if not re.fullmatch(r'[0-9]{1,24}', chat) or not isinstance(text, str) or not text.startswith('/'):
        return None
    parts = text.split()
    command, arg = parts[0].split('@')[0].lower(), (parts[1] if len(parts) > 1 else '')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        bound = db.execute('SELECT platform_users.* FROM platform_tg JOIN platform_users ON platform_users.id=platform_tg.user_id '
                           'WHERE platform_tg.chat_id=?', (chat,)).fetchone()
        if command == '/bind':
            code = arg.upper()
            if not arg:
                return '用法：/bind 绑定码'
            if not CODE.fullmatch(code):
                return '绑定码格式无效，请向管理员获取新的 12 位绑定码。'
            if bound:
                return '此 Telegram 已绑定账号。如需更换，请先发送 /unbind。'
            row = db.execute('SELECT platform_users.id,platform_users.name,platform_users.deleting FROM platform_tg '
                             'JOIN platform_users ON platform_users.id=platform_tg.user_id WHERE code_hash=? AND code_expires>?',
                             (code_hash(code), now)).fetchone()
            if not row or row['deleting']:
                return '绑定码无效或已过期，请向管理员重新获取。'
            username = (message.get('from') or {}).get('username')
            db.execute('UPDATE platform_tg SET chat_id=?,username=?,bound_at=?,code_hash=NULL,code_expires=NULL WHERE user_id=?',
                       (chat, username if isinstance(username, str) and len(username) <= 64 else '', now, row['id']))
            return '绑定成功：%s。\n发送 /traffic 查询流量。' % row['name']
        if command in ('/traffic', '/status'):
            return user_report(db, bound, now) if bound else '尚未绑定账号。请发送 /bind 绑定码。'
        if command == '/unbind':
            if not bound:
                return '当前 Telegram 尚未绑定账号。'
            unbind(db, bound['id'])
            return '已解除账号 %s 的 Telegram 绑定。' % bound['name']
        if command in ('/start', '/help'):
            return HELP
        return '未知命令。\n\n' + HELP


def poll_bot(store, now=None):
    config = settings(store, True)
    if not (config['bot_enabled'] and config['bot_token']):
        return 0
    updates = tg_call(config['bot_token'], 'getUpdates', {'offset': config['bot_offset'], 'limit': 100, 'timeout': 0,
                                                          'allowed_updates': ['message']})
    handled = 0
    for item in updates if isinstance(updates, list) else []:
        update_id = item.get('update_id') if isinstance(item, dict) else None
        if type(update_id) is not int:
            continue
        # Advance first: a reply that fails is not retried, a crash never replays a /bind.
        update(store, bot_offset=update_id + 1)
        reply = handle_update(store, item, now)
        if reply:
            deliver(config['bot_token'], item['message']['chat']['id'], reply)
        handled += 1
    return handled


# ---------------------------------------------------------------- incidents and queue

def queue(db, now, text, chat=None):
    db.execute('INSERT INTO notifications(at,title,status,chat_id) VALUES(?,?,?,?)', (now, text, 'pending', chat))


def transition(db, key, title, active, now, config, user_chat=None, user_text=None):
    old = db.execute('SELECT * FROM incidents WHERE key=?', (key,)).fetchone()
    if (old is None and not active) or (old and bool(old['active']) == active):
        return
    db.execute('INSERT OR REPLACE INTO incidents VALUES(?,?,?,?)', (key, int(active), now, title))
    if config['enabled']:
        queue(db, now, title if active else '已恢复：' + title)
    if active and user_chat and user_text and config['bot_enabled']:
        queue(db, now, user_text, user_chat)


def days_left(value, today):
    try:
        return (datetime.date.fromisoformat(value) - today).days
    except (TypeError, ValueError):
        return 9999


def scan(store, now=None):
    now = time.time() if now is None else now
    config = settings(store, True)
    pct = config['quota_percent']
    today = datetime.datetime.fromtimestamp(now).date()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute("UPDATE tasks SET status='unknown',finished=?,message='执行超时且结果未知，请核对节点' WHERE status='running' AND started<?", (now, now-2100))
        for node in db.execute('SELECT * FROM nodes WHERE deleted IS NULL AND revoked=0 AND last_seen IS NOT NULL').fetchall():
            if node['maintenance']:
                continue
            offline = now - node['last_seen'] > 120
            transition(db, 'offline:' + node['id'], node['name'] + ' · 节点离线', offline, now, config)
            if offline:
                continue
            snap = json.loads(node['snapshot'])
            if snap.get('error'):
                continue
            for item in snap.get('instances', []):
                for user in item.get('users', []):
                    if user.get('account_id'):
                        continue  # unified-account members alert once per account below
                    prefix = node['id'] + ':' + item['core'] + ':' + item['protocol'] + ':' + str(item['port']) + ':' + user['name']
                    label = node['name'] + ' · ' + item['protocol'] + ':' + str(item['port']) + ' · ' + user['name']
                    if item.get('traffic_state') == 'ready':
                        quota = user.get('quota', 0)
                        transition(db, 'quota:' + prefix, label + ' · 流量已达配额的 %d%%' % pct, bool(quota and user.get('used', 0) >= quota * pct / 100), now, config)
                        transition(db, 'overquota:' + prefix, label + ' · 流量已用尽', bool(quota and user.get('used', 0) >= quota), now, config)
                    transition(db, 'expiry:' + prefix, label + ' · 已到期或将在 3 天内到期', days_left(user.get('expire_date', ''), today) <= 3, now, config)
            linked = {r['account_id'] for r in db.execute('SELECT account_id FROM platform_links WHERE node_id=?', (node['id'],))}
            for account_id, account in snap.get('accounts', {}).items():
                if account_id in linked:
                    continue
                label = node['name'] + ' · 统一用户 ' + account.get('name', '')
                quota = account.get('quota', 0)
                transition(db, 'account-quota:' + node['id'] + ':' + account_id, label + ' · 流量已达配额的 %d%%' % pct, bool(quota and account.get('cycle_used', 0) >= quota * pct / 100), now, config)
                transition(db, 'account-over:' + node['id'] + ':' + account_id, label + ' · 流量已用尽', bool(quota and account.get('cycle_used', 0) >= quota), now, config)
                transition(db, 'account-expiry:' + node['id'] + ':' + account_id, label + ' · 已到期或将在 3 天内到期', days_left(account.get('expire_date', ''), today) <= 3, now, config)
        platform_users.rollover(db, now)
        platform_users.forget_missing(db)
        for user in db.execute('SELECT platform_users.*, platform_tg.chat_id AS tg_chat FROM platform_users '
                               'LEFT JOIN platform_tg ON platform_tg.user_id=platform_users.id').fetchall():
            used = platform_users.usage(db, user['id'])
            label = '平台用户 ' + user['name']
            chat = user['tg_chat']
            usage_text = '已使用：%s\n总配额：%s' % (size(used), size(user['quota']))
            transition(db, 'puser-quota:' + user['id'], label + ' · 总流量已达配额的 %d%%' % pct, bool(user['quota'] and used >= user['quota'] * pct / 100), now, config,
                       chat, '⚠️ 流量提醒\n用户：%s\n%s\n使用率已达 %d%%' % (user['name'], usage_text, used * 100 // max(user['quota'], 1)))
            transition(db, 'puser-over:' + user['id'], label + ' · 总流量已用尽，已停用全部节点', bool(user['quota'] and used >= user['quota']), now, config,
                       chat, '🚫 流量已用尽\n用户：%s\n%s\n账号已停用，请联系管理员。' % (user['name'], usage_text))
            transition(db, 'puser-expiry:' + user['id'], label + ' · 已到期或将在 3 天内到期', bool(user['enabled']) and days_left(user['expire_date'], today) <= 3, now, config,
                       chat, '⚠️ 账号即将到期\n用户：%s\n到期时间：%s' % (user['name'], user['expire_date']))
            failing = db.execute("SELECT 1 FROM platform_links WHERE user_id=? AND state IN ('failed','unknown')", (user['id'],)).fetchone()
            transition(db, 'puser-sync:' + user['id'], label + ' · 节点同步失败或结果未知', bool(failing), now, config)
        platform_users.auto_authority(db, now)
        platform_users.schedule(db, now)
        for task in db.execute("SELECT tasks.*, nodes.name FROM tasks JOIN nodes ON nodes.id=tasks.node_id WHERE tasks.status IN ('failed','unknown') AND finished>?", (now - 3600,)).fetchall():
            transition(db, 'task:' + task['id'], task['name'] + ' · 任务失败或结果未知：' + {'install':'安装协议','update':'修改实例','delete':'删除实例','user_add':'新增用户','user_update':'修改用户','user_delete':'删除用户','start':'启动服务','stop':'停止服务','restart':'重启服务','share':'导出连接','inspect':'检查配置','platform_apply':'平台用户同步','agent_upgrade':'一键升级','forward_apply':'端口转发','agent_set_url':'切换面板地址','core_update':'更新内核'}.get(task['action'], '节点操作') + '（' + task['id'][:8] + '）', True, now, config)
        if config['enabled'] and config['daily_enabled']:
            daily_report(db, now, config)
        db.execute('DELETE FROM samples WHERE bucket<?', (int(now//60)-7*1440,))
        from . import daily
        daily.prune(db, now)
        db.execute("DELETE FROM incidents WHERE key LIKE 'task:%' AND at<?", (now-2*86400,))
        db.execute("INSERT OR REPLACE INTO settings VALUES('monitor_heartbeat',?)", (str(now),))


def daily_report(db, now, config):
    """Queue the report once a day, within an hour after the configured time (panel server local time)."""
    local = datetime.datetime.fromtimestamp(now)
    hour, minute = map(int, config['daily_time'].split(':'))
    start = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if not start <= local < start + datetime.timedelta(hours=1):
        return
    day = local.date().isoformat()
    sent = db.execute("SELECT value FROM settings WHERE key='daily_report_day'").fetchone()
    if sent and sent[0] == day:
        return
    db.execute("INSERT OR REPLACE INTO settings VALUES('daily_report_day',?)", (day,))
    nodes = db.execute('SELECT last_seen,maintenance FROM nodes WHERE deleted IS NULL AND revoked=0').fetchall()
    online = sum(1 for n in nodes if n['last_seen'] and now - n['last_seen'] <= 120)
    users = db.execute('SELECT * FROM platform_users WHERE deleting IS NULL ORDER BY name').fetchall()
    total, rows = 0, []
    for user in users:
        used = platform_users.usage(db, user['id'])
        total += used
        state = platform_users.state_of(user, used, local.date())
        quota = '%s（%d%%）' % (size(user['quota']), used * 100 // user['quota']) if user['quota'] else '∞'
        rows.append('%s %s  %s / %s%s' % ('✅' if not state else '❌', user['name'], size(used), quota,
                                          '' if not state else '  ' + platform_users.STATE_TEXT.get(state, state)))
    text = '\n'.join(['📊 每日流量报告', '时间：' + local.strftime('%Y-%m-%d %H:%M'), '节点：在线 %d / %d' % (online, len(nodes)),
                      '平台用户：%d 个，总用量 %s' % (len(users), size(total)), '━━━━━━━━━━━━'])
    for index, row in enumerate(rows):
        if len(text) + len(row) > 3800:
            text += '\n…另有 %d 个用户' % (len(rows) - index)
            break
        text += '\n' + row
    queue(db, now, text)


def send_pending(store):
    config = settings(store, True)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # Rows left 'sending' by a dead process may have been delivered: drop them, never resend.
        db.execute("DELETE FROM notifications WHERE status!='pending'")
        pending = db.execute("SELECT * FROM notifications WHERE status='pending' ORDER BY id LIMIT 20").fetchall()
        for row in pending:
            db.execute("UPDATE notifications SET status='sending' WHERE id=?", (row['id'],))
    for row in pending:
        allowed = config['bot_enabled'] if row['chat_id'] else config['enabled']
        if allowed and config['bot_token']:
            deliver(config['bot_token'], row['chat_id'] or config['chat_id'], row['title'])
        with store.connect() as db:
            db.execute('DELETE FROM notifications WHERE id=?', (row['id'],))


def test_message(store, now=None):
    now = time.time() if now is None else now
    if not settings(store, True)['enabled']:
        raise ValueError('请先保存并启用 TG 通知')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        last = db.execute("SELECT value FROM settings WHERE key='notify_test_at'").fetchone()
        if last and now - float(last[0]) < 60:
            raise ValueError('请等待一分钟后再发送测试')
        db.execute("INSERT OR REPLACE INTO settings VALUES('notify_test_at',?)", (str(now),))
        queue(db, now, '🔔 测试消息：Vaio 面板 TG 通知已配置成功')


def worker(store):
    with open(store.path + '.monitor.lock', 'a') as lock:
        os.chmod(store.path + '.monitor.lock', 0o600)
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(30)
        tick = 0
        while True:
            try:
                poll_bot(store)
            except Exception:
                logging.warning('Telegram 用户机器人轮询失败，请检查网络与 Bot Token')
            try:
                if tick % 3 == 0:
                    scan(store)
                    day = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
                    if store.setting('backup_day') != day:
                        backups.create(store)
                        with store.connect() as db:
                            db.execute("INSERT OR REPLACE INTO settings VALUES('backup_day',?)", (day,))
                send_pending(store)
            except Exception:
                logging.error('监控或备份检查失败，请检查数据库权限和可用空间')
            tick += 1
            time.sleep(TICK)


def start(store):
    threading.Thread(target=worker, args=(store,), daemon=True, name='vaio-monitor').start()
