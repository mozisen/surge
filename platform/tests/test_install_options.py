import tempfile
import base64
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent.runtime import Runtime, UPSTREAM_SHA
from agent.inventory import sanitize_snapshot
from vaio.common import validate_task


class InstallationOptionsTest(unittest.TestCase):
    def test_reality_private_derivation_and_validation(self):
        private = base64.urlsafe_b64encode(bytes.fromhex(
            "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")).decode().rstrip("=")
        public = base64.urlsafe_b64encode(bytes.fromhex(
            "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a")).decode().rstrip("=")
        validate_task(self.request("vless", sni="example.com", private_key=private, short_id="AABB"))
        for fields in ({"short_id": "abc"}, {"short_id": "zz"}, {"private_key": "invalid"},
                       {"short_id": 12}, {"private_key": ";" * 43}):
            with self.assertRaises(ValueError):
                validate_task(self.request("vless", sni="example.com", **fields))
        with self.assertRaises(ValueError):
            validate_task(self.request("anytls", sni="example.com", private_key=private))
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(Path(tmp)/"cfg", Path(tmp)/"state")
            raw_public = bytes.fromhex("302a300506032b656e032100") + base64.urlsafe_b64decode(public + "=")
            with patch("agent.runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0, raw_public, b"")) as run:
                self.assertEqual(runtime.supplied_keys(private), (private, public))
                self.assertNotIn(private, str(run.call_args.args))
                self.assertEqual(run.call_args.kwargs["input"][-32:], base64.urlsafe_b64decode(private + "="))
            with patch("agent.runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 1, b"", b"failure")):
                with self.assertRaises(ValueError):
                    runtime.supplied_keys(private)
        self.assertEqual(sanitize_snapshot({"install_options_version": 2})["install_options_version"], 2)
        self.assertEqual(sanitize_snapshot({"install_options_version": True})["install_options_version"], 0)

    def test_reality_private_derivation_live_openssl(self):
        algorithms = subprocess.run(["openssl", "list", "-public-key-algorithms"], capture_output=True, text=True)
        if algorithms.returncode or "X25519" not in algorithms.stdout:
            self.skipTest("本机 OpenSSL 不支持 X25519，真实推导需在支持它的节点验证")
        with tempfile.TemporaryDirectory() as tmp:
            private = base64.urlsafe_b64encode(bytes.fromhex(
                "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a")).decode().rstrip("=")
            public = Runtime(Path(tmp)/"cfg", Path(tmp)/"state").supplied_keys(private)[1]
            self.assertEqual(base64.urlsafe_b64decode(public+"=").hex(),
                             "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a")

    def request(self, proto="anytls", **params):
        return dict(action="install", protocol=proto,
                    core="xray" if proto.startswith("snell") or proto == "vless" else "singbox",
                    port=24443, revision="0"*64, params=params)

    def test_cross_protocol_and_injection_rejected(self):
        bad = [
            self.request("snell", sni="example.com"),
            self.request("anytls", sni="example.com", mode="unshaped"),
            self.request("snell-v6", dns="1.1.1.1\npsk=bad"),
            self.request("snell-v6", tfo="false"),
            self.request("vless", sni="example.com", credential="not-a-uuid"),
            self.request(sni="example.com", certificate_mode="acme"),
            self.request(sni="example.com", certificate_mode="acme", acme_email="a@b.com;cmd"),
            self.request(sni="example.com", certificate_mode="existing", panel_key="/etc/shadow"),
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_task(value)

    def test_supported_options(self):
        validate_task(self.request("snell-v6", name="alice", dns="1.1.1.1,2001:4860:4860::8888",
                                  mode="unshaped", dns_ip_preference="prefer-ipv4", tfo=False))
        validate_task(self.request(sni="node.example.com", certificate_mode="acme", acme_email="admin@example.com"))
        validate_task(self.request("vless", sni="example.com", credential=str(uuid.uuid4())))
        self.assertEqual(sanitize_snapshot({"install_options_version": 1})["install_options_version"], 1)
        self.assertEqual(sanitize_snapshot({})["install_options_version"], 0)

    def test_bootstrap_preserves_existing_script_and_conflicts(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = Runtime(base/"cfg", base/"state")
            runtime.ensure_main_script(base/"bin")
            script = base/"bin/vless-server.sh"
            self.assertEqual(hashlib.sha256(script.read_bytes()).hexdigest(), UPSTREAM_SHA)
            self.assertEqual(script.stat().st_mode & 0o777, 0o755)
            self.assertEqual((base/"bin/vless").resolve(), script.resolve())
            self.assertEqual((base/"cfg/role").read_text(), "server\n")
            script.write_text("existing user version")
            runtime.ensure_main_script(base/"bin")
            self.assertEqual(script.read_text(), "existing user version")
            (base/"bin/vless").unlink()
            (base/"bin/vless").write_text("unrelated")
            with self.assertRaisesRegex(ValueError, "占用"):
                runtime.ensure_main_script(base/"bin")
            self.assertEqual((base/"bin/vless").read_text(), "unrelated")

    def test_bootstrap_rejects_bad_vendor_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = Runtime(base/"cfg", base/"state")
            with patch("agent.runtime.UPSTREAM_SHA", "bad"), self.assertRaises(RuntimeError):
                runtime.ensure_main_script(base/"bin")
            self.assertFalse((base/"bin").exists())

    def test_certificate_workflows(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            runtime = Runtime(base/"cfg", base/"state")
            calls = []
            def command(args, **kwargs):
                calls.append(args)
                for flag in ("-keyout", "-out", "--key-file", "--fullchain-file"):
                    if flag in args:
                        Path(args[args.index(flag)+1]).write_text("test only")
                return "PUBLIC" if kwargs.get("capture") else ""
            runtime.command = command
            runtime.upstream = lambda op: calls.append([op])
            row = dict(instance_id=str(uuid.uuid4()), sni="node.example.com", certificate_mode="self")
            runtime.certificate(row)
            self.assertTrue(any("subjectAltName=DNS:node.example.com" in args for args in calls))
            row = dict(instance_id=str(uuid.uuid4()), sni="node.example.com", certificate_mode="acme",
                       certificate_core="singbox", acme_email="admin@example.com")
            with patch("agent.bridge.Bridge.check_port"):
                runtime.certificate(row)
            hook = Path(row["panel_cert"]).parent / "reload.sh"
            self.assertIn("grep -Fq", hook.read_text())
            self.assertIn("try-restart vless-singbox", hook.read_text())
            self.assertEqual(hook.read_text().count("if grep -Fq"), 2)
            self.assertTrue(any("--install-cert" in args and "--reloadcmd" in args for args in calls))

    def test_acme_busy_port_has_no_install_or_service_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(Path(tmp)/"cfg", Path(tmp)/"state")
            with patch("agent.bridge.Bridge.check_port", side_effect=ValueError("busy")), patch.object(runtime, "upstream") as install:
                with self.assertRaisesRegex(ValueError, "busy"):
                    runtime.certificate(dict(instance_id=str(uuid.uuid4()), certificate_mode="acme", sni="example.com"))
                install.assert_not_called()

    def test_snell_options_reach_runtime_and_surge(self):
        from agent.bridge import Bridge
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(Path(tmp)/"cfg", Path(tmp)/"state")
            row = dict(port=24443, psk="test-password", version="6", snell_id="a"*24,
                       mode="unshaped", dns="1.1.1.1", dns_ip_preference="ipv4-only", tfo=False,
                       users=[dict(name="alice", uuid="test-password", enabled=True)])
            with patch.object(runtime, "ensure_unit"), patch.object(runtime, "service"), patch.object(runtime, "upstream"), patch.object(runtime, "is_running", return_value=True), patch("agent.runtime.time.sleep"):
                runtime.apply("xray", "snell-v6", None, row, {})
            text = runtime.config_path("xray", "snell-v6", row).read_text()
            self.assertIn("mode = unshaped", text)
            self.assertIn("dns-ip-preference = ipv4-only", text)
            self.assertIn("dns = 1.1.1.1", text)
            link = Bridge.share("snell-v6", row, dict(name="alice", host="example.com"))
            self.assertIn("mode=unshaped", link)
            self.assertIn("tfo=false", link)

    def test_tls_links_only_skip_self_signed(self):
        from agent.bridge import Bridge
        row = dict(port=24443, sni="example.com", panel_cert="/cert", certificate_mode="acme",
                   users=[dict(name="alice", uuid="test-password")])
        self.assertIn("insecure=0", Bridge.share("hy2", row, dict(name="alice", host="example.com")))
        self.assertNotIn("allowInsecure", Bridge.share("anytls", row, dict(name="alice", host="example.com")))
