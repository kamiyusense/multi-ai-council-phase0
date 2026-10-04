"""Static checks over the recorded Step 7 proof 5 result and its DURABLE adoption candidate.

Reads only committed files. No network, no provider call, no registry write. The adoption itself
(flipping the production registry) is a separate human-approved change; these tests prove the
candidate is bound to the exact current registry and that the recorded evidence supports the gate.
"""
from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

from automation.command_bus import signal_step7_live_proof as live
from automation.command_bus.control_tower_registration import assess_registration_readiness
from automation.command_bus import durable_adoption_approval as dap
from automation.command_bus.lane_identity_adoption import registry_digest
from automation.command_bus.sf8_readiness import CheckResult, assess_pre_adoption_readiness

ROOT = Path(__file__).resolve().parents[3]
P5 = ROOT / "docs/evidence/signal-step7-proof5"
SF8 = ROOT / "docs/evidence/signal-sf8"
LANE = "chatgpt-semi-auto"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def pre_adoption_production():
    """The registry as it was before the adoption: the committed candidate with the lane at PLACEHOLDER.

    Reached only through the production guard, so the live file must still carry the approved DURABLE row.
    """
    from automation.command_bus.tests.pre_adoption_registry import pre_adoption
    return pre_adoption(load(ROOT / "automation/command_bus/config/control_tower_registry.json"))


RECEIPT = load(P5 / "live-terminal-receipt.json")
EVIDENCE = load(P5 / "live-proof-evidence.json")
MARKER = load(P5 / "live-attempt-marker.json")
PLAN = load(P5 / "plan.bound.json")
READBACK = load(P5 / "jules-output-github-readback.json")
CANDIDATE = load(P5 / "adoption-candidate.json")
CANDIDATE_REGISTRY = load(SF8 / "registry-candidate-chatgpt-semi-auto-durable.json")
LEGACY_RECORD = load(SF8 / "adoption-record-candidate-chatgpt-semi-auto.json")
ACTIVE_RAW = {"QUEUED", "PLANNING", "IN_PROGRESS", "RUNNING"}


class RecordedProofResultTests(unittest.TestCase):
    def test_terminal_receipt_is_complete_and_closes_the_proof(self):
        self.assertEqual((RECEIPT["status"], RECEIPT["code"]), ("COMPLETE", "NONE"))
        self.assertIs(RECEIPT["rerun_allowed"], False)
        self.assertIs(RECEIPT["additional_jules_get_allowed"], False)
        self.assertIs(RECEIPT["additional_jules_post_allowed"], False)
        self.assertEqual(RECEIPT["lane_id"], LANE)
        self.assertEqual(RECEIPT["evidence_payload_sha256"], EVIDENCE["evidence_payload_sha256"])

    def test_budget_was_exactly_one_post_two_gets_and_no_retry(self):
        total = EVIDENCE["counters"]["whole_proof_total"]
        self.assertEqual(total, {"authority_dispatch": 0, "jules_get": 2, "jules_post": 1})
        self.assertEqual(EVIDENCE["counters"]["carrier_share"], {"jules_get": 1, "jules_post": 1})
        self.assertEqual(EVIDENCE["counters"]["this_half"]["jules_get"], 1)
        self.assertEqual(EVIDENCE["counters"]["this_half"]["jules_post"], 0)
        self.assertEqual(EVIDENCE["counters"]["limits"], live.LIMITS)
        self.assertEqual((EVIDENCE["retry"], EVIDENCE["fallback"]), (0, "disabled"))

    def test_provider_was_active_at_the_one_fresh_read(self):
        self.assertIn(EVIDENCE["provider_raw_state"], ACTIVE_RAW)
        self.assertEqual(EVIDENCE["canonical_runtime_state"], "RUNNING")
        self.assertEqual(EVIDENCE["scope"], "LIVE")

    def test_identity_chain_is_exact(self):
        self.assertEqual(EVIDENCE["lane_id"], LANE)
        self.assertEqual(MARKER["lane_id"], LANE)
        self.assertEqual(MARKER["session_id"], EVIDENCE["session_id"])
        self.assertEqual(MARKER["authority_run_id"], EVIDENCE["authority_run_id"])
        self.assertNotIn(EVIDENCE["session_id"], live.FORBIDDEN_SESSION_IDS)
        self.assertNotIn(EVIDENCE["authority_run_id"], live.RESERVED_AUTHORITY_RUNS)
        self.assertNotEqual(EVIDENCE["authority_run_id"], live.PROVIDER_OIDC_RUN_ID)
        self.assertEqual(EVIDENCE["starting_branch"], PLAN["work_branch"])
        self.assertEqual(EVIDENCE["target_head"], PLAN["expected_target_head"])
        self.assertEqual(EVIDENCE["target_tree"], PLAN["expected_target_tree"])

    def test_nothing_production_was_written_by_the_proof(self):
        self.assertIs(EVIDENCE["production_registry_written"], False)
        self.assertIs(EVIDENCE["issue33_written"], False)
        self.assertIs(EVIDENCE["merged"], False)

    def test_bound_plan_is_valid_and_matches_the_recorded_digest(self):
        live.validate_plan(PLAN, CANDIDATE_REGISTRY, require_bound=True)
        self.assertEqual(live.plan_digest(PLAN), CANDIDATE["proof"]["plan_sha256"])
        self.assertEqual(PLAN["request"]["command_id"], "relay-dev-loop-136-signal-active-proof-5")

    def test_evidence_directory_holds_no_secret_material(self):
        pattern = re.compile(r"(?i)(api[_-]?key|authorization|bearer\s+[a-z0-9]|ghp_|ghs_|AIza|-----BEGIN)")
        for path in P5.glob("*.json"):
            self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), path.name)


class OutputReadbackTests(unittest.TestCase):
    def test_recorded_assessment_equals_a_fresh_computation(self):
        reasons = live.assess_output_readback(READBACK["output"], evidence=EVIDENCE)
        self.assertEqual(list(reasons), READBACK["assessment_reasons"])

    def test_the_recorded_deviation_is_only_the_missing_trailing_newline(self):
        self.assertEqual(READBACK["assessment"], "DEVIATION")
        self.assertEqual(READBACK["assessment_reasons"], ["proof content is not the exact allowed content"])
        self.assertEqual(READBACK["output"]["changed_files"], [live.ALLOWED_PATH])
        self.assertEqual(READBACK["output"]["changed_file_content"] + "\n", live.ALLOWED_CONTENT)
        self.assertEqual((READBACK["output_blob_bytes"], READBACK["expected_content_bytes"]), (21, 22))
        self.assertIs(READBACK["output"]["merged"], False)

    def test_assessment_logic_is_not_loosened_and_accepts_the_exact_output(self):
        exact = copy.deepcopy(READBACK["output"])
        exact["changed_file_content"] = live.ALLOWED_CONTENT
        self.assertEqual(live.assess_output_readback(exact, evidence=EVIDENCE), ())
        extra = copy.deepcopy(exact)
        extra["changed_files"] = [live.ALLOWED_PATH, "README.md"]
        self.assertIn("unexpected changed paths", live.assess_output_readback(extra, evidence=EVIDENCE))
        merged = copy.deepcopy(exact)
        merged["merged"] = True
        self.assertIn("output pull request is merged", live.assess_output_readback(merged, evidence=EVIDENCE))


class AdoptionCandidateTests(unittest.TestCase):
    def checks(self):
        ref = "docs/evidence/signal-step7-proof5/live-proof-evidence.json"
        live_names = ("prepared_persistence", "canonical_receipt", "provider_authentication",
                      "owner_authority_authentication", "publisher_accepted", "collector_readback")
        out = {name: CheckResult("PASS", "LIVE", ref) for name in live_names}
        for name in ("negative_stale_mismatch_tests", "recovery_test"):
            out[name] = CheckResult("PASS", "STATIC", "automation/command_bus/tests/test_signal_step7_auto_publish.py")
        return out

    def test_pre_adoption_gate_is_ready_for_human_approval_only(self):
        result = assess_pre_adoption_readiness(self.checks())
        self.assertEqual(result.status, "READY_FOR_HUMAN_APPROVAL")
        self.assertIs(result.registry_write_allowed, False)
        self.assertIs(result.human_approval_required, True)
        self.assertEqual(EVIDENCE["pre_adoption_gate"]["status"], "READY_FOR_HUMAN_APPROVAL")
        self.assertIs(EVIDENCE["pre_adoption_gate"]["registry_write_allowed"], False)

    def test_gate_fails_closed_when_a_live_check_is_missing_or_static(self):
        broken = self.checks()
        broken["provider_authentication"] = CheckResult("PASS", "STATIC", broken["provider_authentication"].evidence_ref)
        self.assertEqual(assess_pre_adoption_readiness(broken).status, "NOT_READY")
        del broken["collector_readback"]
        self.assertEqual(assess_pre_adoption_readiness(broken).status, "NOT_READY")

    def test_candidate_is_bound_to_the_exact_current_registry_digest(self):
        current = pre_adoption_production()
        self.assertEqual(CANDIDATE["current_registry_digest_sha256"], registry_digest(current))

    def test_candidate_diff_touches_only_the_adopted_lane(self):
        current = pre_adoption_production()
        dap.check_single_lane_diff(current, CANDIDATE_REGISTRY, LANE)
        before = {e["loop_id"]: e for e in current["loops"]}
        after = {e["loop_id"]: e for e in CANDIDATE_REGISTRY["loops"]}
        self.assertEqual(set(before), set(after))
        changed = [k for k in before if before[k] != after[k]]
        self.assertEqual(changed, [LANE])
        self.assertEqual(after[LANE]["identity_state"], "DURABLE")

    def test_legacy_record_is_not_an_adoption_approval(self):
        # the old record cites an authority (identity) run; it is marked superseded and never counts
        self.assertEqual(CANDIDATE["legacy_adoption_record"]["status"], "SUPERSEDED_NOT_AN_APPROVAL")
        self.assertIsNone(CANDIDATE["adoption_approval_ref"])
        self.assertIsNone(CANDIDATE["adoption_record_ref"])
        self.assertEqual(CANDIDATE["adoption_approval_kind_required"], dap.APPROVAL_KIND)
        run_id = LEGACY_RECORD["approval_ref"].rsplit("/", 1)[-1]
        self.assertIn(run_id, dap.KNOWN_AUTHORITY_RUN_IDS)

    def test_deviation_is_recorded_not_hidden(self):
        self.assertEqual(READBACK["deviation_type"], "MISSING_TRAILING_NEWLINE_ONLY")
        self.assertEqual(CANDIDATE["jules_output"]["deviation_type"], READBACK["deviation_type"])
        self.assertEqual(dap.classify_output(READBACK["output"], EVIDENCE),
                         (dap.OUTPUT_DEVIATION, dap.DEVIATION_MISSING_NEWLINE))

    def test_global_registration_stays_not_wired_with_three_placeholder_lanes(self):
        result = assess_registration_readiness(CANDIDATE_REGISTRY, None)
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(result.placeholder_loop_ids, ("claude-gemini", "claude-claude", "work-gemini"))

    def test_candidate_document_never_allows_a_write(self):
        self.assertEqual(CANDIDATE["status"], "PENDING_HUMAN_APPROVAL")
        self.assertIs(CANDIDATE["registry_write_allowed"], False)
        self.assertIs(CANDIDATE["human_approval_required"], True)
        self.assertIs(CANDIDATE["production_registry_changed_by_this_candidate"], False)
        self.assertIs(CANDIDATE["issue33_changed_by_this_candidate"], False)
        self.assertEqual(CANDIDATE["jules_output"]["assessment"], READBACK["assessment"])
        self.assertEqual(CANDIDATE["proof"]["session_id"], EVIDENCE["session_id"])
        self.assertEqual((CANDIDATE["retry"], CANDIDATE["fallback"]), (0, "disabled"))


if __name__ == "__main__":
    unittest.main()
