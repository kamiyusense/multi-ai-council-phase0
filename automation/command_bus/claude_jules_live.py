"""LIVE wiring of the Claude x Jules AUTO loop (stages 6-7).

Builds the unchanged ``ClaudeJulesAutoLoop`` on the production adapters in
``claude_jules_live_adapter`` and adds the three pieces the fake world used to
simulate:

* ``LiveResultFacts`` - Claude's own evidence: carrier workflow run + accepted
  Jules session (read from the run's job log), fresh PR readback, git compare,
  the full test suite run on the exact candidate head/tree in a scratch
  worktree, and Claude's independent review record (see below).
* ``poll_results`` - the wake adapter: lists PRs whose base is the isolated
  work branch of each outstanding Claude dispatch and feeds them to the same
  normalizer/inbox as a webhook, with synthetic delivery id
  ``poll-<PR>-<HEAD>``.  The result id is identical for webhook and poll, so
  nothing is ever processed twice.
* Review records (``CLAUDE_AUTO_REVIEW_V1``) - the semantic review is done by
  Claude reading the diff; it is persisted create-only, bound to the exact
  command, head and tree, before the inspection may run.  Without it the loop
  WAITs (``AWAITING_CLAUDE_REVIEW``) instead of guessing.

CLI (all commands print one JSON object):
  python -m automation.command_bus.claude_jules_live status|step|poll|budget
  python -m automation.command_bus.claude_jules_live record-review --file review.json
  python -m automation.command_bus.claude_jules_live build-settlement --file {"command_id", "status_request_path"}
  python -m automation.command_bus.claude_jules_live record-settlement --file settlement.json
  python -m automation.command_bus.claude_jules_live recovery-history [--recovery-policy v1]
  python -m automation.command_bus.claude_jules_live observe|takeover|renew|handback|reclaim [--write]
  python -m automation.command_bus.claude_jules_live carrier [--file since.txt]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

from .claude_jules_adoption import SafeAdoption, adoption_receipt_path
from .claude_jules_reinspection import ReinspectionStore
from .claude_jules_autoloop import ClaudeJulesAutoLoop
from .claude_jules_dispatch import (
    EVIDENCE_ROOT, DispatchResult, canonical_json, command_path, dispatch_receipt_path, sha256_of, validate_dispatch_intent,
)
from .claude_jules_live_adapter import GitHubRestReader, GitLiveClient, fresh_pr_view, pull_request_payload
from .claude_jules_handover import (
    SEMIAUTO_HOLDER, append_decision, decide_handback, decide_reclaim, decide_renew, decide_takeover, observe_stream,
)
from .claude_jules_inspection import InspectionStore
from .claude_jules_live_budget import LiveBudgetLedger
from .claude_jules_result_event import ResultEventInbox, normalize_pull_request_event
from .claude_jules_recovery_policy import recovery_policy
from .claude_jules_settlement import (
    ReadbackMismatch, ReadbackUnavailable, observation_from_readback_run, settlement_path, settlement_status,
    validate_settlement_observation, verify_readback,
)
from .loop_owner_backend import LoopOwnerGitHubBackend

CARRIER_WORKFLOW = "jules-chat-semiauto.yml"
REVIEW_PROFILE = "CLAUDE_AUTO_REVIEW_V1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SESSION_LOG = re.compile(r"Jules session accepted: sessions/([0-9]{1,32})\b")
_TEST_RAN = re.compile(r"^Ran ([0-9]+) tests? in ", re.M)
_TEST_FAILED = re.compile(r"^FAILED \(([^)]*)\)", re.M)
DEFAULT_TEST_COMMAND = [sys.executable or "python3", "-m", "unittest", "discover", "-s", "automation/command_bus/tests", "-t", "."]
OBSERVATION_PROFILE = "CLAUDE_AUTO_DISPATCH_OBSERVATION_V1"
_OBSERVATION_KEYS = {"schema_version", "profile", "command_id", "workflow_run_id", "job_id", "session_id",
                     "log_line", "source", "observed_at", "observation_sha256"}
_REVIEW_KEYS = {"schema_version", "profile", "command_id", "candidate_head", "candidate_tree", "reviewer",
                "observations", "findings", "summary", "reviewed_at", "review_sha256"}


def review_path(command_id: str, head: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", command_id or "") or not _SHA40.fullmatch(head or ""):
        raise ValueError("unsafe review identity")
    return f"{EVIDENCE_ROOT}/claude-auto-reviews/{command_id}/{head}.json"


def observation_path(command_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", command_id or ""):
        raise ValueError("unsafe command id")
    return f"{EVIDENCE_ROOT}/claude-auto-dispatch-observations/{command_id}.json"


def build_observation(*, command_id: str, workflow_run_id: str, job_id: str, log_line: str,
                      observed_at: str, source: str = "github-mcp get_job_logs") -> dict[str, Any]:
    sessions = _SESSION_LOG.findall(log_line)
    if len(sessions) != 1:
        raise ValueError("log line must contain exactly one accepted Jules session")
    record = {"schema_version": 1, "profile": OBSERVATION_PROFILE, "command_id": command_id,
              "workflow_run_id": str(workflow_run_id), "job_id": str(job_id), "session_id": sessions[0],
              "log_line": log_line.strip(), "source": source, "observed_at": observed_at}
    record["observation_sha256"] = sha256_of(record)
    return validate_observation(record)


def validate_observation(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _OBSERVATION_KEYS:
        raise ValueError("observation keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != OBSERVATION_PROFILE:
        raise ValueError("unsupported observation")
    if record["observation_sha256"] != sha256_of({k: v for k, v in record.items() if k != "observation_sha256"}):
        raise ValueError("observation digest mismatch")
    if _SESSION_LOG.findall(record["log_line"]) != [record["session_id"]]:
        raise ValueError("observation log line does not carry its session id")
    observation_path(record["command_id"])
    return record


def build_review(*, command_id: str, head: str, tree: str, observations: dict[str, Any],
                 findings: list[dict[str, Any]], summary: str, reviewed_at: str) -> dict[str, Any]:
    record = {"schema_version": 1, "profile": REVIEW_PROFILE, "command_id": command_id, "candidate_head": head,
              "candidate_tree": tree, "reviewer": "claude-auto", "observations": observations,
              "findings": findings, "summary": summary, "reviewed_at": reviewed_at}
    record["review_sha256"] = sha256_of(record)
    return validate_review(record)


def validate_review(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _REVIEW_KEYS:
        raise ValueError("review record keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != REVIEW_PROFILE or record["reviewer"] != "claude-auto":
        raise ValueError("unsupported review record")
    if record["review_sha256"] != sha256_of({k: v for k, v in record.items() if k != "review_sha256"}):
        raise ValueError("review record digest mismatch")
    review_path(record["command_id"], record["candidate_head"])
    if not _SHA40.fullmatch(record["candidate_tree"] or ""):
        raise ValueError("review tree invalid")
    obs = record["observations"]
    if not isinstance(obs, dict) or any(not isinstance(v, dict) or set(v) != {"result", "evidence"}
                                        or v["result"] not in {"PASS", "FAIL"} or not str(v["evidence"]).strip()
                                        for v in obs.values()):
        raise ValueError("review observations malformed")
    if not isinstance(record["findings"], list) or any(not isinstance(f, dict) or set(f) != {"category", "detail"}
                                                        for f in record["findings"]):
        raise ValueError("review findings malformed")
    return record


class LiveResultFacts:
    """Claude's independent evidence collector against real GitHub."""

    def __init__(self, *, git: GitLiveClient, rest: GitHubRestReader, policy: dict[str, Any],
                 scratch_dir: str, test_command: list[str] | None = None, test_timeout: int = 1800):
        self.git, self.rest, self.policy = git, rest, policy
        self.scratch, self.test_timeout = scratch_dir, test_timeout
        self.test_command = test_command or DEFAULT_TEST_COMMAND
        self._tests: dict[str, dict[str, Any]] = {}

    # -- dispatch evidence -------------------------------------------------
    def dispatch_observation(self, command_id: str) -> dict[str, Any] | None:
        commits = self.git.added_by(self.policy["carrier_branch"], command_path(command_id))
        if len(commits) != 1:
            return None
        runs = [r for r in self.rest.workflow_runs_for_commit(CARRIER_WORKFLOW, commits[0]) if r.get("event") == "push"]
        if len(runs) != 1 or runs[0].get("status") != "completed":
            return None
        run = runs[0]
        sessions: set[str] = set()
        source = None
        if run.get("conclusion") == "success":
            jobs = self.rest.run_jobs(run["id"])
            try:
                for job in jobs:
                    sessions.update(_SESSION_LOG.findall(self.rest.job_log(job["id"]) or ""))
                source = "JOB_LOG"
            except Exception:
                # Job-log storage can be unreachable from the container; then only a Claude-recorded
                # observation for exactly this REST-verified run and job may supply the session id.
                # It stays marked as a transcription: provider settlement never binds to it.
                sessions = self._recorded_session(command_id, str(run["id"]), {str(j["id"]) for j in jobs})
                source = "RECORDED_TRANSCRIPTION"
        return {"command_id": command_id, "workflow_run_id": str(run["id"]), "conclusion": run.get("conclusion"),
                "session_id": sessions.pop() if len(sessions) == 1 else None, "command_commit": commits[0],
                "session_source": source}

    def _recorded_session(self, command_id: str, run_id: str, job_ids: set[str]) -> set[str]:
        content = self.git.get(observation_path(command_id), self.policy["data_branch"])
        if content is None:
            return set()
        record = validate_observation(json.loads(content.text))
        if record["command_id"] != command_id or record["workflow_run_id"] != run_id or record["job_id"] not in job_ids:
            raise ValueError("recorded observation does not bind the verified workflow run")
        return {record["session_id"]}

    def fresh_pr(self, number: int) -> dict[str, Any] | None:
        return fresh_pr_view(self.rest.pull(number))

    def timeout_reconciliation(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Reacquire GitHub results without treating absence as provider completion.

        This performs repository-scoped GETs only. There is no new Jules/model
        authority and no cancellation/dispatch here. A missing result cannot
        establish that the provider stopped; only recorded, REST-verified
        readbacks of the accepted session (``claude_jules_settlement``) can say
        SETTLED or RUNNING. Without them the boundary stays UNKNOWN (WAIT).
        """
        request = intent["carrier_request"]
        events = []
        for pr in self.rest.pulls_for_base(request["work_branch"]):
            event = normalize_pull_request_event(
                event_name="pull_request", delivery_id=f"timeout-{pr['number']}-{pr['head']['sha']}",
                payload=pull_request_payload(pr), expected_repo=self.policy["target_repo"],
            )
            if event.status == "ACCEPTED":
                events.append(event.record)
        status, ref = self.provider_settlement(intent)
        return {"command_id": request["command_id"], "snapshot_head": request["expected_target_head"],
                "status": status, "evidence_ref": f"github-result-pr-readback; {ref}",
                "result_events": events}

    def provider_settlement(self, intent: dict[str, Any]) -> tuple[str, str]:
        command_id = intent["carrier_request"]["command_id"]
        try:
            observation = self.dispatch_observation(command_id) or {}
        except Exception as exc:
            return "UNKNOWN", f"dispatch observation unavailable: {type(exc).__name__}"
        if observation.get("session_id") and observation.get("session_source") != "JOB_LOG":
            # A transcribed session id is a claim, not an independent read; binding a
            # settlement to it could settle the wrong session while the real one runs.
            return "UNKNOWN", "accepted session only transcribed; dispatch job log readback unavailable"
        prefix = settlement_path(command_id, "0").rsplit("/", 1)[0] + "/"
        try:
            records = [json.loads(c.text) for c in self.git.list(prefix, self.policy["data_branch"])]
        except json.JSONDecodeError:
            return "UNKNOWN", "settlement record invalid: not JSON"
        except Exception as exc:
            return "UNKNOWN", f"settlement records unavailable: {type(exc).__name__}"
        return settlement_status(
            records, command_id=command_id, accepted_session_id=observation.get("session_id"),
            dispatched_at=intent["prepared_at"],
            verify=lambda r: verify_readback(r, git=self.git, rest=self.rest,
                                             carrier_branch=self.policy["carrier_branch"]))

    def compare(self, base: str, head: str) -> dict[str, Any] | None:
        return self.git.compare(base, head)

    def commit_tree(self, sha: str) -> str | None:
        return self.git.get_commit_tree(sha)

    # -- Claude's own test run on the exact head ----------------------------
    def run_tests(self, head: str) -> dict[str, Any] | None:
        if head in self._tests:
            return self._tests[head]
        tree = self.git.get_commit_tree(head)
        if tree is None:
            return None
        os.makedirs(self.scratch, exist_ok=True)
        worktree = tempfile.mkdtemp(prefix=f"candidate-{head[:12]}-", dir=self.scratch)
        try:
            subprocess.run(["git", "worktree", "add", "--detach", worktree, head], cwd=self.git.repo_dir,
                           check=True, capture_output=True, text=True)
            checked = subprocess.run(["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=worktree, check=True,
                                     capture_output=True, text=True).stdout.split()
            if checked != [head, tree]:
                return None
            proc = subprocess.run(self.test_command, cwd=worktree, capture_output=True, text=True,
                                  timeout=self.test_timeout, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        except (subprocess.SubprocessError, OSError):
            return None
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", worktree], cwd=self.git.repo_dir,
                           capture_output=True, text=True)
            shutil.rmtree(worktree, ignore_errors=True)
        output = proc.stderr + proc.stdout
        ran = _TEST_RAN.findall(output)
        failed = _TEST_FAILED.findall(output)
        counts = dict(re.findall(r"(failures|errors)=([0-9]+)", failed[-1])) if failed else {}
        result = {"head_sha": head, "tree_sha": tree, "tests_run": int(ran[-1]) if ran else 0,
                  "exit_code": proc.returncode, "failures": int(counts.get("failures", 0)),
                  "errors": int(counts.get("errors", 0))}
        if proc.returncode != 0 and not failed:
            result["errors"] = max(result["errors"], 1)  # crashed runner is never a pass
        self._tests[head] = result
        return result

    def environment_digest(self) -> str:
        """What the candidate test run depends on locally; a re-run after an environment failure needs this to change."""
        import platform
        return sha256_of({"test_command": list(self.test_command), "python": sys.version,
                          "platform": platform.platform()})

    def test_sources(self, head: str, paths: list[str]) -> dict[str, str] | None:
        sources = {}
        for path in paths:
            text = self.git.show(head, path)
            if text is None:
                return None
            sources[path] = text
        return sources

    # -- Claude's semantic review --------------------------------------------
    def _review(self, command_id: str, head: str) -> dict[str, Any] | None:
        content = self.git.get(review_path(command_id, head), self.policy["data_branch"])
        if content is None:
            return None
        record = validate_review(json.loads(content.text))
        if record["command_id"] != command_id or record["candidate_head"] != head:
            raise ValueError("review record identity mismatch")
        if self.git.get_commit_tree(head) != record["candidate_tree"]:
            raise ValueError("review record tree differs from the candidate")
        return record

    def review_ready(self, intent: dict[str, Any], spec: dict[str, Any], head: str) -> bool:
        return self._review(intent["carrier_request"]["command_id"], head) is not None

    def review(self, intent: dict[str, Any], spec: dict[str, Any], head: str):
        record = self._review(intent["carrier_request"]["command_id"], head)
        if record is None:
            return {}, []
        return record["observations"], record["findings"]

    def small_repair(self, intent: dict[str, Any], inspection: dict[str, Any]) -> str | None:
        """Claude pushes its repair to ``claude-auto-repair/<command_id>``; only a direct child is accepted."""
        head = self.git.get_branch_head(f"claude-auto-repair/{intent['carrier_request']['command_id']}")
        if head is None or not self.git.ensure_commit(head):
            return None
        parent = self.git._git("rev-parse", f"{head}^").stdout.strip()
        return head if parent == inspection["candidate_head"] else None


class CarrierQuietGuard:
    """Write to the shared carrier only while it is quiet and the stream is ours.

    The carrier workflow runs in one concurrency group; GitHub keeps at most
    one pending run per group and cancels an older pending run when a newer
    one queues.  Immediately before each claim/command write Claude checks:

    * no carrier workflow run is unfinished (REST);
    * no other controller is mid-dispatch: every other Loop claim made within
      ``pending_window`` already has its command file (a claim without its
      command means someone is between the two writes);
    * no foreign claim targets Claude's isolated target branches (the stream
      ownership/target check; Claude's own commands are its dispatch intents);
    * the carrier tip is at least ``quiet`` old (a margin, not the guarantee).

    Busy -> WAIT with nothing written; foreign stream use -> BLOCKED;
    unreadable -> UNKNOWN.
    """

    def __init__(self, *, git: GitLiveClient, rest: GitHubRestReader, carrier_branch: str,
                 workflow_file: str = CARRIER_WORKFLOW, quiet: timedelta = timedelta(minutes=5),
                 pending_window: timedelta = timedelta(minutes=30), clock: Any = None,
                 isolated_targets: tuple[str, ...] = (), data_branch: str | None = None):
        self.git, self.rest, self.branch, self.workflow = git, rest, carrier_branch, workflow_file
        self.quiet, self.pending_window = quiet, pending_window
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.isolated_targets, self.data_branch = tuple(isolated_targets), data_branch

    def _own_command_ids(self) -> set[str]:
        if self.data_branch is None:
            return set()
        prefix = f"{EVIDENCE_ROOT}/claude-auto-dispatch-intents/"
        return {json.loads(c.text)["carrier_request"]["command_id"] for c in self.git.list(prefix, self.data_branch)}

    def __call__(self, command_id: str | None = None) -> DispatchResult:
        try:
            active = self.rest.active_workflow_runs(self.workflow)
            tip = self.git.remote_head(self.branch)
            committed = self.git.commit_time(tip) if tip else None
            claims = [json.loads(c.text) for c in self.git.list("automation/command_bus/loop_id_claims/", self.branch)]
            commands = {c.path.rsplit("/", 1)[-1][:-5] for c in
                        self.git.list("automation/command_bus/jules_api_requests/", self.branch)}
            own = self._own_command_ids()
        except Exception as exc:  # unreadable is never quiet
            return DispatchResult("UNKNOWN", f"carrier activity unverifiable: {exc}")
        if active:
            ids = ", ".join(str(r.get("id")) for r in active)
            return DispatchResult("WAIT", f"CARRIER_BUSY: carrier workflow run(s) unfinished: {ids}")
        if tip is None or committed is None:
            return DispatchResult("UNKNOWN", "carrier tip unavailable")
        now = self.clock()
        for claim in claims:
            other = claim.get("command_id")
            if other == command_id:
                continue
            if claim.get("target_branch") in self.isolated_targets and other not in own:
                return DispatchResult("BLOCKED", f"foreign claim {claim.get('loop_id')} targets the isolated stream")
            try:
                claimed = datetime.fromisoformat(str(claim.get("claimed_at")).replace("Z", "+00:00"))
            except ValueError:
                return DispatchResult("UNKNOWN", f"claim {claim.get('loop_id')} has an unreadable time")
            if other not in commands and now - claimed < self.pending_window:
                return DispatchResult("WAIT", f"CARRIER_BUSY: Loop {claim.get('loop_id')} claimed without its "
                                              f"command yet (another controller mid-dispatch)")
        mine = [c for c in claims if command_id is not None and c.get("command_id") == command_id]
        if mine:
            try:  # our own claim at the tip is not another controller's activity
                path = f"automation/command_bus/loop_id_claims/{mine[0]['loop_id']}.json"
                if tip in self.git.added_by(self.branch, path):
                    parent = self.git._git("rev-parse", f"{tip}^").stdout.strip()
                    committed = self.git.commit_time(parent) or committed
            except Exception as exc:
                return DispatchResult("UNKNOWN", f"carrier tip ownership unverifiable: {exc}")
        age = now - datetime.fromisoformat(committed)
        if age < self.quiet:
            return DispatchResult("WAIT", f"CARRIER_BUSY: carrier changed {int(age.total_seconds())}s ago "
                                          f"(quiet window {int(self.quiet.total_seconds())}s)")
        return DispatchResult("PASS", "carrier quiet: no unfinished run, no pending claim, no foreign stream use")


def cancelled_carrier_runs(rest: GitHubRestReader, *, since: str,
                           workflow_file: str = CARRIER_WORKFLOW) -> list[dict[str, Any]]:
    """Interference check: carrier runs cancelled since ``since`` (anyone's)."""
    start = datetime.fromisoformat(since.replace("Z", "+00:00"))
    return [{"id": r["id"], "head_sha": r["head_sha"], "created_at": r["created_at"]}
            for r in rest.recent_workflow_runs(workflow_file)
            if r.get("conclusion") == "cancelled"
            and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= start]


def outstanding_dispatches(git: GitLiveClient, policy: dict[str, Any], origin_loop_id: str) -> list[dict[str, Any]]:
    """Dispatched commands whose result is still unsettled.

    A dispatch is settled once it is adopted, or once Claude's inspection ordered a
    Jules corrective (``JULES_CORRECTIVE*``) and a later round was dispatched, so a
    superseded failed candidate never blocks a handback or keeps being polled.
    """
    prefix = f"{EVIDENCE_ROOT}/claude-auto-dispatch-intents/"
    mine = []
    for content in git.list(prefix, policy["data_branch"]):
        intent = validate_dispatch_intent(json.loads(content.text))
        if intent["origin_loop_id"] == origin_loop_id:
            mine.append(intent)
    inspections = ReinspectionStore(git, data_branch=policy["data_branch"]).extend_all(
        InspectionStore(git, data_branch=policy["data_branch"]).list_all())
    adoption = SafeAdoption(client=git, refs=git, policy=policy)
    found = []
    for intent in mine:
        command_id = intent["carrier_request"]["command_id"]
        receipt = git.get(dispatch_receipt_path(command_id), policy["data_branch"])
        if receipt is None or json.loads(receipt.text).get("state") != "DISPATCHED":
            continue
        adopted = git.get(adoption_receipt_path(command_id), policy["data_branch"])
        if adopted is not None:
            digest = json.loads(adopted.text).get("inspection_sha256")
            matches = [r for r in inspections if r["command_id"] == command_id and r["inspection_sha256"] == digest]
            verified = adoption.verify_adopted(intent=intent, inspection=matches[0] if len(matches) == 1 else None)
            if verified.status != "VERIFIED":
                raise ValueError(f"unverifiable adoption receipt for {command_id}: {verified.reason}")
            continue
        corrective = any(r["command_id"] == command_id and r["decision"].startswith("JULES_CORRECTIVE")
                         for r in inspections)
        if corrective:
            # A later *intent* may be half-written. Supersession requires a
            # DISPATCHED receipt for the corrective of this exact task family.
            family = re.sub(r"-fix[0-9]+$", "", intent["task_id"])
            settled = False
            for other in mine:
                if other["origin_round"] <= intent["origin_round"] or not re.fullmatch(re.escape(family) + r"-fix[0-9]+", other["task_id"]):
                    continue
                later = git.get(dispatch_receipt_path(other["carrier_request"]["command_id"]), policy["data_branch"])
                if later is not None:
                    record = json.loads(later.text)
                    if record.get("state") == "DISPATCHED" and record.get("intent_sha256") == other["intent_sha256"]:
                        settled = True
                        break
            if settled:
                continue
        found.append(intent)
    return found


def poll_results(*, git: GitLiveClient, rest: GitHubRestReader, policy: dict[str, Any],
                 origin_loop_id: str) -> list[dict[str, Any]]:
    """Wake adapter: record every open Jules result head of outstanding dispatches."""
    inbox = ResultEventInbox(git, data_branch=policy["data_branch"])
    outcomes = []
    for intent in outstanding_dispatches(git, policy, origin_loop_id):
        work = intent["carrier_request"]["work_branch"]
        for pr in rest.pulls_for_base(work):
            head = pr["head"]["sha"]
            normalized = normalize_pull_request_event(
                event_name="pull_request", delivery_id=f"poll-{pr['number']}-{head}",
                payload=pull_request_payload(pr), expected_repo=policy["target_repo"])
            entry = {"command_id": intent["carrier_request"]["command_id"], "pr": pr["number"], "head": head,
                     "normalized": normalized.status, "reason": normalized.reason}
            if normalized.status == "ACCEPTED":
                recorded = inbox.record(normalized.record)
                entry["inbox"] = recorded.status
            outcomes.append(entry)
    return outcomes


def wake_resume(*, loop: ClaudeJulesAutoLoop, git: GitLiveClient, rest: GitHubRestReader,
                policy: dict[str, Any], origin_loop_id: str, now: str, max_steps: int = 12,
                poller: Any = poll_results, clock: Any = None) -> dict[str, Any]:
    """Ingest result PRs, restore durable controller state and continue to a real boundary.

    The wake itself grants no authority.  The unchanged controller still
    enforces owner fencing, live authorization, budgets, exact-head checks and
    append-only duplicate guards on every mutating step.
    """
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or not 1 <= max_steps <= 100:
        raise ValueError("max_steps must be an integer in 1..100")
    poll_error = None
    try:
        polled = poller(git=git, rest=rest, policy=policy, origin_loop_id=origin_loop_id)
    except Exception as exc:
        # Do not resend ingestion writes. Already durable records can still
        # permit controller progress; it revalidates them independently.
        polled = []
        poll_error = f"UNKNOWN: poll outcome unavailable; no resend: {exc}"
    results = loop.run_until_boundary(now=now, max_steps=max_steps, clock=clock)
    return {
        "poll": polled,
        "poll_error": poll_error,
        "steps": [
            {
                "action": result.action,
                "status": result.status,
                "reason": result.reason,
                "details": {k: v for k, v in result.details.items() if k != "intent"},
            }
            for result in results
        ],
    }


def stream_activity(*, git: GitLiveClient, rest: GitHubRestReader, policy: dict[str, Any], lane_id: str,
                    target_branch: str, owner_chain: list[dict[str, Any]], now: str):
    """Read the stream's carrier claims and their result PRs (ChatGPT's and Claude's alike)."""
    claims = [json.loads(c.text) for c in git.list("automation/command_bus/loop_id_claims/", policy["carrier_branch"])]
    stream = [c for c in claims if c.get("lane_id") == lane_id and c.get("target_branch") == target_branch]
    prs = {c["command_id"]: rest.pulls_for_base(f"jules-work/{c['command_id']}") for c in stream}
    return observe_stream(lane_id=lane_id, target_branch=target_branch, claims=stream, result_prs=prs,
                          owner_chain=owner_chain, now=now)


def handover(action: str, *, git: GitLiveClient, rest: GitHubRestReader, policy: dict[str, Any],
             origin_loop_id: str, lane_id: str, now: str, write: bool) -> dict[str, Any]:
    """observe / takeover / handback / reclaim for one stream; writes only with ``write``."""
    backend = LoopOwnerGitHubBackend(git, branch=policy["data_branch"])
    read = backend.read_chain(origin_loop_id)
    if read.status != "READ":
        return {"status": "UNKNOWN", "reason": read.reason}
    chain = [json.loads(c.text) for c in git.list(f"automation/command_bus/loop_owner_events/{origin_loop_id}/",
                                                   policy["data_branch"])]
    target = policy["allowed_target_branches"][0]
    head = git.get_branch_head(target)
    if head is None:
        return {"status": "UNKNOWN", "reason": "stream target branch unavailable"}
    if action == "observe" or action == "takeover":
        activity = stream_activity(git=git, rest=rest, policy=policy, lane_id=lane_id, target_branch=target,
                                   owner_chain=chain, now=now)
        if action == "observe":
            return {"status": "OBSERVED", "activity": activity.__dict__, "owner": chain[-1] if chain else None}
        decision = decide_takeover(owner_chain=chain, activity=activity, auto_holder=policy["holder_id"],
                                   loop_id=origin_loop_id, expected_repo=policy["target_repo"],
                                   expected_pr=policy["expected_pr"], target_head=head, now=now)
    elif action == "renew":
        prefix = f"{EVIDENCE_ROOT}/claude-auto-dispatch-intents/"
        half = 0
        for content in git.list(prefix, policy["data_branch"]):
            intent = validate_dispatch_intent(json.loads(content.text))
            if intent["origin_loop_id"] == origin_loop_id and git.get(
                    dispatch_receipt_path(intent["carrier_request"]["command_id"]), policy["data_branch"]) is None:
                half += 1
        decision = decide_renew(owner_chain=chain, auto_holder=policy["holder_id"],
                                outstanding_dispatches=len(outstanding_dispatches(git, policy, origin_loop_id)),
                                half_written_intents=half, target_head=head, now=now)
    elif action == "handback":
        outstanding = len(outstanding_dispatches(git, policy, origin_loop_id))
        decision = decide_handback(owner_chain=chain, auto_holder=policy["holder_id"],
                                   outstanding_dispatches=outstanding, target_head=head, now=now)
    else:
        decision = decide_reclaim(owner_chain=chain, semiauto_holder=SEMIAUTO_HOLDER, target_head=head, now=now)
    if write:
        decision = append_decision(backend, decision)
    return {"status": decision.status, "reason": decision.reason, "event": decision.event}


# -- CLI ---------------------------------------------------------------------
def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def build_live(args: argparse.Namespace) -> tuple[ClaudeJulesAutoLoop, GitLiveClient, GitHubRestReader, dict[str, Any]]:
    policy, roadmap = _load(args.policy), _load(args.roadmap)
    campaign_policy = _load(args.campaign_policy) if getattr(args, "campaign_policy", None) else None
    git = GitLiveClient(args.repo_dir, message_trailer=args.trailer or "")
    rest = GitHubRestReader(policy["target_repo"])
    facts = LiveResultFacts(git=git, rest=rest, policy=policy, scratch_dir=args.scratch)
    loop = ClaudeJulesAutoLoop(client=git, refs=git, policy=policy,
                               owner_reader=LoopOwnerGitHubBackend(git, branch=policy["data_branch"]),
                               roadmap=roadmap, facts=facts, origin_loop_id=args.origin_loop_id, lane_id=args.lane_id,
                               campaign_policy=campaign_policy,
                               recovery_policy=(recovery_policy() if getattr(args, "recovery_policy", None) == "v1"
                                                else None),
                               carrier_guard=CarrierQuietGuard(
                                   git=git, rest=rest, carrier_branch=policy["carrier_branch"],
                                   isolated_targets=tuple(policy["allowed_target_branches"]),
                                   data_branch=policy["data_branch"]))
    return loop, git, rest, policy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude_jules_live")
    parser.add_argument("command", choices=["status", "step", "poll", "wake-resume", "budget", "record-review", "record-observation", "record-settlement",
                                            "build-settlement", "recovery-history",
                                            "observe", "takeover", "renew", "handback", "reclaim",
                                            "carrier"])
    parser.add_argument("--policy", required=True)
    parser.add_argument("--roadmap", required=True)
    parser.add_argument("--campaign-policy", help="optional CLAUDE_AUTO_CAMPAIGN_POLICY_V1 JSON; legacy policy remains the default")
    parser.add_argument("--recovery-policy", choices=["v1"],
                        help="opt in to reasoned bounded recovery v1; omitted keeps the legacy retry behaviour")
    parser.add_argument("--origin-loop-id", required=True)
    parser.add_argument("--lane-id", required=True)
    parser.add_argument("--repo-dir", default=".")
    parser.add_argument("--scratch", default=os.path.join(tempfile.gettempdir(), "claude-jules-live"))
    parser.add_argument("--trailer", default="")
    parser.add_argument("--file")
    parser.add_argument("--max-steps", type=int, default=12, help="wake-resume controller step budget (1..100)")
    parser.add_argument("--write", action="store_true", help="append the owner event (handover commands only)")
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    now = args.now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    loop, git, rest, policy = build_live(args)
    if args.command == "budget":
        slots = LiveBudgetLedger(git, data_branch=policy["data_branch"]).slots()
        out: Any = {"used": len(slots), "cap": 10, "slots": [{k: s[k] for k in ("slot", "command_id", "acquired_at")} for s in slots]}
    elif args.command == "poll":
        out = {"now": now, "results": poll_results(git=git, rest=rest, policy=policy, origin_loop_id=args.origin_loop_id)}
    elif args.command == "wake-resume":
        out = {"now": now, **wake_resume(
            loop=loop, git=git, rest=rest, policy=policy, origin_loop_id=args.origin_loop_id,
            now=now, max_steps=args.max_steps,
            clock=(None if args.now else lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
        )}
    elif args.command == "record-review":
        record = validate_review(_load(args.file))
        path = review_path(record["command_id"], record["candidate_head"])
        if git.get(path, policy["data_branch"]) is None:
            git.create(path, canonical_json(record), f"Claude AUTO review {record['command_id']}", policy["data_branch"])
        stored = git.get(path, policy["data_branch"])
        out = {"path": path, "verified": stored is not None and json.loads(stored.text) == record}
    elif args.command == "record-observation":
        record = validate_observation(_load(args.file))
        path = observation_path(record["command_id"])
        if git.get(path, policy["data_branch"]) is None:
            git.create(path, canonical_json(record), f"Claude AUTO dispatch observation {record['command_id']}",
                       policy["data_branch"])
        stored = git.get(path, policy["data_branch"])
        out = {"path": path, "verified": stored is not None and json.loads(stored.text) == record}
    elif args.command == "build-settlement":
        request = _load(args.file)
        try:
            out = {"record": observation_from_readback_run(
                command_id=request["command_id"], status_request_path=request["status_request_path"], git=git,
                rest=rest, carrier_branch=policy["carrier_branch"], observed_at=now), "written": False}
        except (ReadbackUnavailable, ReadbackMismatch) as exc:
            out = {"record": None, "written": False, "status": "UNKNOWN", "reason": f"{type(exc).__name__}: {exc}"}
    elif args.command == "recovery-history":
        events = loop.campaign_state.events()
        out = {"campaign_id": loop.campaign_policy["campaign_id"],
               "recovery_policy": "v1" if loop.recovery_policy is not None else "legacy",
               "events": [{"type": e["event_type"], "recorded_at": e["recorded_at"],
                           **{k: e["payload"].get(k) for k in ("task_id", "cause", "attempt", "decision", "reason",
                                                               "not_before", "provider_budget_effect")
                              if k in e["payload"]}}
                          for e in events if e["event_type"] in {"RECOVERY_ATTEMPT", "RECOVERY_DECISION",
                                                                "TASK_BLOCKED", "TASK_REPLAN"}]}
    elif args.command == "record-settlement":
        record = validate_settlement_observation(_load(args.file))
        path = settlement_path(record["command_id"], record["workflow_run_id"])
        try:  # a record is stored only when the job's own log confirms it
            verify_readback(record, git=git, rest=rest, carrier_branch=policy["carrier_branch"])
        except (ReadbackUnavailable, ReadbackMismatch) as exc:
            print(json.dumps({"path": path, "verified": False, "written": False,
                              "reason": f"{type(exc).__name__}: {exc}"}, indent=2, sort_keys=True))
            return 2
        if git.get(path, policy["data_branch"]) is None:
            git.create(path, canonical_json(record), f"Claude AUTO provider settlement {record['command_id']}",
                       policy["data_branch"])
        stored = git.get(path, policy["data_branch"])
        out = {"path": path, "verified": stored is not None and json.loads(stored.text) == record}
    elif args.command == "carrier":
        quiet = CarrierQuietGuard(git=git, rest=rest, carrier_branch=policy["carrier_branch"],
                                  isolated_targets=tuple(policy["allowed_target_branches"]),
                                  data_branch=policy["data_branch"])()
        out = {"now": now, "quiet": quiet.status, "reason": quiet.reason}
        if args.file:  # --file holds an ISO timestamp: list carrier runs cancelled since then
            with open(args.file, encoding="utf-8") as handle:
                out["cancelled_since"] = cancelled_carrier_runs(rest, since=handle.read().strip())
    elif args.command in {"observe", "takeover", "renew", "handback", "reclaim"}:
        out = handover(args.command, git=git, rest=rest, policy=policy, origin_loop_id=args.origin_loop_id,
                       lane_id=args.lane_id, now=now, write=args.write)
    elif args.command == "status":
        out = {"now": now, "outstanding": [i["carrier_request"]["command_id"] for i in
                                           outstanding_dispatches(git, policy, args.origin_loop_id)]}
    else:
        result = loop.step(now=now)
        out = {"now": now, "action": result.action, "status": result.status, "reason": result.reason,
               "details": {k: v for k, v in result.details.items() if k != "intent"}}
    out["pushes"] = git.pushes
    print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
