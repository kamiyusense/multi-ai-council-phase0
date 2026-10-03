"""STATIC tests of the carrier-success -> automatic publish path (workflow_run) for Step 7.

Everything runs on an in-memory fake of GitHub and Jules. No network, no Jules key, no write to any
real repository. Every case that must not publish asserts that no Jules call happened.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from automation.command_bus import signal_step7_live_proof as live
from automation.command_bus import signal_step7_live_proof_cli as cli
from automation.command_bus.tests import test_signal_step7_live_workflow as base

MAIN = "c" * 40
OLD_AUTHORITY_SHA = "9" * 40
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "workflow_run_carrier_success.json"


def ahead(files, *, ahead_by=2, behind_by=0, status="ahead"):
    return {"status": status, "ahead_by": ahead_by, "behind_by": behind_by,
            "files": [{"filename": f} if isinstance(f, str) else f for f in files]}


class AutoCase(unittest.TestCase):
    world = base.EndToEndCliTests.world
    jules_calls = base.EndToEndCliTests.jules_calls

    def run_auto(self, world, tmp, *, prepare_only=False, **env_changes):
        evidence_path = Path(tmp) / "provider-oidc.json"
        evidence_path.write_text(json.dumps(world.provider_evidence), encoding="utf-8")
        env = {"GITHUB_TOKEN": "gh-token-xyz", "JULES_API_KEY": "jules-key-xyz",
               "GITHUB_EVENT_NAME": "workflow_run", "CARRIER_RUN_ID": "9001", "GITHUB_SHA": MAIN,
               "PROVIDER_OIDC_EVIDENCE_PATH": str(evidence_path)}
        env.update(env_changes)
        out, github_output = Path(tmp) / "result.json", Path(tmp) / "github-output.txt"
        argv = ["--plan", str(base.TEMPLATE_PATH), "--registry", str(base.REGISTRY_PATH),
                "--bound-plan-from-data-branch", "--result-out", str(out), "--github-output", str(github_output)]
        if prepare_only:
            argv.append("--prepare-only")
        code = cli.main(argv, env=env, http=world, clock=base.FixedClock())
        result = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
        outputs = github_output.read_text(encoding="utf-8") if github_output.exists() else ""
        return code, result, outputs

    def writes(self, world):
        return [c for c in world.calls if c[0] in {"PUT", "POST"}]

    def assert_untouched(self, world):
        self.assertEqual(self.jules_calls(world), [])
        self.assertEqual(self.writes(world), [])
        branch = world.bound["data_branch"]
        for path in (live.ATTEMPT_MARKER_PATH, live.TERMINAL_RECEIPT_PATH, live.EVIDENCE_PATH):
            self.assertNotIn((branch, path), world.files)


class AutoHappyPathTests(AutoCase):
    def test_carrier_success_publishes_with_exactly_one_get_and_no_typed_input(self):
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            code, result, _ = self.run_auto(world, tmp)
        self.assertEqual((code, result["status"]), (0, "COMPLETE"), result)
        called = self.jules_calls(world)
        self.assertEqual([c[1].rsplit("/", 1)[1] for c in called], [world.session_id])
        self.assertEqual(result["counters"]["whole_proof_total"], {"jules_post": 1, "jules_get": 2, "authority_dispatch": 0})
        evidence = json.loads(world.files[(world.bound["data_branch"], live.EVIDENCE_PATH)][0])
        self.assertEqual(evidence["authority_run_id"], world.authority_run)
        self.assertEqual({branch for branch, _ in world.files}, {world.bound["data_branch"]})

    def test_prepare_only_is_read_only_needs_no_jules_key_and_hands_over_the_resolved_ids(self):
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            code, result, outputs = self.run_auto(world, tmp, prepare_only=True, JULES_API_KEY="")
        self.assertEqual((code, result["status"]), (0, "READY"), result)
        self.assert_untouched(world)
        self.assertEqual(sorted(outputs.splitlines()), sorted([
            "go=true", f"session_id={world.session_id}", f"authority_run_id={world.authority_run}",
            f"command_id={world.bound['request']['command_id']}"]))

    def test_publish_job_recomputes_and_stops_if_it_disagrees_with_prepare(self):
        for name, changes in {"session": {"EXPECT_SESSION_ID": "123456"},
                              "authority": {"EXPECT_AUTHORITY_RUN_ID": "123456"}}.items():
            with self.subTest(name):
                world = self.world()
                with tempfile.TemporaryDirectory() as tmp:
                    code, result, _ = self.run_auto(world, tmp, **changes)
                self.assertEqual(code, 1)
                self.assertIn(result["code"], {"SESSION_ID_INPUT_MISMATCH", "AUTHORITY_RUN_EXPECTATION_MISMATCH"})
                self.assert_untouched(world)

    def test_matching_prepare_outputs_are_accepted(self):
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            code, result, _ = self.run_auto(world, tmp, EXPECT_SESSION_ID=world.session_id,
                                            EXPECT_AUTHORITY_RUN_ID=world.authority_run)
        self.assertEqual((code, result["status"]), (0, "COMPLETE"), result)


class AutoNoopTests(AutoCase):
    """Not this proof's carrier success: exit 0, go=false, nothing read from Jules, nothing written."""

    def assert_noop(self, world, tmp, code_prefix=None, **env_changes):
        code, result, outputs = self.run_auto(world, tmp, **env_changes)
        self.assertEqual((code, result["status"], result["go"]), (0, "NOOP", "false"), result)
        self.assertEqual(outputs.splitlines(), ["go=false"])
        if code_prefix:
            self.assertTrue(result["code"].startswith(code_prefix), result)
        self.assert_untouched(world)

    def test_carrier_runs_that_are_not_the_exact_signal_carrier_success_are_noops(self):
        other = {"full_name": "someone/else"}
        cases = {
            "wrong_repository": {"repository": other}, "wrong_head_repository": {"head_repository": other},
            "wrong_workflow": {"name": "Some other workflow"}, "wrong_path": {"path": ".github/workflows/x.yml"},
            "wrong_event": {"event": "pull_request"}, "wrong_branch": {"head_branch": "main"},
            "not_completed": {"status": "in_progress"}, "failed_carrier": {"conclusion": "failure"},
            "cancelled_carrier": {"conclusion": "cancelled"}, "rerun": {"run_attempt": 2},
            "foreign_actor": {"actor": {"id": 1}}, "foreign_triggering_actor": {"triggering_actor": {"id": 1}},
            "bad_head_sha": {"head_sha": "not-a-sha"},
        }
        for name, changes in cases.items():
            with self.subTest(name):
                world = self.world()
                world.carrier_run_json = base.carrier_run(**changes)
                with tempfile.TemporaryDirectory() as tmp:
                    self.assert_noop(world, tmp, "CARRIER_RUN_NOT_ELIGIBLE")

    def test_unreadable_run_or_wrong_event_name_or_bad_run_id_are_noops(self):
        world = self.world()
        world.carrier_run_json = None
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_noop(world, tmp, "CARRIER_RUN_UNREADABLE")
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_noop(world, tmp, "EVENT_NOT_WORKFLOW_RUN", GITHUB_EVENT_NAME="push")
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_noop(world, tmp, "CARRIER_RUN_ID_INVALID", CARRIER_RUN_ID="9001/../1")

    def test_an_unrelated_carrier_command_is_a_noop(self):
        world = self.world()
        world.carrier_logs[1] = base.carrier_log("relay-dev-loop-1-some-other-command", "111222333")
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_noop(world, tmp, "CARRIER_COMMAND_NOT_THIS_PROOF")

    def test_a_command_id_that_only_resembles_ours_is_a_noop(self):
        world = self.world()
        command_id = world.bound["request"]["command_id"]
        world.carrier_logs[1] = base.carrier_log(command_id + "-x", world.session_id)
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_noop(world, tmp, "CARRIER_COMMAND_NOT_THIS_PROOF")

    def test_no_bound_plan_on_the_data_branch_is_a_noop(self):
        world = self.world()
        del world.files[(world.bound["data_branch"], live.BOUND_PLAN_PATH)]
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_noop(world, tmp, "NO_BOUND_PLAN")

    def test_existing_terminal_receipt_or_attempt_marker_make_a_replayed_event_a_noop(self):
        for name, path in (("receipt", live.TERMINAL_RECEIPT_PATH), ("marker", live.ATTEMPT_MARKER_PATH)):
            with self.subTest(name):
                world = self.world()
                world.seed(world.bound["data_branch"], path, "{}")
                with tempfile.TemporaryDirectory() as tmp:
                    code, result, _ = self.run_auto(world, tmp)
                self.assertEqual((code, result["status"]), (0, "NOOP"), result)
                self.assertEqual(self.jules_calls(world), [])
                self.assertEqual(self.writes(world), [])

    def test_a_replayed_event_after_a_completed_publish_never_reads_jules_again(self):
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            first = self.run_auto(world, tmp)
            second = self.run_auto(world, tmp)
            third = self.run_auto(world, tmp, prepare_only=True)
        self.assertEqual(first[1]["status"], "COMPLETE")
        self.assertEqual((second[0], second[1]["status"]), (0, "NOOP"))
        self.assertEqual((third[0], third[1]["status"]), (0, "NOOP"))
        self.assertEqual(len(self.jules_calls(world)), 1)


class AutoStopTests(AutoCase):
    """It IS this proof's carrier success but something is off: hard stop before Jules, nothing recorded."""

    def assert_stop(self, world, tmp, code, **env_changes):
        got, result, outputs = self.run_auto(world, tmp, **env_changes)
        self.assertEqual((got, result["status"], result["code"]), (1, "STOPPED", code), result)
        self.assertEqual(outputs.splitlines(), ["go=false"])
        self.assert_untouched(world)

    def test_session_resolution_failures_stop(self):
        command_id = self.world().bound["request"]["command_id"]
        base_log = base.carrier_log(command_id, "111").splitlines()
        no_session = "\n".join(line for line in base_log if "SESSION_ID" not in line)
        two_sessions = base.carrier_log(command_id, "111") + base.carrier_log(command_id, "222")
        for name, log, code in (("none", no_session, "CARRIER_SESSION_NOT_UNIQUE"),
                                ("several", two_sessions, "CARRIER_SESSION_NOT_UNIQUE")):
            with self.subTest(name):
                world = self.world()
                world.carrier_logs[1] = log
                with tempfile.TemporaryDirectory() as tmp:
                    self.assert_stop(world, tmp, code)

    def test_old_sessions_stop(self):
        for old in sorted(live.FORBIDDEN_SESSION_IDS):
            with self.subTest(old):
                world = self.world()
                world.carrier_logs[1] = base.carrier_log(world.bound["request"]["command_id"], old)
                with tempfile.TemporaryDirectory() as tmp:
                    self.assert_stop(world, tmp, "CARRIER_SESSION_FORBIDDEN")

    def test_authority_resolution_failures_stop(self):
        run_id = "7700000002"
        cases = {
            "none": [], "after_the_carrier_run": [base.issuer_run(run_id, created_at="2026-10-03T00:05:00Z")],
            "before_the_plan": [base.issuer_run(run_id, created_at="2000-01-01T00:00:00Z")],
            "stale": [base.issuer_run(run_id, created_at="2026-10-02T22:00:00Z")],
            "foreign_actor": [base.issuer_run(run_id, actor={"id": 1})],
            "foreign_triggering_actor": [base.issuer_run(run_id, triggering_actor={"id": 1})],
            "wrong_branch": [base.issuer_run(run_id, head_branch="other")],
            "rerun": [base.issuer_run(run_id, run_attempt=2)],
            "failed": [base.issuer_run(run_id, conclusion="failure")],
            "reserved": [base.issuer_run("37031275812")],
            "several": [base.issuer_run(run_id), base.issuer_run("7700000003", created_at="2026-10-03T00:03:00Z")],
        }
        for name, runs in cases.items():
            with self.subTest(name):
                world = self.world()
                world.issuer_runs = runs
                with tempfile.TemporaryDirectory() as tmp:
                    self.assert_stop(world, tmp, "AUTHORITY_RUN_NOT_UNIQUE")

    def test_target_and_branch_drift_stop_before_any_record_is_written(self):
        cases = {
            "target_head_drift": (lambda w: setattr(w, "pr_head", "f" * 40), "TARGET_HEAD_MISMATCH"),
            "target_not_draft": (lambda w: setattr(w, "pr_draft", False), "TARGET_PR_NOT_DRAFT"),
            "work_branch_drift": (lambda w: w.branch_head.__setitem__(w.work_branch, "f" * 40),
                                  "BRANCH_HEAD_OR_TREE_MISMATCH"),
            "target_branch_drift": (lambda w: w.branch_head.__setitem__(w.target_branch, "f" * 40),
                                    "BRANCH_HEAD_OR_TREE_MISMATCH"),
            "wrong_tree": (lambda w: w.commit_tree.__setitem__(base.HEAD, "9" * 40), "BRANCH_HEAD_OR_TREE_MISMATCH"),
        }
        for name, (mutate, code) in cases.items():
            with self.subTest(name):
                world = self.world()
                mutate(world)
                with tempfile.TemporaryDirectory() as tmp:
                    self.assert_stop(world, tmp, code)

    def test_a_bound_plan_for_another_lane_or_task_or_target_stops(self):
        def reseed(world, change):
            plan = json.loads(json.dumps(world.bound))
            change(plan)
            world.seed(plan["data_branch"], live.BOUND_PLAN_PATH, json.dumps(plan))

        cases = {
            "wrong_lane": (lambda p: p.update(lane_id="chatgpt-semi-auto-other"), "WRONG_LANE_ID"),
            "fixture_lane": (lambda p: p.update(lane_id="fixture-lane"), "WRONG_LANE_ID"),
            "wrong_allowed_path": (lambda p: p.update(allowed_path="docs/evidence/other/PROOF.md"),
                                   "ALLOWED_OUTPUT_MISMATCH"),
            "wrong_allowed_content": (lambda p: p.update(allowed_content="other\n"), "ALLOWED_OUTPUT_MISMATCH"),
            "wrong_carrier_lane": (lambda p: p["carrier_claim"].update(lane_id="J-RED"), "CARRIER_IDENTITY_MISMATCH"),
            "wrong_proof_task": (lambda p: p["carrier_claim"].update(task_id="signal-active-proof-1"),
                                 "CARRIER_IDENTITY_MISMATCH"),
            "claim_command_differs": (lambda p: p["carrier_claim"].update(command_id="relay-dev-loop-136-other"),
                                      "CARRIER_IDENTITY_MISMATCH"),
            "retry_not_zero": (lambda p: p["carrier_claim"].update(retry=1), "CARRIER_IDENTITY_MISMATCH"),
            "fallback_enabled": (lambda p: p["carrier_claim"].update(fallback="enabled"), "CARRIER_IDENTITY_MISMATCH"),
            "unbound_target": (lambda p: p.update(expected_target_head="0" * 40), "PLAN_NOT_BOUND_TO_TARGET"),
        }
        for name, (change, code) in cases.items():
            with self.subTest(name):
                world = self.world()
                reseed(world, change)
                with tempfile.TemporaryDirectory() as tmp:
                    got, result, _ = self.run_auto(world, tmp)
                self.assertEqual(got, 1, (name, result))
                self.assertNotEqual(result["status"], "COMPLETE")
                self.assertEqual(self.jules_calls(world), [], name)
                self.assertNotIn((world.bound["data_branch"], live.ATTEMPT_MARKER_PATH), world.files)

    def test_a_typed_digest_that_differs_from_the_data_branch_plan_stops(self):
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_stop(world, tmp, "BOUND_PLAN_DIGEST_MISMATCH", PLAN_SHA256="0" * 64)


class AutoMainDriftTests(AutoCase):
    def drifted(self, compare):
        world = self.world(authority_sha=OLD_AUTHORITY_SHA)
        world.compare = compare
        return world

    def test_unrelated_main_progress_does_not_waste_the_proof(self):
        seen = []

        def compare(base_sha, head_sha):
            seen.append((base_sha, head_sha))
            return 200, ahead(["src/relay/acp_client.py", "docs/RELAY_M9_RUNNER.md", "tests/relay/test_x.py",
                               "automation/command_bus/tests/test_other.py",
                               "automation/command_bus/jules_api_requests/relay-dev-loop-9-x.json",
                               "docs/BLUE_BWJ4_PROOF_AUTHORIZATION.json"])

        world = self.drifted(compare)
        with tempfile.TemporaryDirectory() as tmp:
            code, result, _ = self.run_auto(world, tmp)
        self.assertEqual((code, result["status"]), (0, "COMPLETE"), result)
        self.assertEqual(seen[0], (OLD_AUTHORITY_SHA, MAIN))
        self.assertEqual(len(self.jules_calls(world)), 1)

    def test_a_change_to_any_contract_path_or_an_unverifiable_compare_stops_before_jules(self):
        hundred = [f"docs/a{i}.md" for i in range(100)]
        cases = {
            "workflow_changed": (200, ahead([".github/workflows/signal-sf8-authority-issuer.yml"])),
            "publish_workflow_changed": (200, ahead([".github/workflows/signal-step7-live-publish.yml"])),
            "command_bus_code_changed": (200, ahead(["automation/command_bus/signal_step7_live_proof.py"])),
            "command_bus_config_changed": (200, ahead(["automation/command_bus/config/control_tower_registry.json"])),
            "sf8_evidence_changed": (200, ahead(["docs/evidence/signal-sf8/registry-candidate-chatgpt-semi-auto-durable.json"])),
            "rename_from_contract_path": (200, ahead([{"filename": "docs/x.md",
                                                       "previous_filename": ".github/workflows/a.yml"}])),
            "file_without_a_name": (200, ahead([{"status": "modified"}])),
            "truncated_file_list": (200, ahead(hundred)),
            "diverged": (200, ahead(["docs/a.md"], status="diverged")),
            "behind": (200, ahead(["docs/a.md"], status="behind")),
            "behind_by_one": (200, ahead(["docs/a.md"], behind_by=1)),
            "not_ahead": (200, ahead(["docs/a.md"], ahead_by=0)),
            "files_not_a_list": (200, {"status": "ahead", "ahead_by": 1, "behind_by": 0, "files": None}),
            "compare_unreadable": (404, {}),
            "compare_server_error": (500, {}),
        }
        for name, (status, body) in cases.items():
            with self.subTest(name):
                world = self.drifted(lambda b, h, status=status, body=body: (status, body))
                with tempfile.TemporaryDirectory() as tmp:
                    got, result, _ = self.run_auto(world, tmp)
                self.assertEqual(got, 1, (name, result))
                self.assertIn(result["code"], {"MAIN_DRIFT_CONTRACT_CHANGED", "MAIN_DRIFT_UNVERIFIED"}, (name, result))
                self.assert_untouched(world)

    def test_the_executing_code_sha_is_bound_too(self):
        executing = "e" * 40
        calls = []

        def compare(base_sha, head_sha):
            calls.append((base_sha, head_sha))
            return 200, ahead(["docs/a.md"])

        world = self.world()  # authority run is at main
        world.compare = compare
        with tempfile.TemporaryDirectory() as tmp:
            code, result, _ = self.run_auto(world, tmp, GITHUB_SHA=executing)
        self.assertEqual((code, result["status"]), (0, "COMPLETE"), result)
        self.assertEqual(set(calls), {(MAIN, executing)})  # preflight and the publish half each bind it
        world = self.world()
        world.compare = lambda b, h: (200, ahead([".github/workflows/x.yml"]))
        with tempfile.TemporaryDirectory() as tmp:
            self.assert_untouched_after_stop(world, tmp, "MAIN_DRIFT_CONTRACT_CHANGED", GITHUB_SHA=executing)

    def assert_untouched_after_stop(self, world, tmp, code, **env):
        got, result, _ = self.run_auto(world, tmp, **env)
        self.assertEqual((got, result["code"]), (1, code), result)
        self.assert_untouched(world)

    def test_authority_at_main_needs_no_compare_at_all(self):
        world = self.world()
        world.compare = lambda b, h: self.fail("no compare is needed when everything is the same SHA")
        with tempfile.TemporaryDirectory() as tmp:
            code, result, _ = self.run_auto(world, tmp)
        self.assertEqual((code, result["status"]), (0, "COMPLETE"), result)


class DriftPolicyUnitTests(unittest.TestCase):
    class Compare:
        def __init__(self, result):
            self.result, self.calls = result, []

        def compare(self, base_sha, head_sha):
            self.calls.append((base_sha, head_sha))
            return self.result

    def test_equal_shas_pass_without_a_compare_port(self):
        live.check_authority_sha_binding(MAIN, MAIN, MAIN, None)
        live.check_authority_sha_binding(MAIN, MAIN, None, None)

    def test_different_shas_need_the_compare_port(self):
        with self.assertRaises(live.LiveProofError) as caught:
            live.check_authority_sha_binding(OLD_AUTHORITY_SHA, MAIN, MAIN, None)
        self.assertEqual(caught.exception.code, "AUTHORITY_RUN_NOT_EXACT_MAIN")

    def test_invalid_shas_fail_closed(self):
        for args in (("zz", MAIN, MAIN), (None, MAIN, MAIN), (MAIN, "short", MAIN), (MAIN, MAIN, "short")):
            with self.subTest(args), self.assertRaises(live.LiveProofError):
                live.check_authority_sha_binding(*args, self.Compare(ahead(["docs/a.md"])))

    def test_both_main_and_the_executing_sha_are_compared_once_each(self):
        compare = self.Compare(ahead(["docs/a.md"]))
        live.check_authority_sha_binding(OLD_AUTHORITY_SHA, MAIN, "e" * 40, compare)
        self.assertEqual(compare.calls, [(OLD_AUTHORITY_SHA, MAIN), (OLD_AUTHORITY_SHA, "e" * 40)])

    def test_contract_path_classification(self):
        for path in (".github/workflows/a.yml", ".github/CODEOWNERS", "automation/command_bus/x.py",
                     "automation/command_bus/schema/a.json", "automation/command_bus/config/a.json",
                     "docs/evidence/signal-sf8/a.json", "", None):
            self.assertTrue(live.is_contract_path(path), path)
        for path in ("src/relay/a.py", "docs/a.md", "automation/command_bus/tests/test_a.py",
                     "automation/command_bus/jules_api_requests/a.json", "automation/command_bus/loop_id_claims/9.json",
                     "docs/evidence/signal-active-proof-5/a.json", "README.md"):
            self.assertFalse(live.is_contract_path(path), path)


class WorkflowRunEventFixtureTests(unittest.TestCase):
    """The job guard is evaluated against a realistic workflow_run payload and mutated copies of it."""

    WORKFLOW = base.WORKFLOW

    def literals(self):
        condition = re.findall(r"^    if: (.+)$", self.WORKFLOW, re.M)[0]
        equals = re.findall(r"github\.event\.workflow_run\.([a-z_.]+) == ('[^']*'|\d+)", condition)
        owners = re.findall(r"format\('\{0\}', github\.event\.workflow_run\.([a-z_.]+)\)", condition)
        return equals, owners

    @staticmethod
    def pick(payload, dotted):
        value = payload["workflow_run"]
        for part in dotted.split("."):
            value = value[part]
        return value

    def passes(self, payload):
        equals, owners = self.literals()
        for dotted, literal in equals:
            expected = literal.strip("'") if literal.startswith("'") else int(literal)
            if self.pick(payload, dotted) != expected:
                return False
        return all(str(self.pick(payload, dotted)) == live.OWNER_ACTOR_ID for dotted in owners)

    def test_the_real_shaped_payload_passes_and_covers_every_guarded_field(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        equals, owners = self.literals()
        self.assertGreaterEqual(len(equals), 8)
        self.assertEqual(sorted(owners), ["actor.id", "triggering_actor.id"])
        self.assertTrue(self.passes(payload))

    def test_every_single_field_change_makes_the_guard_fail(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        equals, owners = self.literals()
        for dotted, _ in equals + [(o, "") for o in owners]:
            mutated = json.loads(json.dumps(payload))
            run = mutated["workflow_run"]
            parts = dotted.split(".")
            for part in parts[:-1]:
                run = run[part]
            run[parts[-1]] = "changed" if not isinstance(run[parts[-1]], int) else run[parts[-1]] + 1
            self.assertFalse(self.passes(mutated), dotted)

    def test_replaying_the_same_event_is_deduplicated_by_the_per_run_group_and_the_data_branch_guards(self):
        self.assertIn("${{ github.event.workflow_run.id || github.run_id }}", self.WORKFLOW)
        self.assertIn("TERMINAL_RECEIPT_EXISTS", Path(cli.__file__).read_text(encoding="utf-8"))


class ProviderStateOverAutoPathTests(AutoCase):
    def test_non_active_or_failed_provider_states_never_publish_and_leave_a_terminal_receipt(self):
        for state in ("COMPLETED", "FAILED", "PAUSED", None, "SOMETHING_NEW"):
            with self.subTest(state):
                world = self.world(session_state=state)
                with tempfile.TemporaryDirectory() as tmp:
                    code, result, _ = self.run_auto(world, tmp)
                self.assertEqual((code, result["status"]), (1, "UNKNOWN"), (state, result))
                self.assertEqual(len(self.jules_calls(world)), 1)
                self.assertIn((world.bound["data_branch"], live.TERMINAL_RECEIPT_PATH), world.files)
                self.assertNotIn((world.bound["data_branch"], live.EVIDENCE_PATH), world.files)

    def test_a_provider_http_error_is_unknown_and_not_retried(self):
        world = self.world(session_status=500)
        with tempfile.TemporaryDirectory() as tmp:
            code, result, _ = self.run_auto(world, tmp)
        self.assertEqual((code, result["status"]), (1, "UNKNOWN"), result)
        self.assertEqual(len(self.jules_calls(world)), 1)

    def test_a_second_event_after_a_failed_publish_never_reads_jules_again(self):
        world = self.world(session_state="COMPLETED")
        with tempfile.TemporaryDirectory() as tmp:
            first = self.run_auto(world, tmp)
            second = self.run_auto(world, tmp)
        self.assertEqual(first[1]["status"], "UNKNOWN")
        self.assertEqual((second[0], second[1]["status"]), (0, "NOOP"))
        self.assertEqual(len(self.jules_calls(world)), 1)


class StaticSafetyTests(unittest.TestCase):
    def test_a_new_proof_needs_a_fresh_human_gate_and_budget_not_carried_over_from_proof_4(self):
        template = json.loads(base.TEMPLATE_PATH.read_text(encoding="utf-8"))
        self.assertIs(template["human_approval_required"], True)
        self.assertIs(template["registry_write_allowed"], False)
        self.assertEqual(template["limits"], {"authority_dispatch": 1, "jules_get": 2, "jules_post": 1, "retry": 0})
        bound = live.bind_plan(template, loop_number=136, target_pr=1, target_head="a" * 40, target_tree="b" * 40,
                               now="2026-10-03T00:00:00+00:00")
        text = json.dumps(bound)
        for old in ("135", "569271609782168660", "37098007717", "37098060038", "37098873248"):
            self.assertNotIn(old, text)
        self.assertEqual(bound["carrier_claim"]["loop_number"], 136)
        self.assertEqual(bound["request"]["command_id"], "relay-dev-loop-136-signal-active-proof-5")

    def test_the_proof_constants_name_proof_5_only(self):
        self.assertEqual(live.PROOF_TASK_ID, "signal-active-proof-5")
        self.assertEqual(live.ALLOWED_PATH, "docs/evidence/signal-active-proof-5/PROOF.md")
        self.assertEqual(live.ALLOWED_CONTENT, "signal active proof 5\n")
        self.assertEqual(live.DATA_RECORD_DIR, "docs/evidence/signal-active-proof-5")
        template = json.loads(base.TEMPLATE_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("proof-4", json.dumps(template))
        self.assertNotIn("proof-3", json.dumps(template))
        for old in ("301196275118188780", "5943440322658150300", "11944164406087664763", "569271609782168660"):
            self.assertIn(old, live.FORBIDDEN_SESSION_IDS)

    def test_the_cli_prepare_mode_never_builds_the_jules_reader(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertIn("reader = None if args.prepare_only else JulesActiveSessionGetReader", source)


if __name__ == "__main__":
    unittest.main()
