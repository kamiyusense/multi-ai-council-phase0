import copy
import json
import unittest
from dataclasses import replace
from datetime import timedelta

from automation.command_bus.blue_work_reconcile_prepare import assess_cloud_review
from automation.command_bus.cloud_work_lanes import LANES, lane_identity
from automation.command_bus.jules_result_lineage import verify_result_lineage
from automation.command_bus.next_jules_prepare import NextTaskPlan, prepare_next_jules, recheck_next_jules, used_loop_numbers
from automation.command_bus.work_closed_loop_prepare import prepare_static_cycle
from .closed_loop_fixtures import snapshot, NOW, PROMPT, HEAD, BASE, TREE


class ClosedLoopTests(unittest.TestCase):
    def run_cycle(self, inputs=None):
        return prepare_static_cycle(snapshot() if inputs is None else inputs, now=NOW)

    def test_formal_cycle_four_lanes_never_sends_reserves_or_adopts(self):
        for lane in LANES:
            with self.subTest(lane=lane):
                result = self.run_cycle(snapshot(lane))
                self.assertEqual(result["status"], "PREPARED")
                self.assertEqual(result["lineage"]["status"], "VERIFIED_SNAPSHOT")
                self.assertEqual(result["review"]["decision"], "PASS")
                plan = result["next_task"]
                self.assertEqual(plan["claim"]["schema_version"], 3)
                self.assertEqual(plan["claim"]["lane_id"], lane_identity(lane)["jules_lane"])
                self.assertEqual(plan["claim"]["loop_number"], 901)
                self.assertEqual(plan["command"]["work_branch"], "jules-work/relay-dev-loop-901-mock-next")
                self.assertEqual(plan["reservation_state"], "NOT_RESERVED")
                for key in ("external_send_attempted", "model_executed", "adoption_performed", "claim_reserved"):
                    self.assertIs(result[key], False)
                self.assertIs(plan["external_write_attempted"], False)

    def test_no_independent_review_does_not_prepare_next_task(self):
        result = self.run_cycle(snapshot(with_review=False))
        self.assertEqual(result["wake"]["status"], "PREPARED")
        self.assertEqual(result["review"]["status"], "NOT_EXECUTED")
        self.assertNotIn("next_task", result)

    def test_nonpass_reviews_do_not_prepare_corrective_task(self):
        for decision in ("FAIL", "BLOCKED", "UNKNOWN"):
            result = self.run_cycle(snapshot(decision=decision))
            self.assertEqual(result["status"], "BLOCKED")
            self.assertNotIn("next_task", result)

    def test_no_next_useful_task_completes_finite_cycle(self):
        x = snapshot()
        x["review"]["records"]["responses"][0]["next_command_proposal"] = None
        result = self.run_cycle(x)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertNotIn("next_task", result)

    def test_replay_is_deterministic_and_does_not_mutate_input(self):
        x = snapshot()
        before = copy.deepcopy(x)
        self.assertEqual(self.run_cycle(x), self.run_cycle(x))
        self.assertEqual(x, before)

    def test_consumed_review_recovers_without_second_next_task(self):
        x = snapshot()
        first = self.run_cycle(x)
        x["review"]["records"] = first["review"]["recovered_records"]
        second = self.run_cycle(json.loads(json.dumps(x)))
        self.assertEqual(second["status"], "NO_OP")
        self.assertNotIn("next_task", second)

    def test_implementation_identity_cannot_review_itself(self):
        x = snapshot()
        x["review"]["implementer_id"] = "mock-independent-work"
        self.assertEqual(self.run_cycle(x)["status"], "BLOCKED")

    def test_result_head_tree_exact_binding(self):
        for field in ("head", "tree"):
            x = snapshot()
            x["review"]["current_result"][field] = "b" * 40
            result = self.run_cycle(x)
            self.assertIn(result["status"], {"STALE", "UNKNOWN"})
            self.assertNotIn("next_task", result)

    def test_test_evidence_cannot_be_reused_from_other_head_or_tree(self):
        for field, value in (("head_sha", "b" * 40), ("tree_sha", "b" * 40), ("evidence_ref", ""), ("status", "in_progress")):
            x = snapshot()
            x["review"]["checks"][0][field] = value
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_failed_or_missing_negative_tests_block_next(self):
        x = snapshot()
        x["review"]["checks"][0]["conclusion"] = "failure"
        self.assertEqual(self.run_cycle(x)["status"], "BLOCKED")
        x = snapshot()
        x["review"]["checks"] = [c for c in x["review"]["checks"] if c["kind"] != "negative"]
        self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_path_operation_modes_and_complete_diff_fence(self):
        for changes in ({"filename": "docs/unrelated.md"}, {"status": "removed"}, {"status": "renamed"}, {"symlink": True}, {"symlink": None}):
            x = snapshot()
            x["review"]["changed_files"][0].update(changes)
            self.assertEqual(self.run_cycle(x)["status"], "BLOCKED")
        for value in (False, None, 1):
            x = snapshot()
            x["review"]["files_complete"] = value
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_review_response_binding_matrix(self):
        changes = {"request_id": "other", "loop_id": "other", "correlation_id": "other", "round": 2,
                   "expected_target_head": "b" * 40, "expected_target_tree": "b" * 40,
                   "reviewer_generation": 2, "review_kind": "OTHER", "reviewer_role": "implementer",
                   "submitted_at": "2026-10-01T14:00:00Z", "evidence_refs": [], "rationale_summary": ""}
        for field, value in changes.items():
            with self.subTest(field=field):
                x = snapshot()
                x["review"]["records"]["responses"][0][field] = value
                self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_review_claim_expired_or_not_owner(self):
        for field, value in (("expires_at", "2026-10-01T11:59:00Z"), ("reviewer_instance_id", "other"), ("claimed_at", "2026-10-01T12:01:00Z")):
            x = snapshot()
            x["review"]["records"]["claims"][0][field] = value
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_overlapping_reviewers_and_duplicate_consumption_block(self):
        x = snapshot()
        other = dict(x["review"]["records"]["claims"][0], claim_id="other", reviewer_instance_id="other")
        x["review"]["records"]["claims"].append(other)
        self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_reviewer_takeover_after_response_fences_delayed_consumption(self):
        x = snapshot()
        claim = x["review"]["records"]["claims"][0]
        claim["expires_at"] = "2026-10-01T12:00:01Z"
        x["review"]["records"]["claims"].append(dict(claim, claim_id="replacement", reviewer_instance_id="replacement",
            reviewer_generation=2, claimed_at="2026-10-01T12:00:01Z", expires_at="2026-10-01T13:00:00Z"))
        result = prepare_static_cycle(x, now=NOW + timedelta(seconds=2))
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIn("superseded", result["review"]["reason"])
        x = snapshot()
        first = self.run_cycle(x)
        x["review"]["records"] = first["review"]["recovered_records"]
        x["review"]["records"]["receipts"] *= 2
        self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_comparison_partial_pages_and_false_identical_fail_closed(self):
        for changes in ({"total_commits": 250}, {"total_commits": True}, {"status": "identical"}, {"commits": []}):
            x = snapshot()
            x["source"]["comparison"].update(changes)
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_chat_and_result_share_each_lane_without_task_rewrite(self):
        for lane in LANES:
            result = self.run_cycle(snapshot(lane, with_review=False))
            command = json.loads(result["wake"]["review_body"].split("\n", 1)[1])
            command.update(command_id=lane + "-chat-bounded", task="Read the experiment document.", allowed_paths=["docs/example.md"])
            body = lane_identity(lane)["command_prefix"] + "\n" + json.dumps(command)
            gate = assess_cloud_review(body=body, active_generation=1, fixed_generation=1,
                current_target={k: command[k] for k in ("target_repository", "target_pr", "target_branch", "expected_target_head")},
                reviews=[{"id": 1, "state": "COMMENTED", "body": body}], comments=[], records_complete=True, now=NOW, lane=lane)
            self.assertEqual(gate.purpose, "CHAT_REQUEST")
            self.assertEqual(gate.status, "VALIDATED")
            self.assertEqual(json.loads(body.split("\n", 1)[1])["task"], "Read the experiment document.")

    def test_claim_schema_archival_lane_head_tree_tamper(self):
        for field, value in (("schema_version", 2), ("schema_version", True), ("state", "HISTORICAL_BACKFILL"),
                             ("lane_id", "J-RED"), ("lane_display", "❤️"), ("expected_target_head", "b" * 40),
                             ("expected_target_tree", "b" * 40), ("work_branch", "jules-work/other"), ("retry", False)):
            x = snapshot()
            x["source"]["claim"][field] = value
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN", field)

    def test_formal_command_unsafe_policy_and_time(self):
        for field, value in (("target_branch", "main"), ("retry", False), ("fallback", "enabled"),
                             ("merge_allowed", True), ("force_push_allowed", True),
                             ("created_at", "2026-10-01T14:00:00Z"), ("allowed_paths", ["../secret"]),
                             ("work_branch", "canonical")):
            x = snapshot()
            x["source"]["request"][field] = value
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN", field)

    def test_session_not_guessed_from_actor_or_branch(self):
        for field, value in (("state", "IN_PROGRESS"), ("outputs", []), ("name", "sessions/other")):
            x = snapshot()
            x["source"]["session_readback"][field] = value
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")
        x = snapshot()
        x["source"]["session_readback"]["outputs"][0]["pullRequest"]["url"] = "https://github.com/other/repo/pull/42"
        self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_session_source_start_branch_create_time_binding(self):
        for mutate in (lambda s: s["sourceContext"].update(source="sources/github/other/repo"),
                       lambda s: s["sourceContext"]["githubRepoContext"].update(startingBranch="other"),
                       lambda s: s.update(createTime="2026-10-01T10:02:00Z")):
            x = snapshot()
            mutate(x["source"]["session_readback"])
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_dispatch_exact_commit_run_job_and_log(self):
        for mutate in (lambda s: s["dispatch_run"].update(head_sha="b" * 40),
                       lambda s: s["dispatch_run"].update(path=".github/workflows/other.yml"),
                       lambda s: s["dispatch_run"].update(conclusion="failure"),
                       lambda s: s["dispatch_job"].update(run_id=999),
                       lambda s: s.update(dispatch_log=""),
                       lambda s: s.update(dispatch_log=s["dispatch_log"] + "Jules session accepted: sessions/12345\n"),
                       lambda s: s["command_commit"]["files"][0].update(status="modified"),
                       lambda s: s["command_commit"]["files"].append({"filename": "other", "status": "added"})):
            x = snapshot()
            mutate(x["source"])
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_ancestry_wrong_base_merge_base_head(self):
        for field in ("base_commit", "merge_base_commit"):
            x = snapshot()
            x["source"]["comparison"][field]["sha"] = "b" * 40
            self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")
        x = snapshot()
        x["source"]["comparison"]["commits"][-1]["sha"] = "b" * 40
        self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_snapshot_disagreement_unknown(self):
        x = snapshot()
        x["wake"]["result_pr"]["number"] = 43
        self.assertEqual(self.run_cycle(x)["status"], "UNKNOWN")

    def test_stale_delayed_event_does_not_review_or_prepare_next(self):
        x = snapshot()
        x["wake"]["event"]["pull_request"]["head"]["sha"] = "b" * 40
        result = self.run_cycle(x)
        self.assertEqual(result["status"], "STALE")
        self.assertNotIn("next_task", result)

    def test_four_color_cross_prefix_pair_matrix(self):
        for lane in LANES:
            result = self.run_cycle(snapshot(lane, with_review=False))
            body = result["wake"]["review_body"]
            c = json.loads(body.split("\n", 1)[1])
            args = dict(body=body, active_generation=1, fixed_generation=1,
                        current_target={k: c[k] for k in ("target_repository", "target_pr", "target_branch", "expected_target_head")},
                        reviews=[{"id": 1, "state": "COMMENTED", "body": body}], comments=[], records_complete=True, now=NOW)
            for worker_lane in LANES:
                state = assess_cloud_review(**args, lane=worker_lane).status
                self.assertEqual(state, "VALIDATED" if worker_lane == lane else "NO_OP")

    def test_other_color_reserved_id_cannot_be_chat_request(self):
        result = self.run_cycle(snapshot(with_review=False))
        command = json.loads(result["wake"]["review_body"].split("\n", 1)[1])
        command["command_id"] = command["command_id"].replace("blue-", "red-", 1)
        body = "[CW_BLUE_V1]\n" + json.dumps(command)
        gate = assess_cloud_review(body=body, active_generation=1, fixed_generation=1, current_target=None,
                                    reviews=[], comments=[], records_complete=True, now=NOW, lane="blue")
        self.assertEqual(gate.status, "UNKNOWN")

    def test_next_namespace_uses_claim_command_and_work_branch_all_colors(self):
        x = snapshot()["next_snapshot"]
        x["tree_entries"].append({"path": "automation/command_bus/jules_api_requests/relay-dev-loop-999-red-task.json", "type": "blob"})
        x["branch_refs"].append({"ref": "refs/heads/jules-work/relay-dev-loop-1001-green-task"})
        self.assertEqual(used_loop_numbers(tree_entries=x["tree_entries"], branch_refs=x["branch_refs"], complete=True), {900, 999, 1001})
        plan = prepare_next_jules(lane="blue", task_id="bounded-next", prompt=PROMPT,
                    allowed_paths=["docs/example.md"], expires_at="2026-10-01T13:00:00Z", review_decision="PASS", now=NOW, **x)
        self.assertEqual(plan.claim["loop_number"], 1002)

    def test_actual_legacy_corrective_ids_reserve_numeric_namespace_only(self):
        rows = [{"path": "automation/command_bus/jules_api_requests/relay-dev-loop-015b-shared-timeout-contract-complete-tests.json", "type": "blob"},
                {"path": "automation/command_bus/jules_api_requests/relay-dev-loop-043b-isolation-checkpoint.json", "type": "blob"}]
        refs = [{"ref": "refs/heads/jules-work/relay-dev-loop-043b-isolation-checkpoint"}]
        refs.append({"ref": "refs/heads/jules-work/relay-dev-loop-080-antigravity-account-route-readonly-checklist-10691954638077367390"})
        self.assertEqual(used_loop_numbers(tree_entries=rows, branch_refs=refs, complete=True), {15, 43, 80})
        from automation.command_bus.loop_id_claim import extract_numbered_loop
        self.assertIsNone(extract_numbered_loop("relay-dev-loop-043b-isolation-checkpoint"))

    def test_next_recheck_collision_stale_and_expiry_never_retries(self):
        x = snapshot()["next_snapshot"]
        output = self.run_cycle()["next_task"]
        plan = NextTaskPlan(**output)
        args = dict(target=x["target"], tree_entries=x["tree_entries"], branch_refs=x["branch_refs"], ledger_complete=True, now=NOW)
        self.assertEqual(recheck_next_jules(plan, **args), plan)
        rows = x["tree_entries"] + [{"path": "automation/command_bus/loop_id_claims/901.json", "type": "blob"}]
        self.assertEqual(recheck_next_jules(plan, **dict(args, tree_entries=rows)).status, "BLOCKED")
        self.assertEqual(recheck_next_jules(plan, **dict(args, target=dict(x["target"], head="b" * 40))).status, "STALE")
        self.assertEqual(recheck_next_jules(plan, **dict(args, now=NOW + timedelta(hours=1))).status, "UNKNOWN")

    def test_next_incomplete_ledger_stale_target_and_bounded_prompt(self):
        x = snapshot()
        for mutate in (lambda s: s["next_snapshot"].update(ledger_complete=False),
                       lambda s: s["next_snapshot"]["target"].update(tree="b" * 40),
                       lambda s: s["review"]["records"]["responses"][0]["next_command_proposal"].update(prompt="Do anything")):
            y = copy.deepcopy(x)
            mutate(y)
            self.assertIn(self.run_cycle(y)["status"], {"UNKNOWN", "STALE"})

    def test_same_finding_no_progress_blocks_next(self):
        x = snapshot()
        x["review"]["records"]["responses"][0]["next_command_proposal"].update(previous_finding="receipt mismatch", current_finding="receipt mismatch", meaningful_delta=False)
        self.assertEqual(self.run_cycle(x)["status"], "BLOCKED")

    def test_malformed_and_unmarked_snapshot_fails_closed(self):
        for x in (None, {}, {"source_mode": "LIVE"}, {"source_mode": "MOCK", "lane": "purple"}):
            self.assertEqual(prepare_static_cycle(x, now=NOW)["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
