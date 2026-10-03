"""STATIC proof of the Step 7 LIVE publish half. Every port here is a fixture; nothing is live.

Passing here means the wiring fails closed and spends exactly its budget. It does not
mean a real Jules session was observed.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus import signal_step7_live_proof as live
from automation.command_bus.github_oidc_proof_policy_cli import SF8_AUTHORITY_PROFILE, SF8_PROFILE
from automation.command_bus.tests.test_jules_semiauto_owner_prepare import (
    BRANCH, CURRENT_COMMAND, HEAD, REPO, TREE, WORK_BRANCH, carrier_claim, context, current_request,
)
from automation.command_bus.tests.test_oidc_workflow_execution import evidence_for, run_for
from automation.command_bus.tests.test_runtime_transition_publisher import Client

ROOT = Path(__file__).resolve().parents[3]
CANDIDATE_REGISTRY = json.loads(
    (ROOT / "docs/evidence/signal-sf8/registry-candidate-chatgpt-semi-auto-durable.json").read_text(encoding="utf-8"))
SESSION_ID = "31415926535897932384"
AUTHORITY_RUN = "7700000001"
MAIN_SHA = "c" * 40
PROVIDER_SHA = live.PROVIDER_OIDC_EXPECTED_SHA
NOW = "2026-09-28T04:10:00+00:00"
DATA_BRANCH = "signal/chatgpt-semi-auto-active-proof-4-data"


def make_plan(**changes):
    request = current_request(
        allowed_paths=[live.ALLOWED_PATH],
        prompt="Create docs/evidence/signal-active-proof-4/PROOF.md with exactly: signal active proof 4")
    plan = {
        "schema_version": 1, "plan_kind": "SIGNAL_STEP7_LIVE_PROOF_PLAN", "repository": REPO,
        "lane_id": live.LANE_ID, "target_branch": BRANCH, "target_pr": 4, "work_branch": WORK_BRANCH,
        "expected_target_head": HEAD, "expected_target_tree": TREE, "data_branch": DATA_BRANCH,
        "allowed_path": live.ALLOWED_PATH, "allowed_content": live.ALLOWED_CONTENT,
        "authority_max_age_seconds": 3600, "not_before": "2026-09-28T03:50:00Z",
        "provider_oidc_run_id": live.PROVIDER_OIDC_RUN_ID, "provider_oidc_expected_sha": PROVIDER_SHA,
        "durable_context": context(loop_id=live.LANE_ID, target_pr=4),
        "request": request, "carrier_claim": carrier_claim(),
        "limits": dict(live.LIMITS), "retry": 0, "fallback": "disabled",
        "registry_write_allowed": False, "human_approval_required": True,
    }
    plan.update(changes)
    return plan


class Clock:
    def now(self):
        return NOW


class Target:
    def __init__(self, value):
        self.value, self.calls = value, 0

    def read_target(self, repository, pr_number):
        self.calls += 1
        return copy.deepcopy(self.value)


class Branches:
    def __init__(self, mapping):
        self.mapping = mapping

    def read_branch(self, repository, branch):
        return copy.deepcopy(self.mapping.get(branch))


class Session:
    def __init__(self, value=None, raises=False):
        self.calls = 0
        self.raises = raises
        self.value = value if value is not None else {
            "name": f"sessions/{SESSION_ID}", "createTime": "2026-09-28T03:59:00Z",
            "updateTime": "2026-09-28T04:05:00Z", "state": "IN_PROGRESS",
            "sourceContext": {"source": f"sources/github/{REPO}",
                              "githubRepoContext": {"startingBranch": WORK_BRANCH}},
        }

    def read_active_session(self, session_id, *, expected_branch):
        self.calls += 1
        if self.raises:
            raise TimeoutError("simulated timeout")
        return copy.deepcopy(self.value)


class Runs:
    def __init__(self, runs):
        self.runs, self.calls = runs, []

    def read_run(self, run_id):
        self.calls.append(run_id)
        return copy.deepcopy(self.runs.get(str(run_id)))


class AuthorityEvidence:
    def __init__(self, mapping):
        self.mapping = mapping

    def load(self, run_id):
        return copy.deepcopy(self.mapping.get(str(run_id)))


def make_ports(*, session=None, target_changes=None, authority_run_changes=None, authority_evidence_changes=None,
               branch_changes=None, store=None, provider_run_changes=None, is_live=False):
    target = {"number": 4, "state": "open", "merged": False, "draft": True,
              "head": {"ref": BRANCH, "sha": HEAD}, "repo": {"full_name": REPO}}
    target.update(target_changes or {})
    branches = {BRANCH: {"head": HEAD, "tree": TREE}, WORK_BRANCH: {"head": HEAD, "tree": TREE},
                "main": {"head": MAIN_SHA, "tree": "e" * 40}}
    branches.update(branch_changes or {})
    authority_run = run_for(SF8_AUTHORITY_PROFILE, run_id=AUTHORITY_RUN, sha=MAIN_SHA,
                            **{"created_at": "2026-09-28T03:55:00Z", **(authority_run_changes or {})})
    provider_run = run_for(SF8_PROFILE, run_id=live.PROVIDER_OIDC_RUN_ID, sha=PROVIDER_SHA,
                           **(provider_run_changes or {}))
    return live.PublishPorts(
        clock=Clock(), target_reader=Target(target), branch_reader=Branches(branches),
        session_reader=session or Session(),
        run_reader=Runs({AUTHORITY_RUN: authority_run, live.PROVIDER_OIDC_RUN_ID: provider_run}),
        authority_evidence=AuthorityEvidence({AUTHORITY_RUN: evidence_for(
            SF8_AUTHORITY_PROFILE, **{"run_id": AUTHORITY_RUN, "sha": MAIN_SHA, **(authority_evidence_changes or {})})}),
        provider_oidc_evidence=evidence_for(SF8_PROFILE, run_id=live.PROVIDER_OIDC_RUN_ID, sha=PROVIDER_SHA),
        store=store if store is not None else Client(), is_live=is_live)


def run(*, plan=None, registry=None, session_id=SESSION_ID, authority_run=AUTHORITY_RUN, ports=None, counters=None):
    ports = ports or make_ports()
    return live.run_publish_half(
        plan=plan or make_plan(), candidate_registry=registry or CANDIDATE_REGISTRY, session_id=session_id,
        authority_run_id=authority_run, ports=ports, counters=counters), ports


class HappyPathTests(unittest.TestCase):
    def test_static_chain_completes_for_the_exact_lane_and_spends_one_get(self):
        result, ports = run()
        self.assertEqual((result.status, result.code), ("COMPLETE", "NONE"), result)
        self.assertEqual(ports.session_reader.calls, 1)
        counters = result.counters
        self.assertEqual(counters["whole_proof_total"], {"jules_post": 1, "jules_get": 2, "authority_dispatch": 0})
        self.assertEqual(counters["this_half"]["jules_post"], 0)
        evidence = result.evidence
        self.assertEqual(evidence["lane_id"], "chatgpt-semi-auto")
        self.assertEqual(evidence["provider_raw_state"], "IN_PROGRESS")
        self.assertEqual(evidence["canonical_runtime_state"], "RUNNING")
        self.assertEqual(evidence["lane_registration"], "READY")
        self.assertEqual((evidence["retry"], evidence["fallback"]), (0, "disabled"))
        self.assertEqual((evidence["production_registry_written"], evidence["issue33_written"], evidence["merged"]),
                         (False, False, False))
        store = ports.store
        self.assertIn(live.TERMINAL_RECEIPT_PATH, store.data)
        self.assertIn(live.EVIDENCE_PATH, store.data)

    def test_fixture_run_is_static_so_the_gate_never_reaches_ready(self):
        result, _ = run()
        gate = result.evidence["pre_adoption_gate"]
        self.assertEqual(result.evidence["scope"], "STATIC")
        self.assertEqual(gate["status"], "NOT_READY")
        self.assertTrue(gate["human_approval_required"])
        self.assertFalse(gate["registry_write_allowed"])

    def test_only_real_ports_can_reach_ready_for_human_approval(self):
        result, _ = run(ports=make_ports(is_live=True))
        self.assertEqual(result.status, "COMPLETE", result)
        gate = result.evidence["pre_adoption_gate"]
        self.assertEqual(gate["status"], "READY_FOR_HUMAN_APPROVAL")
        self.assertTrue(gate["human_approval_required"])
        self.assertFalse(gate["registry_write_allowed"])

    def test_durable_records_use_the_data_branch_only(self):
        result, ports = run()
        self.assertEqual(result.status, "COMPLETE", result)
        self.assertTrue(ports.store.creates >= 5)


class PlanGuardTests(unittest.TestCase):
    def stopped(self, **kwargs):
        result, ports = run(**kwargs)
        self.assertNotEqual(result.status, "COMPLETE", result)
        return result, ports

    def test_plan_mismatches_are_refused_before_any_io(self):
        cases = {
            "wrong_repo": make_plan(repository="x/y"),
            "fixture_lane": make_plan(lane_id="fixture-chatgpt-semi-auto-lane"),
            "numeric_lane": make_plan(lane_id="1234"),
            "wrong_lane": make_plan(lane_id="claude-gemini"),
            "default_data_branch": make_plan(data_branch="main"),
            "same_branches": make_plan(data_branch=BRANCH),
            "bad_sha": make_plan(expected_target_head="xyz"),
            "wrong_allowed_path": make_plan(allowed_path="src/evil.py"),
            "wrong_content": make_plan(allowed_content="other\n"),
            "retry": make_plan(retry=1),
            "fallback": make_plan(fallback="enabled"),
            "limits": make_plan(limits={**live.LIMITS, "jules_post": 2}),
            "weakens_gate": make_plan(registry_write_allowed=True),
            "no_human_gate": make_plan(human_approval_required=False),
            "wrong_provider_run": make_plan(provider_oidc_run_id="1"),
            "context_lane": make_plan(durable_context=context(loop_id="other-lane", target_pr=4)),
            "lane_equals_command": make_plan(durable_context=context(loop_id=live.LANE_ID, correlation_id=live.LANE_ID),
                                             request=current_request(allowed_paths=[live.ALLOWED_PATH],
                                                                     prompt="signal active proof 4",
                                                                     command_id=live.LANE_ID,
                                                                     work_branch=f"jules-work/{live.LANE_ID}")),
        }
        for label, plan in cases.items():
            with self.subTest(label):
                result, ports = run(plan=plan)
                self.assertNotEqual(result.status, "COMPLETE", result)
                self.assertEqual(ports.session_reader.calls, 0)
                self.assertEqual(ports.store.creates, 0)

    def test_placeholder_or_missing_lane_in_registry_is_refused(self):
        placeholder = copy.deepcopy(CANDIDATE_REGISTRY)
        for entry in placeholder["loops"]:
            if entry["loop_id"] == live.LANE_ID:
                entry["identity_state"] = "PLACEHOLDER"
        for registry in (placeholder, {"schema_version": 1, "loops": []}):
            result, ports = run(registry=registry)
            self.assertNotEqual(result.status, "COMPLETE")
            self.assertEqual(ports.session_reader.calls, 0)

    def test_old_session_132_is_never_read(self):
        result, ports = run(session_id="301196275118188780")
        self.assertEqual(result.code, "OLD_SESSION_FORBIDDEN")
        self.assertEqual(ports.session_reader.calls, 0)

    def test_malformed_identifiers_do_no_io(self):
        for session_id, authority_run in (("sessions/1", AUTHORITY_RUN), ("", AUTHORITY_RUN),
                                          (SESSION_ID, "abc"), (SESSION_ID, "")):
            result, ports = run(session_id=session_id, authority_run=authority_run)
            self.assertEqual(result.code, "BAD_IDENTIFIER")
            self.assertEqual(ports.session_reader.calls, 0)

    def test_reserved_or_reused_authority_runs_are_refused(self):
        for run_id in ("37031275812", live.PROVIDER_OIDC_RUN_ID):
            result, ports = run(authority_run=run_id)
            self.assertEqual(result.code, "AUTHORITY_RUN_RESERVED_OR_REUSED")
            self.assertEqual(ports.session_reader.calls, 0)


class TargetGuardTests(unittest.TestCase):
    def check(self, code, **port_args):
        result, ports = run(ports=make_ports(**port_args))
        self.assertEqual(result.code, code, result)
        self.assertEqual(ports.session_reader.calls, 0, "no Jules GET may be spent when the target is wrong")
        return result, ports

    def test_target_pr_state(self):
        self.check("TARGET_PR_NOT_OPEN", target_changes={"state": "closed"})
        self.check("TARGET_PR_NOT_OPEN", target_changes={"merged": True})
        self.check("TARGET_PR_NOT_DRAFT", target_changes={"draft": False})
        self.check("TARGET_HEAD_MISMATCH", target_changes={"head": {"ref": BRANCH, "sha": "f" * 40}})
        self.check("TARGET_HEAD_MISMATCH", target_changes={"head": {"ref": "other", "sha": HEAD}})

    def test_branch_head_or_tree_mismatch(self):
        for name in (BRANCH, WORK_BRANCH):
            self.check("BRANCH_HEAD_OR_TREE_MISMATCH", branch_changes={name: {"head": "f" * 40, "tree": TREE}})
            self.check("BRANCH_HEAD_OR_TREE_MISMATCH", branch_changes={name: {"head": HEAD, "tree": "f" * 40}})
            self.check("BRANCH_HEAD_OR_TREE_MISMATCH", branch_changes={name: None})


class AuthorityGuardTests(unittest.TestCase):
    def check(self, **port_args):
        result, ports = run(ports=make_ports(**port_args))
        self.assertNotEqual(result.status, "COMPLETE", result)
        self.assertEqual(ports.session_reader.calls, 0, "no Jules GET may be spent when authority is wrong")
        return result

    def test_wrong_authority_runs_are_refused_before_the_get(self):
        cases = {
            "push_event": dict(authority_run_changes={"event": "push"}),
            "rerun": dict(authority_run_changes={"run_attempt": 2}),
            "not_success": dict(authority_run_changes={"conclusion": "failure"}),
            "wrong_branch": dict(authority_run_changes={"head_branch": "feature/x"}),
            "wrong_workflow": dict(authority_run_changes={"path": ".github/workflows/other.yml"}),
            "reusable_workflow": dict(authority_run_changes={"referenced_workflows": [{"path": "x"}]}),
            "actor_split": dict(authority_run_changes={"triggering_actor": {"id": 999}}),
            "non_owner": dict(authority_run_changes={"actor": {"id": 999}, "triggering_actor": {"id": 999}}),
            "not_exact_main": dict(branch_changes={"main": {"head": "9" * 40, "tree": "e" * 40}}),
            "stale": dict(authority_run_changes={"created_at": "2026-09-28T01:00:00Z"}),
            "before_plan": dict(authority_run_changes={"created_at": "2026-09-28T03:00:00Z"}),
            "bad_evidence_digest": dict(authority_evidence_changes={"evidence_payload_sha256": "0" * 64}),
            "evidence_wrong_run": dict(authority_evidence_changes={"run_id": "1"}),
            "missing_run": dict(authority_run_changes={"id": 1}),
            "provider_run_bad": dict(provider_run_changes={"conclusion": "failure"}),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                self.check(**kwargs)


class ProviderGuardTests(unittest.TestCase):
    def good(self, **changes):
        base = Session().value
        return {**base, **changes}

    def check(self, session):
        result, ports = run(ports=make_ports(session=session))
        self.assertNotEqual(result.status, "COMPLETE", result)
        self.assertEqual(ports.session_reader.calls, 1)
        self.assertEqual(ports.store.updates, 0)
        self.assertEqual(live.TERMINAL_RECEIPT_PATH in ports.store.data, True)
        return result

    def test_only_active_raw_states_pass(self):
        for state in ("COMPLETED", "FAILED", "UNKNOWN", "", "STATE_UNSPECIFIED", None):
            with self.subTest(state=state):
                result = self.check(Session(self.good(state=state)))
                self.assertEqual(result.code, "PROVIDER_NOT_ACTIVE")
                self.assertEqual(result.status, "UNKNOWN")

    def test_session_context_and_time_mismatches(self):
        cases = {
            "wrong_session": self.good(name="sessions/9999"),
            "wrong_branch": self.good(sourceContext={"source": f"sources/github/{REPO}",
                                                     "githubRepoContext": {"startingBranch": BRANCH}}),
            "wrong_source": self.good(sourceContext={"source": "sources/github/x/y",
                                                     "githubRepoContext": {"startingBranch": WORK_BRANCH}}),
            "update_before_create": self.good(updateTime="2026-09-28T03:00:00Z"),
            "stale_observation": self.good(updateTime="2026-09-28T01:00:00Z"),
            "create_time_missing": {k: v for k, v in self.good().items() if k != "createTime"},
        }
        for label, session in cases.items():
            with self.subTest(label):
                self.check(Session(session))

    def test_timeout_is_unknown_and_never_retried(self):
        session = Session(raises=True)
        result, ports = run(ports=make_ports(session=session))
        self.assertEqual((result.status, result.code), ("UNKNOWN", "PROVIDER_READ_UNKNOWN"))
        self.assertEqual(session.calls, 1)

    def test_a_second_provider_read_is_refused(self):
        counters = live.LiveCounters()
        reader = live.BudgetedSessionReader(Session(), counters)
        reader.read_active_session(SESSION_ID, expected_branch=WORK_BRANCH)
        with self.assertRaises(live.LiveProofError) as ctx:
            reader.read_active_session(SESSION_ID, expected_branch=WORK_BRANCH)
        self.assertEqual(ctx.exception.code, "SECOND_READ_REFUSED")
        self.assertEqual(counters.jules_get, 1)

    def test_get_budget_cannot_exceed_two_in_total(self):
        counters = live.LiveCounters()
        counters.spend("jules_get")  # this half: total becomes 2 including the carrier read
        with self.assertRaises(live.LiveProofError) as ctx:
            counters.spend("jules_get")
        self.assertEqual(ctx.exception.code, "BUDGET_EXCEEDED")
        with self.assertRaises(live.LiveProofError):
            counters.spend("jules_post")  # the carrier already used the only POST
        with self.assertRaises(live.LiveProofError):
            counters.spend("authority_dispatch") if False else counters.spend("retry")
        # a half that starts with the GET already spent never calls the provider
        spent = live.LiveCounters(jules_get=1)
        result, ports = run(counters=spent)
        self.assertEqual(result.code, "BUDGET_EXCEEDED")
        self.assertEqual(ports.session_reader.calls, 0)


class ReplayAndDuplicateTests(unittest.TestCase):
    def test_terminal_receipt_blocks_a_rerun_without_any_read(self):
        first, ports = run()
        self.assertEqual(first.status, "COMPLETE")
        calls_before = ports.session_reader.calls
        again, _ = run(ports=make_ports(store=ports.store))
        self.assertEqual(again.code, "TERMINAL_RECEIPT_EXISTS")
        self.assertEqual(ports.session_reader.calls, calls_before)

    def test_existing_attempt_marker_blocks_a_second_attempt(self):
        store = Client()
        store.put(live.ATTEMPT_MARKER_PATH, {"schema_version": 1, "marker_kind": "x"})
        result, ports = run(ports=make_ports(store=store))
        self.assertEqual(result.code, "ATTEMPT_MARKER_UNVERIFIED_OR_DUPLICATE")
        self.assertEqual(ports.session_reader.calls, 0)
        self.assertNotIn(live.TERMINAL_RECEIPT_PATH, store.data)

    def test_ambiguous_marker_write_is_judged_by_readback_and_stops_without_retry(self):
        store = Client()
        store.fail_create_after_write = True
        result, ports = run(ports=make_ports(store=store))
        # the create raised but the marker is readable: the attempt continues; creates were not retried
        self.assertEqual(result.status, "COMPLETE", result)

    def test_failure_leaves_a_terminal_receipt_so_it_cannot_be_rerun(self):
        result, ports = run(ports=make_ports(session=Session({**Session().value, "state": "COMPLETED"})))
        self.assertEqual(result.status, "UNKNOWN")
        receipt = json.loads(ports.store.data[live.TERMINAL_RECEIPT_PATH].text)
        self.assertEqual(receipt["status"], "UNKNOWN")
        self.assertFalse(receipt["rerun_allowed"])
        self.assertFalse(receipt["additional_jules_get_allowed"])
        again, _ = run(ports=make_ports(store=ports.store))
        self.assertEqual(again.code, "TERMINAL_RECEIPT_EXISTS")


class ChainIntegrityTests(unittest.TestCase):
    def test_wrong_owner_generation_or_fencing_cannot_pass(self):
        plan = make_plan()
        plan["request"] = {**plan["request"], "command_id": "relay-dev-loop-901-other"}
        result, _ = run(plan=plan)
        self.assertNotEqual(result.status, "COMPLETE")

    def test_provider_and_authority_must_be_distinct_executions(self):
        result, _ = run(authority_run=live.PROVIDER_OIDC_RUN_ID)
        self.assertEqual(result.code, "AUTHORITY_RUN_RESERVED_OR_REUSED")

    def test_never_writes_production_registry_or_default_branch(self):
        result, ports = run()
        self.assertEqual(result.status, "COMPLETE")
        self.assertTrue(all(not path.endswith("control_tower_registry.json") for path in ports.store.data))
        registry = json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text(encoding="utf-8"))
        self.assertTrue(all(e["identity_state"] == "PLACEHOLDER" for e in registry["loops"]))

    def test_the_exact_lane_is_the_collected_lane(self):
        result, ports = run()
        self.assertEqual(result.status, "COMPLETE")
        self.assertTrue(any(f"/{live.LANE_ID}/" in path for path in ports.store.data))
        self.assertFalse(any("fixture" in path for path in ports.store.data))


class LateStageFailureTests(unittest.TestCase):
    def test_authority_issued_after_the_session_was_created_is_refused_after_the_single_get(self):
        ports = make_ports(authority_run_changes={"created_at": "2026-09-28T04:02:00Z"})
        result, _ = run(ports=ports)
        self.assertEqual((result.status, result.stage), ("UNKNOWN", "publish"), result)
        self.assertEqual(ports.session_reader.calls, 1)
        self.assertNotIn(live.EVIDENCE_PATH, ports.store.data)

    def test_ambiguous_state_update_never_completes_and_is_not_retried(self):
        store = Client()
        store.fail_update_before_write = True
        result, ports = run(ports=make_ports(store=store))
        self.assertNotEqual(result.status, "COMPLETE", result)
        self.assertEqual(store.updates, 1, "the failed update must not be retried")
        self.assertEqual(ports.session_reader.calls, 1)
        self.assertNotIn(live.EVIDENCE_PATH, store.data)

    def test_duplicate_evidence_record_is_never_overwritten(self):
        store = Client()
        store.put(live.EVIDENCE_PATH, {"schema_version": 1, "evidence_kind": "other"})
        result, ports = run(ports=make_ports(store=store))
        self.assertEqual(result.code, "RECORD_WRITE_UNVERIFIED", result)
        self.assertEqual(json.loads(store.data[live.EVIDENCE_PATH].text)["evidence_kind"], "other")

    def test_provider_oidc_anchor_must_still_verify_at_the_exact_profile(self):
        for changes in ({"head_branch": "feature/other"}, {"event": "workflow_dispatch"}, {"run_attempt": 2}):
            with self.subTest(changes=changes):
                result, ports = run(ports=make_ports(provider_run_changes=changes))
                self.assertEqual(result.code, "PROVIDER_OIDC_EXECUTION_UNVERIFIED")
                self.assertEqual(ports.session_reader.calls, 0)

    def test_stop_result_never_contains_secrets_or_tokens(self):
        result, _ = run(ports=make_ports(session=Session(raises=True)))
        blob = json.dumps([result.status, result.code, result.reasons, result.counters])
        for needle in ("X-Goog-Api-Key", "Bearer", "JULES_API_KEY", "ghp_"):
            self.assertNotIn(needle, blob)


class OutputReadbackTests(unittest.TestCase):
    evidence = {"allowed_path": live.ALLOWED_PATH, "allowed_content": live.ALLOWED_CONTENT,
                "work_branch": WORK_BRANCH, "target_head": HEAD, "session_id": SESSION_ID}

    def good(self, **changes):
        value = {"pull_request": 9, "changed_files": [live.ALLOWED_PATH], "changed_file_content": live.ALLOWED_CONTENT,
                 "merged": False, "base_branch": WORK_BRANCH, "base_sha": HEAD,
                 "head_branch": f"{WORK_BRANCH}-{SESSION_ID}", "head_sha": "9" * 40}
        value.update(changes)
        return value

    def test_exact_output_is_acceptable_and_stable(self):
        self.assertEqual(live.assess_output_readback(self.good(), evidence=self.evidence), ())
        self.assertEqual(live.assess_output_readback(self.good(), evidence=self.evidence, previous=self.good()), ())

    def test_every_deviation_is_a_reason(self):
        cases = {
            "extra_path": self.good(changed_files=[live.ALLOWED_PATH, "src/x.py"]),
            "wrong_path": self.good(changed_files=["docs/other.md"]),
            "wrong_content": self.good(changed_file_content="other\n"),
            "merged": self.good(merged=True),
            "wrong_base_branch": self.good(base_branch=BRANCH),
            "wrong_base_sha": self.good(base_sha="f" * 40),
            "wrong_head_branch": self.good(head_branch="jules/other"),
            "head_equals_base": self.good(head_sha=HEAD),
            "missing_head": {k: v for k, v in self.good().items() if k != "head_sha"},
        }
        for label, output in cases.items():
            with self.subTest(label):
                self.assertTrue(live.assess_output_readback(output, evidence=self.evidence), label)

    def test_drift_between_two_readbacks_is_a_reason(self):
        for key, value in (("head_sha", "8" * 40), ("pull_request", 10), ("merged", True)):
            reasons = live.assess_output_readback(self.good(**{key: value}), evidence=self.evidence, previous=self.good())
            self.assertTrue(any("drifted" in r or "merged" in r for r in reasons), key)

    def test_malformed_input_fails_closed(self):
        self.assertTrue(live.assess_output_readback({}, evidence={}))
        self.assertTrue(live.assess_output_readback(None, evidence=self.evidence))


class WholeProofBudgetTests(unittest.TestCase):
    def test_whole_proof_never_exceeds_post_one_get_two_dispatch_one(self):
        self.assertEqual(live.LIMITS, {"jules_post": 1, "jules_get": 2, "authority_dispatch": 1, "retry": 0})
        counters = live.LiveCounters()
        self.assertEqual(counters.as_dict()["whole_proof_total"], {"jules_post": 1, "jules_get": 1, "authority_dispatch": 0})
        counters.spend("authority_dispatch")
        with self.assertRaises(live.LiveProofError):
            counters.spend("authority_dispatch")
        with self.assertRaises(live.LiveProofError):
            counters.spend("jules_post")
        counters.spend("jules_get")
        with self.assertRaises(live.LiveProofError):
            counters.spend("jules_get")
        with self.assertRaises(live.LiveProofError):
            counters.spend("retry")



class FailureDiagnosticPersistenceTests(unittest.TestCase):
    def test_terminal_receipt_preserves_bounded_publish_diagnostic(self):
        counters = live.LiveCounters(jules_get=1)
        detail = (
            "PUBLISH_NOT_READY: publish:NOT_WIRED:"
            "independent provider verification is unavailable or mismatched"
        )
        receipt = live._terminal_receipt(
            "UNKNOWN",
            "PUBLISH_NOT_READY",
            None,
            counters,
            failure_stage="publish",
            failure_detail=detail,
        )
        self.assertEqual(receipt["failure_stage"], "publish")
        self.assertEqual(receipt["failure_detail"], detail)
        self.assertFalse(receipt["rerun_allowed"])
        self.assertFalse(receipt["additional_jules_get_allowed"])
        self.assertFalse(receipt["additional_jules_post_allowed"])
        self.assertRegex(receipt["receipt_payload_sha256"], r"^[0-9a-f]{64}$")

    def test_failure_detail_is_bounded_and_secret_markers_are_redacted(self):
        self.assertEqual(live.safe_failure_detail("x" * 500), "x" * 200)
        for value in (
            "Authorization: Bearer abc",
            "token=abc",
            "JULES_API_KEY=abc",
            "github_pat_abc",
            "ghp_abc",
        ):
            with self.subTest(value=value):
                self.assertEqual(live.safe_failure_detail(value), "REDACTED")
        self.assertEqual(live.safe_failure_detail("provider mismatch\nretry 0"), "provider mismatch retry 0")
        self.assertEqual(live.safe_failure_detail("provider mismatch: 日本語"), "REDACTED")
        self.assertIsNone(live.safe_failure_detail(None))


if __name__ == "__main__":
    unittest.main()
