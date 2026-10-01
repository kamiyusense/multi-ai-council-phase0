"""Unit contracts for Claude AUTO dispatch preparation, policy and fencing."""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import unittest
from datetime import datetime

from automation.command_bus import jules_carrier_current
from automation.command_bus.claude_jules_dispatch import (
    build_dispatch_intent, check_dispatch_authority, sha256_of, used_loop_numbers,
    validate_dispatch_intent, validate_policy,
)
from automation.command_bus.claude_jules_task_prompt import (
    corrective_task_spec, render_task_prompt, validate_task_spec,
)
from automation.command_bus.claude_loop import (
    make_structured_verdict, numbered_command_id, prepare_jules_semiauto_bundle,
    prepare_jules_semiauto_request, prepare_loop_claim, prepare_next_action,
)
from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    CARRIER, HOLDER, LOOP, NOW, REPO, TARGET, FakeGitHub, owner_event, policy, task_spec,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
HEAD, TREE = "a" * 40, "b" * 40


def prepared(round_number=1, generation=1):
    verdict = make_structured_verdict(
        verdict_id="v1", loop_id=LOOP, round=round_number, generation=generation,
        correlation_id=f"{LOOP}-round-{round_number}", mode="JULES_BACKEND", decision="CONTINUE",
        expected_target_head=HEAD, expected_target_tree=TREE, reasons=["r"], evidence_refs=["e"],
        next_prompt=render_task_prompt(task_spec(), loop_label="Loop 777"))
    return prepare_next_action(verdict, expected_repo=REPO, expected_pr=999,
                               expires_at="2026-10-01T14:00:00+00:00",
                               path_policy=task_spec()["allowed_paths"]).request


def bundle(command_id=None, lane="J-BLUE"):
    command_id = command_id or numbered_command_id(777, "alpha-helper")
    common = dict(target_branch=TARGET, default_branch="main", created_at=NOW, command_id=command_id)
    request = prepare_jules_semiauto_request(prepared(), **common).request
    claim = prepare_loop_claim(request, lane_id=lane, claimed_at=NOW).request
    result = prepare_jules_semiauto_bundle(prepared(), claim, **common)
    return result, request, claim


def intent(**overrides):
    result, request, claim = bundle()
    values = dict(origin_loop_id=LOOP, origin_round=1, origin_correlation_id=f"{LOOP}-round-1",
                  origin_generation=1, attempt=1, task_id="alpha-helper", task_spec_sha256=sha256_of(task_spec()),
                  carrier_request=result.request["carrier_request"], carrier_claim=claim,
                  origin_binding=result.request["origin_binding"], prepared_at=NOW)
    values.update(overrides)
    return build_dispatch_intent(**values)


class PinnedCarrierTests(unittest.TestCase):
    def test_vendored_carrier_validators_match_pinned_blob_shas(self):
        for name, expected in jules_carrier_current.PINNED_BLOB_SHA.items():
            data = (ROOT / "jules_carrier_current" / name).read_bytes()
            blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
            self.assertEqual(blob, expected, name)
        compat = (ROOT / "tests" / "test_claude_jules_current_carrier_compatibility.py").read_text()
        for expected in jules_carrier_current.PINNED_BLOB_SHA.values():
            self.assertIn(expected, compat)


class BundleTests(unittest.TestCase):
    def test_bundle_emits_exact_carrier_request_claim_and_binding(self):
        result, request, claim = bundle()
        self.assertEqual(result.status, "PREPARED", result.reason)
        carrier = result.request["carrier_request"]
        self.assertEqual(carrier, request)
        self.assertEqual(set(carrier), jules_carrier_current.jules_api_request.REQUIRED_KEYS)
        jules_carrier_current.jules_api_request.validate_request(carrier, now=datetime.fromisoformat(NOW))
        jules_carrier_current.loop_id_claim.verify_command_claim(carrier, claim)
        self.assertEqual((claim["loop_id"], claim["lane_display"], claim["state"]), ("777", "💙", "CLAIMED"))
        binding = result.request["origin_binding"]
        self.assertEqual((binding["origin_loop_id"], binding["claim_loop_id"]), (LOOP, "777"))

    def test_bundle_rejects_claim_the_carrier_would_reject(self):
        _, request, claim = bundle()
        common = dict(target_branch=TARGET, default_branch="main", created_at=NOW, command_id=request["command_id"])
        for key, value in (("lane_display", "green"), ("expected_target_tree", "c" * 40),
                           ("state", "HISTORICAL_BACKFILL"), ("schema_version", 2), ("retry", 1)):
            bad = dict(claim, **{key: value})
            self.assertEqual(prepare_jules_semiauto_bundle(prepared(), bad, **common).status, "UNKNOWN", key)

    def test_unnumbered_command_cannot_be_claimed(self):
        common = dict(target_branch=TARGET, default_branch="main", created_at=NOW, command_id="claude-free-form")
        request = prepare_jules_semiauto_request(prepared(), **common).request
        self.assertEqual(prepare_loop_claim(request, lane_id="J-BLUE", claimed_at=NOW).status, "BLOCKED")
        self.assertEqual(prepare_loop_claim(dict(request, command_id=numbered_command_id(5, "x")),
                                            lane_id="J-PURPLE", claimed_at=NOW).status, "BLOCKED")

    def test_numbered_command_id_bounds(self):
        self.assertEqual(numbered_command_id(7, "abc"), "relay-dev-loop-007-abc")
        for bad in ((True, "abc"), (-1, "abc"), (7, "Bad_Upper"), (7, "a" * 60)):
            with self.assertRaises(ValueError):
                numbered_command_id(*bad)


class IntentTests(unittest.TestCase):
    def test_intent_digest_and_cross_binding_fail_closed(self):
        record = intent()
        self.assertEqual(validate_dispatch_intent(copy.deepcopy(record)), record)
        tampered = copy.deepcopy(record)
        tampered["carrier_request"]["prompt"] += " extra"
        with self.assertRaises(ValueError):
            validate_dispatch_intent(tampered)
        with self.assertRaises(ValueError):
            intent(origin_round=2)  # binding says round 1
        with self.assertRaises(ValueError):
            intent(task_id="other-task")
        with self.assertRaises(ValueError):
            intent(origin_generation=True)

    def test_used_loop_numbers_reads_claims_and_numbered_commands(self):
        gh = FakeGitHub()
        for path in ("automation/command_bus/loop_id_claims/118.json",
                     "automation/command_bus/jules_api_requests/relay-dev-loop-121-x.json",
                     "automation/command_bus/jules_api_requests/unnumbered-smoke.json"):
            gh.files[(CARRIER, path)] = GitHubContent(path, "{}", "s")
        self.assertEqual(used_loop_numbers(gh, CARRIER), {118, 121})
        gh.files[(CARRIER, "automation/command_bus/loop_id_claims/notes.txt")] = GitHubContent("automation/command_bus/loop_id_claims/notes.txt", "", "s")
        with self.assertRaises(ValueError):
            used_loop_numbers(gh, CARRIER)


class PolicyAndFenceTests(unittest.TestCase):
    def test_committed_policy_is_valid_and_grants_nothing(self):
        record = json.loads((ROOT / "config" / "claude_jules_autoloop_policy.json").read_text())
        validate_policy(record)
        self.assertEqual(record["allowed_target_branches"], [])
        self.assertEqual(record["allowed_lane_ids"], [])
        self.assertIsNone(record["live_dispatch_authorization"])

    def test_proposed_live_proof_roadmap_renders_a_valid_carrier_request(self):
        from automation.command_bus.claude_jules_autoloop import validate_roadmap
        record = json.loads((ROOT / "config" / "claude_jules_autoloop_roadmap.proposed.json").read_text())
        validate_roadmap(record)
        [entry] = record["tasks"]
        spec = entry["task_spec"]
        self.assertEqual([p["path"] for p in spec["allowed_paths"]], ["docs/CLAUDE_JULES_AUTOLOOP_LIVE_PROOF_NOTE.md"])
        verdict = make_structured_verdict(
            verdict_id="v", loop_id=LOOP, round=1, generation=1, correlation_id=f"{LOOP}-round-1",
            mode="JULES_BACKEND", decision="CONTINUE", expected_target_head=HEAD, expected_target_tree=TREE,
            reasons=["r"], evidence_refs=["e"], next_prompt=render_task_prompt(spec, loop_label="Loop 900"))
        prep = prepare_next_action(verdict, expected_repo=REPO, expected_pr=999,
                                   expires_at="2026-10-01T14:00:00+00:00", path_policy=spec["allowed_paths"]).request
        request = prepare_jules_semiauto_request(prep, target_branch=TARGET, default_branch="main", created_at=NOW,
                                                 command_id=numbered_command_id(900, spec["task_id"])).request
        jules_carrier_current.jules_api_request.validate_request(request, now=datetime.fromisoformat(NOW))
        self.assertIn("Loop 900 — bounded SHORT", request["prompt"])
        self.assertIn("docs/CLAUDE_JULES_AUTOLOOP_LIVE_PROOF_NOTE.md: permitted operations ADD", request["prompt"])

    def test_policy_negative_matrix(self):
        for overrides in (
            {"controller_id": "chatgpt"}, {"max_rounds": 7}, {"max_rounds": True},
            {"allowed_target_branches": ["main"]}, {"allowed_target_branches": [CARRIER]},
            {"allowed_lane_ids": ["J-PURPLE"]}, {"data_branch": "main"}, {"expected_pr": 0},
            {"live_dispatch_authorization": {"approved_by": "x"}},
            {"live_dispatch_authorization": dict(policy()["live_dispatch_authorization"], max_dispatches=7)},
        ):
            with self.assertRaises(ValueError, msg=str(overrides)):
                validate_policy(policy(**overrides))
        with self.assertRaises(ValueError):
            validate_policy(dict(policy(), extra=1))

    def test_owner_fence_matrix(self):
        pol = policy()
        ok = owner_event()
        self.assertEqual(check_dispatch_authority(ok, policy=pol, origin_loop_id=LOOP, generation=1, now=NOW).status, "PASS")
        cases = {
            "SEMI_AUTO": owner_event(role="SEMI_AUTO"),
            "not owned": owner_event(holder="other"),
            "stale owner generation": owner_event(generation=2, event_type="RENEW"),
            "released": dict(ok, event_type="RELEASE"),
            "expired": owner_event(expires_at="2026-10-01T12:59:59+00:00"),
            "future": dict(ok, claimed_at="2026-10-01T13:30:00+00:00"),
            "another PR": dict(ok, expected_pr=1),
            "another loop": dict(ok, loop_id="other-loop"),
        }
        for label, event in cases.items():
            result = check_dispatch_authority(event, policy=pol, origin_loop_id=LOOP, generation=1, now=NOW)
            self.assertEqual(result.status, "BLOCKED", label)
        self.assertEqual(check_dispatch_authority(None, policy=pol, origin_loop_id=LOOP, generation=1, now=NOW).status, "UNKNOWN")


class TaskPromptTests(unittest.TestCase):
    def test_prompt_has_the_twelve_sections_in_mandatory_order(self):
        prompt = render_task_prompt(task_spec(), loop_label="Loop 123")
        headers = ["Loop 123 — bounded MEDIUM", "Goal:", "Read first:", "Allowed changed paths only:",
                   "Hard scope / Do Not Touch:", "Reuse-first:", "Required semantics:", "Negative/tamper cases:",
                   "Acceptance criteria:", "Validation:", "Publication:", "Stop and report instead of guessing if:"]
        positions = [prompt.index(h) for h in headers]
        self.assertEqual(positions, sorted(positions))
        for required in ("retry=0", "fallback=disabled", "no Merge", "No vacuous tests", "helper_exact_value"):
            self.assertIn(required, prompt)

    def test_task_spec_negative_matrix(self):
        bad = []
        for key, value in (("size", "HUGE"), ("task_id", "Bad Id"), ("goal", " "), ("read_first", []),
                           ("validation_commands", ["python -m http.server & serve"]),
                           ("validation_commands", ["npm run dev -- --watch"]),
                           ("acceptance_checks", ["dup", "dup"]), ("schema_version", True)):
            bad.append(dict(task_spec(), **{key: value}))
        for paths in ([{"path": "src/*.py", "allowed_ops": ["ADD"]}],
                      [{"path": "../x.py", "allowed_ops": ["ADD"]}],
                      [{"path": "x.py", "allowed_ops": ["DELETE"]}],
                      [{"path": "x.py", "allowed_ops": ["ADD"]}, {"path": "x.py", "allowed_ops": ["MODIFY"]}]):
            bad.append(dict(task_spec(), allowed_paths=paths))
        for spec in bad:
            with self.assertRaises(ValueError, msg=str(spec)):
                validate_task_spec(spec)
        with self.assertRaises(ValueError):
            render_task_prompt(task_spec(), loop_label="Loop x")
        with self.assertRaises(ValueError):
            render_task_prompt(dict(task_spec(), goal="x" * 9000), loop_label="Loop 123")

    def test_corrective_is_a_new_mission_with_findings(self):
        fix = corrective_task_spec(task_spec(), attempt=1, findings=[{"category": "semantic_gap", "detail": "missing negative"}],
                                   reduce_size=True)
        self.assertEqual((fix["task_id"], fix["size"]), ("alpha-helper-fix1", "SHORT"))
        self.assertIn("missing negative", fix["semantics"][0])
        again = corrective_task_spec(fix, attempt=2, findings=[{"category": "typo", "detail": "x"}])
        self.assertEqual(again["task_id"], "alpha-helper-fix2")
        with self.assertRaises(ValueError):
            corrective_task_spec(task_spec(), attempt=1, findings=[])
        with self.assertRaises(ValueError):
            corrective_task_spec(task_spec(), attempt=1, findings=[{"category": "x"}])


if __name__ == "__main__":
    unittest.main()
