"""Unit contracts for result ingress, lineage, independent inspection and adoption."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import unittest

from automation.command_bus.claude_jules_adoption import SafeAdoption, adoption_receipt_path, lock_path
from automation.command_bus.claude_jules_dispatch import build_dispatch_intent, sha256_of
from automation.command_bus.claude_jules_inspection import (
    find_vacuous_tests, inspect_result, validate_inspection_record, validate_small_repair,
)
from automation.command_bus.claude_jules_result_event import (
    ResultEventInbox, normalize_pull_request_event, verify_github_signature, verify_result_lineage,
)
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    DATA, NOW, REPO, TARGET, GOOD_TEST, VACUOUS_TEST, FakeGitHub, policy, task_spec,
)
from automation.command_bus.claude_loop import (
    numbered_command_id, prepare_jules_semiauto_bundle, prepare_jules_semiauto_request, prepare_loop_claim,
)
from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.tests.test_claude_jules_dispatch_contract import intent, prepared

SESSION = "9000001"


def payload(**pr_overrides):
    work = intent()["carrier_request"]["work_branch"]
    repo = {"full_name": REPO}
    pr = {"number": 300, "state": "open", "merged": False,
          "body": f"x\n*PR created automatically by Jules for task [{SESSION}](https://jules.google.com/task/{SESSION}) started*",
          "base": {"ref": work, "repo": repo}, "head": {"ref": f"{work}-{SESSION}", "sha": "c" * 40, "repo": repo}}
    pr.update(pr_overrides)
    return {"action": "opened", "repository": repo, "pull_request": pr}


def redigest(event, **changes):
    record = dict(event, **changes)
    record.pop("event_sha256")
    record["event_sha256"] = sha256_of(record)
    return record


def normalized(**kw):
    return normalize_pull_request_event(event_name="pull_request", delivery_id="d-1", payload=payload(**kw), expected_repo=REPO)


class SignatureTests(unittest.TestCase):
    def test_github_hmac_sha256_signature(self):
        body, secret = b'{"a":1}', b"secret"
        good = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_github_signature(secret, body, good))
        self.assertFalse(verify_github_signature(b"wrong", body, good))
        self.assertFalse(verify_github_signature(secret, body + b" ", good))
        self.assertFalse(verify_github_signature(secret, body, good.replace("sha256=", "sha1=")))
        self.assertFalse(verify_github_signature(secret, body, None))
        self.assertFalse(verify_github_signature(b"", body, good))


class NormalizeTests(unittest.TestCase):
    def test_jules_result_is_normalized_with_deterministic_identity(self):
        result = normalized()
        self.assertEqual(result.status, "ACCEPTED")
        record = result.record
        self.assertEqual(record["id"], f"jules-result-pr300-{'c' * 40}")
        self.assertEqual((record["head_ref_session_id"], record["body_session_ids"]), (SESSION, [SESSION]))
        self.assertEqual(record["command_id"], intent()["carrier_request"]["command_id"])

    def test_unrelated_or_forged_events_never_reach_the_controller(self):
        work = intent()["carrier_request"]["work_branch"]
        fork = {"full_name": "evil/fork"}
        cases = {
            "IGNORED": [payload(base={"ref": "feature/x", "repo": {"full_name": REPO}}), payload(state="closed")],
            "REJECTED": [payload(head={"ref": f"{work}-{SESSION}", "sha": "c" * 40, "repo": fork}),
                         payload(head={"ref": "jules-work/other-1", "sha": "c" * 40, "repo": {"full_name": REPO}}),
                         payload(head={"ref": f"{work}-{SESSION}", "sha": "BAD", "repo": {"full_name": REPO}})],
        }
        for expected, payloads in cases.items():
            for item in payloads:
                result = normalize_pull_request_event(event_name="pull_request", delivery_id="d", payload=item, expected_repo=REPO)
                self.assertEqual(result.status, expected, item)
        closed = dict(payload(), action="closed")
        self.assertEqual(normalize_pull_request_event(event_name="pull_request", delivery_id="d", payload=closed, expected_repo=REPO).status, "IGNORED")
        self.assertEqual(normalize_pull_request_event(event_name="push", delivery_id="d", payload=payload(), expected_repo=REPO).status, "IGNORED")
        self.assertEqual(normalize_pull_request_event(event_name="pull_request", delivery_id="bad id!", payload=payload(), expected_repo=REPO).status, "REJECTED")
        self.assertEqual(normalize_pull_request_event(event_name="pull_request", delivery_id="d", payload=payload(), expected_repo="x/y").status, "REJECTED")

    def test_inbox_conflicting_record_for_same_id_is_blocked(self):
        gh = FakeGitHub()
        inbox = ResultEventInbox(gh, data_branch=DATA)
        record = normalized().record
        self.assertEqual(inbox.record(record).status, "RECORDED")
        forged = dict(record, command_id="relay-dev-loop-001-other")
        self.assertEqual(inbox.record(forged).status, "BLOCKED")


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.intent = intent()
        self.event = normalized().record
        self.receipt = {"state": "DISPATCHED", "intent_sha256": self.intent["intent_sha256"],
                        "command_id": self.intent["carrier_request"]["command_id"]}
        self.obs = {"command_id": self.event["command_id"], "workflow_run_id": "run-1", "conclusion": "success", "session_id": SESSION}
        self.pr = {"number": 300, "state": "open", "merged": False, "base_ref": self.event["base_ref"], "head_sha": "c" * 40,
                   "head_ref": self.event["head_ref"], "body": payload()["pull_request"]["body"]}

    def check(self, **kw):
        args = dict(intent=self.intent, dispatch_receipt=self.receipt, dispatch_observation=self.obs, fresh_pr=self.pr)
        args.update(kw)
        return verify_result_lineage(kw.pop("event", self.event), **{k: v for k, v in args.items() if k != "event"}).status

    def test_lineage_pass_and_failure_matrix(self):
        self.assertEqual(self.check(), "PASS")
        self.assertEqual(self.check(dispatch_observation=None), "UNKNOWN")
        self.assertEqual(self.check(dispatch_observation=dict(self.obs, session_id="1")), "BLOCKED")
        self.assertEqual(self.check(dispatch_observation=dict(self.obs, conclusion="failure")), "UNKNOWN")
        self.assertEqual(self.check(dispatch_receipt=None), "UNKNOWN")
        self.assertEqual(self.check(dispatch_receipt=dict(self.receipt, intent_sha256="0" * 64)), "BLOCKED")
        self.assertEqual(self.check(fresh_pr=dict(self.pr, head_sha="d" * 40)), "STALE")
        self.assertEqual(self.check(fresh_pr=dict(self.pr, merged=True)), "BLOCKED")
        self.assertEqual(self.check(fresh_pr=dict(self.pr, state="closed")), "STALE")
        self.assertEqual(self.check(event=redigest(self.event, body_session_ids=["1"])), "BLOCKED")
        self.assertEqual(self.check(event=redigest(self.event, head_ref_session_id="1",
                                                   head_ref=self.event["base_ref"] + "-1")), "BLOCKED")
        self.assertEqual(self.check(fresh_pr=dict(self.pr, head_ref=self.event["base_ref"] + "-77")), "BLOCKED")
        self.assertEqual(self.check(fresh_pr=dict(self.pr, body="no footer")), "BLOCKED")
        self.assertEqual(self.check(fresh_pr=dict(self.pr, body=self.pr["body"] + " https://jules.google.com/task/5)")), "BLOCKED")
        # A stored record edited without its digest is rejected outright.
        self.assertEqual(self.check(event=dict(self.event, pr_number=301)), "BLOCKED")
        self.assertEqual(self.check(event=redigest(self.event, body_session_ids=[])), "UNKNOWN")
        self.assertEqual(self.check(event=dict(self.event, command_id="relay-dev-loop-001-x")), "BLOCKED")


class VacuousTests(unittest.TestCase):
    def test_detector(self):
        self.assertEqual(find_vacuous_tests({"t.py": GOOD_TEST}), [])
        self.assertEqual(len(find_vacuous_tests({"t.py": VACUOUS_TEST})), 1)
        for src in ("def test_a():\n    pass\n", "def test_a():\n    x = 1\n", "def test_a():\n    assert True\n",
                    "def test_a():\n    '''doc'''\n"):
            self.assertEqual(len(find_vacuous_tests({"t.py": src})), 1, src)
        helper = "def test_a(self):\n    self.check_roundtrip(1)\n"
        raises = "def test_a(self):\n    with self.assertRaises(ValueError):\n        f()\n"
        self.assertEqual(find_vacuous_tests({"t.py": helper, "u.py": raises}), [])
        self.assertEqual(find_vacuous_tests({"t.py": "def test_a(:\n"})[0]["category"], "test_failure")


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.intent, self.spec = intent(), task_spec()
        req = self.intent["carrier_request"]
        self.head = "c" * 40
        self.lineage = {"command_id": req["command_id"], "session_id": SESSION, "workflow_run_id": "r", "candidate_head": self.head}
        self.compare = {"base_sha": req["expected_target_head"], "merge_base": req["expected_target_head"], "head_sha": self.head,
                        "ahead_by": 1, "behind_by": 0,
                        "files": [{"path": p["path"], "status": "added"} for p in self.spec["allowed_paths"]]}
        self.tests = {"head_sha": self.head, "tree_sha": "e" * 40, "tests_run": 10, "exit_code": 0, "failures": 0, "errors": 0}
        self.obs = {n: {"result": "PASS", "evidence": "direct"} for n in self.spec["acceptance_checks"] + ["negative_cases_exercised", "regression_suite_reviewed"]}

    def run_inspect(self, **kw):
        args = dict(intent=self.intent, task_spec=self.spec, lineage=self.lineage, compare=self.compare, candidate_tree="e" * 40,
                    test_evidence=self.tests, changed_test_sources={"t.py": GOOD_TEST}, acceptance_observations=self.obs,
                    reviewer_findings=[], prior_inspections=[], inspected_at=NOW)
        args.update(kw)
        return inspect_result(**args)

    def test_pass_requires_every_independent_check(self):
        outcome = self.run_inspect()
        self.assertEqual((outcome.verdict, outcome.decision), ("PASS", "ADOPT_CANDIDATE"))
        self.assertFalse(outcome.record["self_report_used"])
        self.assertEqual(len([c for c in outcome.record["checks"] if c["state"] == "PASS"]), len(outcome.record["checks"]))

    def test_missing_evidence_is_unknown_not_pass(self):
        for kw in ({"test_evidence": None}, {"test_evidence": dict(self.tests, head_sha="d" * 40)},
                   {"acceptance_observations": {}}, {"changed_test_sources": None}, {"lineage": None},
                   {"compare": None}, {"candidate_tree": None},
                   {"acceptance_observations": dict(self.obs, helper_exact_value={"result": "PASS", "evidence": " "})}):
            outcome = self.run_inspect(**kw)
            self.assertEqual((outcome.verdict, outcome.decision), ("UNKNOWN", "INVESTIGATE"), kw)

    def test_fence_ancestry_delete_and_test_failures_need_jules_corrective(self):
        outside = dict(self.compare, files=self.compare["files"] + [{"path": "README.md", "status": "modified"}])
        deleted = dict(self.compare, files=[{"path": self.spec["allowed_paths"][0]["path"], "status": "removed"}])
        behind = dict(self.compare, behind_by=1)
        for kw in ({"compare": outside}, {"compare": deleted}, {"compare": behind},
                   {"test_evidence": dict(self.tests, exit_code=1, failures=2)},
                   {"reviewer_findings": [{"category": "semantic_gap", "detail": "x"}]}):
            outcome = self.run_inspect(**kw)
            self.assertEqual((outcome.verdict, outcome.decision), ("FAIL_MAJOR", "JULES_CORRECTIVE"), kw)

    def test_minor_findings_select_small_repair_and_repeats_escalate(self):
        path = self.spec["allowed_paths"][1]["path"]
        minor = self.run_inspect(changed_test_sources={path: VACUOUS_TEST})
        self.assertEqual(minor.decision, "CLAUDE_SMALL_REPAIR")
        unknown_cat = self.run_inspect(reviewer_findings=[{"category": "mystery", "detail": "x"}])
        self.assertEqual(unknown_cat.decision, "INVESTIGATE")
        prior = [{"task_id": "alpha-helper", "verdict": "FAIL_MAJOR"}]
        major = self.run_inspect(reviewer_findings=[{"category": "semantic_gap", "detail": "x"}], prior_inspections=prior)
        self.assertEqual(major.decision, "JULES_CORRECTIVE_REDUCED")
        stop = self.run_inspect(reviewer_findings=[{"category": "semantic_gap", "detail": "x"}], prior_inspections=prior * 2)
        self.assertEqual(stop.decision, "STOP_HUMAN")

    def test_small_repair_gate(self):
        path = self.spec["allowed_paths"][1]["path"]
        record = self.run_inspect(changed_test_sources={path: VACUOUS_TEST}).record
        ok = {"base_sha": self.head, "behind_by": 0, "files": [{"path": path, "status": "modified"}]}
        self.assertEqual(validate_small_repair(inspection=record, task_spec=self.spec, repair_compare=ok, repairs_already_made=0)[0], "PASS")
        for compare, made in ((dict(ok, base_sha="f" * 40), 0), (dict(ok, files=[{"path": "README.md", "status": "modified"}]), 0),
                              (dict(ok, files=[{"path": path, "status": "removed"}]), 0), (ok, 1), (dict(ok, files=[]), 0)):
            self.assertEqual(validate_small_repair(inspection=record, task_spec=self.spec, repair_compare=compare,
                                                   repairs_already_made=made)[0], "BLOCKED")


    def test_stored_inspection_record_is_revalidated_fail_closed(self):
        path = self.spec["allowed_paths"][1]["path"]
        record = self.run_inspect(changed_test_sources={path: VACUOUS_TEST}).record
        self.assertIs(validate_inspection_record(record), record)

        def resealed(**changes):
            r = dict(record, **changes)
            r.pop("inspection_sha256")
            r["inspection_sha256"] = sha256_of(r)
            return r
        bad = [
            dict(record, verdict="PASS"),                                     # undigested tamper
            resealed(verdict="PASS", decision="ADOPT_CANDIDATE"),             # PASS with findings
            resealed(decision="ADOPT_CANDIDATE"),                             # verdict/decision mismatch
            resealed(self_report_used=True),
            {k: v for k, v in record.items() if k != "checks"},
            "not a record",
        ]
        for value in bad:
            with self.assertRaises(ValueError):
                validate_inspection_record(value)


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        snapshot = self.gh.branches[TARGET]
        self.candidate = self.gh.child(snapshot, {"automation/command_bus/alpha.py": "x"}, "jules")
        # Build an intent whose snapshot is the fake target head.
        tree = self.gh.get_commit_tree(snapshot)
        p = copy.deepcopy(prepared())
        p["expected_target_head"], p["expected_target_tree"] = snapshot, tree
        common = dict(target_branch=TARGET, default_branch="main", created_at=NOW, command_id=numbered_command_id(778, "alpha-helper"))
        request = prepare_jules_semiauto_request(p, **common).request
        claim = prepare_loop_claim(request, lane_id="J-BLUE", claimed_at=NOW).request
        b = prepare_jules_semiauto_bundle(p, claim, **common).request
        self.intent = build_dispatch_intent(origin_loop_id=p["loop_id"], origin_round=1, origin_correlation_id=p["correlation_id"],
                                            origin_generation=1, attempt=1, task_id="alpha-helper", task_spec_sha256=sha256_of(task_spec()),
                                            carrier_request=b["carrier_request"], carrier_claim=claim, origin_binding=b["origin_binding"], prepared_at=NOW)
        self.inspection = {"verdict": "PASS", "decision": "ADOPT_CANDIDATE", "intent_sha256": self.intent["intent_sha256"],
                           "command_id": request["command_id"], "candidate_head": self.candidate,
                           "candidate_tree": self.gh.get_commit_tree(self.candidate), "inspection_sha256": "1" * 64, "task_id": "alpha-helper"}

    def adopt(self, inspection=None, intent_record=None):
        return SafeAdoption(client=self.gh, refs=self.gh, policy=policy()).adopt(
            intent=intent_record or self.intent, inspection=inspection or self.inspection, adopted_at=NOW)

    def test_adoption_is_ff_only_and_read_back(self):
        result = self.adopt()
        self.assertEqual(result.status, "ADOPTED")
        self.assertEqual(self.gh.branches[TARGET], self.candidate)
        self.assertEqual(self.adopt().status, "NO-OP")

    def test_non_pass_tampered_or_drifted_candidates_are_refused(self):
        for bad in (dict(self.inspection, verdict="FAIL_MINOR"), dict(self.inspection, intent_sha256="0" * 64),
                    dict(self.inspection, candidate_tree="0" * 40)):
            self.assertEqual(self.adopt(inspection=bad).status, "BLOCKED")
        outside = self.gh.child(self.gh.branches[TARGET], {"README.md": "changed"}, "outside")
        self.assertEqual(self.adopt(inspection=dict(self.inspection, candidate_head=outside,
                                                     candidate_tree=self.gh.get_commit_tree(outside))).status, "BLOCKED")
        self.assertEqual(self.gh.branches[TARGET], self.intent["carrier_request"]["expected_target_head"])

    def test_adoption_is_serialized_per_canonical_head(self):
        # A second controller already locked this canonical HEAD for another command.
        path = lock_path(TARGET, self.intent["carrier_request"]["expected_target_head"])
        self.gh.files[(DATA, path)] = GitHubContent(path, json.dumps({"command_id": "relay-dev-loop-779-alpha-helper"}), "s")
        self.assertEqual(self.adopt().status, "BLOCKED")
        self.assertEqual(self.gh.branches[TARGET], self.intent["carrier_request"]["expected_target_head"])

    def test_existing_receipt_is_reverified_not_trusted(self):
        self.assertEqual(self.adopt().status, "ADOPTED")
        path = adoption_receipt_path(self.intent["carrier_request"]["command_id"])
        good = self.gh.files[(DATA, path)]
        for change in ({"head_after": "e" * 40}, {"command_id": "relay-dev-loop-779-alpha-helper"}, {"force_push": True}):
            record = dict(json.loads(good.text), **change)
            self.gh.files[(DATA, path)] = GitHubContent(path, json.dumps(record), "s")
            self.assertEqual(self.adopt().status, "UNKNOWN", change)
        self.gh.files[(DATA, path)] = GitHubContent(path, "{not json", "s")
        self.assertEqual(self.adopt().status, "UNKNOWN")
        self.gh.files[(DATA, path)] = good
        self.assertEqual(self.adopt().status, "NO-OP")
        self.assertEqual(len([w for w in self.gh.writes if w[0] == "ff"]), 1)


if __name__ == "__main__":
    unittest.main()
