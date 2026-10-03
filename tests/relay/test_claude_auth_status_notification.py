"""M6/M7: official ``_auth/status_update`` (claude-agent-acp) is consumed as sanitized classification only.

All identities below are SYNTHETIC (``*.invalid``); no real Claude CLI, account or model is involved.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from providers.claude_acp import build_claude_profile
from providers.codex_acp import build_codex_profile
from relay.acp_client import _acp_initialize
from relay.acp_stdio_relay_transport import AcpStdioStaticTransport
from relay.acp_stdio_transport import spawn_stdio_transport
from relay.claude_auth_readonly import AUTH_STATUS_UPDATE_METHOD, summarize_claude_auth_status_update as summarize
from relay.duplicate_guard import DuplicateGuard
from relay.envelope import DispatchEnvelope, DispatchSlot
from relay.lifecycle import RelayLifecycle
from relay.result import RelayState

REPO = Path(__file__).resolve().parents[2]
TRIPWIRE = REPO / "fixtures" / "relay" / "claude_cli_tripwire.py"
EMAIL, ORG = "synthetic.person@example.invalid", "SyntheticOrg-Inc"
_FALSE = {"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False}

# What the official adapter pushes (shapes observed from claude-agent-acp 0.84.0 / 0.85.1 with a synthetic CLI answer).
SUBSCRIPTION = {"kind": "account", "label": "Claude Pro", "account": {"plan": "pro", "email": EMAIL, "organization": ORG}}
API_KEY = {"kind": "api_key", "label": "Anthropic API key", "detail": "apiKeyHelper"}
GATEWAY = {"kind": "gateway", "label": "Custom model gateway", "detail": "gw.example.invalid"}
EXTERNAL = {"kind": "external", "label": "AWS Bedrock"}
NONE = {"kind": "none", "label": "Not logged in"}
CASES = (
    (SUBSCRIPTION, "CLAUDE_SUBSCRIPTION_ACCOUNT"), (API_KEY, "API_KEY_ROUTE_VIOLATION"),
    (GATEWAY, "EXTERNAL_ROUTE_VIOLATION"), (EXTERNAL, "EXTERNAL_ROUTE_VIOLATION"), (NONE, "NOT_AUTHENTICATED"),
)


def notification(auth_status, method=AUTH_STATUS_UPDATE_METHOD):
    return {"jsonrpc": "2.0", "method": method, "params": {"authStatus": auth_status}}


def profile():
    return build_claude_profile("account", {**_FALSE, "dangerous_permission_bypass": False, "hide_claude_auth": False})


def fake_agent(frames_after_init=(), frames_in_prompt=(), prompt_text="synthetic reply"):
    """Fake ACP agent (NOT the official adapter) pushing the given frames at the given points."""
    code = (
        "import sys, json\n"
        "def send(o):\n"
        "    sys.stdout.write(json.dumps(o) + '\\n'); sys.stdout.flush()\n"
        "r = json.loads(sys.stdin.readline())\n"
        "send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'protocolVersion': 1}})\n"
        f"for f in {list(frames_after_init)!r}: send(f)\n"
        "r = json.loads(sys.stdin.readline())\n"
        "send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'sessionId': 's1'}})\n"
        "r = json.loads(sys.stdin.readline())\n"
        f"for f in {list(frames_in_prompt)!r}: send(f)\n"
        "send({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 's1', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': " + repr(prompt_text) + "}}}})\n"
        "send({'jsonrpc': '2.0', 'id': r['id'], 'result': {'stopReason': 'end_turn'}})\n"
    )
    return (sys.executable, "-c", code)


def dispatch(command, provider_profile=None):
    provider_profile = provider_profile or profile()
    t = AcpStdioStaticTransport(provider_profile, command)
    env = DispatchEnvelope.build(
        slot=DispatchSlot("case", provider_profile.provider_id, 0),
        correlation_id="corr-auth",
        payload={"prompt": "hi"},
        timeout_seconds=10,
    )
    res = RelayLifecycle(transport=t, duplicate_guard=DuplicateGuard()).dispatch_mock(env, cwd=tempfile.gettempdir())
    return t, res


class TestSummarizer(unittest.TestCase):
    def test_kind_mapping(self):
        for status, state in CASES:
            with self.subTest(kind=status["kind"]):
                r = summarize(status)
                self.assertEqual((r["auth_state"], r["plan_type"], r["quota"], r["side_effects"]), (state, "UNKNOWN", "UNKNOWN", 0))

    def test_malformed_or_unknown_kind_is_unknown(self):
        for bad in (None, [], "account", {}, {"kind": 1}, {"kind": "Account"}, {"kind": "new_kind"}, {"label": "Claude Pro"}):
            with self.subTest(bad=bad):
                self.assertEqual(summarize(bad)["auth_state"], "UNKNOWN")

    def test_nothing_private_is_copied(self):
        blob = json.dumps(summarize(SUBSCRIPTION))
        for secret in (EMAIL, ORG, "Claude Pro", "pro", "apiKeyHelper"):
            self.assertNotIn(secret, blob)


class TestRelayConsumesTheNotification(unittest.TestCase):
    def test_every_kind_is_classified_after_initialize_and_mid_prompt(self):
        for status, state in CASES:
            for where in ("after_init", "in_prompt"):
                with self.subTest(kind=status["kind"], where=where):
                    kwargs = {"frames_after_init": [notification(status)]} if where == "after_init" else {"frames_in_prompt": [notification(status)]}
                    t, res = dispatch(fake_agent(**kwargs))
                    self.assertEqual(res.state, RelayState.SIMULATED, res.error)
                    self.assertEqual([e["auth_state"] for e in t.auth_status_evidence], [state])

    def test_notification_is_not_text_nor_execution_nor_retry(self):
        t, res = dispatch(fake_agent(frames_in_prompt=[notification(SUBSCRIPTION), notification(API_KEY)]))
        self.assertEqual(res.state, RelayState.SIMULATED)
        self.assertIn(b"synthetic reply", res.raw)
        self.assertNotIn(b"Claude Pro", res.raw)
        self.assertEqual((t.spawn_count, t.prompt_count, res.prompt_attempts, res.simulated), (1, 1, 1, True))
        self.assertEqual([e["auth_state"] for e in t.auth_status_evidence], ["CLAUDE_SUBSCRIPTION_ACCOUNT", "API_KEY_ROUTE_VIOLATION"])

    def test_raw_account_data_never_reaches_evidence_or_result(self):
        t, res = dispatch(fake_agent(frames_after_init=[notification(SUBSCRIPTION)], frames_in_prompt=[notification(SUBSCRIPTION)]))
        blob = json.dumps(t.auth_status_evidence) + res.raw.decode("utf-8") + repr(res)
        for secret in (EMAIL, ORG, "Claude Pro", "gw.example.invalid"):
            self.assertNotIn(secret, blob)

    def test_malformed_notifications_are_unknown_and_do_not_break_the_turn(self):
        frames = [{"jsonrpc": "2.0", "method": AUTH_STATUS_UPDATE_METHOD},
                  {"jsonrpc": "2.0", "method": AUTH_STATUS_UPDATE_METHOD, "params": {"authStatus": "none"}},
                  notification({"kind": "something_new"})]
        t, res = dispatch(fake_agent(frames_in_prompt=frames))
        self.assertEqual(res.state, RelayState.SIMULATED)
        self.assertEqual([e["auth_state"] for e in t.auth_status_evidence], ["UNKNOWN"] * 3)

    def test_other_unknown_notification_methods_still_fail_closed_in_prompt(self):
        t, res = dispatch(fake_agent(frames_in_prompt=[notification(NONE, method="_other/notice")]))
        self.assertEqual(res.state, RelayState.UNKNOWN)
        self.assertEqual(t.auth_status_evidence, [])

    def test_claude_auth_extension_is_not_accepted_for_codex(self):
        codex = build_codex_profile("account", dict(_FALSE))
        t, res = dispatch(fake_agent(frames_in_prompt=[notification(SUBSCRIPTION)]), provider_profile=codex)
        self.assertEqual(res.state, RelayState.UNKNOWN)
        self.assertEqual(t.auth_status_evidence, [])

    def test_flood_of_auth_notifications_is_bounded(self):
        t, res = dispatch(fake_agent(frames_in_prompt=[notification(NONE)] * 40))
        self.assertEqual(res.state, RelayState.UNKNOWN)
        self.assertLessEqual(len(t.auth_status_evidence), 17)


@unittest.skipUnless(os.environ.get("RELAY_CLAUDE_ACP_DIR") and shutil.which("node") and os.name != "nt",
                     "RELAY_CLAUDE_ACP_DIR / node / POSIX not available (TEST_ENVIRONMENT_NOT_PREPARED)")
class TestOfficialAdapterPushWithSyntheticCli(unittest.TestCase):
    """The official adapter itself pushes ``_auth/status_update``; its input is a SYNTHETIC ``auth status --json``."""

    def observe(self, cli_json):
        home = tempfile.mkdtemp()
        log = os.path.join(home, "tripwire.log")
        env = {"HOME": home, "CLAUDE_CODE_EXECUTABLE": str(TRIPWIRE), "RELAY_TRIPWIRE_LOG": log,
               "RELAY_TRIPWIRE_AUTH_STATUS_JSON": cli_json}
        sink, raw = [], []

        async def go():
            cm = spawn_stdio_transport("node", os.path.join(os.environ["RELAY_CLAUDE_ACP_DIR"], "dist", "index.js"),
                                       env=env, cwd=home, shutdown_timeout=3)
            stdout, stdin, _proc = await cm.__aenter__()
            try:
                await _acp_initialize(stdout, stdin, 30, sink)
                # the push follows the initialize response; read it with the same wire helper
                line = await asyncio.wait_for(stdout.readline(), 10)
                raw.append(json.loads(line))
            finally:
                await cm.__aexit__(None, None, None)

        asyncio.run(go())
        with open(log, encoding="utf-8") as fh:
            return raw[0], [json.loads(x) for x in fh if x.strip()]

    def test_official_push_shape_matches_what_relay_classifies(self):
        cases = (
            ({"loggedIn": True, "apiProvider": "firstParty", "subscriptionType": "pro", "email": EMAIL, "orgName": ORG}, "CLAUDE_SUBSCRIPTION_ACCOUNT"),
            ({"loggedIn": True, "apiProvider": "firstParty", "apiKeySource": "apiKeyHelper"}, "API_KEY_ROUTE_VIOLATION"),
            ({"loggedIn": False, "apiProvider": "bedrock"}, "EXTERNAL_ROUTE_VIOLATION"),
            ({"loggedIn": False}, "NOT_AUTHENTICATED"),
        )
        for cli, state in cases:
            with self.subTest(state=state):
                frame, calls = self.observe(json.dumps(cli))
                self.assertEqual((frame["method"], "id" in frame), (AUTH_STATUS_UPDATE_METHOD, False))
                self.assertEqual(summarize(frame["params"]["authStatus"])["auth_state"], state)
                self.assertEqual(calls, [["auth", "status", "--json"]])  # the only process the adapter ran

    def test_official_adapter_and_cli_status_summarizer_agree(self):
        from relay.claude_auth_readonly import summarize_claude_auth_evidence
        for cli in ({"loggedIn": True, "apiProvider": "firstParty", "subscriptionType": "max"},
                    {"loggedIn": True, "apiProvider": "firstParty", "apiKeySource": "env", "subscriptionType": "pro"},
                    {"loggedIn": False, "apiProvider": "firstParty", "subscriptionType": "pro"},
                    {"loggedIn": False, "apiProvider": "vertex"}, {"loggedIn": False}):
            with self.subTest(cli=cli):
                frame, _calls = self.observe(json.dumps(cli))
                self.assertEqual(summarize(frame["params"]["authStatus"])["auth_state"],
                                 summarize_claude_auth_evidence(cli)["auth_state"])


if __name__ == "__main__":
    unittest.main()
