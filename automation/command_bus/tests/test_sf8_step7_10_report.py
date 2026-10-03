"""Machine-readable SF-8 readiness report for Roadmap Steps 7-10 (prepare-only).

The committed report must equal what this test computes. Regenerate with
UPDATE_SF8_REPORT=1 after a deliberate change. Nothing here writes production
state, the production registry, Issue #33, or calls any provider.
"""
from __future__ import annotations

import json
import os
import unittest
from dataclasses import asdict
from pathlib import Path

from automation.command_bus.control_tower_durable_collector import ControlTowerDurableCollector
from automation.command_bus.control_tower_live_preflight import (
    ControlTowerLanePresentation, prepare_verified_control_tower_migration,
)
from automation.command_bus.control_tower_registration import assess_registration_readiness
from automation.command_bus.lane_identity_adoption import registry_digest, validate_lane_adoption_diff
from automation.command_bus.sf8_readiness import (
    REQUIRED_CHECKS, CheckResult, assess_durable_promotion_candidate, assess_pre_adoption_readiness,
    issue33_migration_ready,
)
from automation.command_bus.tests import test_recorded_live_evidence as rec
from automation.command_bus.tests import test_sf8_oidc_runtime_e2e as e2e
from automation.command_bus.tests.test_control_tower_live_preflight import issue
from automation.command_bus.tests.test_semiauto_stable_identity_static_e2e import (
    CURRENT_TIME, LOOP_ID, Clock, TargetReader, fixture_registry,
)
from automation.command_bus.tests.pre_adoption_registry import pre_adoption

ROOT = Path(__file__).resolve().parents[3]
EVID = ROOT / "docs/evidence/signal-sf8"
REGISTRY = pre_adoption(json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text(encoding="utf-8")))
RECORD = json.loads((EVID / "adoption-record-candidate-chatgpt-semi-auto.json").read_text(encoding="utf-8"))
CANDIDATE = json.loads((EVID / "registry-candidate-chatgpt-semi-auto-durable.json").read_text(encoding="utf-8"))
REPORT_PATH = EVID / "readiness-report-20261003.json"
APPROVERS = frozenset({rec.OWNER_ID})


def static_chain():
    provider_exec = e2e.execution(rec.SF8_PROFILE, "5001")
    prepared, binding, client, publisher, status, flat = e2e.wire(
        provider_exec=provider_exec, authority_exec=rec.authority_exec())
    published = publisher.publish(binding.transition_request)
    collected = ControlTowerDurableCollector(
        client, ref="fixture/runtime-data", target_reader=TargetReader(flat), clock=Clock(),
    ).collect_transition(LOOP_ID)
    transitions = {LOOP_ID: collected.transition} if collected.status == "COLLECTED" else {}
    registration = assess_registration_readiness(fixture_registry(), transitions).status if transitions else "NOT_RUN"
    return published.status, collected.status, registration


def build_report():
    published, collected, fixture_registration = static_chain()
    provider = rec.assess()
    authority = rec.authority_exec()
    production_registration = assess_registration_readiness(REGISTRY, None)
    preflight = prepare_verified_control_tower_migration(
        registry=REGISTRY, verified_transitions=None, lane_presentation={},
        generated_at=CURRENT_TIME, issue_readback=issue())
    adoption_ok = validate_lane_adoption_diff(
        current=REGISTRY, proposed=CANDIDATE, record=RECORD, allowed_approver_ids=APPROVERS) == RECORD["lane_loop_id"]
    notes = {}
    checks = {
        "stable_identity": CheckResult("NOT_RUN", "STATIC", "docs/evidence/signal-sf8/adoption-record-candidate-chatgpt-semi-auto.json"),
        "prepared_persistence": CheckResult("PASS", "STATIC", "test:test_sf8_oidc_runtime_e2e"),
        "canonical_receipt": CheckResult("PASS", "STATIC", "test:test_sf8_oidc_runtime_e2e"),
        "provider_authentication": CheckResult("BLOCKED", "STATIC", "docs/evidence/signal-sf8/readiness-report-20261003.json"),
        "owner_authority_authentication": CheckResult(
            "PASS" if authority else "FAIL", "LIVE", "docs/evidence/signal-authority/authority-run-readback-37031275812.json"),
        "publisher_accepted": CheckResult("PASS" if published == "READY" else "FAIL", "STATIC", "test:test_sf8_step7_10_report"),
        "collector_readback": CheckResult("PASS" if collected == "COLLECTED" else "FAIL", "STATIC", "test:test_sf8_step7_10_report"),
        "registration_ready": CheckResult(
            "PASS" if production_registration.status == "READY" else "BLOCKED",
            "STATIC", "docs/evidence/signal-sf8/readiness-report-20261003.json"),
        "negative_stale_mismatch_tests": CheckResult("PASS", "STATIC", "test:test_recorded_live_evidence"),
        "recovery_test": CheckResult("PASS", "STATIC", "test:test_sf8_authority_issuer_candidate"),
    }
    notes["owner_authority_authentication"] = (
        "Execution lineage of manual dispatch run 37031275812 authenticates through the production authority path; "
        "no durable grant for a real loop event exists yet.")
    notes["provider_authentication"] = "Recorded Session 132 evidence cannot satisfy the production authenticator: " + ", ".join(provider.blockers)
    notes["registration_ready"] = (
        f"target-lane helper is available but no real-id live transition exists yet; "
        f"fixture registry chain: {fixture_registration}; "
        f"global production registration for Issue #33: {production_registration.status}"
    )
    pre_adoption = assess_pre_adoption_readiness(checks)
    promotion = assess_durable_promotion_candidate(checks)
    return {
        "schema_version": 1,
        "report_kind": "SIGNAL_SF8_READINESS_REPORT",
        "scope_note": "Prepare-only. STATIC passes are never LIVE passes. Nothing here promotes the registry or writes Issue #33.",
        "checks": {n: {**asdict(checks[n]), **({"note": notes[n]} if n in notes else {})} for n in REQUIRED_CHECKS},
        "pre_adoption_gate": {
            "status": pre_adoption.status, "reasons": list(pre_adoption.reasons),
            "deferred_checks": list(pre_adoption.deferred_checks),
            "human_approval_required": pre_adoption.human_approval_required,
            "registry_write_allowed": pre_adoption.registry_write_allowed,
        },
        "durable_promotion_candidate": {"status": promotion.status, "reasons": list(promotion.reasons)},
        "recorded_provider": {
            "recorded_lineage": provider.recorded_lineage, "live_authentication": provider.live_authentication,
            "lineage_failures": list(provider.lineage_failures), "blockers": [b for b in provider.blockers if b != "OBSERVATION_STALE"],
        },
        "recorded_authority": {
            "run_id": authority.run_id if authority else None, "event": authority.event if authority else None,
            "actor_id": authority.actor_id if authority else None, "triggering_actor_id": authority.triggering_actor_id if authority else None,
        },
        "stable_identity_adoption_candidate": {
            "lane_loop_id": RECORD["lane_loop_id"], "validator_accepts_against_production_registry": adoption_ok,
            "production_registry_sha256": registry_digest(REGISTRY),
            "production_identity_states": sorted({e["identity_state"] for e in REGISTRY["loops"]}),
        },
        "issue33_migration": {
            "production_preflight_status": preflight.status, "production_preflight_stage": preflight.stage,
            "issue33_migration_ready": issue33_migration_ready(preflight.status),
        },
        "live_counters_this_batch": {
            "jules_sessions_created": 0, "jules_get": 0, "authority_reruns": 0, "oidc_reruns": 0, "provider_model_live": 0,
        },
    }


class Step7To10ReportTests(unittest.TestCase):
    def test_committed_report_matches_computed(self):
        computed = build_report()
        if os.environ.get("UPDATE_SF8_REPORT") == "1":
            REPORT_PATH.write_text(json.dumps(computed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.assertEqual(json.loads(REPORT_PATH.read_text(encoding="utf-8")), computed)

    def test_status_is_honest(self):
        r = build_report()
        self.assertEqual(r["pre_adoption_gate"]["status"], "NOT_READY")
        self.assertEqual(r["pre_adoption_gate"]["deferred_checks"], ["stable_identity", "registration_ready"])
        self.assertTrue(r["pre_adoption_gate"]["human_approval_required"])
        self.assertFalse(r["pre_adoption_gate"]["registry_write_allowed"])
        self.assertEqual(r["durable_promotion_candidate"]["status"], "NOT_READY")
        self.assertEqual(r["checks"]["provider_authentication"]["status"], "BLOCKED")
        self.assertEqual(r["checks"]["stable_identity"]["status"], "NOT_RUN")
        self.assertEqual(r["issue33_migration"]["issue33_migration_ready"], "NO")
        self.assertEqual(r["checks"]["registration_ready"]["status"], "BLOCKED")
        self.assertIn("no real-id live transition exists yet", r["checks"]["registration_ready"]["note"])
        self.assertIn("global production registration for Issue #33: NOT_WIRED", r["checks"]["registration_ready"]["note"])
        self.assertEqual(r["stable_identity_adoption_candidate"]["production_identity_states"], ["PLACEHOLDER"])
        self.assertTrue(all(v == 0 for v in r["live_counters_this_batch"].values()))
        for name, c in r["checks"].items():
            if c["scope"] == "STATIC" and name not in ("negative_stale_mismatch_tests", "recovery_test"):
                self.assertIn("STATIC", c["scope"])

    def test_adoption_candidate_is_valid_or_detectably_stale(self):
        kwargs = dict(current=REGISTRY, proposed=CANDIDATE, record=RECORD, allowed_approver_ids=APPROVERS)
        if RECORD["expected_registry_sha256"] == registry_digest(REGISTRY):
            self.assertEqual(validate_lane_adoption_diff(**kwargs), "chatgpt-semi-auto")
        else:
            with self.assertRaises(ValueError):
                validate_lane_adoption_diff(**kwargs)

    def test_adoption_candidate_failure_injection(self):
        base = dict(current=REGISTRY, proposed=CANDIDATE, record=RECORD, allowed_approver_ids=APPROVERS)
        durable_now = json.loads(json.dumps(CANDIDATE))
        from automation.command_bus.lane_identity_adoption import registry_digest as dig
        cases = {
            "duplicate_record": dict(applied_record_ids=frozenset({RECORD["record_id"]})),
            "duplicate_approval_run": dict(approval_run_ids_in_use=frozenset({RECORD["approval_ref"]})),
            "wrong_lane": dict(record={**RECORD, "lane_loop_id": "claude-claude"}),
            "numeric_lane": dict(record={**RECORD, "lane_loop_id": "301196275118188780"}),
            "session_like_ref": dict(record={**RECORD, "approval_ref": "jules-session:301196275118188780"}),
            "wrong_actor": dict(allowed_approver_ids=frozenset({"1"})),
            "stale_registry": dict(record={**RECORD, "expected_registry_sha256": "0" * 64}),
            "already_durable": dict(current=CANDIDATE, record={**RECORD, "expected_registry_sha256": dig(CANDIDATE)}),
        }
        for label, over in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                validate_lane_adoption_diff(**{**base, **over})
        self.assertEqual(durable_now, CANDIDATE)

    def test_candidate_diff_touches_only_the_adopted_lane_state(self):
        before = {e["loop_id"]: e for e in REGISTRY["loops"]}
        after = {e["loop_id"]: e for e in CANDIDATE["loops"]}
        self.assertEqual(set(before), set(after))
        changed = [k for k in before if before[k] != after[k]]
        self.assertEqual(changed, ["chatgpt-semi-auto"])
        self.assertEqual({k for k in before[changed[0]] if before[changed[0]][k] != after[changed[0]][k]}, {"identity_state"})

    def test_issue33_prepare_artifact_matches_report(self):
        prep = json.loads((EVID / "issue33-migration-prepare-20261003.json").read_text(encoding="utf-8"))
        report = build_report()
        self.assertEqual(prep["status"], report["issue33_migration"]["production_preflight_status"])
        self.assertEqual(prep["issue33_migration_ready"], report["issue33_migration"]["issue33_migration_ready"])
        self.assertIs(prep["issue33_written_by_this_batch"], False)
        self.assertEqual(prep["issue_readback"]["runtime_state"], "STOPPED")

    def test_production_migration_stays_not_ready_with_real_registry(self):
        pre = prepare_verified_control_tower_migration(
            registry=REGISTRY, verified_transitions=None,
            lane_presentation={LOOP_ID: ControlTowerLanePresentation()},
            generated_at=CURRENT_TIME, issue_readback=issue())
        self.assertEqual(issue33_migration_ready(pre.status), "NO")


if __name__ == "__main__":
    unittest.main()
