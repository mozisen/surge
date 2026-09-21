import argparse
import getpass
import os
import re
from pathlib import Path
from werkzeug.security import generate_password_hash
from .store import Store


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Vaio Panel 管理工具")
    parser.add_argument("command", choices=["init", "serve"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if args.command == "init":
        username = input("管理员账号 [admin]: ").strip() or "admin"
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            raise SystemExit("账号需为 3–32 位字母、数字、点、下划线或短横线")
        password = getpass.getpass("管理员密码（至少 12 位）: ")
        if not 12 <= len(password) <= 128 or password != getpass.getpass("再次输入: "):
            raise SystemExit("密码需为 12–128 位，且两次输入一致")
        path = os.environ.get("VAIO_DATABASE", str(Path(__file__).resolve().parent.parent / "data/panel.sqlite"))
        store = Store(path)
        with store.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('password',?)", (generate_password_hash(password, method="pbkdf2:sha256:600000"),))
            db.execute("INSERT OR REPLACE INTO settings VALUES('username',?)", (username,))
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM attempts")
        print("管理员账号和密码已设置，所有旧登录会话已失效。")
    else:
        from .server import create_app
        create_app().run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
