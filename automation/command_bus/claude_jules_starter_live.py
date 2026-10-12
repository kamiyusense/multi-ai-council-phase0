"""LIVE write port for the loop: disabled unless a human-approved, unexpired authorization names the exact writes.

``GhLiveWritePort`` is ``GhLoopPort`` (GitHub reads through ``gh``) plus the only writes the loop needs:

* an intent or start receipt comment, and a loop checkpoint comment;
* adding the label ``jules`` to one authorized issue;
* creating an issue whose body holds this campaign's task block.

It is **prepare-only by default**. Every write is sent only when all of the following hold. Otherwise the write is
recorded as prepared and ``PreparedOnly`` is raised, and nothing is sent:

* a ``CLAUDE_JULES_LIVE_AUTHORIZATION_V1`` record is given;
* the record matches the campaign and the repository;
* it is approved by a named human with an approval reference;
* it has not expired;
* it confirms the GitHub-native subscription route;
* it carries the human's statement that usage credits are off (no metered overage for unattended runs);
* the write itself is inside its limits: allowed kind, allowed issue, a count below the maximum, and a body that
  is a loop record (never an ``@jules`` message, never free text).

Never retried: a timeout or a failed exit raises ``WriteOutcomeUnknown``. The loop then reads GitHub back and
decides; it never sends the same write blindly.  After every write the issue cache is dropped, so the next read is
fresh.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import claude_jules_production_starter as st
from .claude_jules_loop import CHECKPOINT_MARKER
from .claude_jules_durable_budget import USABLE, DurableBudget, origin_of, pre_label_problems
from .claude_jules_loop import TransientRead
from .claude_jules_starter_gh import CARRIER_BRANCH, MESSAGE_DIR, GhLoopPort, Getter, find_duplicate_issue

AUTH_PROFILE = "CLAUDE_JULES_LIVE_AUTHORIZATION_V1"
AUTH_PROFILE_V2 = "CLAUDE_JULES_LIVE_AUTHORIZATION_V2"     # V1 + durable budget binding; required for a label
WRITE_KINDS = {"comment", "add_label", "create_issue", "api_message"}
API_MESSAGES_PER_WAKE, API_MESSAGES_PER_DAY = 1, 3          # owner limits for Jules API resends, 2026-10-11
_AUTH_KEYS = {"profile", "campaign_id", "repository", "issues", "writes", "max_labels", "max_writes", "expires_at",
              "approved_by", "approval_ref", "route", "billing", "usage_credits_confirmed_off"}
_AUTH_KEYS_V2 = _AUTH_KEYS | {"budget_id", "max_activations"}
_RECORD_MARKERS = (st.INTENT_MARKER, st.START_RECEIPT_MARKER, CHECKPOINT_MARKER)


class LiveWriteRefused(st.PreparedOnly):
    """The write is outside the authorization: not sent (treated like a prepared write by the loop)."""


def validate_authorization(auth: Any, *, campaign: dict[str, Any], now: str) -> list[str]:
    v1 = isinstance(auth, dict) and set(auth) == _AUTH_KEYS and auth.get("profile") == AUTH_PROFILE
    v2 = isinstance(auth, dict) and set(auth) == _AUTH_KEYS_V2 and auth.get("profile") == AUTH_PROFILE_V2
    if not (v1 or v2):
        return ["authorization is not a CLAUDE_JULES_LIVE_AUTHORIZATION_V1/V2 record"]
    problems = []
    if v2:
        if not isinstance(auth["budget_id"], str) or not auth["budget_id"].strip():
            problems.append("authorization budget_id missing")
        n = auth["max_activations"]
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            problems.append("authorization max_activations invalid")
    if auth["campaign_id"] != campaign.get("campaign_id"):
        problems.append("authorization is for another campaign")
    if auth["repository"] != campaign.get("repository"):
        problems.append("authorization is for another repository")
    if not isinstance(auth["approved_by"], str) or not auth["approved_by"].strip():
        problems.append("authorization is not approved by a named human")
    if not isinstance(auth["approval_ref"], str) or not auth["approval_ref"].strip():
        problems.append("authorization has no approval reference")
    try:
        if st._ts(now) >= st._ts(auth["expires_at"]):
            problems.append("authorization expired")
    except (TypeError, ValueError):
        problems.append("authorization expires_at invalid")
    if auth["route"] != (campaign.get("policy") or {}).get("route", st.ROUTE) or auth["route"] not in st.ROUTES \
            or auth["billing"] != "subscription":
        problems.append("authorization must name the campaign's subscription start route")
    if auth["usage_credits_confirmed_off"] is not True:
        problems.append("usage credits are not confirmed off by the human (metered overage risk)")
    if not isinstance(auth["writes"], list) or not auth["writes"] or not set(auth["writes"]) <= WRITE_KINDS:
        problems.append("authorization writes invalid")
    issues = auth["issues"]
    if issues != "campaign" and (not isinstance(issues, list) or not all(isinstance(i, int) for i in issues)):
        problems.append("authorization issues must be a list of issue numbers or \"campaign\"")
    for key in ("max_labels", "max_writes"):
        if isinstance(auth[key], bool) or not isinstance(auth[key], int) or auth[key] < 1:
            problems.append(f"authorization {key} invalid")
    return problems


def gh_run(cmd: list[str], payload: dict[str, Any]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                          timeout=60)


class GhLiveWritePort(GhLoopPort):
    def __init__(self, get: Getter, *, repo: str, campaign: dict[str, Any], route_declaration: dict[str, Any],
                 signals: list[dict[str, Any]] | None, authorization: dict[str, Any] | None,
                 runner: Callable[[list[str], dict[str, Any]], Any] = gh_run,
                 now: Callable[[], str] = lambda: st._fmt(datetime.now(timezone.utc)),
                 budget: DurableBudget | None = None, carrier: Any = None):
        super().__init__(get, repo=repo, campaign=campaign, route_declaration=route_declaration, signals=signals)
        self.runner, self.now = runner, now
        self.budget = budget                      # the cross-wake budget; per-wake counters below are not one
        self.ambiguous: str | None = None         # a label whose outcome is unknown: no more labels this wake
        self.reservations: list[dict[str, Any]] = []
        self.authorization = authorization
        self.problems = ["no LIVE authorization: prepare-only"] if authorization is None else \
            validate_authorization(authorization, campaign=campaign, now=now())
        self.sent: list[dict[str, Any]] = []
        self.labels_sent = 0
        self.carrier = carrier                    # git client for the Jules API carrier branch (None: no resend)
        self.api_messages_sent = 0
        self.retry_after: str | None = None       # a rolling-window budget refusal: when a start is possible again

    @property
    def live(self) -> bool:
        return not self.problems

    def _allowed_issue(self, n: int) -> bool:
        issues = self.authorization["issues"]
        if issues == "campaign":
            task, _ = st._task_of(self.read_issue(n).get("body") or "")
            meta = (task or {}).get("campaign") or {}
            return isinstance(meta, dict) and meta.get("campaign_id") == self.campaign["campaign_id"]
        return n in issues

    def _send(self, kind: str, path: str, payload: dict[str, Any], issue: int | None) -> Any:
        if not self.live:
            self._prepare(kind, issue=issue, payload=payload, refused=self.problems)
        problems = list(validate_authorization(self.authorization, campaign=self.campaign, now=self.now()))
        if kind not in self.authorization["writes"]:
            problems.append(f"{kind} is not an authorized write")
        if len(self.sent) >= self.authorization["max_writes"]:
            problems.append("authorized write count used up")
        if problems:
            self.prepared.append({"write": kind, "issue": issue, "payload": payload, "refused": problems})
            raise LiveWriteRefused("; ".join(problems))
        cmd = ["gh", "api", "--method", "POST", path, "--input", "-"]
        try:
            proc = self.runner(cmd, payload)
        except subprocess.TimeoutExpired as exc:
            raise st.WriteOutcomeUnknown(f"{kind} #{issue}: timeout") from exc
        finally:
            self._issue_list = self._pull_list = None   # a created issue shows up in the next listing
            if issue is not None:
                self._issues.pop(issue, None)           # the next read is fresh (readback)
        self.sent.append({"write": kind, "issue": issue, "path": path})
        if getattr(proc, "returncode", 1) != 0:
            raise st.WriteOutcomeUnknown(f"{kind} #{issue}: exit {getattr(proc, 'returncode', None)}")
        return proc

    STOP_LABEL = "loop-stop"

    def stop_requested(self) -> str | None:
        """The human's stop switch, readable from a phone: close the control issue or give it ``loop-stop``.
        Only NEW starts and NEW task issues stop; records and reviews of running work continue.  A campaign with
        no control issue, a missing or unreadable one, or one that is not the campaign's control issue never starts
        anything new (there would be no stop switch and no place for its checkpoints)."""
        n = self.campaign.get("control_issue")
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            return "the campaign has no control issue (required for LIVE: it is the stop switch)"
        try:
            self._issues.pop(n, None)
            control = self.read_issue(n)
        except TransientRead as exc:
            return f"control issue unreadable ({exc})"
        if control.get("state") == "MISSING":
            return f"control issue #{n} does not exist"
        if st._task_of(control.get("body") or "")[0] is not None:
            return f"control issue #{n} is a task issue, not a control issue"
        if control.get("state") != "OPEN":
            return f"control issue #{n} is closed (human stop)"
        if self.STOP_LABEL in (control.get("labels") or []):
            return f"control issue #{n} has the {self.STOP_LABEL!r} label (human stop)"
        return None

    def _refuse(self, kind: str, issue: int | None, reason: str, payload: dict[str, Any]):
        self.prepared.append({"write": kind, "issue": issue, "payload": payload, "refused": [reason]})
        raise LiveWriteRefused(reason)

    def add_comment(self, n, body):
        payload = {"body": body}
        if not self.live:
            self._prepare("comment", issue=n, payload=payload, refused=self.problems)
        if body.lstrip().startswith("@") or not any(m in body for m in _RECORD_MARKERS):
            self._refuse("comment", n, "only loop records may be posted (no @mention, no free text)", payload)
        control = self.campaign.get("control_issue")
        if n != control and not self._allowed_issue(n):
            self._refuse("comment", n, f"issue #{n} is not authorized", payload)
        self._send("comment", f"repos/{self.repo}/issues/{n}/comments", payload, n)

    def add_label(self, n, label):
        payload = {"labels": [label]}
        if not self.live:
            self._prepare("add_label", issue=n, payload=payload, refused=self.problems)
        if label != st.LABEL:
            self._refuse("add_label", n, f"only the {st.LABEL!r} label may be added", payload)
        try:
            allowed = self._allowed_issue(n)
        except TransientRead as exc:
            self._refuse("add_label", n, f"issue #{n} unreadable before the label ({exc})", payload)
        if not allowed:
            self._refuse("add_label", n, f"issue #{n} is not authorized", payload)
        stop = self.stop_requested()
        if stop:
            self._refuse("add_label", n, f"HUMAN_STOP: {stop}", payload)
        if self.ambiguous:
            self._refuse("add_label", n, f"an earlier label outcome is unknown ({self.ambiguous}); read back first",
                         payload)
        if self.labels_sent >= self.authorization["max_labels"]:          # per-wake cap (secondary)
            self._refuse("add_label", n, "authorized label count used up", payload)
        # ---- the cross-wake boundary: a V2 authorization bound to a durable budget, fresh GitHub state
        if self.authorization.get("profile") != AUTH_PROFILE_V2:
            self._refuse("add_label", n, "a V1 authorization has per-wake counters only; a label needs a V2 "
                                         "authorization bound to the durable budget", payload)
        if self.budget is None:
            self._refuse("add_label", n, "no durable budget ledger: per-wake counters are not a global budget",
                         payload)
        if self.authorization["budget_id"] != self.budget.decl["budget_id"]:
            self._refuse("add_label", n, "authorization is for another budget", payload)
        if self.budget.decl.get("campaign_id", self.campaign["campaign_id"]) != self.campaign["campaign_id"]:
            self._refuse("add_label", n, "the budget declaration is for another campaign", payload)
        self._issues.pop(n, None)                      # fresh read, never this wake's cache
        try:
            issue = self.read_issue(n)
        except TransientRead as exc:
            self._refuse("add_label", n, f"issue #{n} unreadable before the label ({exc})", payload)
        problems, activation = pre_label_problems(
            issue, repository=self.repo, campaign=self.campaign,
            trusted=set(self.campaign["policy"]["trusted_writers"]), base_head=self.base_head,
            changed_paths=self.base_changed_paths)
        if problems:
            self._refuse("add_label", n, "; ".join(problems), payload)
        api = self.campaign["policy"]["route"] == st.ROUTE_API
        if api:                                        # everything that could refuse is checked before the slot
            try:
                path, request = self.api_start_request(n, issue)
            except ValueError as exc:
                self._refuse("add_label", n, f"API start request: {exc}", payload)
            if self.carrier is None or self.carrier.remote_head(CARRIER_BRANCH) is None:
                self._refuse("add_label", n, f"API route: carrier branch {CARRIER_BRANCH} unavailable", payload)
        res = self.budget.reserve(activation, origin=origin_of(self.authorization),
                                  max_for_origin=self.authorization["max_activations"], now=self.now())
        self.reservations.append({"issue": n, "status": res.status, "reason": res.reason})
        if res.status not in USABLE:
            if res.retry_after:
                self.retry_after = res.retry_after
            self._refuse("add_label", n, f"budget {res.status}: {res.reason}", payload)
        self.labels_sent += 1                          # counted before sending: a lost response still counts
        try:
            if api:
                self._send_api_start(n, path, request)
            else:
                self._send("add_label", f"repos/{self.repo}/issues/{n}/labels", payload, n)
        except st.WriteOutcomeUnknown as exc:
            self.ambiguous = f"issue #{n}: {exc}"      # the slot stays consumed; the next wake reads back
            raise
        if not self.budget.holds(res.record):
            self.ambiguous = f"issue #{n}: budget slot {res.record['slot']} no longer holds this activation"
            raise st.WriteOutcomeUnknown(self.ambiguous)

    def create_issue(self, title, body):
        payload = {"title": title, "body": body}
        if not self.live:
            self._prepare("create_issue", payload=payload, refused=self.problems)
        task, _ = st._task_of(body)
        meta = (task or {}).get("campaign") or {}
        if not isinstance(meta, dict) or meta.get("campaign_id") != self.campaign["campaign_id"]:
            self._refuse("create_issue", None, "issue body must hold this campaign's task block", payload)
        stop = self.stop_requested()
        if stop:
            self._refuse("create_issue", None, f"HUMAN_STOP: {stop}", payload)
        self._issue_list = None                        # fresh listing: Layer 3 may have created it since
        dup = find_duplicate_issue(self._all_issues(), title, body)
        if dup is not None:
            self._refuse("create_issue", dup["issue"], f"DUPLICATE: issue #{dup['issue']} ({dup['match']})", payload)
        proc = self._send("create_issue", f"repos/{self.repo}/issues", payload, None)
        try:
            return int(json.loads(proc.stdout)["number"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise st.WriteOutcomeUnknown("issue created but its number is unreadable") from exc

    def start_rate_limited_until(self):
        """The rolling 24-hour start limit, checked before any intent: None when a start may be attempted."""
        if not self.live or self.budget is None:
            return None
        return self.budget.rate_limited_until(self.now())

    def _send_api_start(self, n, path, request):
        """The API route's label: one create-only start request file; the start workflow calls the Jules API."""
        problems = list(validate_authorization(self.authorization, campaign=self.campaign, now=self.now()))
        if "add_label" not in self.authorization["writes"]:
            problems.append("add_label (start) is not an authorized write")
        if len(self.sent) >= self.authorization["max_writes"]:
            problems.append("authorized write count used up")
        if problems:
            self.prepared.append({"write": "add_label", "issue": n, "path": path, "refused": problems})
            raise LiveWriteRefused("; ".join(problems))
        self.sent.append({"write": "add_label", "issue": n, "path": path})
        try:
            self.carrier.create(path, json.dumps(request, indent=2, ensure_ascii=False) + "\n",
                                f"Jules API start for issue #{n}", CARRIER_BRANCH)
        except RuntimeError as exc:
            if "create-only conflict" not in str(exc):  # an existing file is an earlier start: never a second one
                raise st.WriteOutcomeUnknown(f"API start #{n}: {exc}") from exc
        except Exception as exc:                       # noqa: BLE001 - outcome unknown, read back next wake
            raise st.WriteOutcomeUnknown(f"API start #{n}: {type(exc).__name__}") from exc
        finally:
            self._issues.pop(n, None)                  # the readback sees the carrier afresh

    def api_message(self, rid, *, issue, receipt, head):
        """Resend an ignored corrective through the Jules API: one create-only request file on the carrier branch.

        Limits (owner, 2026-10-11): one per corrective round (the request id), one per wake, three per 24 hours.
        Returns "SENT", or "NOT_SENT: ..." / "REFUSED: ..." when nothing was written; an unknown push outcome raises
        ``WriteOutcomeUnknown`` and the next wake reads the carrier back instead of sending again."""
        try:
            path, request = self.api_message_request(rid, receipt=receipt, head=head)
        except ValueError as exc:
            return f"NOT_SENT: {exc}"
        if not self.live:
            self._prepare("api_message", issue=issue, path=path, request=request, refused=self.problems)
        problems = list(validate_authorization(self.authorization, campaign=self.campaign, now=self.now()))
        if "api_message" not in self.authorization["writes"]:
            problems.append("api_message is not an authorized write")
        if len(self.sent) >= self.authorization["max_writes"]:
            problems.append("authorized write count used up")
        if self.api_messages_sent >= API_MESSAGES_PER_WAKE:
            problems.append("Jules API message already sent this wake")
        if stop := self.stop_requested():
            problems.append(f"HUMAN_STOP: {stop}")
        if self.carrier is None:
            problems.append("no carrier git client")
        if not problems:
            since = st._fmt(st._ts(self.now()) - timedelta(hours=24))
            try:
                recent = self._carrier_commits(MESSAGE_DIR.rstrip("/"), since=since)
            except TransientRead as exc:
                recent = None
                problems.append(f"Jules API messages of the last 24 hours unreadable ({exc})")
            if recent is not None and len(recent) >= API_MESSAGES_PER_DAY:
                problems.append(f"{len(recent)} Jules API messages in the last 24 hours (limit "
                                f"{API_MESSAGES_PER_DAY})")
        if problems:
            self.prepared.append({"write": "api_message", "issue": issue, "path": path, "refused": problems})
            return "REFUSED: " + "; ".join(problems)
        self.api_messages_sent += 1                    # counted before sending: a lost response still counts
        self.sent.append({"write": "api_message", "issue": issue, "path": path})
        try:
            self.carrier.create(path, json.dumps(request, indent=2, ensure_ascii=False) + "\n",
                                f"Jules API resend {rid}", CARRIER_BRANCH)
        except RuntimeError as exc:
            if "create-only conflict" in str(exc):
                return "SENT"                          # an earlier wake sent it; the file is the record
            if "does not exist" in str(exc):           # GitLiveClient checks the branch before writing anything
                return f"NOT_SENT: carrier branch {CARRIER_BRANCH} does not exist"
            raise st.WriteOutcomeUnknown(f"api_message {rid}: {exc}") from exc
        except Exception as exc:                       # noqa: BLE001 - any other failure: outcome unknown
            raise st.WriteOutcomeUnknown(f"api_message {rid}: {type(exc).__name__}") from exc
        return "SENT"

    def _prepare(self, kind: str, **data: Any):
        self.prepared.append({"write": kind, **data})
        raise st.PreparedOnly(kind)
