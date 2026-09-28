import ast
import copy
import hashlib
import inspect
import json
import unittest
from typing import Any
from unittest import mock

import src.providers.live_readiness_snapshot as snapshot_mod

from src.providers.live_readiness_snapshot import (
    build_live_readiness_snapshot,
    render_snapshot_summary_ja,
    _canonical_json
)
from src.providers.live_readiness_pipeline import (
    PROVIDER_ORDER,
    build_live_readiness_pipeline as real_build_live_readiness_pipeline,
)
from src.providers.preflight import validate_provider_static as real_validate_provider_static
from src.providers.live_readiness import COMMON_PROOFS, PROVIDER_PROOFS


class TestLiveReadinessSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.valid_configs = {
            "openai": {
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "custom_model_provider_configured": False,
                    "arbitrary_codex_config_present": False,
                },
                "platform": None,
                "architecture": None,
                "provider_meta": None,
            },
            "anthropic": {
                "auth_kind": "account",
                "route_evidence": {
                    "api_key_present": False,
                    "gateway_configured": False,
                    "external_cloud_configured": False,
                    "dangerous_permission_bypass": False,
                    "hide_claude_auth": False,
                },
                "platform": None,
                "architecture": None,
                "provider_meta": {
                    "claudeCode": {
                        "options": {
                            "allowDangerouslySkipPermissions": False,
                        }
                    }
                },
            },
            "google": {
                "auth_kind": "account",
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
                "provider_meta": None,
            },
        }

        self.unknown_inventory = {
            p: {proof: None for proof in (COMMON_PROOFS | PROVIDER_PROOFS[p])}
            for p in PROVIDER_ORDER
        }

        self.confirmed_inventory = {
            p: {proof: {"status": "CONFIRMED", "evidence_ref": "evidence"} for proof in (COMMON_PROOFS | PROVIDER_PROOFS[p])}
            for p in PROVIDER_ORDER
        }

    def _assert_fail_closed(self, result: dict[str, Any]) -> None:
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["dispatch_allowed"])
        self.assertTrue(result["human_approval_required"])
        self.assertEqual(result["retry_count"], 0)
        self.assertEqual(result["fallback_state"], "disabled")
        self.assertEqual(result["preflight_states"], {})
        self.assertEqual(result["preflight_snapshots"], {})
        self.assertIsNone(result["preflight_packet_sha256"])
        self.assertEqual(result["provider_states"], {})
        self.assertEqual(result["blocking_providers"], list(PROVIDER_ORDER))

        base_json = _canonical_json({k: v for k, v in result.items() if k != "snapshot_packet_sha256"})
        expected_hash = hashlib.sha256(base_json.encode("utf-8")).hexdigest()
        self.assertEqual(result["snapshot_packet_sha256"], expected_hash)

    def test_valid_explicit_configs_unknown_inventory(self) -> None:
        result = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.unknown_inventory})

        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["dispatch_allowed"])
        self.assertEqual(result["retry_count"], 0)

        # Preflights passed but pipeline resolves to blocked/unknown due to UNKNOWN inventory
        self.assertEqual(result["preflight_states"]["openai"], "PASS")
        self.assertEqual(result["preflight_states"]["anthropic"], "PASS")
        self.assertEqual(result["preflight_states"]["google"], "PASS")
        self.assertEqual(result["inventory_state"], "UNRESOLVED")
        self.assertTrue(result["unresolved_count"] > 0)

        self.assertEqual(
            result["blocking_providers"],
            ["openai", "anthropic", "google"]
        )

    def test_valid_synthetic_confirmed_inventory(self) -> None:
        result = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.confirmed_inventory})

        self.assertEqual(result["state"], "READY_FOR_HUMAN_APPROVAL")
        # Fixed fields must still be false/disabled
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["dispatch_allowed"])
        self.assertEqual(result["retry_count"], 0)

        self.assertEqual(result["inventory_state"], "PROOF_RECORDS_COMPLETE")
        self.assertEqual(result["unresolved_count"], 0)
        self.assertEqual(result["blocking_providers"], [])

        for p in PROVIDER_ORDER:
            self.assertEqual(result["provider_states"][p], "READY_FOR_HUMAN_APPROVAL")

    def test_malformed_input(self) -> None:
        self._assert_fail_closed(build_live_readiness_snapshot(None))
        self._assert_fail_closed(build_live_readiness_snapshot({}))

        bad_configs = copy.deepcopy(self.valid_configs)
        del bad_configs["google"]
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_configs, 'inventory': self.unknown_inventory}))

    def test_openai_anthropic_google_structural_constraints(self) -> None:
        bad_openai = copy.deepcopy(self.valid_configs)
        del bad_openai["openai"]["auth_kind"]
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_openai, 'inventory': self.unknown_inventory}))

        bad_anthropic = copy.deepcopy(self.valid_configs)
        bad_anthropic["anthropic"]["provider_meta"] = None
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_anthropic, 'inventory': self.unknown_inventory}))

        bad_google = copy.deepcopy(self.valid_configs)
        bad_google["google"]["platform"] = 123
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_google, 'inventory': self.unknown_inventory}))

    def test_strict_route_evidence_keys(self) -> None:
        import copy
        bad_openai = copy.deepcopy(self.valid_configs)
        bad_openai["openai"]["route_evidence"]["extra"] = False
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_openai, 'inventory': self.unknown_inventory}))

        bad_anthropic = copy.deepcopy(self.valid_configs)
        del bad_anthropic["anthropic"]["route_evidence"]["api_key_present"]
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_anthropic, 'inventory': self.unknown_inventory}))

        bad_google = copy.deepcopy(self.valid_configs)
        bad_google["google"]["route_evidence"]["api_key_present"] = "False"
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_google, 'inventory': self.unknown_inventory}))

    def test_validate_provider_static_not_called_on_structural_failure(self) -> None:
        import unittest.mock
        import copy
        with unittest.mock.patch("src.providers.live_readiness_snapshot.validate_provider_static") as mock_val:
            bad_configs = copy.deepcopy(self.valid_configs)
            # anthropic is bad, but openai is first in list.
            # openai should NOT be validated if anthropic is bad structurally.
            del bad_configs["anthropic"]["route_evidence"]["api_key_present"]
            self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': bad_configs, 'inventory': self.unknown_inventory}))
            mock_val.assert_not_called()

    def test_validate_provider_static_exception_stops_immediately(self) -> None:
        import unittest.mock
        with unittest.mock.patch("src.providers.live_readiness_snapshot.validate_provider_static") as mock_val:
            mock_val.side_effect = Exception("Boom")
            self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.unknown_inventory}))
            mock_val.assert_called_once()

    def test_malformed_preflight_outputs(self) -> None:
        import unittest.mock
        with unittest.mock.patch("src.providers.live_readiness_snapshot.validate_provider_static") as mock_val:
            # Missing key
            mock_val.return_value = {
                "static_configuration_status": "PASS",
                "live_readiness": "BLOCKED",
            }
            self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.unknown_inventory}))

    def test_malformed_pipeline_outputs(self) -> None:
        import unittest.mock
        with unittest.mock.patch("src.providers.live_readiness_snapshot.build_live_readiness_pipeline") as mock_pipe:
            # Wrong state
            mock_pipe.return_value = {
                "state": "TAMPERED_STATE",
                "live_ready": False,
                "dispatch_allowed": False,
                "human_approval_required": True,
                "retry_count": 0,
                "fallback_state": "disabled",
                "inventory_state": "BLOCKED_UNKNOWN",
                "unresolved_count": -1,
                "unresolved_by_provider": {},
                "inventory_packet_sha256": None,
                "provider_states": {},
                "blocking_providers": list(PROVIDER_ORDER),
                "bundle_packet_sha256": None,
                "pipeline_packet_sha256": None
            }
            self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.unknown_inventory}))

    def test_non_serializable_input(self) -> None:
        bad_inventory = copy.deepcopy(self.unknown_inventory)
        bad_inventory["openai"]["finite_timeout"] = lambda: None
        self._assert_fail_closed(build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': bad_inventory}))

    def test_source_mutation_isolation(self) -> None:
        configs = copy.deepcopy(self.valid_configs)
        inv = copy.deepcopy(self.confirmed_inventory)

        result = build_live_readiness_snapshot({'provider_configs': configs, 'inventory': inv})

        # Mutate source
        configs["openai"]["auth_kind"] = "hacked"
        inv["anthropic"]["sdk_retry_zero"] = "hacked"

        self.assertEqual(result["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(result["preflight_snapshots"]["openai"]["provider_id"], "openai")

    def test_japanese_renderer(self) -> None:
        result = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': self.confirmed_inventory})
        summary = render_snapshot_summary_ja(result)

        self.assertIn("ライブ実行: 禁止", summary)
        self.assertIn("人間承認が必要", summary)
        self.assertIn("全体状態: READY_FOR_HUMAN_APPROVAL", summary)
        self.assertIn("未解決の証明数: 0", summary)
        self.assertIn("プロバイダー状態:", summary)
        self.assertIn("- openai: READY_FOR_HUMAN_APPROVAL", summary)
        self.assertIn("事前確認状態:", summary)
        self.assertIn("- openai: PASS", summary)

        # No arbitrary strings or raw objects dumped
        self.assertNotIn("{", summary)
        self.assertNotIn("}", summary)

    def test_equivalent_input_dict_key_orders_identical_snapshot_digest(self) -> None:
        configs1 = copy.deepcopy(self.valid_configs)
        configs2 = copy.deepcopy(self.valid_configs)

        # Reverse route_evidence keys order in configs2 openai
        keys = list(configs2["openai"]["route_evidence"].keys())
        configs2["openai"]["route_evidence"] = {k: configs2["openai"]["route_evidence"][k] for k in reversed(keys)}

        res1 = build_live_readiness_snapshot({'provider_configs': configs1, 'inventory': self.unknown_inventory})
        res2 = build_live_readiness_snapshot({'provider_configs': configs2, 'inventory': self.unknown_inventory})

        self.assertEqual(res1["snapshot_packet_sha256"], res2["snapshot_packet_sha256"])

    def test_changing_evidence_ref_changes_digest_but_summary_hides_it(self) -> None:
        inv1 = copy.deepcopy(self.confirmed_inventory)
        inv2 = copy.deepcopy(self.confirmed_inventory)
        inv2["openai"]["chatgpt_route_retry_zero"] = {"status": "CONFIRMED", "evidence_ref": "different"}

        res1 = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': inv1})
        res2 = build_live_readiness_snapshot({'provider_configs': self.valid_configs, 'inventory': inv2})

        self.assertNotEqual(res1["snapshot_packet_sha256"], res2["snapshot_packet_sha256"])

        sum1 = render_snapshot_summary_ja(res1)
        sum2 = render_snapshot_summary_ja(res2)

        self.assertEqual(sum1, sum2)
        self.assertNotIn("different_evidence_ref", sum1)


    def _real_preflight_for(self, provider: str) -> dict[str, Any]:
        config = self.valid_configs[provider]
        return real_validate_provider_static(
            provider_id=provider,
            auth_kind=config["auth_kind"],
            route_evidence=copy.deepcopy(config["route_evidence"]),
            platform=config["platform"],
            architecture=config["architecture"],
            provider_meta=copy.deepcopy(config["provider_meta"]),
        )

    def _real_preflights(self) -> dict[str, dict[str, Any]]:
        return {
            provider: self._real_preflight_for(provider)
            for provider in PROVIDER_ORDER
        }

    def _real_pipeline(self, inventory: dict[str, Any]) -> dict[str, Any]:
        return real_build_live_readiness_pipeline(
            {
                "preflights": self._real_preflights(),
                "inventory": copy.deepcopy(inventory),
            }
        )

    def test_dependency_call_order_and_exactly_once(self) -> None:
        call_order: list[str] = []

        def wrapped_validate(**kwargs):
            call_order.append(kwargs["provider_id"])
            return self._real_preflight_for(kwargs["provider_id"])

        with mock.patch(
            "src.providers.live_readiness_snapshot.validate_provider_static",
            side_effect=wrapped_validate,
        ) as validate_mock, mock.patch(
            "src.providers.live_readiness_snapshot.build_live_readiness_pipeline",
            wraps=real_build_live_readiness_pipeline,
        ) as pipeline_mock:
            result = build_live_readiness_snapshot(
                {
                    "provider_configs": copy.deepcopy(self.valid_configs),
                    "inventory": copy.deepcopy(self.unknown_inventory),
                }
            )

        self.assertEqual(call_order, list(PROVIDER_ORDER))
        self.assertEqual(validate_mock.call_count, 3)
        pipeline_mock.assert_called_once()
        self.assertEqual(result["state"], "BLOCKED_UNKNOWN")
        self.assertIs(result["live_ready"], False)
        self.assertIs(result["dispatch_allowed"], False)

    def test_all_structural_failures_block_dependencies(self) -> None:
        cases: list[tuple[str, Any]] = [
            ("top-level-not-mapping", None),
            ("top-level-missing", {"provider_configs": {}}),
            (
                "top-level-extra",
                {
                    "provider_configs": copy.deepcopy(self.valid_configs),
                    "inventory": copy.deepcopy(self.unknown_inventory),
                    "extra": False,
                },
            ),
        ]

        missing_provider = copy.deepcopy(self.valid_configs)
        missing_provider.pop("google")
        cases.append((
            "provider-set-missing",
            {"provider_configs": missing_provider, "inventory": self.unknown_inventory},
        ))

        extra_provider = copy.deepcopy(self.valid_configs)
        extra_provider["other"] = copy.deepcopy(extra_provider["openai"])
        cases.append((
            "provider-set-extra",
            {"provider_configs": extra_provider, "inventory": self.unknown_inventory},
        ))

        for provider in PROVIDER_ORDER:
            missing_config_key = copy.deepcopy(self.valid_configs)
            missing_config_key[provider].pop("auth_kind")
            cases.append((
                f"{provider}-config-missing",
                {"provider_configs": missing_config_key, "inventory": self.unknown_inventory},
            ))

            extra_config_key = copy.deepcopy(self.valid_configs)
            extra_config_key[provider]["extra"] = None
            cases.append((
                f"{provider}-config-extra",
                {"provider_configs": extra_config_key, "inventory": self.unknown_inventory},
            ))

            bad_auth = copy.deepcopy(self.valid_configs)
            bad_auth[provider]["auth_kind"] = 123
            cases.append((
                f"{provider}-auth-type",
                {"provider_configs": bad_auth, "inventory": self.unknown_inventory},
            ))

            route_key = next(iter(self.valid_configs[provider]["route_evidence"]))
            missing_route = copy.deepcopy(self.valid_configs)
            missing_route[provider]["route_evidence"].pop(route_key)
            cases.append((
                f"{provider}-route-missing",
                {"provider_configs": missing_route, "inventory": self.unknown_inventory},
            ))

            extra_route = copy.deepcopy(self.valid_configs)
            extra_route[provider]["route_evidence"]["extra"] = False
            cases.append((
                f"{provider}-route-extra",
                {"provider_configs": extra_route, "inventory": self.unknown_inventory},
            ))

            for bad_bool in (0, 1, "false", None):
                bad_route_type = copy.deepcopy(self.valid_configs)
                bad_route_type[provider]["route_evidence"][route_key] = bad_bool
                cases.append((
                    f"{provider}-route-type-{bad_bool!r}",
                    {
                        "provider_configs": bad_route_type,
                        "inventory": self.unknown_inventory,
                    },
                ))

        openai_platform = copy.deepcopy(self.valid_configs)
        openai_platform["openai"]["platform"] = "linux"
        cases.append((
            "openai-platform",
            {"provider_configs": openai_platform, "inventory": self.unknown_inventory},
        ))

        anthropic_meta = copy.deepcopy(self.valid_configs)
        anthropic_meta["anthropic"]["provider_meta"] = None
        cases.append((
            "anthropic-meta",
            {"provider_configs": anthropic_meta, "inventory": self.unknown_inventory},
        ))

        google_platform = copy.deepcopy(self.valid_configs)
        google_platform["google"]["platform"] = ""
        cases.append((
            "google-platform",
            {"provider_configs": google_platform, "inventory": self.unknown_inventory},
        ))

        google_arch = copy.deepcopy(self.valid_configs)
        google_arch["google"]["architecture"] = 7
        cases.append((
            "google-architecture",
            {"provider_configs": google_arch, "inventory": self.unknown_inventory},
        ))

        google_meta = copy.deepcopy(self.valid_configs)
        google_meta["google"]["provider_meta"] = {}
        cases.append((
            "google-meta",
            {"provider_configs": google_meta, "inventory": self.unknown_inventory},
        ))

        with mock.patch(
            "src.providers.live_readiness_snapshot.validate_provider_static"
        ) as validate_mock, mock.patch(
            "src.providers.live_readiness_snapshot.build_live_readiness_pipeline"
        ) as pipeline_mock:
            for name, payload in cases:
                with self.subTest(name=name):
                    self._assert_fail_closed(build_live_readiness_snapshot(payload))
            validate_mock.assert_not_called()
            pipeline_mock.assert_not_called()

    def test_nonserializable_input_calls_no_dependencies(self) -> None:
        bad_inventory = copy.deepcopy(self.unknown_inventory)
        proof = next(iter(bad_inventory["openai"]))
        bad_inventory["openai"][proof] = object()

        with mock.patch(
            "src.providers.live_readiness_snapshot.validate_provider_static"
        ) as validate_mock, mock.patch(
            "src.providers.live_readiness_snapshot.build_live_readiness_pipeline"
        ) as pipeline_mock:
            self._assert_fail_closed(
                build_live_readiness_snapshot(
                    {
                        "provider_configs": copy.deepcopy(self.valid_configs),
                        "inventory": bad_inventory,
                    }
                )
            )
            validate_mock.assert_not_called()
            pipeline_mock.assert_not_called()

    def test_preflight_exception_stops_without_later_provider_or_pipeline(self) -> None:
        calls: list[str] = []

        def fake_validate(**kwargs):
            provider = kwargs["provider_id"]
            calls.append(provider)
            if provider == "anthropic":
                raise RuntimeError("boom")
            return self._real_preflight_for(provider)

        with mock.patch(
            "src.providers.live_readiness_snapshot.validate_provider_static",
            side_effect=fake_validate,
        ) as validate_mock, mock.patch(
            "src.providers.live_readiness_snapshot.build_live_readiness_pipeline"
        ) as pipeline_mock:
            self._assert_fail_closed(
                build_live_readiness_snapshot(
                    {
                        "provider_configs": copy.deepcopy(self.valid_configs),
                        "inventory": copy.deepcopy(self.unknown_inventory),
                    }
                )
            )

        self.assertEqual(calls, ["openai", "anthropic"])
        self.assertEqual(validate_mock.call_count, 2)
        pipeline_mock.assert_not_called()

    def test_malformed_preflight_matrix_blocks_pipeline(self) -> None:
        valid = self._real_preflight_for("openai")
        cases: list[tuple[str, dict[str, Any]]] = []

        extra = copy.deepcopy(valid)
        extra["extra"] = False
        cases.append(("extra-key", extra))

        missing = copy.deepcopy(valid)
        missing.pop("provider_id")
        cases.append(("missing-key", missing))

        for name, field, value in (
            ("wrong-provider", "provider_id", "google"),
            ("wrong-agent", "external_agent", "__tampered__"),
            ("wrong-version", "pinned_version", "__tampered__"),
            ("bad-status", "static_configuration_status", "READY"),
            ("bad-live-readiness", "live_readiness", "READY"),
            ("reasons-not-list", "reasons", "bad"),
            ("reasons-nonstr", "reasons", ["ok", 7]),
            ("retry-one", "retry_count", 1),
            ("retry-bool", "retry_count", False),
            ("fallback", "fallback_state", "enabled"),
            ("live-ready", "live_ready", True),
        ):
            item = copy.deepcopy(valid)
            item[field] = value
            cases.append((name, item))

        for name, bad_openai in cases:
            with self.subTest(name=name):
                def fake_validate(**kwargs):
                    provider = kwargs["provider_id"]
                    if provider == "openai":
                        return copy.deepcopy(bad_openai)
                    return self._real_preflight_for(provider)

                with mock.patch(
                    "src.providers.live_readiness_snapshot.validate_provider_static",
                    side_effect=fake_validate,
                ), mock.patch(
                    "src.providers.live_readiness_snapshot.build_live_readiness_pipeline"
                ) as pipeline_mock:
                    self._assert_fail_closed(
                        build_live_readiness_snapshot(
                            {
                                "provider_configs": copy.deepcopy(self.valid_configs),
                                "inventory": copy.deepcopy(self.unknown_inventory),
                            }
                        )
                    )
                    pipeline_mock.assert_not_called()

    def test_pipeline_exception_is_one_attempt(self) -> None:
        with mock.patch(
            "src.providers.live_readiness_snapshot.build_live_readiness_pipeline",
            side_effect=RuntimeError("boom"),
        ) as pipeline_mock:
            self._assert_fail_closed(
                build_live_readiness_snapshot(
                    {
                        "provider_configs": copy.deepcopy(self.valid_configs),
                        "inventory": copy.deepcopy(self.unknown_inventory),
                    }
                )
            )
            pipeline_mock.assert_called_once()

    def test_malformed_pipeline_matrix_fails_closed(self) -> None:
        ready = self._real_pipeline(self.confirmed_inventory)
        blocked = self._real_pipeline(self.unknown_inventory)
        cases: list[tuple[str, dict[str, Any]]] = []

        extra = copy.deepcopy(ready)
        extra["extra"] = False
        cases.append(("extra-key", extra))

        missing = copy.deepcopy(ready)
        missing.pop("state")
        cases.append(("missing-key", missing))

        for name, field, value in (
            ("bad-state", "state", "LIVE"),
            ("live-ready", "live_ready", True),
            ("dispatch", "dispatch_allowed", True),
            ("human", "human_approval_required", False),
            ("retry", "retry_count", 1),
            ("retry-bool", "retry_count", False),
            ("fallback", "fallback_state", "enabled"),
            ("inventory-state", "inventory_state", "READY"),
            ("count-bool", "unresolved_count", False),
            ("count-negative", "unresolved_count", -2),
        ):
            item = copy.deepcopy(ready)
            item[field] = value
            cases.append((name, item))

        wrong_counts = copy.deepcopy(ready)
        wrong_counts["unresolved_by_provider"].pop("google")
        cases.append(("count-provider-set", wrong_counts))

        negative_count = copy.deepcopy(ready)
        negative_count["unresolved_by_provider"]["openai"] = -1
        cases.append(("count-negative-provider", negative_count))

        sum_mismatch = copy.deepcopy(ready)
        sum_mismatch["unresolved_by_provider"]["openai"] = 1
        cases.append(("count-sum", sum_mismatch))

        wrong_states = copy.deepcopy(ready)
        wrong_states["provider_states"].pop("google")
        cases.append(("state-provider-set", wrong_states))

        bad_state = copy.deepcopy(ready)
        bad_state["provider_states"]["openai"] = "LIVE"
        cases.append(("provider-state", bad_state))

        duplicate_blocking = copy.deepcopy(blocked)
        duplicate_blocking["blocking_providers"] = ["openai", "openai"]
        cases.append(("blocking-duplicate", duplicate_blocking))

        wrong_order = copy.deepcopy(blocked)
        wrong_order["blocking_providers"] = ["google", "openai", "anthropic"]
        cases.append(("blocking-order", wrong_order))

        inconsistent_blocking = copy.deepcopy(ready)
        inconsistent_blocking["blocking_providers"] = ["openai"]
        cases.append(("blocking-inconsistent", inconsistent_blocking))

        empty_states_wrong_blockers = copy.deepcopy(blocked)
        empty_states_wrong_blockers["blocking_providers"] = []
        cases.append(("empty-state-blockers", empty_states_wrong_blockers))

        blocked_all_ready = copy.deepcopy(ready)
        blocked_all_ready["state"] = "BLOCKED_UNKNOWN"
        cases.append(("blocked-all-ready", blocked_all_ready))

        for field in (
            "inventory_packet_sha256",
            "bundle_packet_sha256",
            "pipeline_packet_sha256",
        ):
            bad_hash = copy.deepcopy(ready)
            bad_hash[field] = "A" * 64
            cases.append((f"{field}-uppercase", bad_hash))

        pipeline_hash_null = copy.deepcopy(ready)
        pipeline_hash_null["pipeline_packet_sha256"] = None
        cases.append(("pipeline-hash-null", pipeline_hash_null))

        ready_bad_inventory = copy.deepcopy(ready)
        ready_bad_inventory["inventory_state"] = "UNRESOLVED"
        cases.append(("ready-inventory", ready_bad_inventory))

        ready_bad_count = copy.deepcopy(ready)
        ready_bad_count["unresolved_count"] = 1
        cases.append(("ready-count", ready_bad_count))

        ready_bad_provider = copy.deepcopy(ready)
        ready_bad_provider["provider_states"]["openai"] = "BLOCKED_UNKNOWN"
        cases.append(("ready-provider", ready_bad_provider))

        ready_no_inventory_hash = copy.deepcopy(ready)
        ready_no_inventory_hash["inventory_packet_sha256"] = None
        cases.append(("ready-inventory-hash", ready_no_inventory_hash))

        ready_no_bundle_hash = copy.deepcopy(ready)
        ready_no_bundle_hash["bundle_packet_sha256"] = None
        cases.append(("ready-bundle-hash", ready_no_bundle_hash))

        for name, pipeline_result in cases:
            with self.subTest(name=name):
                with mock.patch(
                    "src.providers.live_readiness_snapshot.build_live_readiness_pipeline",
                    return_value=pipeline_result,
                ):
                    self._assert_fail_closed(
                        build_live_readiness_snapshot(
                            {
                                "provider_configs": copy.deepcopy(self.valid_configs),
                                "inventory": copy.deepcopy(self.unknown_inventory),
                            }
                        )
                    )

    def test_source_and_dependency_result_mutation_isolation(self) -> None:
        configs = copy.deepcopy(self.valid_configs)
        inventory = copy.deepcopy(self.confirmed_inventory)
        returned_preflights = {
            provider: self._real_preflight_for(provider)
            for provider in PROVIDER_ORDER
        }
        external_pipeline = self._real_pipeline(self.confirmed_inventory)

        def fake_validate(**kwargs):
            return returned_preflights[kwargs["provider_id"]]

        with mock.patch(
            "src.providers.live_readiness_snapshot.validate_provider_static",
            side_effect=fake_validate,
        ), mock.patch(
            "src.providers.live_readiness_snapshot.build_live_readiness_pipeline",
            return_value=external_pipeline,
        ):
            result = build_live_readiness_snapshot(
                {"provider_configs": configs, "inventory": inventory}
            )

        digest = result["snapshot_packet_sha256"]
        configs["openai"]["auth_kind"] = "tampered"
        proof = next(iter(inventory["openai"]))
        inventory["openai"][proof] = {
            "status": "CONFIRMED",
            "evidence_ref": "tampered",
        }
        returned_preflights["openai"]["provider_id"] = "tampered"
        external_pipeline["state"] = "BLOCKED_UNKNOWN"
        external_pipeline["provider_states"]["openai"] = "BLOCKED_UNKNOWN"

        self.assertEqual(result["snapshot_packet_sha256"], digest)
        self.assertEqual(
            result["preflight_snapshots"]["openai"]["provider_id"],
            "openai",
        )
        self.assertEqual(result["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(
            result["provider_states"]["openai"],
            "READY_FOR_HUMAN_APPROVAL",
        )

    def test_renderer_sanitizes_untrusted_state_and_count_strings(self) -> None:
        marker = "https://evil.invalid/?token=secret"
        summary = render_snapshot_summary_ja(
            {
                "state": marker,
                "unresolved_count": marker,
                "preflight_states": {
                    "openai": marker,
                    "anthropic": "PASS",
                    "google": "PASS",
                },
                "provider_states": {
                    "openai": marker,
                    "anthropic": "READY_FOR_HUMAN_APPROVAL",
                    "google": "READY_FOR_HUMAN_APPROVAL",
                },
                "blocking_providers": [marker, "google"],
                "reasons": [marker],
                "evidence_ref": marker,
            }
        )
        self.assertNotIn(marker, summary)
        self.assertNotIn("token=", summary)
        self.assertIn("全体状態: BLOCKED_UNKNOWN", summary)
        self.assertIn("未解決の証明数: -1", summary)
        self.assertIn(
            "ブロック中のプロバイダー: openai, anthropic, google",
            summary,
        )

    def test_ast_static_boundary_excludes_ambient_io_and_direct_live_gate(self) -> None:
        source = inspect.getsource(snapshot_mod)
        tree = ast.parse(source)
        banned_import_roots = {
            "os",
            "pathlib",
            "subprocess",
            "socket",
            "urllib",
            "requests",
            "http",
            "time",
            "random",
        }
        banned_calls = {
            "open",
            "exec",
            "eval",
            "__import__",
            "evaluate_live_readiness",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name.split(".")[0],
                        banned_import_roots,
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self.assertNotIn(
                        node.module.split(".")[0],
                        banned_import_roots,
                    )
                for alias in node.names:
                    self.assertNotEqual(alias.name, "evaluate_live_readiness")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, banned_calls)
                elif isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, banned_calls)
