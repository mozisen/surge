#!/usr/bin/env python3
"""Optional local ICMP helper for Po0fw.js (Surge scripts cannot send ICMP).

Bind to loopback by default. For LAN use, require --key and firewall/TLS protection.
The helper pings only the configured --target to prevent arbitrary host scanning.
"""

import argparse
import ipaddress
import json
import platform
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


def ping_once(address: str) -> bool:
    osname = platform.system()
    if osname == "Windows":
        cmd = ["ping", "-n", "1", "-w", "1000", address]
    elif osname == "Darwin":
        cmd = ["ping", "-n", "-c", "1", "-W", "1000", address]
    else:
        cmd = ["ping", "-n", "-c", "1", "-W", "1", address]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=3, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Local ICMP Ping probe for po0fw")
    parser.add_argument("--target", required=True, help="Only IP address accepted by /ping")
    parser.add_argument("--host", default="127.0.0.1", help="Listener (loopback by default)")
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--key", default="", help="Required X-Ping-Key for LAN listeners")
    args = parser.parse_args()

    target = str(ipaddress.IPv4Address(args.target))
    if args.host not in ("127.0.0.1", "::1", "localhost") and not args.key:
        parser.error("Non-loopback listener requires --key and firewall protection")

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, data: dict) -> None:
            encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path != "/ping":
                self.reply(404, {"error": "not found"})
                return
            if args.key and self.headers.get("X-Ping-Key") != args.key:
                self.reply(403, {"error": "unauthorized"})
                return
            requested = parse_qs(parsed.query).get("ip", [""])[0]
            if requested != target:
                self.reply(400, {"error": "ip does not match configured target"})
                return
            self.reply(200, {"ip": target, "ok": ping_once(target)})

        def log_message(self, format: str, *arguments: object) -> None:
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ICMP helper listening on {args.host}:{args.port} for {target}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
