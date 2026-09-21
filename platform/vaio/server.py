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
from werkzeug.security import check_password_hash, generate_password_hash

from . import __version__
from .common import MUTATIONS, LEGACY_COMBINATIONS, digest, require_text, validate_task
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
    if url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("公网面板必须设置 HTTPS 地址")
    store = Store(app.config["DATABASE"])
    app.extensions["store"] = store
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
            if not password_ok or username != expected_username:
                count = attempt["count"] + 1 if attempt and attempt["until"] > now else 1
                db.execute("INSERT OR REPLACE INTO attempts VALUES(?,?,?)", (ip, count, now + 900))
                return jsonify(error="账号或密码错误"), 401
            db.execute("DELETE FROM attempts WHERE ip=?", (ip,))
            db.execute("DELETE FROM sessions WHERE expires<?", (now,))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(token), csrf, now + 43200))
            audit(db, "login")
        response = jsonify(csrf=csrf, version=__version__)
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
        if not isinstance(password, str) or (password and not 12 <= len(password) <= 128):
            raise ValueError("新密码需为 12–128 位")
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
    @admin
    def logout():
        with store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (g.session["token"],))
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
        payload = json.dumps({"url": app.config["PUBLIC_URL"], "node_id": node_id, "enroll_token": token})
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
        revision = body().get("revision")
        with store.connect() as db:
            row = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
            if not row or row["revoked"] or not row["last_seen"] or time.time() - row["last_seen"] > 45:
                return jsonify(error="请等待节点上线"), 409
            snap = json.loads(row["snapshot"])
            if not revision or revision != snap.get("revision") or snap.get("error"):
                return jsonify(error="配置状态已变化，请刷新后重试"), 409
            db.execute("UPDATE nodes SET adopted=1 WHERE id=?", (node_id,))
            audit(db, "node.adopt", node_id)
        return jsonify(ok=True)

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
            # Ambiguous tasks are never automatically replayed.
            db.execute("UPDATE tasks SET status='unknown',message='执行结果未确认；请核对节点后重新操作',finished=? WHERE node_id=? AND status='running' AND started<?",
                       (time.time(), node_id, time.time() - 2100))
            db.execute("UPDATE tasks SET result=NULL WHERE action='share' AND finished<?", (time.time() - 600,))
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
            detail = {k: v for k, v in detail.items() if k in ("connection", "backup", "steps", "affected")}
            if task["action"] != "share":
                detail.pop("connection", None)
            db.execute("UPDATE tasks SET status=?,finished=?,message=?,result=? WHERE id=?",
                       (data["status"], time.time(), message, json.dumps(detail), task_id))
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
            if node["maintenance"]:
                return jsonify(error="节点正在维护，请稍后再试"), 409
            capabilities = json.loads(node["snapshot"]).get("write_capabilities", [])
            if "reset_credentials" in task["params"] and json.loads(node["snapshot"]).get("task_api_version", 1) < 2:
                return jsonify(error="节点不支持凭据重置，请先升级 Agent"), 409
            if (task["core"], task["protocol"]) not in LEGACY_COMBINATIONS and {"core": task["core"], "protocol": task["protocol"]} not in capabilities:
                return jsonify(error="节点尚未声明此协议写入能力，请先升级 Agent"), 409
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
            item["result"] = json.loads(item["result"] or "{}")
            if item["action"] == "share" and item["finished"] and item["finished"] < time.time() - 600:
                item["result"] = {}
            output.append(item)
        return jsonify(tasks=output)

    @app.post("/api/tasks/<task_id>/resolve")
    @admin
    def resolve_task(task_id):
        note = require_text(body().get("note"), "核对说明", 500)
        with store.connect() as db:
            if not db.execute("UPDATE tasks SET status='resolved',message=? WHERE id=? AND status='unknown'", ("人工核对：" + note, task_id)).rowcount:
                return jsonify(error="仅待核对任务可以标记已核对"), 409
            audit(db, "task.resolved", detail=task_id)
        return jsonify(ok=True)

    @app.post("/api/tasks/<task_id>/cancel")
    @admin
    def cancel(task_id):
        with store.connect() as db:
            if not db.execute("UPDATE tasks SET status='cancelled',finished=? WHERE id=? AND status='queued'", (time.time(), task_id)).rowcount:
                return jsonify(error="仅等待中的任务可以取消"), 409
            audit(db, "task.cancelled", detail=task_id)
        return jsonify(ok=True)

    @app.get("/api/audit")
    @admin
    def audit_log():
        with store.connect() as db:
            rows = db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200").fetchall()
        return jsonify(events=[dict(r) for r in rows])

    return app
