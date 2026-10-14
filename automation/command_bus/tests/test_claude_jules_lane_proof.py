"""STATIC tests of the Claude -> Jules stable-lane proof plan, runtime facts, receipt and adoption contract.

Fixture-only end to end: Claude runtime facts -> durable export -> existing collector -> accepted transition ->
lane registration READY -> proof terminal receipt -> adoption candidate -> prepared (never issued) approval.
No network, no Jules POST/GET, no provider execution, no issuer dispatch, no registry or Issue write, no LIVE.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus import claude_jules_lane_proof as proof
from automation.command_bus import lane_runtime_export as lre
from automation.command_bus.control_tower_durable_collector import ControlTowerDurableCollector
from automation.command_bus.control_tower_registration import (
    assess_lane_registration_readiness, assess_registration_readiness)
from automation.command_bus.lane_identity_adoption import registry_digest
from automation.command_bus.tests.test_lane_runtime_export import (
    HEAD, NOW, PROD, REPO, TREE, FakeClient, FakeClock, FakeTarget, adopted_registry)

ROOT = Path(__file__).resolve().parents[3]
LANE = proof.LANE_ID
OWNER = "20355232"
FORBIDDEN_SESSIONS = ["301196275118188780", "5943440322658150300", "11944164406087664763", "569271609782168660",
                      "7218641455365522473"]
AUTH = {"approved_by": "owner", "approval_ref": "cmsg_fixture_live_approval", "scope": "claude-jules-auto proof 1",
        "max_dispatches": 1, "expires_at": "2026-10-05T10:00:00Z"}


def plan(**changes):
    value = dict(origin_loop_id="claude-auto-origin-1", origin_generation=1, repository=REPO, default_branch="main",
                 target_branch="fixture/claude-target", target_pr=400, target_head=HEAD, target_tree=TREE,
                 allowed_path="docs/evidence/claude-jules-proof-1/PROOF.md", allowed_content="claude jules proof 1\n",
                 expires_at="2026-10-05T12:00:00Z", forbidden_session_ids=FORBIDDEN_SESSIONS)
    value.update(changes)
    return proof.build_proof_plan(**value)


def dispatch_receipt(p, **changes):
    value = {"schema_version": 1, "profile": "CLAUDE_AUTO_DISPATCH_RECEIPT_V1", "command_id": "relay-dev-loop-140-claude-proof",
             "intent_id": "claude-auto-origin-1-r1-g1-a1", "intent_sha256": "d" * 64, "origin_loop_id": p["origin_loop_id"],
             "origin_round": 1, "origin_generation": 1, "loop_id": "loop-140", "lane_id": "J-GREEN",
             "target_branch": p["target_branch"], "work_branch": "jules-work/relay-dev-loop-140-claude-proof",
             "expected_target_head": p["target_head"], "expected_target_tree": p["target_tree"], "state": "DISPATCHED",
             "reason": "fixture", "retry_count": 0, "fallback_used": False}
    value.update(changes)
    return value


def session(**changes):
    value = {"session_id": "8123456789012345678", "provider_raw_state": "IN_PROGRESS",
             "starting_branch": "jules-work/relay-dev-loop-140-claude-proof", "create_time": "2026-10-04T09:05:00Z",
             "update_time": "2026-10-04T09:25:00Z"}
    value.update(changes)
    return value


def facts(p=None, **changes):
    p = p or plan(live_authorization=AUTH)
    kwargs = dict(dispatch_receipt=dispatch_receipt(p), session=session(), holder_id="claude-auto",
                  claimed_at="2026-10-04T09:00:00Z", expires_at="2026-10-04T11:00:00Z",
                  observed_at="2026-10-04T09:30:00Z", observation_expires_at="2026-10-04T10:30:00Z")
    kwargs.update(changes)
    return proof.runtime_facts_from_dispatch(p, **kwargs)


def context(**changes):
    value = {"loop_id": LANE, "id_owner": proof.ID_OWNER, "correlation_id": "claude-jules-corr-claude-auto-origin-1-r1-g1-a1",
             "target_pr": 400}
    value.update(changes)
    return value


REQUEST = {"origin_loop_id": "claude-auto-origin-1", "command_id": "relay-dev-loop-140-claude-proof",
           "target_branch": "fixture/claude-target", "target_repo": REPO}


def run_pipeline(p=None, registry=None):
    p = p or plan(live_authorization=AUTH)
    candidate_registry = registry or adopted_registry("claude-jules")
    exported = lre.export_lane_runtime("claude-jules", registry=candidate_registry, request=REQUEST,
                                       durable_context=context(), runtime_facts=facts(p))
    collector = ControlTowerDurableCollector(FakeClient(dict(exported.chain_files)), ref="fixture",
                                             target_reader=FakeTarget(), clock=FakeClock())
    collection = collector.collect_transition(LANE)
    return p, exported, collection, candidate_registry


class PlanTests(unittest.TestCase):
    def test_plan_is_valid_but_unauthorized_without_a_human_authorization(self):
        p = plan()
        self.assertIsNone(p["live_authorization"])
        proof.validate_proof_plan(p, registry=PROD)
        with self.assertRaises(proof.ProofError) as caught:
            proof.validate_proof_plan(p, registry=PROD, now=NOW.replace("+00:00", "Z"), require_authorized=True)
        self.assertEqual(caught.exception.code, "PLAN_UNAUTHORIZED")

    def test_authorized_plan_passes_only_inside_its_window(self):
        p = plan(live_authorization=AUTH)
        proof.validate_proof_plan(p, registry=PROD, now="2026-10-04T10:00:00Z", require_authorized=True)
        for late in ("2026-10-05T10:00:00Z", "2026-10-06T00:00:00Z"):
            with self.assertRaises(proof.ProofError):
                proof.validate_proof_plan(p, registry=PROD, now=late, require_authorized=True)

    def test_plan_pins_one_dispatch_and_the_budget(self):
        p = plan()
        self.assertEqual(p["limits"], {"jules_post": 1, "jules_get": 1, "live_budget_slots": 1, "retry": 0})
        self.assertEqual(p["loop_a_slots_used_before"], 4)
        self.assertEqual((p["retry"], p["fallback"]), (0, "disabled"))
        self.assertEqual(p["forbidden_loop_numbers"], [128, 129, 130, 131])

        p9 = plan(loop_a_slots_used_before=9)
        self.assertEqual(p9["loop_a_slots_used_before"], 9)
        self.assertEqual(proof.validate_proof_plan(p9, registry=PROD)["loop_a_slots_used_before"], 9)

    def test_every_tamper_is_rejected(self):
        base = plan(live_authorization=AUTH)

        def tampered(**changes):
            value = {**copy.deepcopy(base), **changes}
            value["plan_sha256"] = proof._digest(value, "plan_sha256")  # a re-signed tamper must still fail its own rule
            return value
        cases = {
            "lane": tampered(lane_id="chatgpt-semi-auto"), "owner": tampered(id_owner="CHAT_LED_SEMI_AUTO_RUNTIME"),
            "limits": tampered(limits={"jules_post": 2, "jules_get": 1, "live_budget_slots": 1, "retry": 0}),
            "retry": tampered(retry=1), "fallback": tampered(fallback="paid"),
            "budget": tampered(loop_a_slots_used_before=10), "loops": tampered(forbidden_loop_numbers=[]),
            "origin is lane": tampered(origin_loop_id=LANE), "origin numeric": tampered(origin_loop_id="136"),
            "default branch": tampered(target_branch="main"), "head": tampered(target_head="zz"),
            "pr": tampered(target_pr=0), "auth max": tampered(live_authorization={**AUTH, "max_dispatches": 2}),
            "auth outlives": tampered(live_authorization={**AUTH, "expires_at": "2026-10-09T00:00:00Z"}),
        }
        for name, bad in cases.items():
            with self.assertRaises(proof.ProofError, msg=name):
                proof.validate_proof_plan(bad, registry=None)
        broken = copy.deepcopy(base); broken["target_head"] = "c" * 40  # digest no longer matches
        with self.assertRaises(proof.ProofError):
            proof.validate_proof_plan(broken, registry=None)
        extra = {**copy.deepcopy(base), "extra": 1}
        with self.assertRaises(proof.ProofError):
            proof.validate_proof_plan(extra, registry=None)

    def test_registry_row_must_be_an_enabled_placeholder(self):
        with self.assertRaises(proof.ProofError) as caught:
            proof.validate_proof_plan(plan(), registry=adopted_registry("claude-jules"))
        self.assertEqual(caught.exception.code, "PLAN_REGISTRY_ROW")
        no_row = {"schema_version": 1, "loops": [e for e in PROD["loops"] if e["loop_id"] != LANE]}
        with self.assertRaises(proof.ProofError):
            proof.validate_proof_plan(plan(), registry=no_row)


class RuntimeFactsTests(unittest.TestCase):
    def test_facts_carry_the_stable_id_and_keep_loop_number_as_evidence(self):
        f = facts()
        self.assertEqual(f["stable_lane_id"], LANE)
        self.assertEqual(f["owner_events"][0]["owner_role"], "AUTO")
        self.assertEqual(f["worker_evidence"]["loop_number"], "loop-140")
        identity = [f["state"]["loop_id"], f["receipt"]["loop_id"], f["provider_observation"]["loop_id"],
                    *[e["loop_id"] for e in f["owner_events"]]]
        self.assertEqual(set(identity), {LANE})  # the Loop number only appears inside transport ids and worker evidence

    def test_refused_dispatches_and_sessions(self):
        p = plan(live_authorization=AUTH)
        bad = {
            "not dispatched": dict(dispatch_receipt=dispatch_receipt(p, state="BLOCKED")),
            "other origin": dict(dispatch_receipt=dispatch_receipt(p, origin_loop_id="someone-else")),
            "other head": dict(dispatch_receipt=dispatch_receipt(p, expected_target_head="c" * 40)),
            "retry": dict(dispatch_receipt=dispatch_receipt(p, retry_count=1)),
            "fallback": dict(dispatch_receipt=dispatch_receipt(p, fallback_used=True)),
            "spent loop 130": dict(dispatch_receipt=dispatch_receipt(p, loop_id="loop-130")),
            "old session 132": dict(session=session(session_id="301196275118188780")),
            "proof 5 session": dict(session=session(session_id="7218641455365522473")),
            "terminal provider": dict(session=session(provider_raw_state="COMPLETED")),
            "other branch": dict(session=session(starting_branch="jules-work/other")),
            "non numeric session": dict(session=session(session_id="abc")),
        }
        for name, changes in bad.items():
            with self.assertRaises(proof.ProofError, msg=name):
                facts(p, **changes)

    def test_a_stable_id_taken_from_the_loop_number_is_refused_by_the_exporter(self):
        p = plan(live_authorization=AUTH)
        f = facts(p)
        f["stable_lane_id"] = "loop-140"
        with self.assertRaises(lre.ExportError):
            lre.export_lane_runtime("claude-jules", registry=adopted_registry("claude-jules"), request=REQUEST,
                                    durable_context=context(), runtime_facts=f)


class EndToEndTests(unittest.TestCase):
    def test_full_fixture_pipeline_reaches_a_prepared_candidate(self):
        p, exported, collection, candidate_registry = run_pipeline()
        self.assertEqual((collection.status, collection.transition.status), ("COLLECTED", "VALID"))
        self.assertEqual(collection.transition.projection.owner, "AUTO")
        registration = assess_lane_registration_readiness(candidate_registry, LANE, collection.transition)
        self.assertEqual(registration.status, "READY")
        receipt = proof.build_terminal_receipt(
            p, status="COMPLETE", code="OK", export_summary=exported.summary, lane_registration=registration.status,
            counters={"jules_post": 1, "jules_get": 1, "live_budget_slots": 1, "retry": 0})
        self.assertFalse(receipt["rerun_allowed"])
        candidate = proof.build_adoption_candidate(p, receipt, current_registry=PROD, proposed_registry=candidate_registry)
        self.assertEqual((candidate["registry_write_allowed"], candidate["human_approval_required"]), (False, True))
        approval = proof.prepare_adoption_approval(
            candidate, approved_by_actor_id=OWNER, approved_at="2026-10-04T10:00:00Z", valid_until="2026-10-05T10:00:00Z",
            approval_run_id="37999999999")
        self.assertEqual(proof.validate_adoption_approval(
            approval, candidate=candidate, current_registry=PROD, proposed_registry=candidate_registry,
            allowed_approver_ids=frozenset({OWNER}), now="2026-10-04T12:00:00Z"), LANE)
        # nothing was written and the production file still says PLACEHOLDER
        self.assertEqual(next(e for e in PROD["loops"] if e["loop_id"] == LANE)["identity_state"], "PLACEHOLDER")
        self.assertEqual(assess_registration_readiness(candidate_registry, {LANE: collection.transition}).status, "NOT_WIRED")

    def test_production_placeholder_row_never_reaches_ready(self):
        with self.assertRaises(ValueError):
            run_pipeline(registry=PROD)

    def test_complete_receipt_needs_ready_registration_and_obeys_the_budget(self):
        p, exported, collection, _ = run_pipeline()
        ok = {"jules_post": 1, "jules_get": 1, "live_budget_slots": 1, "retry": 0}
        with self.assertRaises(proof.ProofError):
            proof.build_terminal_receipt(p, status="COMPLETE", code="X", export_summary=exported.summary,
                                         lane_registration="NOT_WIRED", counters=ok)
        with self.assertRaises(proof.ProofError):
            proof.build_terminal_receipt(p, status="COMPLETE", code="X", export_summary=None, lane_registration="READY", counters=ok)
        for name in ok:
            with self.assertRaises(proof.ProofError, msg=name):
                proof.build_terminal_receipt(p, status="UNKNOWN", code="X", export_summary=None, lane_registration="NOT_WIRED",
                                             counters={**ok, name: ok[name] + 1})
        unknown = proof.build_terminal_receipt(p, status="UNKNOWN", code="PROVIDER_NOT_ACTIVE", export_summary=None,
                                               lane_registration="NOT_WIRED", counters=ok)
        self.assertFalse(unknown["rerun_allowed"])
        with self.assertRaises(proof.ProofError):  # an UNKNOWN proof can never become an adoption candidate
            proof.build_adoption_candidate(p, unknown, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"))


class AdoptionContractTests(unittest.TestCase):
    def setUp(self):
        self.p, exported, collection, self.proposed = run_pipeline()
        self.receipt = proof.build_terminal_receipt(
            self.p, status="COMPLETE", code="OK", export_summary=exported.summary, lane_registration="READY",
            counters={"jules_post": 1, "jules_get": 1, "live_budget_slots": 1, "retry": 0})
        self.candidate = proof.build_adoption_candidate(self.p, self.receipt, current_registry=PROD, proposed_registry=self.proposed)
        self.approval = proof.prepare_adoption_approval(
            self.candidate, approved_by_actor_id=OWNER, approved_at="2026-10-04T10:00:00Z",
            valid_until="2026-10-05T10:00:00Z", approval_run_id="37999999999")

    def check(self, approval=None, **kw):
        args = dict(candidate=self.candidate, current_registry=PROD, proposed_registry=self.proposed,
                    allowed_approver_ids=frozenset({OWNER}), now="2026-10-04T12:00:00Z")
        args.update(kw)
        return proof.validate_adoption_approval(approval if approval is not None else self.approval, **args)

    def test_valid_approval_passes_and_missing_approval_fails(self):
        self.assertEqual(self.check(), LANE)
        for missing in (None, {}, "x"):
            with self.assertRaises(proof.ProofError):
                proof.validate_adoption_approval(missing, candidate=self.candidate, current_registry=PROD,
                                                 proposed_registry=self.proposed, allowed_approver_ids=frozenset({OWNER}),
                                                 now="2026-10-04T12:00:00Z")

    def test_wrong_digests_are_rejected(self):
        for key in ("candidate_sha256", "terminal_receipt_sha256", "evidence_sha256", "current_registry_sha256",
                    "proposed_registry_sha256"):
            with self.assertRaises(proof.ProofError, msg=key):
                self.check({**self.approval, key: "0" * 64})

    def test_chat_jules_approval_run_and_identity_proof_runs_are_not_approvals(self):
        for run in ("37155730052", "37150285702", "36981004299", "37031275812"):
            bad = {**self.approval, "approval_id": f"adopt-durable-{LANE}-{run}", "approval_ref": f"github-actions:run/{run}"}
            with self.assertRaises(proof.ProofError) as caught:
                self.check(bad)
            self.assertEqual(caught.exception.code, "APPROVAL_RUN_NOT_AN_APPROVAL", run)

    def test_other_lane_actor_expiry_replay_and_retry_are_rejected(self):
        cases = [{**self.approval, "lane_id": "chatgpt-semi-auto"}, {**self.approval, "approved_by_actor_id": "1"},
                 {**self.approval, "retry": 1}, {**self.approval, "fallback": "paid"}, {**self.approval, "decision": "ADOPT"},
                 {**self.approval, "approval_run_attempt": 2}, {**self.approval, "extra": 1}]
        for bad in cases:
            with self.assertRaises(proof.ProofError):
                self.check(bad)
        with self.assertRaises(proof.ProofError):
            self.check(now="2026-10-06T00:00:00Z")
        with self.assertRaises(proof.ProofError):
            self.check(now="2026-10-04T09:00:00Z")
        with self.assertRaises(proof.ProofError):
            self.check(applied_approval_ids=frozenset({self.approval["approval_id"]}))

    def test_registry_changes_beyond_one_lane_are_rejected(self):
        second = copy.deepcopy(self.proposed)
        for row in second["loops"]:
            if row["loop_id"] == "chat-work-semi-auto":
                row["identity_state"] = "DURABLE"
        with self.assertRaises(proof.ProofError):
            proof.build_adoption_candidate(self.p, self.receipt, current_registry=PROD, proposed_registry=second)
        renamed = copy.deepcopy(self.proposed)
        next(r for r in renamed["loops"] if r["loop_id"] == LANE)["display_name"] = "Other name"
        with self.assertRaises(proof.ProofError):
            proof.build_adoption_candidate(self.p, self.receipt, current_registry=PROD, proposed_registry=renamed)

    def test_candidate_is_bound_to_the_exact_registries(self):
        self.assertEqual(self.candidate["current_registry_sha256"], registry_digest(PROD))
        self.assertEqual(self.candidate["proposed_registry_sha256"], registry_digest(self.proposed))
        drifted = copy.deepcopy(PROD)
        drifted["loops"][1]["display_name"] = "Drift"
        with self.assertRaises(proof.ProofError):
            self.check(current_registry=drifted)


class RecoveryAndBoundaryTests(unittest.TestCase):
    def test_a_failed_proof_is_terminal_and_cannot_be_rerun_or_adopted(self):
        p = plan(live_authorization=AUTH)
        for status in ("STOPPED", "UNKNOWN"):
            receipt = proof.build_terminal_receipt(p, status=status, code="PROVIDER_NOT_ACTIVE", export_summary=None,
                                                   lane_registration="NOT_WIRED",
                                                   counters={"jules_post": 1, "jules_get": 1, "live_budget_slots": 1, "retry": 0})
            self.assertFalse(receipt["rerun_allowed"])
            self.assertFalse(receipt["production_registry_written"] or receipt["issue33_written"])
            with self.assertRaises(proof.ProofError):
                proof.build_adoption_candidate(p, receipt, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"))

    def test_module_has_no_io_or_dispatch(self):
        text = (ROOT / "automation/command_bus/claude_jules_lane_proof.py").read_text(encoding="utf-8")
        for forbidden in ("urllib", "requests", "http.client", "subprocess", "socket", "open(", "workflow_dispatch"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_chat_jules_modules_are_unchanged_by_this_work(self):
        self.assertEqual(proof.check_single_lane_diff.__module__, "automation.command_bus.durable_adoption_approval")


class FakePorts:
    """In-memory ports: create-only store + collector over the same store. Counts every call."""

    def __init__(self, p, *, dispatch_state="DISPATCHED", session_error=None, session_state="IN_PROGRESS",
                 marker_exists=False, now="2026-10-04T10:00:00Z"):
        self.p, self.files, self.calls = p, {}, []
        self.dispatch_state, self.session_error, self.session_state, self.clock = dispatch_state, session_error, session_state, now
        if marker_exists:
            self.files[proof.ATTEMPT_MARKER_PATH] = {"already": True}

    def create_once(self, path, document):
        self.calls.append(("create_once", path))
        if path in self.files:
            return "EXISTS"
        self.files[path] = copy.deepcopy(document)
        return "CREATED"

    def dispatch(self, plan_):
        self.calls.append(("dispatch",))
        return dispatch_receipt(self.p, state=self.dispatch_state)

    def read_session(self, receipt):
        self.calls.append(("read_session",))
        if self.session_error:
            raise self.session_error
        return session(provider_raw_state=self.session_state)

    def collect(self, loop_id):
        self.calls.append(("collect",))
        chain = {k: v for k, v in self.files.items() if k.startswith("automation/")}
        return ControlTowerDurableCollector(FakeClient(chain), ref="fixture", target_reader=FakeTarget(),
                                            clock=FakeClock()).collect_transition(loop_id)

    def now(self):
        return self.clock

    def count(self, name):
        return sum(1 for c in self.calls if c[0] == name)


class DriverTests(unittest.TestCase):
    def run_it(self, p=None, **port_kw):
        p = p or plan(live_authorization=AUTH)
        ports = FakePorts(p, **port_kw)
        result = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        return p, ports, result

    def test_success_path_is_exactly_one_post_one_get_and_a_prepared_candidate(self):
        _, ports, result = self.run_it()
        self.assertEqual((result.status, result.code), ("COMPLETE", "OK"))
        self.assertEqual(result.counters, {"jules_post": 1, "jules_get": 1, "live_budget_slots": 1, "retry": 0})
        self.assertEqual((ports.count("dispatch"), ports.count("read_session")), (1, 1))
        self.assertEqual(result.candidate["transition"], "PLACEHOLDER->DURABLE")
        self.assertIn(proof.ATTEMPT_MARKER_PATH, ports.files)
        self.assertEqual(ports.files[proof.TERMINAL_RECEIPT_PATH]["status"], "COMPLETE")
        self.assertFalse(ports.files[proof.TERMINAL_RECEIPT_PATH]["rerun_allowed"])
        self.assertTrue(all(path.startswith(("automation/command_bus/", "docs/evidence/claude-jules-stable-lane-proof-1/"))
                            for path in ports.files))

    def test_unauthorized_or_expired_plan_writes_and_calls_nothing(self):
        for p, now in ((plan(), "2026-10-04T10:00:00Z"), (plan(live_authorization=AUTH), "2026-10-06T00:00:00Z")):
            ports = FakePorts(p, now=now)
            result = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
            self.assertEqual(result.status, "STOPPED")
            self.assertEqual((ports.calls, ports.files), ([], {}))

    def test_already_durable_lane_row_refuses_before_any_call(self):
        p = plan(live_authorization=AUTH)
        ports = FakePorts(p)
        result = proof.run_stable_lane_proof(p, current_registry=adopted_registry("claude-jules"),
                                             proposed_registry=adopted_registry("claude-jules"), ports=ports)
        self.assertEqual((result.status, ports.calls), ("STOPPED", []))

    def test_second_run_and_crashed_first_run_are_refused_with_zero_dispatch(self):
        _, ports, result = self.run_it(marker_exists=True)
        self.assertEqual((result.status, result.code), ("STOPPED", "ALREADY_ATTEMPTED"))
        self.assertEqual((ports.count("dispatch"), ports.count("read_session")), (0, 0))
        p = plan(live_authorization=AUTH)
        ports = FakePorts(p)
        first = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        again = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        self.assertEqual((first.status, again.code), ("COMPLETE", "ALREADY_ATTEMPTED"))
        self.assertEqual(ports.count("dispatch"), 1)

    def test_dispatch_not_proven_ends_unknown_without_a_session_read(self):
        _, ports, result = self.run_it(dispatch_state="BLOCKED")
        self.assertEqual((result.status, result.code, ports.count("read_session")), ("UNKNOWN", "DISPATCH_NOT_PROVEN", 0))
        self.assertIsNone(result.candidate)
        self.assertFalse(ports.files[proof.TERMINAL_RECEIPT_PATH]["rerun_allowed"])

    def test_session_read_failure_is_unknown_and_never_retried(self):
        _, ports, result = self.run_it(session_error=RuntimeError("provider down"))
        self.assertEqual((result.status, ports.count("read_session"), ports.count("dispatch")), ("UNKNOWN", 1, 1))
        self.assertTrue(result.code.startswith("AMBIGUOUS:"))
        self.assertIsNone(result.candidate)

    def test_ambiguous_failure_records_a_short_secret_free_reason(self):
        secret = "AIza" + "x" * 30
        _, ports, result = self.run_it(session_error=RuntimeError(f"push to https://user:pw@host/r failed {secret}"))
        self.assertTrue(result.code.startswith("AMBIGUOUS:RuntimeError: push to"))
        self.assertNotIn(secret, result.code)
        self.assertNotIn("user:pw", result.code)
        self.assertLessEqual(len(result.code), 260)
        self.assertEqual(proof.safe_error_detail(RuntimeError("")), "")

    def test_terminal_provider_state_or_bad_session_is_unknown(self):
        _, ports, result = self.run_it(session_state="COMPLETED")
        self.assertEqual((result.status, result.code), ("UNKNOWN", "SESSION_NOT_ACTIVE_ON_WORK_BRANCH"))
        self.assertEqual((ports.count("dispatch"), ports.count("read_session")), (1, 1))
        self.assertIsNone(result.candidate)

    def test_registry_not_ready_never_completes(self):
        p = plan(live_authorization=AUTH)
        ports = FakePorts(p)
        broken = adopted_registry("claude-jules")
        next(r for r in broken["loops"] if r["loop_id"] == LANE)["enabled"] = False
        result = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=broken, ports=ports)
        self.assertNotEqual(result.status, "COMPLETE")
        self.assertIsNone(result.candidate)

    def test_no_run_can_exceed_the_budget(self):
        counters = proof.ProofCounters()
        counters.spend("jules_post"); counters.spend("jules_get"); counters.spend("live_budget_slots")
        for name in ("jules_post", "jules_get", "live_budget_slots", "retry"):
            with self.assertRaises(proof.ProofError):
                counters.spend(name)


class LiveGlueTests(unittest.TestCase):
    """``LiveProofPorts`` with fake existing objects: the glue honours one dispatch, one read, create-only writes."""

    class Dispatcher:
        def __init__(self, p, state="DISPATCHED"):
            self.p, self.state, self.calls = p, state, []

        def dispatch(self, intent, *, now, dispatches_used):
            self.calls.append((now, dispatches_used))
            from automation.command_bus.claude_jules_dispatch import DispatchResult
            return DispatchResult(self.state, "fixture", dispatch_receipt(self.p, state=self.state))

    class Reader:
        def __init__(self):
            self.calls = []

        def read_active_session(self, session_id, *, expected_branch):
            self.calls.append((session_id, expected_branch))
            return {"provider_raw_state": "IN_PROGRESS", "starting_branch": expected_branch,
                    "create_time": "2026-10-04T09:05:00Z", "update_time": "2026-10-04T09:25:00Z"}

    class Store(FakeClient):
        def __init__(self):
            super().__init__({})
            self.creates = []

        def get(self, path, ref):
            return super().get(path, ref)

        def create(self, path, text, message, branch):
            self.creates.append(path)
            self.files[path] = json.loads(text)

    class Clock:
        def now(self):
            return "2026-10-04T10:00:00Z"

    def ports(self, p, **kw):
        store = self.Store()
        collector = ControlTowerDurableCollector(store, ref="fixture", target_reader=FakeTarget(), clock=FakeClock())
        reader = self.Reader()
        ports = proof.LiveProofPorts(
            client=store, data_branch="fixture-data", dispatcher=self.Dispatcher(p, **kw), intent={}, dispatches_used=4,
            session_id_source=lambda command_id: "8123456789012345678", session_reader=reader, collector=collector,
            clock=self.Clock())
        return ports, store, reader

    def test_full_run_through_the_glue(self):
        p = plan(live_authorization=AUTH)
        ports, store, reader = self.ports(p)
        result = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        self.assertEqual((result.status, result.code), ("COMPLETE", "OK"))
        self.assertEqual(len(reader.calls), 1)
        self.assertEqual(ports.dispatcher.calls, [("2026-10-04T10:00:00Z", 4)])
        self.assertEqual(len(store.creates), len(set(store.creates)))  # create-only: no path written twice

    def test_glue_second_run_is_refused_and_dispatch_failure_reads_nothing(self):
        p = plan(live_authorization=AUTH)
        ports, store, reader = self.ports(p)
        proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        again = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        self.assertEqual(again.code, "ALREADY_ATTEMPTED")
        self.assertEqual(len(ports.dispatcher.calls), 1)
        ports, store, reader = self.ports(p, state="BLOCKED")
        result = proof.run_stable_lane_proof(p, current_registry=PROD, proposed_registry=adopted_registry("claude-jules"), ports=ports)
        self.assertEqual((result.status, reader.calls), ("UNKNOWN", []))


if __name__ == "__main__":
    unittest.main()
