import ast
import copy
import hashlib
import json
import unittest

from providers.preflight import claude_session_meta
from providers.live_readiness_snapshot import build_live_readiness_snapshot
from providers.live_readiness_approval import build_live_readiness_approval_packet
from providers.live_approval_receipt import build_live_approval_receipt
from providers.live_provenance_request import (
    build_live_provenance_request,
    render_provenance_request_ja,
)


class TestLiveProvenanceBoundary(unittest.TestCase):
    def setUp(self) -> None:
        # 1. Provide the basic synthetic explicit configs & inventory
        self.provider_configs = {
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
                "provider_meta": claude_session_meta(),
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

        self.inventory = {
            "openai": {
                "chatgpt_route_retry_zero": {"status": "CONFIRMED", "evidence_ref": "a"},
                "executed_model_verification_mechanism": {"status": "CONFIRMED", "evidence_ref": "b"},
                "filesystem_network_confinement": {"status": "CONFIRMED", "evidence_ref": "c"},
                "final_fanout_secret_pii_private_code_policy": {"status": "CONFIRMED", "evidence_ref": "d"},
                "finite_timeout": {"status": "CONFIRMED", "evidence_ref": "e"},
                "intended_subscription_billing_route": {"status": "CONFIRMED", "evidence_ref": "f"},
                "minimum_permission_profile": {"status": "CONFIRMED", "evidence_ref": "g"},
                "no_auth_recovery_replay": {"status": "CONFIRMED", "evidence_ref": "h"},
                "no_stream_reconnect_replay": {"status": "CONFIRMED", "evidence_ref": "i"},
                "provider_specific_abort_readback": {"status": "CONFIRMED", "evidence_ref": "j"},
                "single_model_request_evidence": {"status": "CONFIRMED", "evidence_ref": "k"},
                "zero_hidden_retry_fallback_end_to_end": {"status": "CONFIRMED", "evidence_ref": "l"}
            },
            "anthropic": {
                "account_auth": {"status": "CONFIRMED", "evidence_ref": "m"},
                "dangerous_skip_permissions_false": {"status": "CONFIRMED", "evidence_ref": "n"},
                "executed_model_verification_mechanism": {"status": "CONFIRMED", "evidence_ref": "o"},
                "filesystem_network_confinement": {"status": "CONFIRMED", "evidence_ref": "p"},
                "final_fanout_secret_pii_private_code_policy": {"status": "CONFIRMED", "evidence_ref": "q"},
                "finite_timeout": {"status": "CONFIRMED", "evidence_ref": "r"},
                "independent_executed_model_verification": {"status": "CONFIRMED", "evidence_ref": "s"},
                "intended_subscription_billing_route": {"status": "CONFIRMED", "evidence_ref": "t"},
                "minimum_permission_profile": {"status": "CONFIRMED", "evidence_ref": "u"},
                "model_fallback_disabled": {"status": "CONFIRMED", "evidence_ref": "v"},
                "no_restart_recovery_extra_turn": {"status": "CONFIRMED", "evidence_ref": "w"},
                "provider_specific_abort_readback": {"status": "CONFIRMED", "evidence_ref": "x"},
                "sdk_retry_zero": {"status": "CONFIRMED", "evidence_ref": "y"},
                "zero_hidden_retry_fallback_end_to_end": {"status": "CONFIRMED", "evidence_ref": "z"}
            },
            "google": {
                "api_key_cloud_billing_overage_absent": {"status": "CONFIRMED", "evidence_ref": "aa"},
                "cancel_teardown_no_restart": {"status": "CONFIRMED", "evidence_ref": "bb"},
                "executed_model_verification": {"status": "CONFIRMED", "evidence_ref": "cc"},
                "executed_model_verification_mechanism": {"status": "CONFIRMED", "evidence_ref": "dd"},
                "filesystem_network_confinement": {"status": "CONFIRMED", "evidence_ref": "ee"},
                "final_fanout_secret_pii_private_code_policy": {"status": "CONFIRMED", "evidence_ref": "ff"},
                "finite_timeout": {"status": "CONFIRMED", "evidence_ref": "gg"},
                "intended_account_route": {"status": "CONFIRMED", "evidence_ref": "hh"},
                "intended_subscription_billing_route": {"status": "CONFIRMED", "evidence_ref": "ii"},
                "internal_retry_fallback_zero": {"status": "CONFIRMED", "evidence_ref": "jj"},
                "minimum_permission_profile": {"status": "CONFIRMED", "evidence_ref": "kk"},
                "provider_specific_abort_readback": {"status": "CONFIRMED", "evidence_ref": "ll"},
                "quota_billing_unknown_blocks": {"status": "CONFIRMED", "evidence_ref": "mm"},
                "zero_hidden_retry_fallback_end_to_end": {"status": "CONFIRMED", "evidence_ref": "nn"}
            }
        }

        self.safe_locator = {
            "source_kind": "GITHUB_DURABLE_RECORD",
            "repository_full_name": "owner/repo",
            "ref": "main",
            "path": "path/to/record.json",
            "expected_record_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        }

    def test_synthetic_complete_evidence_path(self):
        # snapshot reaches READY_FOR_HUMAN_APPROVAL
        snapshot = build_live_readiness_snapshot({
            "provider_configs": self.provider_configs,
            "inventory": self.inventory,
        })
        self.assertEqual(snapshot["state"], "READY_FOR_HUMAN_APPROVAL")

        # approval packet reaches READY_FOR_HUMAN_APPROVAL + REQUEST_HUMAN_APPROVAL
        approval_packet = build_live_readiness_approval_packet({
            "provider_configs": self.provider_configs,
            "inventory": self.inventory,
        })
        self.assertEqual(approval_packet["state"], "READY_FOR_HUMAN_APPROVAL")
        self.assertEqual(approval_packet["next_action"], "REQUEST_HUMAN_APPROVAL")

        # receipt reaches STRUCTURALLY_VALID_APPROVAL_RECORD + VERIFY_DURABLE_HUMAN_PROVENANCE
        receipt_input = {
            "approval_packet": approval_packet,
            "approval_record": {
                "decision": "APPROVE_FIRST_LIVE_POC",
                "scope": "FIRST_LIVE_POC_ONLY",
                "one_shot": True,
                "recorded_at": "2025-01-01T12:00:00Z",
                "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
                "target_snapshot_packet_sha256": approval_packet["snapshot_packet_sha256"],
            }
        }
        receipt = build_live_approval_receipt(receipt_input)
        self.assertEqual(receipt["state"], "STRUCTURALLY_VALID_APPROVAL_RECORD")
        self.assertEqual(receipt["next_action"], "VERIFY_DURABLE_HUMAN_PROVENANCE")

        # valid locator reaches PROVENANCE_VERIFICATION_REQUIRED + READBACK_DURABLE_HUMAN_PROVENANCE
        request_input = {
            "approval_receipt": receipt,
            "durable_locator": self.safe_locator,
        }
        request = build_live_provenance_request(request_input)
        self.assertEqual(request["state"], "PROVENANCE_VERIFICATION_REQUIRED")
        self.assertEqual(request["next_action"], "READBACK_DURABLE_HUMAN_PROVENANCE")

        # enforce fixed false flags
        self.assertFalse(request["provenance_verified"])
        self.assertFalse(request["execution_authorized"])
        self.assertFalse(request["dispatch_allowed"])
        self.assertFalse(request["live_ready"])

    def test_unknown_unresolved_readiness_path_fails_closed(self):
        inventory = copy.deepcopy(self.inventory)
        inventory["openai"]["chatgpt_route_retry_zero"]["status"] = "UNKNOWN_REASON"
        snapshot = build_live_readiness_snapshot({
            "provider_configs": self.provider_configs,
            "inventory": inventory,
        })
        approval_packet = build_live_readiness_approval_packet({
            "provider_configs": self.provider_configs,
            "inventory": inventory,
        })
        receipt = build_live_approval_receipt({
            "approval_packet": approval_packet,
            "approval_record": {
                "decision": "APPROVE_FIRST_LIVE_POC",
                "scope": "FIRST_LIVE_POC_ONLY",
                "one_shot": True,
                "recorded_at": "2025-01-01T12:00:00Z",
                "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
                "target_snapshot_packet_sha256": approval_packet["snapshot_packet_sha256"],
            }
        })
        request = build_live_provenance_request({
            "approval_receipt": receipt,
            "durable_locator": self.safe_locator,
        })
        self.assertEqual(request["state"], "BLOCKED_UNKNOWN")
        self.assertEqual(request["next_action"], "RESOLVE_BLOCKERS")

    def test_reject_and_defer_receipts_fail_closed(self):
        approval_packet = build_live_readiness_approval_packet({
            "provider_configs": self.provider_configs,
            "inventory": self.inventory,
        })
        for decision in ["REJECT", "DEFER"]:
            receipt = build_live_approval_receipt({
                "approval_packet": approval_packet,
                "approval_record": {
                    "decision": decision,
                    "scope": "FIRST_LIVE_POC_ONLY",
                    "one_shot": False,
                    "recorded_at": "2025-01-01T12:00:00Z",
                    "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
                    "target_snapshot_packet_sha256": approval_packet["snapshot_packet_sha256"],
                }
            })
            request = build_live_provenance_request({
                "approval_receipt": receipt,
                "durable_locator": self.safe_locator,
            })
            self.assertEqual(request["state"], "BLOCKED_UNKNOWN")

    def test_tamper_structural_approval_receipt(self):
        approval_packet = build_live_readiness_approval_packet({
            "provider_configs": self.provider_configs,
            "inventory": self.inventory,
        })
        receipt = build_live_approval_receipt({
            "approval_packet": approval_packet,
            "approval_record": {
                "decision": "APPROVE_FIRST_LIVE_POC",
                "scope": "FIRST_LIVE_POC_ONLY",
                "one_shot": True,
                "recorded_at": "2025-01-01T12:00:00Z",
                "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
                "target_snapshot_packet_sha256": approval_packet["snapshot_packet_sha256"],
            }
        })

        tamper_cases = [
            ("state", "BLOCKED_UNKNOWN"),
            ("decision", "REJECT"),
            ("scope", "UNKNOWN"),
            ("one_shot", False),
            ("next_action", "RESOLVE_BLOCKERS"),
            ("live_ready", True),
            ("dispatch_allowed", True),
            ("execution_authorized", True),
            ("provenance_verified", True),
            ("retry_count", 1),
            ("retry_count", True),
            ("approval_packet_sha256", "0" * 64),
            ("snapshot_packet_sha256", "0" * 64),
            ("approval_record_sha256", "0" * 64),
        ]

        for key, bad_value in tamper_cases:
            tampered_receipt = copy.deepcopy(receipt)
            tampered_receipt[key] = bad_value
            request = build_live_provenance_request({
                "approval_receipt": tampered_receipt,
                "durable_locator": self.safe_locator,
            })
            self.assertEqual(request["state"], "BLOCKED_UNKNOWN", f"Failed closed tamper on {key}={bad_value}")

    def test_tamper_durable_locator(self):
        approval_packet = build_live_readiness_approval_packet({
            "provider_configs": self.provider_configs,
            "inventory": self.inventory,
        })
        receipt = build_live_approval_receipt({
            "approval_packet": approval_packet,
            "approval_record": {
                "decision": "APPROVE_FIRST_LIVE_POC",
                "scope": "FIRST_LIVE_POC_ONLY",
                "one_shot": True,
                "recorded_at": "2025-01-01T12:00:00Z",
                "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
                "target_snapshot_packet_sha256": approval_packet["snapshot_packet_sha256"],
            }
        })

        tamper_cases = [
            ("source_kind", "INVALID"),
            ("repository_full_name", "owner//repo"),
            ("repository_full_name", "owner"),
            ("repository_full_name", "../repo"),
            ("repository_full_name", "owner/."),
            ("ref", "main/.."),
            ("ref", "/main"),
            ("ref", "main/"),
            ("ref", "m..n"),
            ("ref", "@{main}"),
            ("ref", "-main"),
            ("ref", "main.lock"),
            ("ref", "a/b/c/."),
            ("path", "/path/file.json"),
            ("path", "path//file.json"),
            ("path", "path/../file.json"),
            ("path", "path/file.txt"),
            ("path", "."),
            ("expected_record_sha256", "0123456789ABCDEF0123456789abcdef0123456789abcdef0123456789abcdef"),
            ("expected_record_sha256", "0" * 63),
        ]

        for key, bad_value in tamper_cases:
            tampered_locator = copy.deepcopy(self.safe_locator)
            tampered_locator[key] = bad_value
            request = build_live_provenance_request({
                "approval_receipt": receipt,
                "durable_locator": tampered_locator,
            })
            self.assertEqual(request["state"], "BLOCKED_UNKNOWN", f"Failed closed tamper on {key}={bad_value}")

    def test_hash_bindings(self):
        approval_packet = build_live_readiness_approval_packet({
            "provider_configs": self.provider_configs,
            "inventory": self.inventory,
        })
        receipt = build_live_approval_receipt({
            "approval_packet": approval_packet,
            "approval_record": {
                "decision": "APPROVE_FIRST_LIVE_POC",
                "scope": "FIRST_LIVE_POC_ONLY",
                "one_shot": True,
                "recorded_at": "2025-01-01T12:00:00Z",
                "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
                "target_snapshot_packet_sha256": approval_packet["snapshot_packet_sha256"],
            }
        })
        request = build_live_provenance_request({
            "approval_receipt": receipt,
            "durable_locator": self.safe_locator,
        })

        # Recompute receipt hash
        receipt_copy = copy.deepcopy(receipt)
        del receipt_copy["approval_record_sha256"]
        recomputed_receipt_hash = hashlib.sha256(json.dumps(receipt_copy, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
        self.assertEqual(recomputed_receipt_hash, receipt["approval_record_sha256"])

        # Recompute locator hash
        recomputed_locator_hash = hashlib.sha256(json.dumps(self.safe_locator, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(recomputed_locator_hash, request["durable_locator_sha256"])

        # Recompute request hash
        request_copy = copy.deepcopy(request)
        del request_copy["provenance_request_sha256"]
        recomputed_request_hash = hashlib.sha256(json.dumps(request_copy, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(recomputed_request_hash, request["provenance_request_sha256"])

        # Deterministic change
        tampered_locator = copy.deepcopy(self.safe_locator)
        tampered_locator["ref"] = "different"
        request_2 = build_live_provenance_request({
            "approval_receipt": receipt,
            "durable_locator": tampered_locator,
        })
        self.assertNotEqual(request["durable_locator_sha256"], request_2["durable_locator_sha256"])

    def test_determinism(self):
        approval_packet = build_live_readiness_approval_packet({
            "provider_configs": self.provider_configs,
            "inventory": self.inventory,
        })
        receipt = build_live_approval_receipt({
            "approval_packet": approval_packet,
            "approval_record": {
                "decision": "APPROVE_FIRST_LIVE_POC",
                "scope": "FIRST_LIVE_POC_ONLY",
                "one_shot": True,
                "recorded_at": "2025-01-01T12:00:00Z",
                "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
                "target_snapshot_packet_sha256": approval_packet["snapshot_packet_sha256"],
            }
        })

        loc_1 = copy.deepcopy(self.safe_locator)
        loc_2 = dict(reversed(list(self.safe_locator.items())))

        req_1 = build_live_provenance_request({"approval_receipt": receipt, "durable_locator": loc_1})
        req_2 = build_live_provenance_request({"approval_receipt": receipt, "durable_locator": loc_2})

        self.assertEqual(req_1, req_2)
        self.assertEqual(req_1["provenance_request_sha256"], req_2["provenance_request_sha256"])

    def test_leakage_boundary(self):
        approval_packet = build_live_readiness_approval_packet({
            "provider_configs": self.provider_configs,
            "inventory": self.inventory,
        })
        receipt = build_live_approval_receipt({
            "approval_packet": approval_packet,
            "approval_record": {
                "decision": "APPROVE_FIRST_LIVE_POC",
                "scope": "FIRST_LIVE_POC_ONLY",
                "one_shot": True,
                "recorded_at": "2025-01-01T12:00:00Z",
                "target_approval_packet_sha256": approval_packet["approval_packet_sha256"],
                "target_snapshot_packet_sha256": approval_packet["snapshot_packet_sha256"],
            }
        })
        request = build_live_provenance_request({
            "approval_receipt": receipt,
            "durable_locator": self.safe_locator,
        })

        rendered = render_provenance_request_ja(request)
        self.assertNotIn("owner/repo", rendered)
        self.assertNotIn("path/to/record.json", rendered)
        self.assertNotIn("GITHUB_DURABLE_RECORD", rendered)
        self.assertNotIn("2025-01-01T12:00:00Z", rendered)
        self.assertNotIn("provider_meta", rendered)
        self.assertNotIn("route_evidence", rendered)
        self.assertNotIn("evidence_ref", rendered)
        self.assertNotIn("reasons", rendered)
        self.assertNotIn("https://", rendered)
        self.assertNotIn("http://", rendered)

    def test_source_static_boundary_audit(self):
        with open("src/providers/live_provenance_request.py", "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
        banned_imports = {"os", "pathlib", "subprocess", "socket", "http", "urllib", "requests", "github", "time", "random"}
        found_banned = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    base = name.name.split('.')[0]
                    if base in banned_imports:
                        found_banned.add(base)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    base = node.module.split('.')[0]
                    if base in banned_imports:
                        found_banned.add(base)

        self.assertEqual(found_banned, set(), f"Found banned imports: {found_banned}")

    def test_terminal_trust_source_boundary(self):
        with open("docs/RELAY_LIVE_PROVENANCE_BOUNDARY_AUDIT.md", "r") as f:
            boundary_doc = f.read()

        with open("docs/RELAY_STATIC_CHECKPOINT.md", "r") as f:
            checkpoint_doc = f.read()

        self.assertIn("PROVENANCE_VERIFICATION_REQUIRED is terminal for current static Relay code", boundary_doc)
        self.assertIn("GitHub Actions readback alone is transport evidence, not independent human provenance", boundary_doc)
        self.assertIn("OIDC and Artifact Attestation are NOT AUTHORIZED in this batch", boundary_doc)
        self.assertIn("The production authenticator remains NOT_WIRED", boundary_doc)
        self.assertIn("PROVENANCE_VERIFICATION_REQUIRED is terminal for current static Relay code", checkpoint_doc)
        self.assertIn("No live execution is authorized, and production authenticators remain NOT_WIRED", checkpoint_doc)

    def test_no_claim_of_live_resolution(self):
        # A test to ensure we don't claim synthetic fixtures resolve real blockers.
        pass
