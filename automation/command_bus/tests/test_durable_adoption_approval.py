"""STATIC tests of the DURABLE adoption approval contract, its CLI and its issuer workflow.

No network, no Jules, no provider, no GitHub write, no workflow dispatch. The CLI is driven through a
fake HTTP port; the workflow is only text-checked.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

from automation.command_bus import durable_adoption_approval as dap
from automation.command_bus import durable_adoption_approval_cli as cli
from automation.command_bus import signal_step7_live_proof as live
from automation.command_bus.control_tower_registration import assess_registration_readiness
from automation.command_bus.lane_identity_adoption import registry_digest

ROOT = Path(__file__).resolve().parents[3]
P5 = ROOT / "docs/evidence/signal-step7-proof5"
WORKFLOW_FILE = ROOT / ".github/workflows/signal-durable-adoption-approval-issuer.yml"
LANE = "chatgpt-semi-auto"
OWNER = live.OWNER_ACTOR_ID
RUN_ID = "37200000001"
NOW = "2026-10-04T00:00:00Z"
COMPLETED = "2026-10-03T20:09:53Z"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


RECEIPT = load(P5 / "live-terminal-receipt.json")
EVIDENCE = load(P5 / "live-proof-evidence.json")
OUTPUT = load(P5 / "jules-output-github-readback.json")["output"]
CANDIDATE = load(P5 / "adoption-candidate.json")
CURRENT, PROPOSED = cli.registries_from_production(ROOT)


def exact_output():
    out = copy.deepcopy(OUTPUT)
    out["changed_file_content"] = EVIDENCE["allowed_content"]
    return out


def make(output=OUTPUT, **override):
    approval = dap.build_approval(
        run_id=RUN_ID, actor_id=OWNER, run_attempt=1, now=NOW, receipt=RECEIPT, evidence=EVIDENCE,
        readback_output=output, current_registry=CURRENT, proposed_registry=PROPOSED)
    approval.update(override)
    return approval


def check(approval, **kw):
    args = dict(receipt=RECEIPT, evidence=EVIDENCE, readback_output=OUTPUT, current_registry=CURRENT,
                proposed_registry=PROPOSED, proof_completed_at=COMPLETED,
                allowed_approver_ids=frozenset({OWNER}), now=NOW)
    args.update(kw)
    return dap.validate_durable_adoption_approval(approval, **args)


class ApprovalContractTests(unittest.TestCase):
    def refused(self, code, approval, **kw):
        with self.assertRaises(dap.ApprovalError) as ctx:
            check(approval, **kw)
        self.assertEqual(ctx.exception.code, code)

    def test_newline_only_deviation_with_acknowledgement_is_accepted(self):
        approval = make()
        self.assertEqual(approval["output_assessment"], "DEVIATION")
        self.assertEqual(approval["accepted_deviation"], "MISSING_TRAILING_NEWLINE_ONLY")
        self.assertEqual(check(approval), LANE)

    def test_missing_acknowledgement_is_refused(self):
        self.refused("DEVIATION_NOT_ACKNOWLEDGED", make(accepted_deviation=None))

    def test_different_deviation_is_refused(self):
        self.refused("DEVIATION_TYPE_MISMATCH", make(accepted_deviation="OTHER"))

    def test_other_output_defects_are_never_acknowledgeable(self):
        broken = copy.deepcopy(OUTPUT)
        broken["changed_file_content"] = "something else"
        self.assertEqual(dap.classify_output(broken, EVIDENCE), ("DEVIATION", "OTHER"))
        approval = make(output=broken)
        self.assertIsNone(approval["accepted_deviation"])
        self.refused("DEVIATION_NOT_ACKNOWLEDGED", approval, readback_output=broken)
        merged = copy.deepcopy(OUTPUT)
        merged["merged"] = True
        self.assertEqual(dap.classify_output(merged, EVIDENCE)[1], "OTHER")

    def test_exact_output_needs_no_acknowledgement_and_refuses_one(self):
        out = exact_output()
        self.assertEqual(dap.classify_output(out, EVIDENCE), ("EXACT", None))
        self.assertEqual(check(make(output=out), readback_output=out), LANE)
        self.refused("DEVIATION_ACKNOWLEDGED_WITHOUT_DEVIATION",
                     make(output=out, accepted_deviation="MISSING_TRAILING_NEWLINE_ONLY"), readback_output=out)

    def test_assessment_is_recomputed_not_trusted(self):
        self.refused("OUTPUT_ASSESSMENT_MISMATCH", make(output_assessment="EXACT"))

    def test_old_authority_runs_are_not_adoption_approvals(self):
        for run_id in ("37031275812", "37150285702", "36981004299"):
            approval = make(approval_ref=f"github-actions:run/{run_id}", approval_id=f"adopt-durable-{LANE}-{run_id}")
            self.refused("AUTHORITY_RUN_IS_NOT_AN_ADOPTION_APPROVAL", approval)

    def test_legacy_adoption_record_cannot_be_used_as_an_approval(self):
        legacy = load(ROOT / "docs/evidence/signal-sf8/adoption-record-candidate-chatgpt-semi-auto.json")
        self.refused("APPROVAL_SHAPE", legacy)

    def test_approval_predating_the_proof_is_refused(self):
        self.refused("APPROVAL_BEFORE_PROOF_COMPLETE", make(), proof_completed_at="2026-10-04T01:00:00Z")

    def test_wrong_proof_loop_lane_and_digests_are_refused(self):
        self.refused("WRONG_PROOF", make(proof_task_id="signal-active-proof-4"))
        self.refused("WRONG_LOOP", make(loop_number=135))
        self.refused("WRONG_LANE", make(lane_id="claude-gemini"))
        self.refused("WRONG_TERMINAL_RECEIPT_DIGEST", make(terminal_receipt_sha256="0" * 64))
        self.refused("WRONG_EVIDENCE_DIGEST", make(evidence_payload_sha256="1" * 64))
        self.refused("STALE_CURRENT_REGISTRY", make(current_registry_sha256="2" * 64))
        self.refused("WRONG_PROPOSED_REGISTRY", make(proposed_registry_sha256="3" * 64))

    def test_receipt_that_is_not_complete_is_refused(self):
        receipt = dict(RECEIPT, status="STOPPED")
        self.refused("PROOF_NOT_COMPLETE", make(), receipt=receipt)
        self.refused("PROOF_NOT_COMPLETE", make(), receipt=dict(RECEIPT, rerun_allowed=True))

    def test_wrong_actor_rerun_and_duplicate_are_refused(self):
        self.refused("WRONG_ACTOR", make(approved_by_actor_id="1"))
        self.refused("APPROVAL_RERUN", make(approval_run_attempt=2))
        approval = make()
        self.refused("DUPLICATE_APPROVAL", approval, applied_approval_ids=frozenset({approval["approval_id"]}))
        self.refused("DUPLICATE_APPROVAL", approval, approval_run_ids_in_use=frozenset({RUN_ID}))
        self.refused("APPROVAL_ID_NOT_BOUND_TO_RUN", make(approval_id=f"adopt-durable-{LANE}-999"))

    def test_expired_future_and_overlong_windows_are_refused(self):
        self.refused("APPROVAL_EXPIRED", make(), now="2026-10-06T00:00:00Z")
        self.refused("APPROVAL_FROM_THE_FUTURE", make(), now="2026-10-03T21:00:00Z")
        self.refused("APPROVAL_VALIDITY_WINDOW", make(valid_until="2026-10-30T00:00:00Z"))

    def test_extra_or_missing_fields_and_retry_fallback_are_refused(self):
        approval = make()
        approval["extra"] = 1
        self.refused("APPROVAL_SHAPE", approval)
        self.refused("APPROVAL_RETRY_OR_FALLBACK", make(retry=1))
        self.refused("APPROVAL_RETRY_OR_FALLBACK", make(fallback="enabled"))
        self.refused("APPROVAL_DECISION", make(decision="MERGE"))


class RegistryDiffTests(unittest.TestCase):
    def mutate(self, lane, **fields):
        proposed = copy.deepcopy(PROPOSED)
        for entry in proposed["loops"]:
            if entry["loop_id"] == lane:
                entry.update(fields)
        return proposed

    def test_diff_is_exactly_one_lane_identity_state(self):
        dap.check_single_lane_diff(CURRENT, PROPOSED, LANE)
        changed = [(a["loop_id"], k) for a, b in zip(CURRENT["loops"], PROPOSED["loops"])
                   for k in a if a[k] != b[k]]
        self.assertEqual(changed, [(LANE, "identity_state")])

    def test_unrelated_field_of_the_lane_is_refused(self):
        with self.assertRaises(dap.ApprovalError) as ctx:
            dap.check_single_lane_diff(CURRENT, self.mutate(LANE, identity_state="DURABLE", title="x"), LANE)
        self.assertIn(ctx.exception.code, {"MORE_THAN_IDENTITY_STATE_CHANGED", "REGISTRY_INVALID"})

    def test_second_lane_flip_is_refused(self):
        other = next(e["loop_id"] for e in PROPOSED["loops"] if e["loop_id"] != LANE and e["identity_state"] == "PLACEHOLDER")
        with self.assertRaises(dap.ApprovalError):
            dap.check_single_lane_diff(CURRENT, self.mutate(other, identity_state="DURABLE"), LANE)

    def test_already_durable_current_is_refused(self):
        with self.assertRaises(dap.ApprovalError) as ctx:
            dap.check_single_lane_diff(PROPOSED, PROPOSED, LANE)
        self.assertEqual(ctx.exception.code, "LANE_NOT_PLACEHOLDER_TO_DURABLE")

    def test_global_registration_stays_not_wired_with_three_placeholder_lanes(self):
        self.assertEqual(assess_registration_readiness(PROPOSED, None).status, "NOT_WIRED")

    def test_issue_33_is_not_part_of_the_candidate(self):
        self.assertIs(CANDIDATE["issue33_changed_by_this_candidate"], False)
        self.assertIs(CANDIDATE["registry_write_allowed"], False)
        self.assertEqual(CANDIDATE["status"], "PENDING_HUMAN_APPROVAL")
        self.assertEqual(dap.durable_lanes(CURRENT), ())

    def test_production_registry_today_has_no_durable_lane(self):
        production = load(ROOT / cli.REGISTRY_PATH)
        durable = dap.durable_lanes(production)
        self.assertEqual(durable, (), "a DURABLE lane in production needs a merged DURABLE_ADOPTION_APPROVAL_V1")


class FakeGitHub:
    def __init__(self, run_overrides=None, other_runs=(), output_content=None, total=None):
        self.calls: list[tuple[str, str]] = []
        self.run_overrides = run_overrides or {}
        self.other_runs = other_runs
        self.output_content = OUTPUT["changed_file_content"] if output_content is None else output_content
        self.total = total

    def run(self):
        run = {"id": int(RUN_ID), "name": cli.WORKFLOW_NAME, "path": cli.WORKFLOW_PATH, "event": "workflow_dispatch",
               "head_branch": "main", "run_attempt": 1, "repository": {"full_name": live.REPOSITORY},
               "head_repository": {"full_name": live.REPOSITORY}, "actor": {"id": int(OWNER)},
               "triggering_actor": {"id": int(OWNER)}, "head_sha": "c" * 40}
        run.update(self.run_overrides)
        return run

    @staticmethod
    def _file(text):
        return {"type": "file", "content": base64.b64encode(text.encode()).decode(), "sha": "d" * 40}

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        assert method == "GET", "the issuer must be read-only"
        path = unquote(url.split(f"/repos/{live.REPOSITORY}/", 1)[1])
        ok = lambda payload: (200, {}, json.dumps(payload).encode())
        if path == f"actions/runs/{RUN_ID}":
            return ok(self.run())
        if path.startswith(f"actions/workflows/{cli.WORKFLOW_FILE}/runs"):
            runs = [{"id": int(RUN_ID)}] + [{"id": i} for i in self.other_runs]
            return ok({"total_count": self.total or len(runs), "workflow_runs": runs})
        if path.startswith("commits?"):
            return ok([{"commit": {"committer": {"date": "2026-10-03T20:09:53Z"}}}])
        if path.startswith("pulls/286/files"):
            return ok([{"filename": f} for f in OUTPUT["changed_files"]])
        if path.startswith("pulls/286"):
            return ok({"head": {"sha": OUTPUT["head_sha"], "ref": OUTPUT["head_branch"]},
                       "base": {"sha": OUTPUT["base_sha"], "ref": OUTPUT["base_branch"]}, "merged": False})
        if path.startswith("contents/"):
            name = path.split("?")[0].removeprefix("contents/")
            if name == live.ALLOWED_PATH:
                return ok(self._file(self.output_content))
            return ok(self._file((P5 / name.rsplit("/", 1)[-1]).read_text(encoding="utf-8")))
        return (404, {}, b"{}")


class Clock:
    def now(self):
        return NOW.replace("Z", "+00:00")


def env():
    return {"GITHUB_RUN_ID": RUN_ID, "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": live.REPOSITORY, "GITHUB_SHA": "c" * 40,
            "GITHUB_TOKEN": "ghs_faketoken"}


def run_cli(fake, environment=None, output_exists=False):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "approval.json"
        if output_exists:
            out.write_text("{}")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["--issue", "--output", str(out)], env=environment or env(), http=fake, clock=Clock(), root=ROOT)
        status = json.loads(buf.getvalue())
        record = json.loads(out.read_text()) if rc == 0 else None
    return rc, status, record


class IssuerCliTests(unittest.TestCase):
    def test_issue_path_writes_one_valid_approval_and_only_reads(self):
        fake = FakeGitHub()
        rc, status, record = run_cli(fake)
        self.assertEqual((rc, status["status"]), (0, "ISSUED"), status)
        self.assertEqual(record["approval_ref"], f"github-actions:run/{RUN_ID}")
        self.assertEqual(record["accepted_deviation"], "MISSING_TRAILING_NEWLINE_ONLY")
        self.assertTrue(all(method == "GET" for method, _ in fake.calls))
        self.assertFalse(any("jules" in url.lower() or "sessions" in url for _, url in fake.calls))
        self.assertEqual(check(record), LANE)

    def stopped(self, fake, code, **kw):
        rc, status, _ = run_cli(fake, **kw)
        self.assertEqual(rc, 1)
        self.assertEqual(status["status"], "STOPPED")
        self.assertTrue(status["code"].startswith(code), status)

    def test_second_approval_run_stops(self):
        self.stopped(FakeGitHub(other_runs=(111,)), "ANOTHER_APPROVAL_RUN_EXISTS")

    def test_not_owner_not_main_or_rerun_stops(self):
        self.stopped(FakeGitHub(run_overrides={"actor": {"id": 1}}), "OWN_RUN_NOT_ELIGIBLE")
        self.stopped(FakeGitHub(run_overrides={"triggering_actor": {"id": 1}}), "OWN_RUN_NOT_ELIGIBLE")
        bad = env()
        bad["GITHUB_RUN_ATTEMPT"] = "2"
        self.stopped(FakeGitHub(), "NOT_A_FIRST_ATTEMPT_MAIN_DISPATCH", environment=bad)
        bad = env()
        bad["GITHUB_REF"] = "refs/heads/other"
        self.stopped(FakeGitHub(), "NOT_A_FIRST_ATTEMPT_MAIN_DISPATCH", environment=bad)

    def test_output_that_changed_after_the_recorded_readback_stops(self):
        self.stopped(FakeGitHub(output_content="changed"), "OUTPUT_DIFFERS_FROM_RECORDED_READBACK")

    def test_existing_output_file_stops(self):
        self.stopped(FakeGitHub(), "OUTPUT_ALREADY_EXISTS", output_exists=True)

    def test_missing_token_stops_without_a_network_call(self):
        bad = env()
        bad["GITHUB_TOKEN"] = ""
        fake = FakeGitHub()
        self.stopped(fake, "ValueError", environment=bad)
        self.assertEqual(fake.calls, [])

    def test_proposed_registry_must_be_the_committed_candidate(self):
        self.assertEqual(registry_digest(PROPOSED), registry_digest(load(ROOT / cli.CANDIDATE_REGISTRY_PATH)))


class IssuerWorkflowTests(unittest.TestCase):
    TEXT = WORKFLOW_FILE.read_text(encoding="utf-8")
    CODE = "\n".join(l for l in TEXT.splitlines() if l.strip() and not l.lstrip().startswith("#"))

    def test_only_a_manual_dispatch_without_inputs_starts_it(self):
        self.assertEqual(re.findall(r"^  ([a-z_]+):", self.CODE.split("permissions:")[0], re.M), ["workflow_dispatch"])
        for forbidden in ("push:", "pull_request", "schedule:", "workflow_run", "workflow_call", "issue_comment",
                          "repository_dispatch", "inputs:"):
            self.assertNotIn(forbidden, self.CODE)

    def test_permissions_are_read_only_and_no_secret_or_token_minting(self):
        block = re.search(r"^permissions:\n((?:  .*\n)+)", self.CODE + "\n", re.M).group(1)
        self.assertEqual(sorted(re.findall(r"^  ([a-z-]+): (\w+)", block, re.M)),
                         [("actions", "read"), ("contents", "read"), ("pull-requests", "read")])
        for forbidden in ("id-token", ": write", "secrets.", "JULES", "GEMINI", "API_KEY"):
            self.assertNotIn(forbidden, self.CODE)

    def test_job_guards_owner_main_first_attempt_dispatch(self):
        guard = re.search(r"^    if: (.*)$", self.CODE, re.M).group(1)
        for part in ("github.repository == 'kamiyusense/multi-ai-council-phase0'", "github.ref == 'refs/heads/main'",
                     "github.run_attempt == 1", "github.event_name == 'workflow_dispatch'",
                     f"contains(fromJSON('[\"{OWNER}\"]'), github.actor_id)"):
            self.assertIn(part, guard)

    def test_actions_are_pinned_and_checkout_keeps_no_credentials(self):
        uses = re.findall(r"uses: (\S+)", self.CODE)
        self.assertEqual(len(uses), 2)
        for item in uses:
            self.assertRegex(item, r"@[0-9a-f]{40}$")
        self.assertIn("persist-credentials: false", self.CODE)

    def test_runs_only_the_issue_command_and_uploads_one_named_artifact(self):
        runs = re.findall(r"^\s+run: (.*)$", self.CODE, re.M)
        self.assertEqual(len(runs), 1)
        self.assertIn("durable_adoption_approval_cli --issue --output", runs[0])
        for forbidden in ("curl", "gh ", "git push", "jules", "registry"):
            self.assertNotIn(forbidden, runs[0])
        self.assertIn("name: durable-adoption-approval-${{ github.run_id }}", self.CODE)
        self.assertIn("concurrency:", self.CODE)
        self.assertIn("cancel-in-progress: false", self.CODE)

    def test_workflow_name_matches_what_the_cli_verifies(self):
        self.assertIn(f"name: {cli.WORKFLOW_NAME}", self.TEXT)
        self.assertTrue((ROOT / cli.WORKFLOW_PATH).exists())

    def test_modules_make_no_live_or_write_calls(self):
        for name in ("durable_adoption_approval.py", "durable_adoption_approval_cli.py"):
            text = (ROOT / "automation/command_bus" / name).read_text(encoding="utf-8")
            for forbidden in ("jules.googleapis", "sessions", "subprocess", '"POST"', '"PUT"', '"PATCH"', '"DELETE"'):
                self.assertNotIn(forbidden, text, f"{name} contains {forbidden}")


class FlipDiffFileTests(unittest.TestCase):
    def test_future_flip_diff_changes_one_line_of_the_registry_only(self):
        text = (P5 / "future-flip-registry.diff").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"^diff --git a/(\S+)", text, re.M), [cli.REGISTRY_PATH])
        body = [l for l in text.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        self.assertEqual(body, ['-      "identity_state": "PLACEHOLDER"', '+      "identity_state": "DURABLE"'])

    def test_verify_mode_accepts_an_issued_record_and_rejects_a_tampered_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "a.json"
            good.write_text(json.dumps(make()))
            self.assertEqual(cli.verify_file(good, ROOT, NOW), LANE)
            bad = Path(tmp) / "b.json"
            bad.write_text(json.dumps(make(approved_by_actor_id="1")))
            with self.assertRaises(dap.ApprovalError):
                cli.verify_file(bad, ROOT, NOW)


if __name__ == "__main__":
    unittest.main()
