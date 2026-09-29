import os
import unittest
from dataclasses import replace

from providers.policy import ProviderPolicy, claude_session_meta
from providers.preflight import validate_provider_static
from relay.envelope import validate_payload


class TestMinimumPermissionsStaticInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        inventory_path = os.path.join(
            root,
            "docs",
            "RELAY_MINIMUM_PERMISSIONS_STATIC_INVENTORY.md",
        )
        checkpoint_path = os.path.join(root, "docs", "RELAY_STATIC_CHECKPOINT.md")
        if not os.path.isfile(inventory_path):
            raise AssertionError("minimum-permissions inventory document is missing")
        if not os.path.isfile(checkpoint_path):
            raise AssertionError("static checkpoint document is missing")
        with open(inventory_path, "r", encoding="utf-8") as stream:
            cls.inventory = stream.read()
        with open(checkpoint_path, "r", encoding="utf-8") as stream:
            cls.checkpoint = stream.read()
        cls.rows = cls._parse_inventory(cls.inventory)

    @staticmethod
    def _parse_inventory(content: str) -> dict[str, dict[str, str]]:
        headers = [
            "surface_id",
            "provider/scope",
            "canonical_source",
            "current_static_control",
            "evidence_kind",
            "what_is_still_unproven",
            "state",
        ]
        lines = content.splitlines()
        header_index = None
        for index, line in enumerate(lines):
            if line.startswith("| surface_id |"):
                actual = [cell.strip() for cell in line.strip("|").split("|")]
                if actual != headers:
                    raise AssertionError(f"unexpected inventory headers: {actual}")
                header_index = index
                break
        if header_index is None:
            raise AssertionError("inventory table header is missing")

        rows = {}
        for line in lines[header_index + 2 :]:
            if not line.startswith("| "):
                break
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != len(headers):
                raise AssertionError(f"malformed inventory row: {line}")
            row = dict(zip(headers, cells))
            surface_id = row["surface_id"]
            if surface_id in rows:
                raise AssertionError(f"duplicate surface_id: {surface_id}")
            rows[surface_id] = row
        return rows

    def test_provider_policy_rejects_each_unsafe_mutation(self) -> None:
        base = ProviderPolicy("test", "agent", "1.0")
        mutations = {
            "automatic_retry": 1,
            "fallback_enabled": True,
            "allow_api_key": True,
            "allow_gateway": True,
            "allow_external_cloud": True,
            "dangerous_permission_bypass": True,
            "live_ready": True,
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    replace(base, **{field: value}).assert_static_safety()

        base.assert_static_safety()
        self.assertTrue(base.validate_auth_kind("account"))
        self.assertFalse(base.validate_auth_kind("api_key"))

    def _assert_flag_fails_closed(
        self,
        provider_id: str,
        flags: list[str],
        extra_kwargs: dict | None = None,
    ) -> None:
        extra_kwargs = extra_kwargs or {}
        for flag in flags:
            with self.subTest(provider=provider_id, flag=flag):
                route_evidence = {key: False for key in flags}
                route_evidence[flag] = True
                result = validate_provider_static(
                    provider_id=provider_id,
                    auth_kind="account",
                    route_evidence=route_evidence,
                    **extra_kwargs,
                )
                self.assertEqual(result["static_configuration_status"], "UNKNOWN")
                self.assertEqual(result["live_readiness"], "BLOCKED")
                self.assertFalse(result["live_ready"])
                self.assertEqual(
                    result["reasons"],
                    [f"{flag} must be explicitly False"],
                )

    def test_openai_preflight_rejects_each_route_flag_directly(self) -> None:
        self._assert_flag_fails_closed(
            "openai",
            [
                "api_key_present",
                "gateway_configured",
                "external_cloud_configured",
                "custom_model_provider_configured",
                "arbitrary_codex_config_present",
            ],
        )

    def test_anthropic_preflight_rejects_each_route_and_permission_flag(self) -> None:
        self._assert_flag_fails_closed(
            "anthropic",
            [
                "api_key_present",
                "gateway_configured",
                "external_cloud_configured",
                "dangerous_permission_bypass",
                "hide_claude_auth",
            ],
            {"provider_meta": claude_session_meta()},
        )

    def test_claude_session_meta_and_exact_meta_match_are_fail_closed(self) -> None:
        expected = claude_session_meta()
        self.assertIs(
            expected["claudeCode"]["options"]["allowDangerouslySkipPermissions"],
            False,
        )
        route_evidence = {
            "api_key_present": False,
            "gateway_configured": False,
            "external_cloud_configured": False,
            "dangerous_permission_bypass": False,
            "hide_claude_auth": False,
        }
        mismatched = claude_session_meta()
        mismatched["claudeCode"]["options"]["allowDangerouslySkipPermissions"] = True
        result = validate_provider_static(
            provider_id="anthropic",
            auth_kind="account",
            route_evidence=route_evidence,
            provider_meta=mismatched,
        )
        self.assertEqual(result["static_configuration_status"], "UNKNOWN")
        self.assertEqual(
            result["reasons"],
            ["provider_meta must exactly match claude_session_meta()"],
        )

    def test_google_preflight_rejects_each_route_and_billing_flag_directly(self) -> None:
        self._assert_flag_fails_closed(
            "google",
            [
                "api_key_present",
                "gateway_configured",
                "external_cloud_configured",
                "cloud_billing_selected",
                "overages_enabled",
                "adc_present",
                "vertex_selected",
            ],
            {"platform": "linux", "architecture": "x86_64"},
        )

    def test_wrong_auth_kind_fails_closed_for_every_provider(self) -> None:
        cases = {
            "openai": {
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "custom_model_provider_configured": False,
                    "arbitrary_codex_config_present": False,
                },
            },
            "anthropic": {
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "dangerous_permission_bypass": False,
                    "hide_claude_auth": False,
                },
                "provider_meta": claude_session_meta(),
            },
            "google": {
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "cloud_billing_selected": False,
                    "overages_enabled": False,
                    "adc_present": False,
                    "vertex_selected": False,
                },
                "platform": "linux",
                "architecture": "x86_64",
            },
        }
        for provider_id, kwargs in cases.items():
            with self.subTest(provider=provider_id):
                result = validate_provider_static(
                    provider_id=provider_id,
                    auth_kind="api_key",
                    **kwargs,
                )
                self.assertEqual(result["static_configuration_status"], "UNKNOWN")
                self.assertEqual(
                    result["reasons"],
                    ["invalid auth_kind: api_key"],
                )

    def test_payload_control_overrides_fail_but_secret_key_is_not_filtered(self) -> None:
        blocked_keys = [
            "approvalPolicy",
            "approvalsReviewer",
            "sandbox",
            "sandboxPolicy",
            "cwd",
            "config",
            "billing",
            "auth route",
        ]
        for key in blocked_keys:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate_payload({key: "override"})

        # This proves only that validate_payload is not a generic secret filter.
        # The synthetic value is not a real secret.
        validate_payload({"secret": "synthetic-marker"})

    def test_inventory_has_exact_required_surfaces_and_states(self) -> None:
        required = {
            "provider_policy_common",
            "openai_route_controls",
            "anthropic_route_controls",
            "anthropic_dangerous_permission_bypass",
            "anthropic_session_meta",
            "google_route_controls",
            "google_billing_route_controls",
            "relay_payload_control_overrides",
            "whole_path_minimum_permission_profile",
        }
        self.assertEqual(set(self.rows), required)

        self.assertEqual(
            self.rows["provider_policy_common"]["state"],
            "STATIC_PROVEN",
        )
        self.assertEqual(
            self.rows["whole_path_minimum_permission_profile"]["state"],
            "BLOCKED_UNKNOWN",
        )
        self.assertEqual(
            self.rows["whole_path_minimum_permission_profile"]["evidence_kind"],
            "PARTIAL_STATIC_EVIDENCE",
        )
        for surface_id, row in self.rows.items():
            with self.subTest(surface_id=surface_id):
                self.assertIn(
                    row["state"],
                    {
                        "STATIC_PROVEN",
                        "PARTIAL_STATIC_EVIDENCE",
                        "BLOCKED_UNKNOWN",
                    },
                )
                self.assertTrue(row["current_static_control"])
                self.assertTrue(row["what_is_still_unproven"])

    def test_inventory_does_not_promote_static_controls_to_live_permissions(self) -> None:
        for phrase in (
            "Zero permission changes are made",
            "Zero external/read-only/live evidence is acquired",
            "No exact whole-path minimum-permission profile is selected",
            "common_min_permissions` remains unresolved / `BLOCKED_UNKNOWN",
            "do not prove the authenticated live identity or subscription billing route",
            "first live provider/model turn remains separately human-approved",
        ):
            self.assertIn(phrase, self.inventory)

        for forbidden in (
            "execution_authorized=true",
            "dispatch_allowed=true",
            "live_ready=true",
            "LIVE_AUTHORIZED",
            "READY_FOR_LIVE",
            "REAL_BLOCKERS_RESOLVED",
        ):
            self.assertNotIn(forbidden, self.inventory)

    def test_checkpoint_preserves_prepared_static_boundary(self) -> None:
        section = self.checkpoint.split(
            "## Minimum Permissions Static Inventory Checkpoint",
            1,
        )[1]
        for phrase in (
            "PREPARED/static minimum-permissions-inventory status only",
            "No live execution is performed",
            "No permission/auth/billing/settings changes are performed or authorized by this batch",
            "No exact whole-path minimum-permission profile is selected",
            "common_min_permissions remains unresolved / BLOCKED_UNKNOWN",
            "First live provider/model turn remains separately human-approved",
        ):
            self.assertIn(phrase, section)
