import hashlib
import io
import gzip
import json
import os
import re
import secrets
import shlex
import tarfile
import time
import uuid
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from . import __version__
from . import platform_users
from .common import FORWARD_FIELDS, MUTATIONS, LEGACY_COMBINATIONS, PROTOCOLS, digest, require_text, validate_forward_rule, validate_forward_task, validate_platform_task, validate_task, validate_upgrade_task
from .install_options import ADVANCED_INSTALL_FIELDS, REALITY_INSTALL_FIELDS
from .store import Store

ROOT = Path(__file__).resolve().parent.parent


def agent_archive():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for folder in ("vaio", "agent", "vendor"):
            for path in sorted((ROOT / folder).rglob("*")):
                if path.is_file() and "__pycache__" not in str(path) and path.suffix != ".pyc":
                    archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
        for name in ("vaio-agent", "update-agent.py"):
            archive.add(ROOT / "scripts" / name, arcname="scripts/" + name, recursive=False)
    return gzip.compress(buffer.getvalue(), mtime=0)


class LoopbackProxyFix:
    """Take the client address from Nginx's X-Forwarded-For, but only for requests that reach us over loopback.

    The installer binds gunicorn to 127.0.0.1:18080 behind Nginx, so every request would otherwise share
    127.0.0.1 (one login rate-limit bucket for everyone). A directly exposed backend (e.g. the Docker image on
    0.0.0.0) never sees a loopback peer from outside, so remote clients cannot spoof their address.
    """

    def __init__(self, app):
        self.app = app
        self.proxied = ProxyFix(app, x_for=1, x_proto=0, x_host=0, x_port=0, x_prefix=0)

    def __call__(self, environ, start_response):
        if environ.get("REMOTE_ADDR") in ("127.0.0.1", "::1"):
            return self.proxied(environ, start_response)
        return self.app(environ, start_response)


def queue_url_migration(db, public_url, retry=False, now=None):
    """Queue agent_set_url for nodes that have not switched to public_url yet (once per address; retry re-queues failures)."""
    from .common import validate_set_url_task
    now = time.time() if now is None else now
    prefix = "set-url:" + hashlib.sha256(public_url.encode()).hexdigest()[:12] + ":"
    request = json.dumps(validate_set_url_task({"action": "agent_set_url", "params": {"url": public_url}}))
    count = 0
    for node in db.execute("SELECT id FROM nodes WHERE adopted=1 AND deleted IS NULL AND revoked=0").fetchall():
        last = db.execute("SELECT status FROM tasks WHERE request_key LIKE ? AND node_id=? ORDER BY created DESC LIMIT 1", (prefix + "%", node["id"])).fetchone()
        if last and last["status"] in ("succeeded", "queued", "running", "unknown"):
            continue
        db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
                   (str(uuid.uuid4()), node["id"], "agent_set_url", request, "queued", now, prefix + uuid.uuid4().hex[:8]))
        count += 1
    return count


def create_app(config=None):
    app = Flask(__name__, static_folder=str(ROOT / "web"), static_url_path="/assets")
    app.config.update(MAX_CONTENT_LENGTH=1024 * 1024,
                      DATABASE=os.environ.get("VAIO_DATABASE", str(ROOT / "data/panel.sqlite")),
                      PUBLIC_URL=os.environ.get("VAIO_PUBLIC_URL", "http://127.0.0.1:8080").rstrip("/"),
                      TESTING=False)
    if config:
        app.config.update(config)
    url = urlsplit(app.config["PUBLIC_URL"])
    if url.scheme not in ("http", "https") or not url.hostname or url.path not in ("", "/") or url.query or url.fragment or url.username:
        raise ValueError("VAIO_PUBLIC_URL 必须是完整的 HTTP(S) 根地址")
    allow_http = app.config.get("ALLOW_HTTP", os.environ.get("VAIO_ALLOW_HTTP") == "1")
    if url.scheme != "https" and not allow_http and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("公网面板必须设置 HTTPS 地址（未绑定域名时由安装器设置 VAIO_ALLOW_HTTP=1）")
    store = Store(app.config["DATABASE"])
    app.extensions["store"] = store
    data_dir = Path(app.config["DATABASE"]).resolve().parent
    units = Path(app.config.get("SYSTEMD_DIR", "/etc/systemd/system"))   # root helper units; tests point elsewhere
    with store.connect() as db:
        # The panel came up on a different address than last time (domain bound or changed): tell every node once.
        # First start (fresh install or upgrade from 1.0.0) only records the address the nodes already use.
        db.execute("BEGIN IMMEDIATE")
        last = db.execute("SELECT value FROM settings WHERE key='panel_url'").fetchone()
        if last and last[0] != app.config["PUBLIC_URL"] and url.scheme == "https":
            queue_url_migration(db, app.config["PUBLIC_URL"])
        db.execute("INSERT OR REPLACE INTO settings VALUES('panel_url',?)", (app.config["PUBLIC_URL"],))
    if not app.config["TESTING"] and os.environ.get("VAIO_MONITOR", "1") != "0":
        from .monitor import start
        start(store)
    secure = url.scheme == "https"
    bundle = None

    def body():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("请求必须是 JSON 对象")
        return data

    def audit(db, event, node=None, detail=""):
        db.execute("INSERT INTO audit(at,event,node_id,detail) VALUES(?,?,?,?)", (time.time(), event, node, detail))

    def admin(fn):
        @wraps(fn)
        def decorated(*args, **kwargs):
            with store.connect() as db:
                session = db.execute("SELECT * FROM sessions WHERE token=? AND expires>?",
                                     (digest(request.cookies.get("vaio_session", "")), time.time())).fetchone()
            if not session:
                return jsonify(error="请登录管理面板"), 401
            if request.method != "GET" and not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                return jsonify(error="请求校验失败，请刷新页面"), 403
            g.session = session
            return fn(*args, **kwargs)
        return decorated

    def portal(fn):
        """Platform user's own page. Separate session table: a user cookie never passes `admin`."""
        @wraps(fn)
        def decorated(*args, **kwargs):
            with store.connect() as db:
                session = db.execute("SELECT user_sessions.* FROM user_sessions JOIN platform_users ON platform_users.id=user_sessions.user_id "
                                     "WHERE token=? AND expires>? AND platform_users.password_hash IS NOT NULL AND platform_users.deleting IS NULL",
                                     (digest(request.cookies.get("vaio_session", "")), time.time())).fetchone()
            if not session:
                return jsonify(error="请登录"), 401
            if request.method != "GET" and not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                return jsonify(error="请求校验失败，请刷新页面"), 403
            g.session = session
            return fn(*args, **kwargs)
        return decorated

    def agent(fn):
        @wraps(fn)
        def decorated(node_id, *args, **kwargs):
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            with store.connect() as db:
                node = db.execute("SELECT * FROM nodes WHERE id=? AND revoked=0 AND deleted IS NULL", (node_id,)).fetchone()
            if not node or not node["token_hash"] or not secrets.compare_digest(digest(token), node["token_hash"]):
                return jsonify(error="节点凭据无效或已撤销"), 401
            g.node = node
            return fn(node_id, *args, **kwargs)
        return decorated

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        if secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(ValueError)
    def bad_input(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get("/")
    def index():
        return send_file(ROOT / "web/index.html")

    @app.get("/api/monitor")
    @admin
    def monitor_get():
        from .monitor import settings, bindings
        with store.connect() as db:
            users = bindings(db)
        return jsonify(config=settings(store), users=users, heartbeat=store.setting("monitor_heartbeat"))

    @app.post("/api/monitor")
    @admin
    def monitor_save():
        from .monitor import save_settings
        save_settings(store, body())
        with store.connect() as db:
            audit(db, "notification.settings")
        return jsonify(ok=True)

    @app.post("/api/monitor/test")
    @admin
    def monitor_test():
        from .monitor import test_message
        test_message(store)
        return jsonify(ok=True)

    @app.post("/api/monitor/bot")
    @admin
    def monitor_bot():
        from .monitor import enable_bot
        data = body()
        if set(data) != {"enabled"} or type(data["enabled"]) is not bool:
            raise ValueError("机器人开关无效")
        result = enable_bot(store, data["enabled"])
        with store.connect() as db:
            audit(db, "notification.bot", detail="启用" if data["enabled"] else "禁用")
        return jsonify(ok=True, **result)

    @app.post("/api/users/<user_id>/tg-code")
    @admin
    def user_tg_code(user_id):
        from .monitor import new_code
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            code, expires = new_code(db, user_id)
            audit(db, "notification.bind_code", detail=user_id)
        return jsonify(code=code, expires=expires)

    @app.post("/api/users/<user_id>/tg-unbind")
    @admin
    def user_tg_unbind(user_id):
        from .monitor import unbind
        with store.connect() as db:
            unbind(db, user_id)
            audit(db, "notification.unbind", detail=user_id)
        return jsonify(ok=True)

    @app.get("/api/nodes/<node_id>/history")
    @admin
    def node_history(node_id):
        with store.connect() as db:
            data = [{"at": r["bucket"] * 60, **json.loads(r["metrics"])} for r in db.execute("SELECT bucket,metrics FROM samples WHERE node_id=? AND bucket>=? ORDER BY bucket", (node_id, int(time.time()//60)-1440))]
        return jsonify(samples=data)

    @app.get("/api/backups")
    @admin
    def backup_list():
        from .backups import listing
        return jsonify(backups=listing(store))

    @app.post("/api/backups")
    @admin
    def backup_create():
        from .backups import create
        name = create(store)
        with store.connect() as db:
            audit(db, "backup.create", detail=name)
        return jsonify(name=name)

    @app.post("/api/backups/verify")
    @admin
    def backup_verify():
        from .backups import drill
        data = drill(store, body().get("name"))
        with store.connect() as db:
            audit(db, "backup.verify")
        return jsonify(ok=True, **data)

    @app.get("/healthz")
    def health():
        return jsonify(status="ok", version=__version__)

    @app.post("/api/login")
    def login():
        # Restrict browser logins to the configured origin to prevent login CSRF.
        if request.headers.get("Origin") and request.headers["Origin"] != app.config["PUBLIC_URL"]:
            return jsonify(error="登录来源无效"), 403
        data = body()
        password = data.get("password", "")
        if not isinstance(password, str) or len(password) > 1024:
            raise ValueError("密码格式无效")
        username = data.get("username", "")
        if not isinstance(username, str) or len(username) > 32:
            raise ValueError("账号格式无效")
        ip, now = request.remote_addr or "unknown", time.time()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute("SELECT * FROM attempts WHERE ip=?", (ip,)).fetchone()
            if attempt and attempt["until"] > now and attempt["count"] >= 8:
                return jsonify(error="尝试次数过多，请 15 分钟后重试"), 429
            password_hash = db.execute("SELECT value FROM settings WHERE key='password' ").fetchone()
            if not password_hash:
                return jsonify(error="尚未初始化，请先在服务器运行 python -m vaio init"), 503
            username_row = db.execute("SELECT value FROM settings WHERE key='username'").fetchone()
            expected_username = username_row[0] if username_row else "admin"
            password_ok = check_password_hash(password_hash[0], password)
            role = "admin" if password_ok and username == expected_username else None
            member = None
            if not role and username != expected_username:
                # Platform user with login enabled (the admin's name is never a user login).
                member = db.execute("SELECT * FROM platform_users WHERE name=? AND password_hash IS NOT NULL AND deleting IS NULL",
                                    (username,)).fetchone()
                if member and check_password_hash(member["password_hash"], password):
                    role = "user"
            if not role:
                count = attempt["count"] + 1 if attempt and attempt["until"] > now else 1
                db.execute("INSERT OR REPLACE INTO attempts VALUES(?,?,?)", (ip, count, now + 900))
                return jsonify(error="账号或密码错误"), 401
            db.execute("DELETE FROM attempts WHERE ip=?", (ip,))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            if role == "admin":
                db.execute("DELETE FROM sessions WHERE expires<?", (now,))
                db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(token), csrf, now + 43200))
                audit(db, "login")
            else:
                db.execute("DELETE FROM user_sessions WHERE expires<?", (now,))
                db.execute("INSERT INTO user_sessions VALUES(?,?,?,?)", (digest(token), csrf, now + 43200, member["id"]))
                audit(db, "portal.login", detail=member["name"])
        response = jsonify(csrf=csrf, version=__version__, role=role)
        response.set_cookie("vaio_session", token, httponly=True, secure=secure, samesite="Strict", max_age=43200)
        return response

    @app.get("/api/session")
    @admin
    def session():
        return jsonify(csrf=g.session["csrf"], username=store.setting("username") or "admin", version=__version__, public_url=app.config["PUBLIC_URL"])

    @app.post("/api/account")
    @admin
    def account():
        data = body()
        username = data.get("username", "")
        current = data.get("current_password", "")
        password = data.get("new_password", "")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            raise ValueError("账号需为 3–32 位字母、数字、点、下划线或短横线")
        if not isinstance(current, str) or not current or len(current) > 1024:
            raise ValueError("请输入当前密码")
        if not isinstance(password, str) or (password and not 8 <= len(password) <= 128):
            raise ValueError("新密码需为 8–128 位")
        if password != data.get("confirm_password", ""):
            raise ValueError("两次输入的新密码不一致")
        now = time.time()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Recheck after taking the write lock: another change may revoke this session.
            if not db.execute("SELECT 1 FROM sessions WHERE token=? AND expires>?", (g.session["token"], now)).fetchone():
                return jsonify(error="请重新登录"), 401
            attempt = db.execute("SELECT * FROM attempts WHERE ip='account'").fetchone()
            if attempt and attempt["until"] > now and attempt["count"] >= 8:
                return jsonify(error="尝试次数过多，请 15 分钟后重试"), 429
            stored = db.execute("SELECT value FROM settings WHERE key='password'").fetchone()
            if not stored or not check_password_hash(stored[0], current):
                count = attempt["count"] + 1 if attempt and attempt["until"] > now else 1
                db.execute("INSERT OR REPLACE INTO attempts VALUES('account',?,?)", (count, now + 900))
                return jsonify(error="当前密码错误"), 400
            if db.execute("SELECT 1 FROM platform_users WHERE lower(name)=lower(?)", (username,)).fetchone():
                raise ValueError("该账号名已被平台用户使用，请换一个")
            db.execute("INSERT OR REPLACE INTO settings VALUES('username',?)", (username,))
            if password:
                db.execute("UPDATE settings SET value=? WHERE key='password'",
                           (generate_password_hash(password, method="pbkdf2:sha256:600000"),))
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM attempts WHERE ip='account'")
            audit(db, "account.update", detail="管理员登录信息已修改")
        response = jsonify(ok=True)
        response.delete_cookie("vaio_session")
        return response

    @app.post("/api/logout")
    def logout():
        token = digest(request.cookies.get("vaio_session", ""))
        with store.connect() as db:
            session = (db.execute("SELECT csrf FROM sessions WHERE token=?", (token,)).fetchone()
                       or db.execute("SELECT csrf FROM user_sessions WHERE token=?", (token,)).fetchone())
            if not session:
                return jsonify(error="请登录"), 401
            if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                return jsonify(error="请求校验失败，请刷新页面"), 403
            db.execute("DELETE FROM sessions WHERE token=?", (token,))
            db.execute("DELETE FROM user_sessions WHERE token=?", (token,))
        response = jsonify(ok=True)
        response.delete_cookie("vaio_session")
        return response

    def node_json(row):
        node = {key: row[key] for key in ("id", "name", "group_name", "adopted", "created", "last_seen", "revoked", "notes", "deleted", "maintenance")}
        node["status"] = "revoked" if row["revoked"] else "pending" if not row["last_seen"] else "online" if time.time() - row["last_seen"] < 45 else "offline"
        node["snapshot"] = json.loads(row["snapshot"])
        node["panel_version"] = __version__
        updater = shlex.quote(app.config["PUBLIC_URL"] + "/downloads/update-agent.py")
        node["update_command"] = '(umask 077; f=$(mktemp) || exit 1; trap \'rm -f "$f"\' EXIT HUP INT TERM; curl -fsS --max-time 60 ' + updater + ' -o "$f" && python3 "$f")'
        node["upgrade_available"] = bool(node["snapshot"].get("agent_version") and node["snapshot"]["agent_version"] != __version__)
        node["connection_hint"] = ("节点正在维护，暂不接受新任务" if node["maintenance"] else
            "节点身份已撤销，重新注册后才能连接" if row["revoked"] else
            "安装命令已过期，请重新生成" if node["status"] == "pending" and (row["enroll_expires"] or 0) < time.time() else
            "等待运行安装命令" if node["status"] == "pending" else
            "超过 45 秒未收到心跳，请在节点运行 vaio-agent status 或 vaio-agent logs" if node["status"] == "offline" else
            node["snapshot"].get("error") or "连接正常")
        return node

    @app.get("/api/nodes")
    @admin
    def nodes():
        with store.connect() as db:
            rows = db.execute("SELECT * FROM nodes WHERE deleted IS " + ("NOT NULL" if request.args.get("deleted") == "1" else "NULL") + " ORDER BY created DESC").fetchall()
        return jsonify(nodes=[node_json(r) for r in rows])

    @app.get("/api/nodes/<node_id>")
    @admin
    def node_detail(node_id):
        with store.connect() as db:
            row = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return (jsonify(node_json(row)) if row and not row["deleted"] else (jsonify(error="节点不存在"), 404))

    @app.post("/api/nodes/<node_id>/settings")
    @admin
    def node_settings(node_id):
        data = body()
        name = require_text(data.get("name"), "节点名称")
        group = require_text(data.get("group_name") or "默认分组", "分组", 40)
        notes = data.get("notes", "")
        if not isinstance(notes, str) or len(notes) > 1000 or "\x00" in notes:
            raise ValueError("备注最多 1000 字")
        with store.connect() as db:
            if not db.execute("UPDATE nodes SET name=?,group_name=?,notes=? WHERE id=? AND deleted IS NULL", (name, group, notes, node_id)).rowcount:
                return jsonify(error="节点不存在"), 404
            audit(db, "node.update", node_id, "节点名称、分组或备注已修改")
        return jsonify(ok=True)

    @app.post("/api/nodes/<node_id>/delete")
    @admin
    def delete_node(node_id):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM nodes WHERE id=? AND deleted IS NULL", (node_id,)).fetchone()
            if not row:
                return jsonify(error="节点不存在"), 404
            if row["maintenance"] or db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status IN ('running','unknown')", (node_id,)).fetchone():
                return jsonify(error="节点正在维护或有未核对任务，暂不能删除"), 409
            db.execute("UPDATE nodes SET deleted=?,revoked=1,token_hash=NULL,enroll_hash=NULL WHERE id=?", (time.time(), node_id))
            db.execute("UPDATE tasks SET status='cancelled',finished=? WHERE node_id=? AND status='queued'", (time.time(), node_id))
            audit(db, "node.delete", node_id, "移入回收站；代理服务未卸载")
        return jsonify(ok=True)

    @app.post("/api/nodes/<node_id>/restore")
    @admin
    def restore_node(node_id):
        with store.connect() as db:
            if not db.execute("UPDATE nodes SET deleted=NULL WHERE id=? AND deleted IS NOT NULL", (node_id,)).rowcount:
                return jsonify(error="回收站中未找到节点"), 404
            audit(db, "node.restore", node_id, "恢复记录；需要重新注册")
        return jsonify(ok=True)

    @app.post("/api/agent/<node_id>/maintenance")
    @agent
    def maintenance(node_id):
        enabled = body().get("enabled")
        if type(enabled) is not bool:
            raise ValueError("维护状态无效")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM nodes WHERE id=? AND token_hash=? AND revoked=0 AND deleted IS NULL", (node_id, g.node["token_hash"])).fetchone()
            if not row:
                return jsonify(error="节点身份已失效"), 401
            if enabled and db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status IN ('queued','running','unknown')", (node_id,)).fetchone():
                return jsonify(error="请先完成或核对节点任务再升级"), 409
            db.execute("UPDATE nodes SET maintenance=? WHERE id=?", (enabled, node_id))
            audit(db, "node.maintenance", node_id, "进入维护" if enabled else "结束维护")
        return jsonify(ok=True)

    @app.get("/api/agent/<node_id>/status")
    @agent
    def agent_status(node_id):
        return jsonify(last_seen=g.node["last_seen"], version=json.loads(g.node["snapshot"]).get("agent_version"), maintenance=bool(g.node["maintenance"]))

    @app.get("/downloads/update-agent.py")
    def agent_updater():
        return send_file(ROOT / "scripts/update-agent.py", mimetype="text/plain")

    def enrollment(node_id, token):
        # Download script uses token via stdin, never as a URL query or process argument.
        payload = json.dumps({"url": app.config["PUBLIC_URL"], "node_id": node_id, "enroll_token": token,
                              **({"allow_http": True} if url.scheme == "http" else {})})
        script = (ROOT / "scripts/install-agent.sh").read_text()
        script = script.replace("@@URL@@", shlex.quote(app.config["PUBLIC_URL"]))
        script = script.replace("@@ENROLLMENT@@", payload)
        address = shlex.quote(app.config["PUBLIC_URL"] + "/api/install/" + node_id)
        header = shlex.quote('header = "Authorization: Bearer ' + token + '"')
        command = ("(umask 077; f=$(mktemp) || exit 1; trap 'rm -f \"$f\"' EXIT HUP INT TERM; "
                   + "printf '%s\\n' " + header + " | curl --fail --silent --show-error --max-time 60 --config - "
                   + address + ' -o "$f" && sh "$f")')
        return dict(node_id=node_id, expires_in=1800, script=script, command=command)

    @app.get("/api/install/<node_id>")
    def install_script(node_id):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        with store.connect() as db:
            row = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if (not row or row["revoked"] or not row["enroll_hash"] or
                row["enroll_expires"] <= time.time() or
                not secrets.compare_digest(digest(token), row["enroll_hash"])):
            return jsonify(error="安装凭据无效或已过期，请重新生成"), 401
        return app.response_class(enrollment(node_id, token)["script"], mimetype="text/x-shellscript")

    @app.post("/api/nodes")
    @admin
    def add_node():
        data = body()
        name = require_text(data.get("name"), "节点名称")
        group = data.get("group_name", "默认分组") or "默认分组"
        require_text(group, "分组", 40)
        node_id, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        with store.connect() as db:
            db.execute("INSERT INTO nodes(id,name,group_name,enroll_hash,enroll_expires,created) VALUES(?,?,?,?,?,?)",
                       (node_id, name, group, digest(token), time.time() + 1800, time.time()))
            audit(db, "node.create", node_id, name)
        return jsonify(enrollment(node_id, token)), 201

    @app.post("/api/nodes/<node_id>/enrollment")
    @admin
    def renew(node_id):
        token = secrets.token_urlsafe(32)
        with store.connect() as db:
            if not db.execute("SELECT 1 FROM nodes WHERE id=? AND deleted IS NULL AND maintenance=0", (node_id,)).fetchone():
                return jsonify(error="节点不存在"), 404
            if db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status='running'", (node_id,)).fetchone():
                return jsonify(error="有执行中任务，暂不能重置节点身份"), 409
            db.execute("UPDATE nodes SET enroll_hash=?, enroll_expires=?,token_hash=NULL,revoked=0,adopted=0,last_seen=NULL WHERE id=?",
                       (digest(token), time.time() + 1800, node_id))
            db.execute("UPDATE tasks SET status='cancelled',finished=? WHERE node_id=? AND status='queued'", (time.time(), node_id))
            audit(db, "node.reenroll", node_id)
        return jsonify(enrollment(node_id, token))

    @app.post("/api/nodes/<node_id>/adopt")
    @admin
    def adopt(node_id):
        data = body()
        if set(data) - {"revision", "clear_users"}:
            raise ValueError("参数无效")
        revision = data.get("revision")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
            if not row or row["revoked"] or not row["last_seen"] or time.time() - row["last_seen"] > 45:
                return jsonify(error="请等待节点上线"), 409
            snap = json.loads(row["snapshot"])
            if not revision or revision != snap.get("revision") or snap.get("error"):
                return jsonify(error="配置状态已变化，请刷新后重试"), 409
            # Adopted servers are managed by the platform: switch user authority in the same step.
            switch = snap.get("authority_version") == 1 and snap.get("accounts_version") == 1 and snap.get("user_authority") != "platform"
            users = sum(len(i.get("users") or []) for i in snap.get("instances", []))
            if switch and users and data.get("clear_users") is not True:
                return jsonify(error="接管将切到平台管理并删除节点上的 %d 个脚本用户，请确认" % users), 409
            db.execute("UPDATE nodes SET adopted=1 WHERE id=?", (node_id,))
            audit(db, "node.adopt", node_id)
            if not switch:
                return jsonify(ok=True, authority="platform" if snap.get("user_authority") == "platform" else "unsupported")
            if db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status IN ('queued','running','unknown')", (node_id,)).fetchone():
                return jsonify(ok=True, authority="pending", message="节点有未完成的任务，完成后请在节点详情中切换为平台管理")
            task_id = str(uuid.uuid4())
            request_body = validate_platform_task({"action": "platform_apply", "params": {"ops": [{"op": "set_authority", "mode": "platform"}]}})
            db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
                       (task_id, node_id, "platform_apply", json.dumps(request_body), "queued", time.time(), "system:" + task_id))
            audit(db, "task.queued", node_id, task_id + " platform_apply（接管时切到平台管理）")
        return jsonify(ok=True, authority="switching", task_id=task_id)

    @app.post("/api/nodes/<node_id>/revoke")
    @admin
    def revoke(node_id):
        with store.connect() as db:
            if db.execute("SELECT 1 FROM nodes WHERE id=? AND maintenance=1", (node_id,)).fetchone():
                return jsonify(error="节点正在维护，请完成升级后再撤销"), 409
            db.execute("UPDATE nodes SET revoked=1,token_hash=NULL,enroll_hash=NULL WHERE id=?", (node_id,))
            db.execute("UPDATE tasks SET status='cancelled',finished=? WHERE node_id=? AND status='queued'", (time.time(), node_id))
            audit(db, "node.revoke", node_id)
        return jsonify(ok=True)

    @app.post("/api/enroll")
    def enroll():
        data = body()
        node_id, token = data.get("node_id"), data.get("enroll_token", "")
        if not isinstance(token, str) or not isinstance(node_id, str):
            raise ValueError("注册参数无效")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM nodes WHERE id=? AND revoked=0 AND deleted IS NULL", (node_id,)).fetchone()
            if not row or not row["enroll_hash"] or row["enroll_expires"] < time.time() or not secrets.compare_digest(digest(token), row["enroll_hash"]):
                return jsonify(error="注册凭据过期、已使用或无效，请重新生成安装脚本"), 401
            identity = secrets.token_urlsafe(48)
            db.execute("UPDATE nodes SET token_hash=?,enroll_hash=NULL,enroll_expires=NULL WHERE id=?", (digest(identity), node_id))
            audit(db, "node.enrolled", node_id)
        return jsonify(token=identity, node_id=node_id)

    @app.get("/downloads/agent.tar.gz")
    def download_agent():
        nonlocal bundle
        if bundle is None:
            bundle = agent_archive()
        return send_file(io.BytesIO(bundle), mimetype="application/gzip", download_name="agent.tar.gz")

    @app.get("/downloads/agent.sha256")
    def checksum():
        import hashlib
        nonlocal bundle
        if bundle is None:
            bundle = agent_archive()
        return hashlib.sha256(bundle).hexdigest() + "  agent.tar.gz\n", 200, {"Content-Type": "text/plain"}

    @app.post("/api/agent/<node_id>/poll")
    @agent
    def poll(node_id):
        data = body()
        snapshot = data.get("snapshot", {})
        from agent.inventory import sanitize_snapshot
        snapshot = sanitize_snapshot(snapshot)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM nodes WHERE id=? AND token_hash=? AND revoked=0 AND deleted IS NULL", (node_id, g.node["token_hash"])).fetchone()
            if not current:
                return jsonify(error="节点身份已失效"), 401
            db.execute("UPDATE nodes SET last_seen=?,snapshot=? WHERE id=?", (time.time(), json.dumps(snapshot), node_id))
            platform_users.ingest(db, node_id, snapshot)
            db.execute("INSERT OR IGNORE INTO samples VALUES(?,?,?)", (node_id, int(time.time() // 60), json.dumps(snapshot.get("metrics", {}))))
            # Ambiguous tasks are never automatically replayed.
            db.execute("UPDATE tasks SET status='unknown',message='执行结果未确认；请核对节点后重新操作',finished=? WHERE node_id=? AND status='running' AND started<?",
                       (time.time(), node_id, time.time() - 2100))
            db.execute("UPDATE tasks SET result=NULL WHERE action='share' AND finished<?", (time.time() - 600,))
            platform_users.auto_authority(db)
            platform_users.schedule(db)
            busy = db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status='running'", (node_id,)).fetchone()
            task = None
            if not busy and not current["maintenance"] and data.get("ready") is True:
                task = db.execute("SELECT * FROM tasks WHERE node_id=? AND status='queued' ORDER BY created LIMIT 1", (node_id,)).fetchone()
                if task:
                    db.execute("UPDATE tasks SET status='running',started=? WHERE id=?", (time.time(), task["id"]))
        return jsonify(task={"id": task["id"], **json.loads(task["request"])} if task else None, interval=10)

    @app.post("/api/agent/<node_id>/tasks/<task_id>/result")
    @agent
    def result(node_id, task_id):
        data = body()
        if data.get("status") not in ("succeeded", "failed", "unknown"):
            raise ValueError("结果状态无效")
        message = require_text(data.get("message", "完成"), "任务结果", 2000)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE id=? AND node_id=?", (task_id, node_id)).fetchone()
            if not task:
                return jsonify(error="任务不存在"), 404
            if task["status"] in ("succeeded", "failed", "unknown", "resolved"):
                return jsonify(ok=True)
            if task["status"] != "running":
                return jsonify(error="任务尚未领取"), 409
            detail = data.get("result", {})
            if not isinstance(detail, dict) or len(json.dumps(detail)) > 32000:
                raise ValueError("结果过大")
            # Keep only intentionally supported result fields; raw logs never enter the panel DB.
            detail = {k: v for k, v in detail.items() if k in ("connection", "config_details", "backup", "steps", "affected", "accounts", "rule")}
            if task["action"] != "share":
                detail.pop("connection", None)
                detail.pop("config_details", None)
            db.execute("UPDATE tasks SET status=?,finished=?,message=?,result=? WHERE id=?",
                       (data["status"], time.time(), message, json.dumps(detail), task_id))
            if task["action"] == "platform_apply":
                platform_users.task_finished(db, task, data["status"], message)
            if task["action"] == "install":
                platform_users.install_finished(db, task, data["status"])
            if task["action"] == "forward_apply":
                from . import relays
                relays.task_finished(db, task, data["status"], detail, message=message)
            audit(db, "task." + data["status"], node_id, task_id)
        return jsonify(ok=True)

    @app.post("/api/nodes/<node_id>/tasks")
    @admin
    def create_task(node_id):
        task = validate_task(body())
        key = require_text(request.headers.get("Idempotency-Key"), "请求 ID", 100, r"[A-Za-z0-9_-]+")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM tasks WHERE request_key=?", (key,)).fetchone()
            if old:
                if old["node_id"] != node_id or json.loads(old["request"]) != task:
                    return jsonify(error="请求 ID 已用于其他操作"), 409
                return jsonify(id=old["id"], status=old["status"])
            node = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
            if not node or node["deleted"] or node["revoked"] or not node["last_seen"] or time.time() - node["last_seen"] > 45:
                return jsonify(error="节点离线或身份已撤销"), 409
            if task["action"] == "share" and not task["params"].get("host") and json.loads(node["snapshot"]).get("config_details_version") != 2:
                return jsonify(error="请先升级节点程序以自动读取完整配置"), 409
            if ("quota_gb" in task["params"] or "reset_day" in task["params"]) and json.loads(node["snapshot"]).get("billing_version") != 1:
                return jsonify(error="请先升级节点程序以使用计费管理"), 409
            if node["maintenance"]:
                return jsonify(error="节点正在维护，请稍后再试"), 409
            capabilities = json.loads(node["snapshot"]).get("write_capabilities", [])
            options_version = json.loads(node["snapshot"]).get("install_options_version", 0)
            if task["action"] == "install" and set(task["params"]) & REALITY_INSTALL_FIELDS and options_version != 2:
                return jsonify(error="节点不支持 Reality 自定义参数，请先升级 Agent"), 409
            if task["action"] == "install" and set(task["params"]) & ADVANCED_INSTALL_FIELDS and options_version not in (1, 2):
                return jsonify(error="节点不支持高级安装参数，请先升级 Agent"), 409
            if "reset_credentials" in task["params"] and json.loads(node["snapshot"]).get("task_api_version", 1) < 2:
                return jsonify(error="节点不支持凭据重置，请先升级 Agent"), 409
            script_share = task["action"] in ("share", "inspect") and json.loads(node["snapshot"]).get("share_version") == 2 and task["protocol"] not in PROTOCOLS
            if not script_share and (task["core"], task["protocol"]) not in LEGACY_COMBINATIONS and {"core": task["core"], "protocol": task["protocol"]} not in capabilities:
                return jsonify(error="节点尚未声明此协议写入能力，请先升级 Agent"), 409
            snapshot = json.loads(node["snapshot"])
            if task["action"].startswith("user_") and snapshot.get("authority_version") == 1:
                # Users are managed by exactly one side; nodes that report it never take panel user edits here.
                return jsonify(error="该节点的用户由平台「用户管理」管理" if snapshot.get("user_authority") == "platform"
                               else "该节点的用户由节点脚本管理，面板只读；可在节点详情中切换为平台管理"), 409
            if task["action"] in MUTATIONS:
                if db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status='unknown'", (node_id,)).fetchone():
                    return jsonify(error="该节点有结果未知的任务，请先核对并处理，再提交写入"), 409
                if not node["adopted"]:
                    return jsonify(error="请先确认接管节点"), 409
                if task["revision"] != json.loads(node["snapshot"]).get("revision"):
                    return jsonify(error="配置已变化，请刷新"), 409
            if db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status IN ('queued','running')", (node_id,)).fetchone():
                return jsonify(error="该节点已有未完成任务，请等待执行完成"), 409
            task_id = str(uuid.uuid4())
            db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
                       (task_id, node_id, task["action"], json.dumps(task), "queued", time.time(), key))
            audit(db, "task.queued", node_id, task_id + " " + task["action"])
        return jsonify(id=task_id, status="queued"), 201

    @app.get("/api/tasks")
    @admin
    def tasks():
        node_id = request.args.get("node_id")
        with store.connect() as db:
            db.execute("UPDATE tasks SET result=NULL WHERE action='share' AND finished<?", (time.time() - 600,))
            db.execute("UPDATE tasks SET status='unknown',message='执行超时，结果未确认；不会自动重试',finished=? WHERE status='running' AND started<?", (time.time(), time.time() - 2100))
            rows = db.execute("SELECT tasks.*,nodes.name node_name FROM tasks JOIN nodes ON nodes.id=tasks.node_id "
                              + ("WHERE node_id=? " if node_id else "") + "ORDER BY created DESC LIMIT 100",
                              (node_id,) if node_id else ()).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["request"] = json.loads(item["request"])
            item["request"].get("params", {}).pop("credential", None)
            item["request"].get("params", {}).pop("private_key", None)
            item["result"] = json.loads(item["result"] or "{}")
            if item["action"] == "share" and item["finished"] and item["finished"] < time.time() - 600:
                item["result"] = {}
            output.append(item)
        return jsonify(tasks=output)

    @app.get("/api/tasks/<task_id>/qr")
    @admin
    def connection_qr(task_id):
        with store.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=? AND action='share' AND status='succeeded'", (task_id,)).fetchone()
        return qr_response(row)

    def qr_response(row):
        import qrcode
        import qrcode.image.svg
        if not row or row['status'] != 'succeeded' or not row['finished'] or row['finished'] < time.time() - 600:
            return jsonify(error="连接信息不存在或已过期"), 404
        connection = json.loads(row['result'] or '{}').get('connection')
        if not isinstance(connection, str) or not connection or len(connection) > 4096:
            return jsonify(error="没有可生成二维码的连接信息"), 404
        output = io.BytesIO()
        try:
            qrcode.make(connection, image_factory=qrcode.image.svg.SvgPathImage).save(output)
        except qrcode.exceptions.DataOverflowError:
            return jsonify(error="连接信息过长，请复制配置"), 400
        response = app.response_class(output.getvalue(), mimetype="image/svg+xml")
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post("/api/tasks/<task_id>/resolve")
    @admin
    def resolve_task(task_id):
        note = require_text(body().get("note"), "核对说明", 500)
        with store.connect() as db:
            if not db.execute("UPDATE tasks SET status='resolved',message=? WHERE id=? AND status='unknown'", ("人工核对：" + note, task_id)).rowcount:
                return jsonify(error="仅待核对任务可以标记已核对"), 409
            platform_users.release_task(db, task_id)
            audit(db, "task.resolved", detail=task_id)
        return jsonify(ok=True)

    @app.post("/api/tasks/<task_id>/cancel")
    @admin
    def cancel(task_id):
        with store.connect() as db:
            if not db.execute("UPDATE tasks SET status='cancelled',finished=? WHERE id=? AND status='queued'", (time.time(), task_id)).rowcount:
                return jsonify(error="仅等待中的任务可以取消"), 409
            platform_users.release_task(db, task_id)
            audit(db, "task.cancelled", detail=task_id)
        return jsonify(ok=True)

    def platform_nodes(db):
        return {r["id"]: r for r in db.execute("SELECT * FROM nodes").fetchall()}

    @app.get("/api/users")
    @admin
    def platform_user_list():
        with store.connect() as db:
            nodes = platform_nodes(db)
            users = [platform_users.describe(db, u, nodes) for u in db.execute("SELECT * FROM platform_users ORDER BY name").fetchall()]
        return jsonify(users=users)

    @app.post("/api/users")
    @admin
    def platform_user_create():
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            data = body()
            # The form always sends a password; without one the user gets create_user's random password.
            password = data.pop("password", None) if isinstance(data, dict) else None
            password = user_password(password) if password is not None else None
            check_admin_name(db, data.get("name") if isinstance(data, dict) else None)
            identity = platform_users.create_user(db, data)
            if password:
                db.execute("UPDATE platform_users SET password_hash=? WHERE id=?", (password, identity))
            audit(db, "platform.user_created", detail=identity)
        return jsonify(id=identity), 201

    @app.get("/api/users/<user_id>")
    @admin
    def platform_user_detail(user_id):
        with store.connect() as db:
            user = db.execute("SELECT * FROM platform_users WHERE id=?", (user_id,)).fetchone()
            if not user:
                return jsonify(error="用户不存在"), 404
            return jsonify(user=platform_users.describe(db, user, platform_nodes(db)))

    def platform_change(user_id, event, action):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM platform_users WHERE id=?", (user_id,)).fetchone():
                return jsonify(error="用户不存在"), 404
            result = action(db)
            audit(db, event, detail=user_id)
            platform_users.schedule(db)
        return jsonify(ok=True, **(result or {}))

    @app.post("/api/users/<user_id>")
    @admin
    def platform_user_update(user_id):
        data = body()
        password = data.pop("password", None) if isinstance(data, dict) else None
        password = user_password(password) if password else None
        def action(db):
            if isinstance(data, dict) and "name" in data:
                check_admin_name(db, data["name"])
            changed = sorted(platform_users.update_user(db, user_id, data)) if data else []
            if password:
                # A reset password signs the user out everywhere.
                db.execute("UPDATE platform_users SET password_hash=? WHERE id=?", (password, user_id))
                db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
                changed.append("password")
            return {"changed": changed}
        return platform_change(user_id, "platform.user_updated", action)

    def user_password(password):
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise ValueError("登录密码需为 8–128 位")
        return generate_password_hash(password, method="pbkdf2:sha256:600000")

    def check_admin_name(db, name):
        admin_name = db.execute("SELECT value FROM settings WHERE key='username'").fetchone()
        if isinstance(name, str) and name.lower() == (admin_name[0] if admin_name else "admin").lower():
            raise ValueError("用户名不能与管理员账号相同")

    @app.post("/api/users/<user_id>/delete")
    @admin
    def platform_user_delete(user_id):
        mode = body().get("mode")
        def action(db):
            db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
            return {"deleted": platform_users.delete_user(db, user_id, mode)}
        return platform_change(user_id, "platform.user_deleted", action)

    @app.post("/api/users/<user_id>/links")
    @admin
    def platform_link_add(user_id):
        data = body()
        if set(data) - {"node_id", "members"} or not isinstance(data.get("node_id"), str):
            raise ValueError("关联参数无效")
        return platform_change(user_id, "platform.link_added", lambda db: {"link_id": platform_users.add_link(
            db, user_id, data["node_id"], data.get("members"))})

    @app.post("/api/users/<user_id>/reset-usage")
    @admin
    def platform_user_reset_usage(user_id):
        return platform_change(user_id, "platform.usage_reset", lambda db: platform_users.reset_usage(db, user_id))

    @app.post("/api/users/<user_id>/reset-credentials")
    @admin
    def platform_user_reset_credentials(user_id):
        data = body()
        return platform_change(user_id, "platform.credentials_reset", lambda db: platform_users.reset_credentials(db, user_id, data.get("link_id"), data.get("member")))

    def link_change(link_id, event, action):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            link = db.execute("SELECT * FROM platform_links WHERE id=?", (link_id,)).fetchone()
            if not link:
                return jsonify(error="关联不存在"), 404
            action(db, link)
            audit(db, event, link["node_id"], link["user_id"])
            platform_users.schedule(db)
        return jsonify(ok=True)

    @app.post("/api/links/<link_id>/remove")
    @admin
    def platform_link_remove(link_id):
        mode = body().get("mode")
        return link_change(link_id, "platform.link_removed", lambda db, link: platform_users.remove_link(db, link_id, mode))

    @app.post("/api/links/<link_id>/members")
    @admin
    def platform_link_member(link_id):
        data = body()
        return link_change(link_id, "platform.member_changed", lambda db, link: platform_users.member_op(db, link, data))

    def node_task(node_id, action, request, check):
        """System-built task for one node (authority switch, upgrade); no parameters cross the wire."""
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            node = db.execute("SELECT * FROM nodes WHERE id=? AND deleted IS NULL AND revoked=0", (node_id,)).fetchone()
            if not node or not node["last_seen"] or time.time() - node["last_seen"] > 45:
                return jsonify(error="节点离线或身份已撤销"), 409
            if node["maintenance"]:
                return jsonify(error="节点正在维护，请稍后再试"), 409
            if not node["adopted"]:
                return jsonify(error="请先确认接管节点"), 409
            error = check(node, json.loads(node["snapshot"]))
            if error:
                return jsonify(error=error), 409
            if callable(request):
                request = request()
            if db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status IN ('queued','running','unknown')", (node_id,)).fetchone():
                return jsonify(error="该节点有未完成或待核对的任务，请先处理"), 409
            task_id = str(uuid.uuid4())
            db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
                       (task_id, node_id, action, json.dumps(request), "queued", time.time(), "system:" + task_id))
            audit(db, "task.queued", node_id, task_id + " " + action)
        return jsonify(id=task_id, status="queued"), 201

    @app.post("/api/nodes/<node_id>/install-users")
    @admin
    def install_users(node_id):
        data = body()
        if set(data) - {"task_id", "user_ids"} or not isinstance(data.get("task_id"), str):
            raise ValueError("参数无效")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            platform_users.plan_install(db, node_id, data["task_id"], data.get("user_ids"))
            audit(db, "platform.install_users", node_id, data["task_id"])
        return jsonify(ok=True)

    @app.post("/api/nodes/<node_id>/authority")
    @admin
    def node_authority(node_id):
        data = body()
        mode = data.get("mode")
        if set(data) - {"mode", "confirm"} or mode not in ("script", "platform"):
            raise ValueError("用户管理方式无效")
        def check(node, snapshot):
            if snapshot.get("authority_version") != 1 or snapshot.get("accounts_version") != 1:
                return "该节点程序或脚本版本过旧，请先升级节点"
            if snapshot.get("user_authority") == mode:
                return "该节点已是此管理方式"
            if mode == "platform" and data.get("confirm") != node["name"]:
                return "请输入节点名称确认：切换后节点上的全部用户和凭据都会删除"
        return node_task(node_id, "platform_apply", validate_platform_task(
            {"action": "platform_apply", "params": {"ops": [{"op": "set_authority", "mode": mode}]}}), check)

    @app.post("/api/nodes/<node_id>/forwards")
    @admin
    def node_forward(node_id):
        """One port-forward change on one node. The base is the rule as last reported by the node."""
        data = body()
        op = data.get("op")
        allowed = {"add": {"op", "rule"}, "update": {"op", "id", "rule"}, "delete": {"op", "id"}, "enable": {"op", "id"}, "disable": {"op", "id"}}
        if op not in allowed or set(data) != allowed[op]:
            raise ValueError("转发操作无效")
        rule = validate_forward_rule(data["rule"]) if "rule" in data else None
        holder = {}

        def check(node, snapshot):
            if snapshot.get("forward_version") != 1:
                return "该节点程序或脚本版本过旧，请先升级节点"
            rules = snapshot.get("forwards", [])
            if op != "add":
                current = next((r for r in rules if r.get("id") == data["id"]), None)
                if current is None:
                    return "转发规则不存在，请刷新后重试"
                holder["base"] = {k: current[k] for k in ("id",) + FORWARD_FIELDS if k in current}
            target = rule if rule else ({**holder["base"], "enabled": True} if op == "enable" else None)
            if target and target.get("enabled", True):
                kinds = lambda t: {"tcp", "udp"} if t == "tcp+udp" else {t}
                for other in rules:
                    if other.get("id") != data.get("id") and other.get("listen_port") == target["listen_port"] and kinds(other.get("transport")) & kinds(target["transport"]):
                        return "监听端口 %d 已被该节点的其他转发规则使用" % target["listen_port"]
                if any(i.get("port") == target["listen_port"] for i in snapshot.get("instances", [])):
                    return "监听端口 %d 已被该节点的代理协议使用" % target["listen_port"]

        def request_body():
            entry = {"op": op}
            if op != "add":
                entry.update(id=data["id"], base=holder["base"])
            if rule is not None:
                entry["rule"] = rule
            return validate_forward_task({"action": "forward_apply", "params": {"ops": [entry]}})
        return node_task(node_id, "forward_apply", request_body, check)

    @app.get("/api/relays")
    @admin
    def relay_list():
        from . import relays
        with store.connect() as db:
            nodes = {n["id"]: n for n in db.execute("SELECT * FROM nodes")}
            lines = [relays.describe(db, line, nodes) for line in db.execute("SELECT * FROM relay_lines ORDER BY created DESC")]
        return jsonify(relays=lines)

    def relay_change(event, action):
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = action(db)
            audit(db, event, None, result if isinstance(result, str) else "")
        return result

    @app.post("/api/relays")
    @admin
    def relay_create():
        from . import relays
        data = body()
        return jsonify(id=relay_change("relay.created", lambda db: relays.create(db, data))), 201

    @app.post("/api/relays/<line_id>/delete")
    @admin
    def relay_delete(line_id):
        from . import relays
        relay_change("relay.deleted", lambda db: relays.remove(db, line_id) or line_id)
        return jsonify(ok=True)

    @app.post("/api/relays/<line_id>/retry")
    @admin
    def relay_retry(line_id):
        from . import relays
        relay_change("relay.retried", lambda db: relays.retry(db, line_id) or line_id)
        return jsonify(ok=True)

    @app.post("/api/relays/<line_id>/share")
    @admin
    def relay_share(line_id):
        from . import relays
        return jsonify(id=relay_change("relay.share", lambda db: relays.share(db, line_id))), 201

    # ------------------------------------------------------------ platform user's own page
    def portal_user(db):
        return db.execute("SELECT * FROM platform_users WHERE id=?", (g.session["user_id"],)).fetchone()

    @app.get("/api/me")
    @portal
    def me():
        from . import portal as portal_view
        from .monitor import bot_info
        with store.connect() as db:
            data = portal_view.view(db, portal_user(db))
        data["telegram"]["bot"] = bot_info(store)
        return jsonify(**data, csrf=g.session["csrf"], version=__version__)

    @app.post("/api/me/share")
    @portal
    def me_share():
        from . import portal as portal_view, relays
        data = body()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            user = portal_user(db)
            if portal_view.busy(db, user["id"]):
                raise ValueError("上一个连接导出仍在进行中，请稍候")
            try:
                if set(data) == {"relay_id"}:
                    line = db.execute("SELECT * FROM relay_lines WHERE id=? AND user_id=? AND removing=0", (data["relay_id"], user["id"])).fetchone() \
                        if isinstance(data["relay_id"], str) else None
                    if not line:
                        raise LookupError("线路不存在")
                    reason = relays.blocked(db, line, {n["id"]: n for n in db.execute("SELECT * FROM nodes")})
                    if reason:
                        raise ValueError(reason + "，无法导出连接")
                    task_id = relays.share(db, line["id"], key_prefix="user-share:" + user["id"] + ":")
                else:
                    node_id, task = portal_view.share_link(db, user, data)
                    task_id = portal_view.queue(db, user["id"], node_id, task)
            except LookupError as error:
                return jsonify(error=str(error)), 404
            audit(db, "portal.share", None, user["name"] + " " + task_id)
        return jsonify(id=task_id), 201

    @app.get("/api/me/tasks/<task_id>")
    @portal
    def me_task(task_id):
        from . import portal as portal_view
        with store.connect() as db:
            row = portal_view.own_task(db, g.session["user_id"], task_id)
        if not row:
            return jsonify(error="导出记录不存在"), 404
        return jsonify(portal_view.task_view(row))

    @app.get("/api/me/tasks/<task_id>/qr")
    @portal
    def me_task_qr(task_id):
        from . import portal as portal_view
        with store.connect() as db:
            return qr_response(portal_view.own_task(db, g.session["user_id"], task_id))

    @app.post("/api/me/tg-code")
    @portal
    def me_tg_code():
        from .monitor import bot_info, new_code
        if body():
            raise ValueError("参数无效")
        if not bot_info(store)["enabled"]:
            raise ValueError("管理员尚未启用 Telegram 机器人")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            code, expires = new_code(db, g.session["user_id"])
            audit(db, "portal.bind_code", detail=g.session["user_id"])
        return jsonify(code=code, expires=expires)

    @app.post("/api/me/tg-unbind")
    @portal
    def me_tg_unbind():
        from .monitor import unbind
        if body():
            raise ValueError("参数无效")
        with store.connect() as db:
            unbind(db, g.session["user_id"])
            audit(db, "portal.unbind", detail=g.session["user_id"])
        return jsonify(ok=True)

    @app.post("/api/me/password")
    @portal
    def me_password():
        data = body()
        current, password = data.get("current_password", ""), data.get("new_password", "")
        if set(data) != {"current_password", "new_password", "confirm_password"} or not isinstance(current, str) or not current or len(current) > 1024:
            raise ValueError("请输入当前密码")
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise ValueError("新密码需为 8–128 位")
        if password != data["confirm_password"]:
            raise ValueError("两次输入的新密码不一致")
        now, key = time.time(), "user:" + g.session["user_id"]
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute("SELECT * FROM attempts WHERE ip=?", (key,)).fetchone()
            if attempt and attempt["until"] > now and attempt["count"] >= 8:
                return jsonify(error="尝试次数过多，请 15 分钟后重试"), 429
            user = portal_user(db)
            if not user or not user["password_hash"] or not check_password_hash(user["password_hash"], current):
                count = attempt["count"] + 1 if attempt and attempt["until"] > now else 1
                db.execute("INSERT OR REPLACE INTO attempts VALUES(?,?,?)", (key, count, now + 900))
                return jsonify(error="当前密码错误"), 400
            db.execute("UPDATE platform_users SET password_hash=? WHERE id=?",
                       (generate_password_hash(password, method="pbkdf2:sha256:600000"), user["id"]))
            db.execute("DELETE FROM user_sessions WHERE user_id=?", (user["id"],))
            db.execute("DELETE FROM attempts WHERE ip=?", (key,))
            audit(db, "portal.password", detail=user["name"])
        response = jsonify(ok=True)
        response.delete_cookie("vaio_session")
        return response

    def address_migration(db):
        key = "set-url:" + hashlib.sha256(app.config["PUBLIC_URL"].encode()).hexdigest()[:12] + ":%"
        nodes = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM nodes WHERE adopted=1 AND deleted IS NULL AND revoked=0")}
        latest = {}
        for row in db.execute("SELECT node_id, status, message FROM tasks WHERE request_key LIKE ? ORDER BY created", (key,)):
            latest[row["node_id"]] = (row["status"], row["message"])
        items = [{"node_id": i, "name": n, "status": latest.get(i, ("missing", ""))[0], "message": latest.get(i, ("", ""))[1]} for i, n in nodes.items()]
        return {"total": len(items), "done": sum(1 for i in items if i["status"] == "succeeded"), "nodes": items}

    @app.get("/api/panel-address")
    @admin
    def panel_address():
        status_file, request_file = data_dir / "address-status.json", data_dir / "address-request.json"
        try:
            status = json.loads(status_file.read_text())
        except (OSError, ValueError):
            status = None
        with store.connect() as db:
            migration = address_migration(db) if url.scheme == "https" else None
        return jsonify(url=app.config["PUBLIC_URL"], secure=url.scheme == "https", legacy_open=allow_http and url.scheme == "https",
                       helper=(units / "vaio-panel-address.path").exists() or app.config.get("ADDRESS_HELPER", False),
                       pending=request_file.exists(), status=status, migration=migration)

    def address_request(payload):
        request_file = data_dir / "address-request.json"
        if request_file.exists():
            raise ValueError("上一个地址操作仍在处理中，请稍候")
        staged = data_dir / ("address-request.%d.tmp" % os.getpid())
        staged.write_text(json.dumps(payload))
        os.replace(staged, request_file)

    @app.post("/api/panel-address")
    @admin
    def panel_address_set():
        data = body()
        domain, port = data.get("domain"), data.get("port", 443)
        if set(data) - {"domain", "port"} or not isinstance(domain, str) or not re.fullmatch(r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}", domain):
            raise ValueError("域名格式无效，请输入不带 https:// 和路径的域名")
        if type(port) is not int or not 1 <= port <= 65535 or port == 18080:
            raise ValueError("端口必须是 1–65535 的整数（18080 为后台端口）")
        address_request({"action": "set_domain", "domain": domain.lower(), "port": port})
        with store.connect() as db:
            audit(db, "panel.address_requested", None, domain.lower() + ":" + str(port))
        return jsonify(ok=True)

    @app.post("/api/panel-address/close-legacy")
    @admin
    def panel_address_close():
        if url.scheme != "https":
            raise ValueError("请先绑定域名并切换到 HTTPS")
        with store.connect() as db:
            migration = address_migration(db)
        waiting = [n["name"] for n in migration["nodes"] if n["status"] != "succeeded"]
        if waiting and body().get("force") is not True:
            return jsonify(error="以下节点尚未改用新地址：" + "、".join(waiting) + "；关闭后它们将无法连接，需在节点重新执行安装命令", waiting=waiting), 409
        address_request({"action": "close_legacy"})
        with store.connect() as db:
            audit(db, "panel.legacy_close_requested", None, "")
        return jsonify(ok=True)

    @app.post("/api/panel-address/retry")
    @admin
    def panel_address_retry():
        if url.scheme != "https":
            raise ValueError("请先绑定域名并切换到 HTTPS")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = queue_url_migration(db, app.config["PUBLIC_URL"], retry=True)
        return jsonify(queued=count)

    @app.get("/api/panel-update")
    @admin
    def panel_update():
        from . import updates
        result = updates.refresh(store, __version__, force=request.args.get("refresh") == "1")
        try:
            status = json.loads((data_dir / "panel-update-status.json").read_text())
        except (OSError, ValueError):
            status = None
        helper = (units / "vaio-panel-update.path").exists() or app.config.get("UPDATE_HELPER", False)
        installing = False
        if not helper and ((units / "vaio-panel-address.path").exists() or app.config.get("ADDRESS_HELPER", False)):
            # Upgraded by a 1.1.0 updater: ask the root address helper (already running the new code) to add the update units.
            installing = True
            if not (data_dir / "address-request.json").exists():
                address_request({"action": "install_update_helper"})
        return jsonify(**result, repository=updates.REPOSITORY, status=status, pending=(data_dir / "panel-update-request.json").exists(),
                       helper=helper, installing=installing)

    @app.post("/api/panel-update")
    @admin
    def panel_update_start():
        from . import updates
        data = body()
        result = updates.refresh(store, __version__)        # may reach GitHub: outside the transaction
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if set(data) != {"version"} or data["version"] != result["latest"] or not result["newer"]:
                raise ValueError("只能更新到检测到的最新版本，请刷新后重试")
            if db.execute("SELECT 1 FROM tasks WHERE status IN ('queued','running') LIMIT 1").fetchone():
                raise ValueError("有待执行或运行中的节点任务，请等待完成后再更新面板")
            request_file = data_dir / "panel-update-request.json"
            if request_file.exists():
                raise ValueError("面板更新已在进行中")
            staged = data_dir / ("panel-update-request.%d.tmp" % os.getpid())
            staged.write_text(json.dumps({"ref": data["version"]}))
            os.replace(staged, request_file)
            audit(db, "panel.update_requested", None, __version__ + " → " + data["version"])
        return jsonify(ok=True)

    @app.post("/api/nodes/upgrade-all")
    @admin
    def nodes_upgrade_all():
        """One-click upgrade for every node that can take it now; the rest are listed with the reason."""
        if body():
            raise ValueError("升级不接受参数")
        queued, skipped = [], []
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for node in db.execute("SELECT * FROM nodes WHERE deleted IS NULL AND revoked=0 ORDER BY created").fetchall():
                snapshot = json.loads(node["snapshot"])
                version = snapshot.get("agent_version")
                if not node["adopted"] or not version or version == __version__:
                    continue
                reason = ("节点离线" if not node["last_seen"] or time.time() - node["last_seen"] > 45 else
                          "节点正在维护" if node["maintenance"] else
                          "节点程序不支持一键升级，请先用命令升级一次" if snapshot.get("upgrade_version") != 1 else
                          "有未完成或待核对的任务" if db.execute("SELECT 1 FROM tasks WHERE node_id=? AND status IN ('queued','running','unknown')", (node["id"],)).fetchone()
                          else None)
                if reason:
                    skipped.append({"name": node["name"], "reason": reason})
                    continue
                task_id = str(uuid.uuid4())
                db.execute("INSERT INTO tasks(id,node_id,action,request,status,created,request_key) VALUES(?,?,?,?,?,?,?)",
                           (task_id, node["id"], "agent_upgrade", json.dumps(validate_upgrade_task({"action": "agent_upgrade", "params": {}})),
                            "queued", time.time(), "system:" + task_id))
                audit(db, "task.queued", node["id"], task_id + " agent_upgrade（一键更新全部节点）")
                queued.append(node["name"])
        return jsonify(queued=queued, skipped=skipped)

    @app.post("/api/nodes/<node_id>/upgrade")
    @admin
    def node_upgrade(node_id):
        if body():
            raise ValueError("升级不接受参数")
        def check(node, snapshot):
            if snapshot.get("upgrade_version") != 1:
                return "该节点程序不支持一键升级，请先用命令完成一次升级"
            if snapshot.get("agent_version") == __version__:
                return "节点程序已是面板版本"
        return node_task(node_id, "agent_upgrade", validate_upgrade_task({"action": "agent_upgrade", "params": {}}), check)

    @app.get("/api/audit")
    @admin
    def audit_log():
        with store.connect() as db:
            rows = db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200").fetchall()
        return jsonify(events=[dict(r) for r in rows])

    app.wsgi_app = LoopbackProxyFix(app.wsgi_app)
    return app
