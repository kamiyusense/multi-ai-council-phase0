import json
import unittest
from pathlib import Path

from providers.codex_acp import build_codex_profile
from relay.acp_stdio_relay_transport import AcpStdioStaticTransport, OfficialAdapterLaunch

REPO = Path(__file__).resolve().parents[2]
CHECKLIST = REPO / "fixtures" / "relay" / "m9_codex_first_live_checklist.json"
STATES = {"STATIC_VERIFIED", "PREPARE_ONLY"}


class TestM9PrepareOnlyChecklist(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(CHECKLIST.read_text(encoding="utf-8"))

    def test_live_is_not_enabled_or_approved(self):
        self.assertIs(self.data["live_enabled"], False)
        self.assertEqual(self.data["human_approval"], "NOT_GRANTED")
        self.assertEqual(self.data["status"], "PREPARE_ONLY")
        self.assertEqual(self.data["scope"], {
            "dispatches": 1, "prompts": 1, "max_generations": 1, "retry": 0, "fallback": "disabled",
            "stop_after": "first terminal outcome (success, failure or UNKNOWN)"})

    def test_items_are_well_formed_and_cover_required_points(self):
        ids = [item["id"] for item in self.data["items"]]
        self.assertEqual(len(ids), len(set(ids)))
        for item in self.data["items"]:
            self.assertEqual(set(item), {"id", "requirement", "state", "evidence"})
            self.assertIn(item["state"], STATES)
            self.assertTrue(item["evidence"])
        required = {
            "provider-codex-only", "one-dispatch", "one-prompt", "one-generation", "title-generation-blocked",
            "retry-zero", "fallback-disabled", "explicit-timeout", "duplicate-guard", "stop-cancel-path",
            "receipt-saved", "gate-log-saved", "backend-turn-start-count-saved", "stop-after-one",
            "no-resend-on-unknown", "no-api-key-route", "subscription-account-only", "no-billing-change",
        }
        self.assertEqual(required, set(ids))

    def test_real_backend_is_still_unreachable_without_code_change(self):
        """The disabled items stay disabled: a backend outside the fixture root is refused."""
        profile = build_codex_profile("account", {
            "api_key_present": False, "gateway_configured": False, "external_cloud_configured": False,
            "custom_model_provider_configured": False, "arbitrary_codex_config_present": False})
        gate = REPO / "src" / "relay" / "codex_turn_gate.py"
        launch = OfficialAdapterLaunch(
            ("node", "codex-acp/dist/index.js"),
            {"CODEX_PATH": str(gate), "RELAY_GATE_BACKEND": "/usr/bin/env"},
            REPO / "fixtures" / "relay",
        )
        with self.assertRaises(ValueError):
            AcpStdioStaticTransport(profile, official=launch)
        self.assertGreaterEqual(len(self.data["disabled_until_human_approval"]), 4)


if __name__ == "__main__":
    unittest.main()
