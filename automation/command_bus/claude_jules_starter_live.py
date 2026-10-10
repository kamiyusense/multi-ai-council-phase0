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
from datetime import datetime, timezone
from typing import Any, Callable

from . import claude_jules_production_starter as st
from .claude_jules_loop import CHECKPOINT_MARKER
from .claude_jules_starter_gh import GhLoopPort, Getter, find_duplicate_issue

AUTH_PROFILE = "CLAUDE_JULES_LIVE_AUTHORIZATION_V1"
WRITE_KINDS = {"comment", "add_label", "create_issue"}
_AUTH_KEYS = {"profile", "campaign_id", "repository", "issues", "writes", "max_labels", "max_writes", "expires_at",
              "approved_by", "approval_ref", "route", "billing", "usage_credits_confirmed_off"}
_RECORD_MARKERS = (st.INTENT_MARKER, st.START_RECEIPT_MARKER, CHECKPOINT_MARKER)


class LiveWriteRefused(st.PreparedOnly):
    """The write is outside the authorization: not sent (treated like a prepared write by the loop)."""


def validate_authorization(auth: Any, *, campaign: dict[str, Any], now: str) -> list[str]:
    if not isinstance(auth, dict) or set(auth) != _AUTH_KEYS or auth.get("profile") != AUTH_PROFILE:
        return ["authorization is not a CLAUDE_JULES_LIVE_AUTHORIZATION_V1 record"]
    problems = []
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
    if auth["route"] != st.ROUTE or auth["billing"] != "subscription":
        problems.append("authorization must name the GitHub-native subscription route")
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
                 now: Callable[[], str] = lambda: st._fmt(datetime.now(timezone.utc))):
        super().__init__(get, repo=repo, campaign=campaign, route_declaration=route_declaration, signals=signals)
        self.runner, self.now = runner, now
        self.authorization = authorization
        self.problems = ["no LIVE authorization: prepare-only"] if authorization is None else \
            validate_authorization(authorization, campaign=campaign, now=now())
        self.sent: list[dict[str, Any]] = []
        self.labels_sent = 0

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
        if not self._allowed_issue(n):
            self._refuse("add_label", n, f"issue #{n} is not authorized", payload)
        if self.labels_sent >= self.authorization["max_labels"]:
            self._refuse("add_label", n, "authorized label count used up", payload)
        self.labels_sent += 1                          # counted before sending: a lost response still counts
        self._send("add_label", f"repos/{self.repo}/issues/{n}/labels", payload, n)

    def create_issue(self, title, body):
        payload = {"title": title, "body": body}
        if not self.live:
            self._prepare("create_issue", payload=payload, refused=self.problems)
        task, _ = st._task_of(body)
        meta = (task or {}).get("campaign") or {}
        if not isinstance(meta, dict) or meta.get("campaign_id") != self.campaign["campaign_id"]:
            self._refuse("create_issue", None, "issue body must hold this campaign's task block", payload)
        self._issue_list = None                        # fresh listing: Layer 3 may have created it since
        dup = find_duplicate_issue(self._all_issues(), title, body)
        if dup is not None:
            self._refuse("create_issue", dup["issue"], f"DUPLICATE: issue #{dup['issue']} ({dup['match']})", payload)
        proc = self._send("create_issue", f"repos/{self.repo}/issues", payload, None)
        try:
            return int(json.loads(proc.stdout)["number"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise st.WriteOutcomeUnknown("issue created but its number is unreadable") from exc

    def _prepare(self, kind: str, **data: Any):
        self.prepared.append({"write": kind, **data})
        raise st.PreparedOnly(kind)
