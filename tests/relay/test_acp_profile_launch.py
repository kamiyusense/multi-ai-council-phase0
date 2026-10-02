import sys
import tempfile
import unittest

from providers.antigravity_acp import build_antigravity_profile
from providers.claude_acp import build_claude_profile
from providers.codex_acp import build_codex_profile
from providers.factory import create_core_adapter
from relay.acp_profile_launch import ACPProfileBridge, resolve_acp_launch
from src.relay.dispatcher import DuplicateConflictGuard, RelayDispatcher

# Local fake ACP agent: echoes provider name and whether _meta reached session/new.
FAKE = (
    "import sys,json\n"
    "name=sys.argv[1]; mode=sys.argv[2] if len(sys.argv)>2 else 'ok'\n"
    "def rd(): return json.loads(sys.stdin.readline())\n"
    "def wr(o): sys.stdout.write(json.dumps(o)+'\\n'); sys.stdout.flush()\n"
    "r=rd(); wr({'jsonrpc':'2.0','id':r['id'],'result':{'protocolVersion':1}})\n"
    "r=rd(); meta=json.dumps(r['params'].get('_meta'),sort_keys=True)\n"
    "wr({'jsonrpc':'2.0','id':r['id'],'result':{'sessionId':'s1'}})\n"
    "r=rd()\n"
    "if mode=='hang': import time; time.sleep(30)\n"
    "if mode=='garbage': sys.stdout.write('nope\\n'); sys.stdout.flush(); sys.exit(0)\n"
    "wr({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':'s1','update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':name+':'+meta}}}})\n"
    "wr({'jsonrpc':'2.0','id':r['id'],'result':{'stopReason':'end_turn'}})\n"
)
_BASE = {"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False}
ROUTES = {
    "openai": {**_BASE, "custom_model_provider_configured": False, "arbitrary_codex_config_present": False},
    "anthropic": {**_BASE, "dangerous_permission_bypass": False, "hide_claude_auth": False},
    "google": {**_BASE, "cloud_billing_selected": False, "overages_enabled": False,
               "adc_present": False, "vertex_selected": False},
}


def profiles():
    return {
        "openai": build_codex_profile("account", ROUTES["openai"]),
        "anthropic": build_claude_profile("account", ROUTES["anthropic"]),
        "google": build_antigravity_profile("account", ROUTES["google"], "linux", "x86_64"),
    }


def bridge_for(pid, profile, mode="ok", timeout=2.0):
    return ACPProfileBridge(
        profile, (sys.executable, "-c", FAKE, pid, mode),
        cwd=tempfile.gettempdir(), acp_timeout=timeout,
    )


def run(pid, profile, mode="ok", timeout=2.0, guard=None):
    bridge = bridge_for(pid, profile, mode, timeout)
    adapter = create_core_adapter(profile, bridge)
    result = RelayDispatcher(adapter, guard or DuplicateConflictGuard()).dispatch(
        pid, {"provider_id": pid, "payload": {"q": "x"}, "timeout_seconds": 5}
    )
    return bridge, result


class ACPProfileLaunchTests(unittest.TestCase):
    def test_resolve_official_executables(self):
        p = profiles()
        self.assertEqual(resolve_acp_launch(p["openai"]).executable, "codex-acp")
        self.assertEqual(resolve_acp_launch(p["anthropic"]).executable, "claude-agent-acp")
        self.assertEqual(resolve_acp_launch(p["google"]).executable, "agy_acp_server.par")
        self.assertIsNone(resolve_acp_launch(p["openai"]).session_meta)

    def test_resolve_rejects_foreign_binary(self):
        class Fake:
            provider_id = "openai"
            binary_name = "../gemini"
            retry_count = 0
            fallback_state = "disabled"
            live_ready = False
            session_meta = None
        with self.assertRaises(ValueError):
            resolve_acp_launch(Fake())
        Fake.binary_name = "gemini"
        with self.assertRaises(ValueError):
            resolve_acp_launch(Fake())
        Fake.binary_name = "claude-agent-acp"  # wrong provider's binary
        with self.assertRaises(ValueError):
            resolve_acp_launch(Fake())

    def test_bridge_refuses_official_adapter_launch(self):
        p = profiles()["openai"]
        with self.assertRaises(ValueError):
            ACPProfileBridge(p, ("codex-acp",), cwd=".")
        with self.assertRaises(ValueError):
            ACPProfileBridge(p, (), cwd=".")

    def test_three_provider_static_e2e(self):
        for pid, profile in profiles().items():
            with self.subTest(pid=pid):
                bridge, r = run(pid, profile)
                self.assertEqual(r["state"], "SIMULATED")
                self.assertEqual(bridge.launch_count, 1)
                self.assertEqual(r["retry_count"], 0)
                self.assertEqual(r["fallback_state"], "disabled")
                self.assertFalse(r["live_turn_executed"])
                self.assertIn(pid.encode(), r["raw_evidence"])

    def test_claude_meta_forwarded_others_not(self):
        p = profiles()
        _, claude = run("anthropic", p["anthropic"])
        self.assertIn("allowDangerouslySkipPermissions", claude["raw_evidence"].decode())
        self.assertIn("false", claude["raw_evidence"].decode())
        _, codex = run("openai", p["openai"])
        self.assertIn("null", codex["raw_evidence"].decode())

    def test_duplicate_is_noop(self):
        p = profiles()["openai"]
        guard = DuplicateConflictGuard()
        bridge = bridge_for("openai", p)
        d = RelayDispatcher(create_core_adapter(p, bridge), guard)
        ctx = {"provider_id": "openai", "payload": {"q": "x"}, "timeout_seconds": 5}
        self.assertEqual(d.dispatch("slot", ctx)["state"], "SIMULATED")
        again = d.dispatch("slot", ctx)
        self.assertEqual(again["state"], "BLOCKED")
        self.assertEqual(bridge.launch_count, 1)

    def test_malformed_and_timeout_fail_closed(self):
        p = profiles()["google"]
        _, bad = run("google", p, mode="garbage")
        self.assertEqual(bad["state"], "UNKNOWN")
        self.assertEqual(bad["retry_count"], 0)
        bridge, slow = run("google", p, mode="hang", timeout=0.3)
        self.assertEqual(slow["state"], "TIMEOUT")
        self.assertEqual(bridge.launch_count, 1)

    def test_one_provider_failure_keeps_peer_evidence(self):
        p = profiles()
        _, ok = run("openai", p["openai"])
        _, bad = run("anthropic", p["anthropic"], mode="garbage")
        self.assertEqual(ok["state"], "SIMULATED")
        self.assertEqual(bad["state"], "UNKNOWN")
        self.assertIn(b"openai", ok["raw_evidence"])


if __name__ == "__main__":
    unittest.main()
