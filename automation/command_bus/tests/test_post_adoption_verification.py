"""STATIC tests of the post-adoption verification of chatgpt-semi-auto, rollback preparation and the mixed registry.

Reads committed files only. No network, no provider call, no workflow dispatch, no registry or Issue write.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from automation.command_bus import post_adoption_verification as pav
from automation.command_bus.lane_identity_adoption import registry_digest
from automation.command_bus.control_tower import build_control_tower, render_control_tower
from automation.command_bus.control_tower_durable_collector import ControlTowerDurableCollector
from automation.command_bus.control_tower_live_preflight import prepare_verified_control_tower_migration
from automation.command_bus.control_tower_registration import (
    assess_lane_registration_readiness, assess_registration_readiness)
from automation.command_bus.control_tower_snapshot import parse_control_tower_snapshot_json
from automation.command_bus.control_tower_verified_input import control_tower_input_from_transition
from automation.command_bus.lane_identity_adoption import registry_digest
from automation.command_bus.sf8_readiness import issue33_migration_ready
from automation.command_bus.tests.pre_adoption_registry import pre_adoption

ROOT = Path(__file__).resolve().parents[3]
SF10 = ROOT / "docs/evidence/signal-sf10"
LANE = "chatgpt-semi-auto"
CHECKPOINT = json.loads((SF10 / "post-adoption-checkpoint.json").read_text(encoding="utf-8"))
FRESH = json.loads((SF10 / "fresh-github-readback.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((ROOT / pav.cli.REGISTRY_PATH).read_text(encoding="utf-8"))


def scratch_root() -> Path:
    tmp = Path(tempfile.mkdtemp())
    for rel in ("docs/evidence/signal-step7-proof5", "docs/evidence/signal-sf8", "automation/command_bus/config"):
        shutil.copytree(ROOT / rel, tmp / rel)
    for ref in pav.STATIC_TEST_REFS.values():
        (tmp / ref).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / ref, tmp / ref)
    return tmp


def edit(root: Path, rel: str, mutate) -> None:
    path = root / rel
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def failed_with(root: Path, fresh=None) -> set[str]:
    return set(pav.verify(root, fresh or FRESH, CHECKPOINT["now"])["failed_items"])


class CheckpointTests(unittest.TestCase):
    def test_committed_checkpoint_is_exactly_what_the_verifier_computes(self):
        # The sealed 2026-10-04 checkpoint is hash-pinned and names the lane-4 row by its old id; the registry row
        # was renamed on 2026-10-14 (work-jules-auto -> symphony-codex-auto), so map that one id back before comparing.
        # The two registry-digest items also change with the renamed row; they are mapped back to the sealed values.
        raw = json.dumps(pav.verify(ROOT, FRESH, CHECKPOINT["now"])).replace("symphony-codex-auto", "work-jules-auto")
        new_digest = registry_digest(json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text(encoding="utf-8")))
        old_digest = CHECKPOINT["items"][0]["detail"].split()[-1]
        self.assertEqual(raw.count(new_digest), 2)
        self.assertEqual(json.loads(raw.replace(new_digest, old_digest)), CHECKPOINT)

    def test_all_25_items_pass_and_the_strict_gate_is_ready(self):
        self.assertEqual(CHECKPOINT["status"], "PASS")
        self.assertEqual([i["n"] for i in CHECKPOINT["items"]], list(range(1, 26)))
        self.assertEqual(CHECKPOINT["failed_items"], [])
        self.assertEqual(CHECKPOINT["strict_gate"], "READY")
        self.assertEqual(set(CHECKPOINT["required_checks"]), set(pav.REQUIRED_CHECKS))
        for name, check in CHECKPOINT["required_checks"].items():
            self.assertEqual(check["status"], "PASS", name)
            self.assertEqual(check["scope"], "STATIC" if name in {"negative_stale_mismatch_tests", "recovery_test"} else "LIVE")

    def test_safety_counters_are_zero_and_nothing_is_written(self):
        safety = CHECKPOINT["safety"]
        self.assertEqual((safety["new_jules_post"], safety["new_jules_get"], safety["provider_calls"],
                          safety["workflow_dispatch"], safety["retry"]), (0, 0, 0, 0, 0))
        self.assertIs(safety["registry_written"], False)
        self.assertIs(safety["issue33_written"], False)

    def test_lane_registration_is_ready_for_the_real_lane_and_projection_expiry_is_recorded(self):
        self.assertEqual(CHECKPOINT["lane_registration"], {"as_of_proof": "READY", "at_now": "READY"})
        projection = CHECKPOINT["durable_projection"]
        self.assertEqual(projection["as_of_proof"], {"display_state": "SEMI_AUTO", "transition": "VALID"})
        self.assertEqual(projection["at_now"]["display_state"], "BLOCKED")
        self.assertIn("lease is expired", projection["at_now"]["reason"])

    def test_global_registration_and_issue33_migration_stay_closed(self):
        self.assertEqual(CHECKPOINT["global_registration"], "NOT_WIRED")
        self.assertEqual(CHECKPOINT["issue33_migration_ready"], "NO")
        self.assertEqual(issue33_migration_ready("NOT_WIRED"), "NO")

    def test_fresh_facts_name_the_unmerged_output_and_the_stopped_issue(self):
        self.assertIs(FRESH["pr286"]["merged"], False)
        self.assertIs(FRESH["pr278"]["merged"], False)
        self.assertTrue(FRESH["issue33"]["title_has_stopped"])
        self.assertTrue(FRESH["issue33"]["owner_none"])


class TamperTests(unittest.TestCase):
    """Each stale, wrong or tampered input must make verification fail closed."""

    def setUp(self):
        self.root = scratch_root()
        self.addCleanup(shutil.rmtree, self.root, True)

    def approval(self, mutate):
        edit(self.root, pav.APPROVAL, mutate)

    def test_untouched_scratch_copy_passes(self):
        self.assertEqual(failed_with(self.root), set())

    def test_missing_approval_record_fails_closed(self):
        (self.root / pav.APPROVAL).unlink()
        with self.assertRaises(OSError):
            failed_with(self.root)

    def test_wrong_actor_wrong_run_and_authority_run_substitution(self):
        self.approval(lambda d: d.update(approved_by_actor_id="1"))
        self.assertIn("committed_adoption_approval_valid", failed_with(self.root))
        self.setUp()
        self.approval(lambda d: d.update(approval_ref="github-actions:run/999", approval_id=f"adopt-durable-{LANE}-999"))
        self.assertIn("approval_run_id", failed_with(self.root))
        self.setUp()
        self.approval(lambda d: d.update(approval_ref="github-actions:run/37150285702", approval_id=f"adopt-durable-{LANE}-37150285702"))
        self.assertIn("committed_adoption_approval_valid", failed_with(self.root))

    def test_wrong_lane_proof_transition_and_deviation_ack(self):
        for field, value in (("lane_id", "claude-jules-auto"), ("proof_task_id", "signal-active-proof-4"),
                             ("transition", "DURABLE->PLACEHOLDER"), ("accepted_deviation", None)):
            self.setUp()
            self.approval(lambda d, f=field, v=value: d.update({f: v}))
            self.assertIn("committed_adoption_approval_valid", failed_with(self.root), field)

    def test_receipt_and_evidence_digests_must_match(self):
        self.approval(lambda d: d.update(terminal_receipt_sha256="0" * 64))
        self.assertTrue({"committed_adoption_approval_valid", "proof5_terminal_receipt_digest"} <= failed_with(self.root))
        self.setUp()
        self.approval(lambda d: d.update(evidence_payload_sha256="1" * 64))
        self.assertTrue({"committed_adoption_approval_valid", "proof5_evidence_digest"} <= failed_with(self.root))

    def test_stale_current_and_wrong_proposed_registry_digests(self):
        self.approval(lambda d: d.update(current_registry_sha256="2" * 64))
        self.assertIn("approved_current_registry_digest", failed_with(self.root))
        self.setUp()
        self.approval(lambda d: d.update(proposed_registry_sha256="3" * 64))
        self.assertIn("approved_proposed_registry_digest", failed_with(self.root))

    def test_second_durable_lane_and_unrelated_changes_after_approval(self):
        def second(reg):
            reg["loops"][1]["identity_state"] = "DURABLE"
        edit(self.root, pav.cli.REGISTRY_PATH, second)
        self.assertTrue({"exactly_one_durable_lane", "adopted_row_equals_approved_entry_except_display_name"} <= failed_with(self.root))
        for field, value in (("display_order", 99), ("safe_detail_ref", "issue:34"), ("enabled", False),
                             ("mode", "AUTO"), ("controller_kind", "CLAUDE"), ("worker_kind", "WORK"),
                             ("loop_id", "chatgpt-semi-auto-x"), ("identity_state", "PLACEHOLDER")):
            self.setUp()
            edit(self.root, pav.cli.REGISTRY_PATH, lambda reg, f=field, v=value: reg["loops"][0].update({f: v}))
            self.assertTrue({"adopted_row_equals_approved_entry_except_display_name", "durable_lane_is_chatgpt_semi_auto"}
                            & failed_with(self.root), field)
        self.setUp()  # only the display name may change
        edit(self.root, pav.cli.REGISTRY_PATH, lambda reg: reg["loops"][0].update(display_name="Chat to Jules"))
        self.assertNotIn("adopted_row_equals_approved_entry_except_display_name", failed_with(self.root))

    def test_registry_back_at_placeholder_is_not_adopted(self):
        edit(self.root, pav.cli.REGISTRY_PATH, lambda reg: reg["loops"][0].update(identity_state="PLACEHOLDER"))
        self.assertTrue({"exactly_one_durable_lane", "durable_lane_is_chatgpt_semi_auto"} <= failed_with(self.root))

    def test_jules_output_fact_changes_are_caught(self):
        merged = copy.deepcopy(FRESH)
        merged["pr286"]["merged"] = True
        self.assertIn("jules_output_pr_286_unmerged_unchanged", failed_with(self.root, merged))
        moved = copy.deepcopy(FRESH)
        moved["pr286"]["head_sha"] = "a" * 40
        self.assertIn("jules_output_pr_286_unmerged_unchanged", failed_with(self.root, moved))
        edit(self.root, f"{pav.P5}/jules-output-github-readback.json",
             lambda d: d["output"].update(changed_file_content=d["output"]["changed_file_content"] + "\n"))
        self.assertIn("recorded_deviation_unchanged", failed_with(self.root))

    def test_issue33_and_target_changes_are_caught(self):
        changed = copy.deepcopy(FRESH)
        changed["issue33"]["updated_at"] = "2026-10-03T22:00:00Z"
        self.assertIn("issue33_unchanged", failed_with(self.root, changed))
        running = copy.deepcopy(FRESH)
        running["issue33"]["title_has_stopped"] = False
        self.assertIn("issue33_unchanged", failed_with(self.root, running))
        moved = copy.deepcopy(FRESH)
        moved["pr278"]["head_sha"] = "b" * 40
        self.assertTrue({"proof5_target_head_tree", "collector_result"} <= failed_with(self.root, moved))

    def test_wrong_collector_result_when_the_durable_chain_is_tampered(self):
        edit(self.root, f"{pav.CHAIN}/automation/command_bus/state/{LANE}.json", lambda d: d.update(state="STOPPED"))
        failed = failed_with(self.root)
        self.assertTrue({"collector_result", "runtime_transition_published"} & failed)
        self.assertIn("strict_sf8_post_adoption_gate", failed)

    def test_approval_run_that_is_not_a_clean_first_attempt_is_caught(self):
        rerun = copy.deepcopy(FRESH)
        rerun["approval_run"]["run_attempt"] = 2
        self.assertIn("approval_attempt_one", failed_with(self.root, rerun))
        other = copy.deepcopy(FRESH)
        other["approval_run"]["triggering_actor_id"] = "1"
        self.assertIn("approval_actor_and_triggering_actor", failed_with(self.root, other))


class MixedRegistryTests(unittest.TestCase):
    def collect(self, now):
        return pav._collect(ROOT, FRESH, now)

    def test_collect_registry_is_not_wired_while_three_lanes_are_placeholder(self):
        collector = ControlTowerDurableCollector(
            pav._DirClient(ROOT), ref="committed", target_reader=pav._Target(FRESH["pr278"], pav.live.REPOSITORY),
            clock=pav._Clock("2026-10-03T22:22:30+00:00"))
        inventory = collector.collect_registry(REGISTRY)
        self.assertEqual(inventory.status, "NOT_WIRED")
        self.assertIn("chat-work-semi-auto", inventory.reason)

    def test_global_registration_is_not_wired_even_with_the_real_durable_transition(self):
        transition = self.collect("2026-10-03T22:22:30+00:00").transition
        result = assess_registration_readiness(REGISTRY, {LANE: transition})
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(result.placeholder_loop_ids, ("chat-work-semi-auto", "claude-jules-auto", "symphony-codex-auto"))
        self.assertEqual(assess_lane_registration_readiness(REGISTRY, LANE, transition).status, "READY")
        for other in ("chat-work-semi-auto", "claude-jules-auto", "symphony-codex-auto"):
            self.assertEqual(assess_lane_registration_readiness(REGISTRY, other, transition).status, "NOT_WIRED")

    def test_mixed_render_keeps_the_durable_lane_and_never_guesses_the_placeholders(self):
        transition = self.collect("2026-10-03T20:09:35+00:00").transition
        lane_input = control_tower_input_from_transition(transition, target_ref="pr:278")
        model = build_control_tower(REGISTRY, {LANE: lane_input}, generated_at="2026-10-03T20:10:00Z")
        by_id = {lane.loop_id: lane for lane in model.lanes}
        self.assertEqual((by_id[LANE].display_state, by_id[LANE].identity_state), ("SEMI_AUTO", "DURABLE"))
        for other in ("chat-work-semi-auto", "claude-jules-auto", "symphony-codex-auto"):
            self.assertEqual((by_id[other].display_state, by_id[other].identity_state), ("UNKNOWN", "PLACEHOLDER"))
            self.assertNotIn(by_id[other].display_state, {"STOPPED", "IDLE", "RUNNING"})
        snapshot = parse_control_tower_snapshot_json(render_control_tower(model).snapshot_json)
        self.assertEqual([loop["identity_state"] for loop in snapshot["loops"]], ["DURABLE", "PLACEHOLDER", "PLACEHOLDER", "PLACEHOLDER"])

    def test_broken_other_lane_does_not_erase_the_healthy_lane(self):
        transition = self.collect("2026-10-03T20:09:35+00:00").transition
        lane_input = control_tower_input_from_transition(transition, target_ref="pr:278")
        model = build_control_tower(REGISTRY, {LANE: lane_input, "claude-jules-auto": object()}, generated_at="2026-10-03T20:10:00Z")
        by_id = {lane.loop_id: lane for lane in model.lanes}
        self.assertEqual(by_id[LANE].display_state, "SEMI_AUTO")
        self.assertEqual(by_id["claude-jules-auto"].display_state, "UNKNOWN")

    def test_issue33_migration_preflight_is_not_wired_and_prepares_no_issue_plan(self):
        from automation.command_bus.control_tower import (
            DEVELOPMENT_END, DEVELOPMENT_START, RUNTIME_END, RUNTIME_START)
        transition = self.collect("2026-10-03T22:22:30+00:00").transition
        issue = {"number": 33, "state": "open", "title": "🚦 Phase 0 Loop Status — ⚫ STOPPED",
                 "body": f"{RUNTIME_START}\n# ⚫ Runtime: STOPPED\n{RUNTIME_END}\n\n{DEVELOPMENT_START}\n- Relay\n{DEVELOPMENT_END}\n"}
        result = prepare_verified_control_tower_migration(
            registry=REGISTRY, verified_transitions={LANE: transition}, lane_presentation={},
            generated_at="2026-10-03T22:22:30+00:00", issue_readback=issue)
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "registration"))
        self.assertIsNone(result.model)
        self.assertIsNone(result.issue_plan)


class RollbackPrepareOnlyTests(unittest.TestCase):
    """The rollback candidate is prepared and tested, never applied."""

    DIFF = (SF10 / "rollback-candidate-registry.diff").read_text(encoding="utf-8")

    def rolled_back(self):
        text = (ROOT / pav.cli.REGISTRY_PATH).read_text(encoding="utf-8")
        self.assertEqual(text.count('"identity_state": "DURABLE"'), 1)
        return text.replace('"identity_state": "DURABLE"', '"identity_state": "PLACEHOLDER"')

    def test_diff_is_one_line_in_the_registry_only(self):
        self.assertEqual(re.findall(r"^diff --git a/(\S+)", self.DIFF, re.M), [pav.cli.REGISTRY_PATH])
        body = [l for l in self.DIFF.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        self.assertEqual(body, ['-      "identity_state": "DURABLE"', '+      "identity_state": "PLACEHOLDER"'])

    def test_rollback_result_is_the_exact_pre_adoption_registry(self):
        restored = json.loads(self.rolled_back())
        # five-row registry: the revert only flips the one adopted row, nothing else moves
        self.assertEqual([l["identity_state"] for l in restored["loops"]],
                         ["PLACEHOLDER", "PLACEHOLDER", "PLACEHOLDER", "PLACEHOLDER", "FROZEN"])
        self.assertEqual({k: v for k, v in restored["loops"][0].items() if k != "identity_state"},
                         {k: v for k, v in REGISTRY["loops"][0].items() if k != "identity_state"})
        self.assertEqual(restored["loops"][1:], REGISTRY["loops"][1:])
        self.assertEqual(pav.PRE_ADOPTION_DIGEST, CHECKPOINT["items"][10]["detail"])

    def test_after_rollback_global_and_lane_are_not_wired(self):
        restored = json.loads(self.rolled_back())
        transition = pav._collect(ROOT, FRESH, "2026-10-03T22:22:30+00:00").transition
        self.assertEqual(assess_registration_readiness(restored, {LANE: transition}).status, "NOT_WIRED")
        self.assertEqual(assess_lane_registration_readiness(restored, LANE, transition).status, "NOT_WIRED")

    def test_approval_and_evidence_are_kept_append_only(self):
        for rel in (pav.APPROVAL, f"{pav.P5}/live-terminal-receipt.json", f"{pav.P5}/live-proof-evidence.json",
                    f"{pav.CHAIN}/automation/command_bus/state/{LANE}.json"):
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertNotIn("durable-adoption-approval", self.DIFF)

    def test_issue33_is_not_part_of_the_rollback(self):
        self.assertNotIn("issue", self.DIFF.replace("issue:33", ""))
        self.assertTrue(FRESH["issue33"]["title_has_stopped"])


if __name__ == "__main__":
    unittest.main()
