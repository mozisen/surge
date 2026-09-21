import argparse
import concurrent.futures
import fcntl
import json
import logging
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from vaio import __version__
from .bridge import Bridge, TransactionUnknown
from .inventory import inventory, read_db, rows
from .runtime import Runtime, active_users, atomic_write
from .script_api import ScriptAPI


def valid_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
        raise ValueError("面板地址格式无效")
    if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("节点只接受 HTTPS 面板，开发环境可使用本机回环地址")
    return url.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("面板不应重定向 Agent 请求")


def post(url, payload, token=None):
    headers = {"Content-Type": "application/json", "User-Agent": "Vaio-Agent/" + __version__}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
        return json.loads(response.read(1024 * 1024))


class Agent:
    def __init__(self, config, state, cfg="/etc/vless-reality", bridge=None):
        self.config = config
        self.url = valid_url(config["url"])
        self.state = Path(state)
        self.state.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.cfg = cfg
        self.script_api = ScriptAPI() if str(cfg) == "/etc/vless-reality" else None
        self.bridge = bridge or Bridge(cfg, state)
        self.journal_path = self.state / "journal.json"
        self.journal = json.loads(self.journal_path.read_text()) if self.journal_path.exists() else {}
        for item in self.journal.values():
            if item["status"] == "running":
                item.update(status="unknown", message="Agent 在执行时重启；为避免重复操作，未自动重试", result={})
        self.save()

    def save(self):
        atomic_write(self.journal_path, json.dumps(self.journal))

    def api(self, suffix, payload):
        return post(self.url + "/api/agent/" + self.config["node_id"] + suffix, payload, self.config["token"])

    def run_task(self, task):
        try:
            result = self.bridge.execute(task)
            return dict(status="succeeded", message="操作完成", result=result)
        except TransactionUnknown as error:
            return dict(status="unknown", message=str(error), result={})
        except (ValueError, RuntimeError) as error:
            return dict(status="failed", message=str(error), result={})
        except Exception:
            logging.exception("任务执行出现异常，请在本机排查")
            return dict(status="failed", message="节点内部异常，请检查 Agent 日志与配置备份", result={})

    def cycle(self, executor, future):
        if future and future.done():
            running_id = next((k for k, v in self.journal.items() if v["status"] == "running"), None)
            if running_id:
                self.journal[running_id] = {**future.result(), "sent": False, "at": time.time()}
                self.save()
            future = None
        for task_id, item in self.journal.items():
            if item["status"] != "running" and not item.get("sent"):
                self.api("/tasks/" + task_id + "/result", {k: item[k] for k in ("status", "message", "result")})
                item["sent"] = True
                # Credentials need not remain on disk after acknowledged delivery.
                item["result"].pop("connection", None)
                self.save()
        try:
            snapshot = inventory(self.cfg)
        except Exception:
            snapshot = {"error": "读取节点状态失败，请检查 db.json 和 Agent 日志", "instances": []}
        if self.script_api:
            snapshot["script_api"] = self.script_api.status()
        task = self.api("/poll", {"snapshot": snapshot, "ready": future is None}).get("task")
        if task and future is None:
            task_id = task["id"]
            if task_id in self.journal:
                self.journal[task_id]["sent"] = False
                self.save()
            else:
                self.journal[task_id] = {"status": "running", "sent": False, "at": time.time()}
                self.save()  # Durable intent before any side effect.
                future = executor.submit(self.run_task, task)
        return future

    def run(self):
        # Prevent two processes from consuming the same identity / journal.
        with open(self.state / ".agent.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future, maintenance, delay, last_maintenance = None, None, 10, 0
                while True:
                    try:
                        # Maintenance is serialized with user tasks by the bridge database lock.
                        if future is None and time.time() - last_maintenance > 60:
                            if maintenance is None or maintenance.done():
                                if maintenance and maintenance.exception():
                                    logging.error("本地到期检查失败，请查看 runtime.log")
                                maintenance = executor.submit(self.bridge.reconcile)
                                last_maintenance = time.time()
                        future = self.cycle(executor, future)
                        delay = 10
                    except Exception as error:
                        # Never log request payloads, tokens, or response credentials.
                        if isinstance(error, urllib.error.HTTPError):
                            reason = {401: "节点身份已失效，请在面板重新注册", 403: "请求被拒绝，请检查反向代理访问限制",
                                      404: "面板地址或接口版本不匹配"}.get(error.code, "面板返回 HTTP " + str(error.code))
                        elif isinstance(error, urllib.error.URLError):
                            reason = "无法建立连接，请检查 DNS、TLS 证书和网络"
                        else:
                            reason = type(error).__name__
                        logging.warning("面板连接失败：%s；将在 %s 秒后重试", reason, min(delay * 2, 60))
                        delay = min(delay * 2, 60)
                    time.sleep(delay + random.random())


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Vaio 节点 Agent")
    parser.add_argument("command", choices=["enroll", "run", "prepare"])
    parser.add_argument("--config", default="/etc/vaio-agent/config.json")
    parser.add_argument("--state", default="/var/lib/vaio-agent")
    parser.add_argument("--cfg", default="/etc/vless-reality")
    parser.add_argument("--instance")
    args = parser.parse_args()
    if args.command == "enroll":
        data = json.load(sys.stdin)
        url = valid_url(data["url"])
        result = post(url + "/api/enroll", {"node_id": data["node_id"], "enroll_token": data["enroll_token"]})
        atomic_write(args.config, json.dumps({"url": url, "node_id": result["node_id"], "token": result["token"]}))
        print("节点注册完成")
    elif args.command == "prepare":
        import re
        if not re.fullmatch(r"[0-9a-f]{24}", args.instance or ""):
            raise SystemExit("实例 ID 无效")
        found = [r for _, p, r in rows(read_db(args.cfg)) if p.startswith("snell") and r.get("snell_id") == args.instance]
        if len(found) != 1 or not active_users(found[0]):
            raise SystemExit("实例不存在、已禁用或已到期")
        Runtime(args.cfg, args.state).upstream("_snell_update_counter_port", args.instance, str(found[0]["port"]))
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        Agent(json.loads(Path(args.config).read_text()), args.state, args.cfg).run()


if __name__ == "__main__":
    main()
