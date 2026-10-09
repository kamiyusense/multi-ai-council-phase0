"""Production Starter: the gate between a Claude PASS and the next Jules task (GitHub-native route only).

The Claude reviewer Routine judges a Jules PR.  On PASS it records a receipt
and creates the next task issue, unlabeled.  This module decides whether that
issue may be started, and drives the start so that one approved task never
becomes two Jules tasks, whatever crashes, duplicate events or lost responses
happen in between.

Responsibilities are split on purpose:

* the **reviewer** judges meaning (diff, acceptance criteria, root cause,
  regressions, test quality) and never adds the ``jules`` label;
* the **starter** judges nothing semantic.  It checks records and identities:
  the predecessor's PASS receipt is real and terminal, it names this issue,
  the issue holds exactly the task the human-approved campaign manifest
  prepared (``task_sha256``), the task stays inside policy (route, kind, paths,
  no human-boundary request), the campaign has capacity, quota is not confirmed
  exhausted, and the start was not already made.

The only start mechanism is ``GitHub issue -> jules label -> Jules GitHub
integration``.  There is no other transport here and no fallback to one.

Start sequence (every step is re-derived from a fresh read of GitHub):

1. ``WRITE_INTENT``: an intent record comment on the issue (before the label,
   so Jules is not engaged yet).  It names attempt, controller and a nonce.
2. readback; only the controller that owns the *current* intent continues.
3. ``WRITE_LABEL``: the ``jules`` label, at most once per attempt.
4. readback; the label is present -> ``WRITE_START_RECEIPT`` (terminal).

Duplicate-start resistance (not assumed exactly-once):

* the label is never added to an issue that ever had it (label history), so a
  replay can never fire a second ``labeled`` event;
* adding a label that is already present creates no event on GitHub;
* a write whose outcome is unknown is never repeated in the same run; the next
  wake re-reads and continues from what GitHub actually holds;
* an intent that did not lead to a label is taken over only after its lease
  expires, by a new attempt that names the one it supersedes; attempts are
  bounded by policy;
* a stale controller always re-reads before writing and stops when the current
  intent is not its own.

Blocked tasks are isolated: a decision names its scope (``task`` / ``campaign``
/ ``global``).  Only a confirmed API/paid route or an invalid policy stops
everything (``HARD_STOP``); confirmed quota exhaustion pauses new starts until
the reset; unknown quota follows policy and never ends the campaign by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from .claude_closed_loop_protocol import RECEIPT_MARKER, TASK_MARKER, _block
from .claude_closed_loop_review import PASS, parse_receipt, validate_task_v2

ROUTE = "jules-github-app-issue-label"
LABEL = "jules"
INTENT_MARKER = "<!-- claude-jules-starter-intent v1"
START_RECEIPT_MARKER = "<!-- claude-jules-starter-receipt v1"
POLICY_PROFILE = "CLAUDE_JULES_STARTER_POLICY_V1"
CAMPAIGN_PROFILE = "CLAUDE_JULES_CAMPAIGN_V1"
INTENT_PROFILE = "CLAUDE_JULES_STARTER_INTENT_V1"
START_RECEIPT_PROFILE = "CLAUDE_JULES_STARTER_RECEIPT_V1"
STARTER_META_PROFILE = "CLAUDE_JULES_STARTER_META_V1"

# step actions
WRITE_INTENT, WRITE_LABEL, WRITE_START_RECEIPT = "WRITE_INTENT", "WRITE_LABEL", "WRITE_START_RECEIPT"
NO_OP, IGNORE, DEFER, BLOCKED, HARD_STOP = "NO_OP", "IGNORE", "DEFER", "BLOCKED", "HARD_STOP"
WRITES = {WRITE_INTENT, WRITE_LABEL, WRITE_START_RECEIPT}
# quota states
QUOTA_OK, QUOTA_UNKNOWN, QUOTA_EXHAUSTED = "OK", "UNKNOWN", "CONFIRMED_EXHAUSTED"

DEFAULT_POLICY: dict[str, Any] = {
    "profile": POLICY_PROFILE,
    "policy_version": 1,
    "repository": "kamiyusense/multi-ai-council-phase0",
    "base_branch": "main",
    "route": ROUTE,
    "billing": "subscription",
    "allow_api_fallback": False,
    "allow_metered_fallback": False,
    "trusted_writers": ["kamiyusense"],
    "max_concurrent_tasks": 1,
    "max_campaign_rounds": None,          # no fixed total; a campaign may set its own
    "max_corrective_rounds": 2,
    "intent_lease_minutes": 15,
    "max_label_attempts": 2,
    "jules_ack_timeout_minutes": 30,
    "read_retry": {"attempts": 3, "backoff_seconds": [0, 5, 30]},
    "allowed_task_kinds": ["proof", "code_change"],
    "on_quota_unknown": "proceed",        # "proceed" or "defer"; unknown alone never ends a campaign
    "base_policy": "descendant_untouched",  # or "exact"
    # The control plane itself (workflows, the Claude x Jules modules, the reviewer) is never a Jules task.
    "forbidden_path_prefixes": [
        ".github/",
        "automation/command_bus/claude_jules_",
        "automation/command_bus/claude_closed_loop_",
    ],
}

# Requests that need a human whatever the task says (scanned in every task string).
_HUMAN_BOUNDARY = re.compile(
    r"\bmerge\s+(?:this|the|a|that)\s+(?:pr|pull\s+request)\b|\bforce[\s-]?push|\bdelete\s+(?:the\s+)?branch"
    r"|\bpush\s+(?:directly\s+)?to\s+(?:main|the\s+default\s+branch)|\brewrite\s+(?:the\s+)?history"
    r"|\bgit\s+(?:reset\s+--hard|clean\s+-[a-z]*f)|\brm\s+-rf\b|\bapi[\s_-]?key\b|\bbilling\b|\bcredits\b"
    r"|\boverages?\b|\bchange\s+(?:repository\s+)?(?:settings|permissions)\b",
    re.I)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_PAID_WORDS = {"api_key", "rest_api_key", "metered", "overage", "paid", "pay_as_you_go"}


# ---------------------------------------------------------------- helpers
def _ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _fmt(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def task_sha256(task: dict[str, Any]) -> str:
    """Identity of a prepared task: SHA-256 of its canonical JSON."""
    return hashlib.sha256(canonical(task).encode()).hexdigest()


def _strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


@dataclass(frozen=True)
class Step:
    action: str
    reason: str
    issue: int | None = None
    scope: str = "task"                  # task / campaign / global
    body: str | None = None              # comment body for WRITE_INTENT / WRITE_START_RECEIPT
    nonce: str | None = None
    retry_after: str | None = None
    checks: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "reason": self.reason, "issue": self.issue, "scope": self.scope,
                "body": self.body, "nonce": self.nonce, "retry_after": self.retry_after, "checks": list(self.checks)}


# ---------------------------------------------------------------- policy
def validate_policy(policy: Any) -> list[str]:
    """Problems that make the policy unusable.  Any problem is a HARD_STOP: nothing starts."""
    if not isinstance(policy, dict) or policy.get("profile") != POLICY_PROFILE:
        return ["policy profile is not CLAUDE_JULES_STARTER_POLICY_V1"]
    problems = []
    if policy.get("route") != ROUTE:
        problems.append(f"policy route must be {ROUTE}")
    if policy.get("billing") != "subscription":
        problems.append("policy billing must be subscription")
    if policy.get("allow_api_fallback") is not False or policy.get("allow_metered_fallback") is not False:
        problems.append("API / metered fallback must be disabled")
    for key, low in (("max_concurrent_tasks", 1), ("max_corrective_rounds", 0), ("intent_lease_minutes", 1),
                     ("max_label_attempts", 1)):
        value = policy.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < low:
            problems.append(f"policy {key} invalid")
    rounds = policy.get("max_campaign_rounds")
    if rounds is not None and (isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 1):
        problems.append("policy max_campaign_rounds must be null or a positive integer")
    if policy.get("on_quota_unknown") not in {"proceed", "defer"}:
        problems.append("policy on_quota_unknown must be proceed or defer")
    if policy.get("base_policy") not in {"exact", "descendant_untouched"}:
        problems.append("policy base_policy invalid")
    if not isinstance(policy.get("trusted_writers"), list) or not policy["trusted_writers"]:
        problems.append("policy trusted_writers missing")
    if not isinstance(policy.get("allowed_task_kinds"), list) or not policy["allowed_task_kinds"]:
        problems.append("policy allowed_task_kinds missing")
    if not isinstance(policy.get("forbidden_path_prefixes"), list):
        problems.append("policy forbidden_path_prefixes missing")
    for key in ("repository", "base_branch"):
        if not isinstance(policy.get(key), str) or not policy[key]:
            problems.append(f"policy {key} missing")
    return problems


def make_policy(**overrides: Any) -> dict[str, Any]:
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    policy.update(overrides)
    return policy


def route_problem(observation: Any) -> tuple[str, str] | None:
    """(action, reason) when the observed start route is not the GitHub-native subscription route."""
    if not isinstance(observation, dict) or not observation:
        return DEFER, "start route not observed (UNKNOWN): nothing starts until it is"
    values = {str(observation.get(k, "")).lower() for k in ("transport", "auth_method", "billing_route")}
    if values & _PAID_WORDS or any("rest" in v and "api" in v for v in values):
        return HARD_STOP, f"API / metered route observed {sorted(values)}: new model work stops"
    if observation.get("transport") != ROUTE or observation.get("billing_route") != "subscription" \
            or observation.get("auth_method") != "account_oauth":
        return DEFER, f"start route is not confirmed GitHub-native subscription ({sorted(values)}): UNKNOWN"
    return None


# ---------------------------------------------------------------- campaign manifest
def render_task_issue(task: dict[str, Any], intro: str) -> str:
    """An issue body that holds exactly one task block (what Jules reads and what the reviewer parses)."""
    return f"{intro.strip()}\n\n{TASK_MARKER}\n{canonical(task)}\n-->\n"


def build_campaign(*, campaign_id: str, loop_id: str, tasks: list[dict[str, Any]], policy: dict[str, Any],
                   external_predecessor: dict[str, Any] | None, manifest_ref: dict[str, str]) -> dict[str, Any]:
    """A campaign manifest from task specs (in order).

    Each spec is ``{"title", "intro", "task": {...task block without campaign/next_task...}}``.  Task ``k`` gets
    ``campaign`` metadata naming its predecessor (task ``k-1``; ``external_predecessor`` for the first) and a
    ``next_task`` whose body is referenced, not inlined (``body_ref``), so blocks never nest.  Built from the last
    task backwards because each ``next_task`` pins the next task's ``task_sha256``.
    """
    entries: list[dict[str, Any]] = []
    following: dict[str, Any] | None = None
    for seq in range(len(tasks), 0, -1):
        spec = tasks[seq - 1]
        task = dict(spec["task"])
        if seq == 1:
            pred = external_predecessor
        else:
            prev = tasks[seq - 2]["task"]
            pred = {"task_id": prev["task_id"], "correlation_id": prev["correlation_id"], "issue": None}
        task["loop_id"] = loop_id
        task["campaign"] = {"profile": STARTER_META_PROFILE, "campaign_id": campaign_id, "seq": seq,
                            "predecessor": pred}
        if following is not None:
            task["next_task"] = {"title": following["title"],
                                 "body_ref": {"campaign_id": campaign_id, "seq": seq + 1,
                                              "task_sha256": following["task_sha256"], **manifest_ref}}
        else:
            task.pop("next_task", None)
        entry = {"seq": seq, "title": spec["title"], "body": render_task_issue(task, spec["intro"]),
                 "task_sha256": task_sha256(task)}
        entries.insert(0, entry)
        following = entry
    manifest = {"profile": CAMPAIGN_PROFILE, "campaign_id": campaign_id, "loop_id": loop_id,
                "repository": policy["repository"], "policy": policy, "tasks": entries}
    validate_campaign(manifest)
    return manifest


def validate_campaign(manifest: Any) -> dict[int, dict[str, Any]]:
    """The entries by seq; raises ValueError for any inconsistency (a broken manifest starts nothing)."""
    if not isinstance(manifest, dict) or manifest.get("profile") != CAMPAIGN_PROFILE:
        raise ValueError("campaign manifest profile invalid")
    if problems := validate_policy(manifest.get("policy")):
        raise ValueError("campaign policy invalid: " + "; ".join(problems))
    entries: dict[int, dict[str, Any]] = {}
    for n, entry in enumerate(manifest.get("tasks") or [], start=1):
        if entry.get("seq") != n:
            raise ValueError("campaign tasks must be numbered 1..n in order")
        blocks = _block(entry.get("body") or "", TASK_MARKER)
        if len(blocks) != 1:
            raise ValueError(f"campaign task {n} body must hold exactly one task block")
        task = blocks[0]
        meta = task.get("campaign") or {}
        if meta.get("campaign_id") != manifest["campaign_id"] or meta.get("seq") != n:
            raise ValueError(f"campaign task {n} metadata does not match the manifest")
        if task_sha256(task) != entry.get("task_sha256"):
            raise ValueError(f"campaign task {n} task_sha256 mismatch")
        if (problem := validate_task_v2(task, pr_base=manifest["policy"]["base_branch"])) is not None:
            raise ValueError(f"campaign task {n}: {problem}")
        entries[n] = {**entry, "task": task}
    if not entries:
        raise ValueError("campaign has no tasks")
    return entries


# ---------------------------------------------------------------- durable starter records
_INTENT_KEYS = {"profile", "campaign_id", "seq", "task_id", "correlation_id", "generation", "issue", "task_sha256",
                "predecessor_correlation_id", "predecessor_pr_head", "attempt", "supersedes", "controller", "nonce",
                "policy_version", "route", "created_at"}
_RECEIPT_KEYS = {"profile", "campaign_id", "seq", "task_id", "correlation_id", "generation", "issue", "task_sha256",
                 "attempt", "intent_comment", "controller", "label", "outcome", "created_at"}


def _record(body: str, marker: str, keys: set[str], profile: str) -> list[dict[str, Any]]:
    out = []
    for rec in _block(body, marker):
        if not isinstance(rec, dict) or set(rec) != keys or rec.get("profile") != profile:
            raise ValueError(f"starter record malformed ({marker})")
        out.append(rec)
    return out


def render_intent(record: dict[str, Any]) -> str:
    _record(f"{INTENT_MARKER}\n{canonical(record)}\n-->", INTENT_MARKER, _INTENT_KEYS, INTENT_PROFILE)
    return (f"Production starter record: start intent for `{record['task_id']}` attempt {record['attempt']} "
            f"(record only; no action needed).\n\n{INTENT_MARKER}\n{canonical(record)}\n-->\n")


def render_start_receipt(record: dict[str, Any]) -> str:
    _record(f"{START_RECEIPT_MARKER}\n{canonical(record)}\n-->", START_RECEIPT_MARKER, _RECEIPT_KEYS,
            START_RECEIPT_PROFILE)
    return (f"Production starter record: `{record['task_id']}` {record['outcome'].lower()} "
            f"(record only; no action needed).\n\n{START_RECEIPT_MARKER}\n{canonical(record)}\n-->\n")


def starter_records(comments: list[dict[str, Any]], trusted: set[str]) -> tuple[list[dict], list[dict]]:
    """Intents (with their comment id / time) and start receipts written by trusted writers.

    A record by anyone else is ignored (it cannot start or stop anything).  A malformed trusted record raises:
    the caller writes nothing over it.
    """
    intents, receipts = [], []
    for c in sorted(comments, key=lambda c: c["id"]):
        if c.get("author") not in trusted:
            continue
        body = c.get("body") or ""
        if INTENT_MARKER in body:
            for rec in _record(body, INTENT_MARKER, _INTENT_KEYS, INTENT_PROFILE):
                intents.append({**rec, "_comment": c["id"], "_at": c["created_at"]})
        if START_RECEIPT_MARKER in body:
            receipts.extend(_record(body, START_RECEIPT_MARKER, _RECEIPT_KEYS, START_RECEIPT_PROFILE))
    return intents, receipts


def current_intent(intents: list[dict[str, Any]], lease: timedelta) -> dict[str, Any] | None:
    """The intent that owns the start now.

    Attempt 1 is the earliest attempt-1 intent (concurrent controllers: earliest comment wins).  Attempt k+1 is
    valid only when it names attempt k in ``supersedes`` and was written after attempt k's lease expired; any
    other intent is ignored.
    """
    firsts = [i for i in intents if i["attempt"] == 1 and i["supersedes"] is None]
    if not firsts:
        return None
    cur = firsts[0]
    while True:
        nxt = [i for i in intents if i["attempt"] == cur["attempt"] + 1 and i["supersedes"] == cur["_comment"]
               and _ts(i["_at"]) >= _ts(cur["_at"]) + lease]
        if not nxt:
            return cur
        cur = nxt[0]


# ---------------------------------------------------------------- the decision
def _trusted_pass_receipts(pred: dict[str, Any], correlation: str, trusted: set[str]) -> list[dict[str, Any]]:
    out = []
    for c in sorted(pred.get("comments") or [], key=lambda c: c["id"]):
        body = c.get("body") or ""
        if c.get("author") not in trusted:
            continue
        start = 0
        while (i := body.find(RECEIPT_MARKER, start)) != -1:
            rec = parse_receipt(body[i:])       # strict v2 for every block; raises on malformed
            if rec["correlation_id"] == correlation:
                out.append(rec)
            start = i + len(RECEIPT_MARKER)
    return out


def _task_of(body: str) -> tuple[dict[str, Any] | None, str | None]:
    if TASK_MARKER not in (body or ""):
        return None, "not a closed-loop task issue"
    try:
        blocks = _block(body, TASK_MARKER)
    except (ValueError, json.JSONDecodeError) as exc:
        return None, f"task metadata unreadable: {exc}"
    if len(blocks) != 1 or not isinstance(blocks[0], dict):
        return None, "issue must hold exactly one task block"
    return blocks[0], None


def next_step(snapshot: dict[str, Any], *, campaign: dict[str, Any], controller: str,
              session_nonces: frozenset[str] = frozenset(), label_written: frozenset[str] = frozenset()) -> Step:
    """One deterministic step from a fresh GitHub snapshot.  Same snapshot, same step."""
    policy = campaign.get("policy") if isinstance(campaign, dict) else None
    if problems := validate_policy(policy):
        return Step(HARD_STOP, "policy invalid: " + "; ".join(problems), scope="global")
    try:
        entries = validate_campaign(campaign)
    except (ValueError, json.JSONDecodeError) as exc:
        return Step(HARD_STOP, f"campaign manifest invalid: {exc}", scope="campaign")
    if (rp := route_problem(snapshot.get("route_observation"))) is not None:
        return Step(rp[0], rp[1], scope="global")
    trusted = set(policy["trusted_writers"])
    now = _ts(snapshot["now"])
    cand = snapshot.get("candidate") or {}
    number = cand.get("number")
    checks: list[str] = ["policy", "manifest", "route"]

    if not cand or cand.get("state") == "MISSING":
        return Step(BLOCKED, "issue missing or deleted", number)
    if not isinstance(cand.get("comments"), list) or not isinstance(cand.get("label_events"), list)             or not isinstance(cand.get("labels"), list):
        return Step(DEFER, "issue comments / labels / label history not read (UNKNOWN): nothing starts", number)
    task, problem = _task_of(cand.get("body") or "")
    if task is None:
        return Step(IGNORE if problem == "not a closed-loop task issue" else BLOCKED, problem, number)
    meta = task.get("campaign")
    if not isinstance(meta, dict) or meta.get("profile") != STARTER_META_PROFILE:
        return Step(BLOCKED, "task has no starter metadata: a human must decide how to start it", number)
    if meta.get("campaign_id") != campaign["campaign_id"]:
        return Step(IGNORE, "issue belongs to another campaign", number)
    entry = entries.get(meta.get("seq"))
    if entry is None:
        return Step(BLOCKED, f"seq {meta.get('seq')!r} is not in the campaign manifest", number)
    if task_sha256(task) != entry["task_sha256"]:
        return Step(BLOCKED, "task differs from the prepared task (edited after preparation)", number)
    if cand.get("title") != entry["title"]:
        return Step(BLOCKED, "issue title differs from the prepared task", number)
    checks.append("task_identity")
    if snapshot.get("repository") != policy["repository"] or campaign.get("repository") != policy["repository"]:
        return Step(BLOCKED, "wrong repository", number)
    if task.get("route") not in (None, ROUTE):
        return Step(BLOCKED, f"task asks for route {task.get('route')!r}; only {ROUTE} may start", number)
    if task.get("kind", "proof") not in policy["allowed_task_kinds"]:
        return Step(BLOCKED, f"task kind {task.get('kind')!r} is not allowed by policy", number)
    if task.get("expected_target_branch") != policy["base_branch"]:
        return Step(BLOCKED, "task targets a branch other than the policy base branch", number)
    for p in task.get("allowed_paths") or []:
        if any(str(p.get("path", "")).startswith(pre) for pre in policy["forbidden_path_prefixes"]):
            return Step(BLOCKED, f"task touches a protected path {p.get('path')!r}", number)
    if task.get("human_boundary") is True or any(_HUMAN_BOUNDARY.search(s) for s in _strings(
            {k: v for k, v in task.items() if k not in {"next_task", "campaign"}})):
        return Step(BLOCKED, "task asks for a human-boundary operation (merge / default write / destructive / "
                             "billing / key): a human must handle it", number)
    if task.get("max_corrective_rounds", 0) > policy["max_corrective_rounds"]:
        return Step(BLOCKED, "task corrective budget exceeds policy", number)
    event_gen = (snapshot.get("event") or {}).get("generation")
    if event_gen is not None and event_gen != task["generation"]:
        return Step(NO_OP, f"wake for generation {event_gen}, task is generation {task['generation']}", number)
    checks.append("task_policy")

    try:
        intents, receipts = starter_records(cand.get("comments") or [], trusted)
    except (ValueError, json.JSONDecodeError) as exc:
        return Step(NO_OP, f"starter record unreadable ({exc}); nothing is written over it", number)
    intents = [i for i in intents if i["correlation_id"] == task["correlation_id"]]
    receipts = [r for r in receipts if r["correlation_id"] == task["correlation_id"]]
    if receipts:
        return Step(NO_OP, "already started (terminal start receipt exists)", number)
    lease = timedelta(minutes=policy["intent_lease_minutes"])
    cur = current_intent(intents, lease)
    labels = set(cand.get("labels") or [])
    ever_labeled = any(e.get("event") == "labeled" and e.get("label") == LABEL for e in cand.get("label_events") or [])
    if LABEL in labels or ever_labeled:
        if cur is not None and LABEL in labels:
            body = render_start_receipt({
                "profile": START_RECEIPT_PROFILE, "campaign_id": campaign["campaign_id"], "seq": meta["seq"],
                "task_id": task["task_id"], "correlation_id": task["correlation_id"],
                "generation": task["generation"], "issue": number, "task_sha256": entry["task_sha256"],
                "attempt": cur["attempt"], "intent_comment": cur["_comment"], "controller": controller,
                "label": LABEL, "outcome": "STARTED", "created_at": _fmt(now)})
            return Step(WRITE_START_RECEIPT, "label observed after the intent: record the start", number,
                        body=body, checks=tuple(checks + ["label_observed"]))
        if cur is not None:
            return Step(BLOCKED, "label was added and later removed: never re-added (a second Jules task)", number)
        return Step(BLOCKED, "issue was labeled outside the starter; not started again", number)
    if cand.get("state") != "OPEN":
        return Step(BLOCKED, "issue is closed", number)
    checks.append("not_started")

    pred_meta = meta.get("predecessor")
    pred = snapshot.get("predecessor")
    if not isinstance(pred_meta, dict) or not pred_meta.get("correlation_id"):
        return Step(BLOCKED, "task names no predecessor", number)
    if not pred:
        return Step(DEFER, "predecessor issue not read yet", number)
    if pred_meta.get("issue") is not None and pred.get("number") != pred_meta["issue"]:
        return Step(BLOCKED, "predecessor issue number differs from the task metadata", number)
    pred_task, problem = _task_of(pred.get("body") or "")
    if pred_task is None or pred_task.get("correlation_id") != pred_meta["correlation_id"] \
            or pred_task.get("task_id") != pred_meta.get("task_id"):
        return Step(BLOCKED, "predecessor issue does not hold the expected predecessor task", number)
    try:
        pred_receipts = _trusted_pass_receipts(pred, pred_meta["correlation_id"], trusted)
    except (ValueError, json.JSONDecodeError, KeyError) as exc:
        return Step(NO_OP, f"predecessor receipt unreadable ({exc}); UNKNOWN, nothing starts", number)
    passes = [r for r in pred_receipts if r["verdict"] == PASS]
    if len(passes) > 1:
        return Step(BLOCKED, "more than one PASS receipt for the predecessor (UNKNOWN)", number)
    if not passes:
        if any(r["verdict"] == "BLOCKED" or r["decision"] == "TASK_BLOCKED" for r in pred_receipts):
            return Step(BLOCKED, "predecessor is blocked; its successor does not start", number)
        return Step(DEFER, "predecessor has no PASS receipt yet", number)
    receipt = passes[0]
    if receipt["decision"] != "ADOPT_RECORDED" or receipt["next_issue"] != number:
        return Step(BLOCKED, "the predecessor PASS receipt does not name this issue as its next issue", number)
    if receipt["task_id"] != pred_meta.get("task_id") or receipt["generation"] != pred_task.get("generation"):
        return Step(BLOCKED, "predecessor receipt identity mismatch", number)
    if pred.get("pr_head") is not None and pred["pr_head"] != receipt["pr_head_sha"]:
        return Step(BLOCKED, "predecessor PR head changed after PASS", number)
    checks.append("predecessor_pass")

    base_head = snapshot.get("base_head")
    if not _SHA40.fullmatch(str(base_head or "")):
        return Step(DEFER, "base branch head not read (UNKNOWN)", number)
    if base_head != task["expected_target_head"]:
        changed = snapshot.get("base_changed_paths")
        allowed = {p["path"] for p in task["allowed_paths"]}
        if policy["base_policy"] == "exact":
            return Step(BLOCKED, "stale task: base branch moved (exact base policy)", number)
        if changed is None:
            return Step(DEFER, "base branch moved and the changed paths are not known (UNKNOWN)", number)
        if set(changed) & allowed:
            return Step(BLOCKED, "stale task: base branch changed an allowed path; re-prepare the task", number)
    checks.append("base")

    rounds = campaign.get("max_rounds", policy.get("max_campaign_rounds"))
    if rounds is not None and meta["seq"] > rounds:
        return Step(DEFER, "campaign round limit reached; a human may extend it", number, scope="campaign")
    active = [a for a in snapshot.get("active_tasks") or [] if a.get("correlation_id") != task["correlation_id"]]
    if len(active) >= policy["max_concurrent_tasks"]:
        return Step(DEFER, f"{len(active)} Jules task(s) still running (limit {policy['max_concurrent_tasks']})",
                    number, scope="global")
    quota = snapshot.get("quota") or {"state": QUOTA_UNKNOWN}
    if quota.get("state") == QUOTA_EXHAUSTED:
        reset = quota.get("reset_at")
        if not reset or now < _ts(reset):
            return Step(DEFER, "Jules quota confirmed exhausted: new starts wait for the reset", number,
                        scope="global", retry_after=reset)
    elif quota.get("state") != QUOTA_OK and policy["on_quota_unknown"] == "defer":
        return Step(DEFER, "quota UNKNOWN and policy defers on unknown", number, scope="global")
    checks.append("capacity")

    def intent_body(attempt: int, supersedes: int | None) -> tuple[str, str]:
        nonce = uuid.uuid4().hex
        return render_intent({
            "profile": INTENT_PROFILE, "campaign_id": campaign["campaign_id"], "seq": meta["seq"],
            "task_id": task["task_id"], "correlation_id": task["correlation_id"], "generation": task["generation"],
            "issue": number, "task_sha256": entry["task_sha256"],
            "predecessor_correlation_id": pred_meta["correlation_id"], "predecessor_pr_head": receipt["pr_head_sha"],
            "attempt": attempt, "supersedes": supersedes, "controller": controller, "nonce": nonce,
            "policy_version": policy["policy_version"], "route": ROUTE, "created_at": _fmt(now)}), nonce

    if cur is None:
        if intents:
            return Step(NO_OP, "intent records exist but none is a valid first attempt (UNKNOWN)", number)
        body, nonce = intent_body(1, None)
        return Step(WRITE_INTENT, "all start conditions hold: record the intent", number, body=body, nonce=nonce,
                    checks=tuple(checks))
    if cur["nonce"] in session_nonces:
        if cur["nonce"] in label_written:
            return Step(DEFER, "label write outcome unknown and not visible: never re-sent in this run", number)
        return Step(WRITE_LABEL, "this controller owns the current intent: add the label once", number,
                    nonce=cur["nonce"], checks=tuple(checks + ["intent_owned"]))
    if now < _ts(cur["_at"]) + lease:
        return Step(DEFER, f"intent attempt {cur['attempt']} by {cur['controller']} is within its lease", number,
                    retry_after=_fmt(_ts(cur["_at"]) + lease))
    if cur["attempt"] >= policy["max_label_attempts"]:
        return Step(BLOCKED, "label attempts exhausted without a visible label; a human must look", number)
    body, nonce = intent_body(cur["attempt"] + 1, cur["_comment"])
    return Step(WRITE_INTENT, f"intent attempt {cur['attempt']} expired without a label: take over", number,
                body=body, nonce=nonce, checks=tuple(checks + ["takeover"]))


# ---------------------------------------------------------------- wake routing
def wake_targets(event: dict[str, Any], *, trusted: Iterable[str]) -> list[dict[str, Any]]:
    """Which issues a GitHub event asks the starter to look at (no reads, no writes).

    * ``issues.opened``: the new issue (normally DEFER until the PASS receipt lands);
    * ``issue_comment.created`` with a trusted reviewer receipt: the receipt's ``next_issue``;
    * ``issues.labeled`` / ``issues.unlabeled`` for ``jules``: reconcile that issue;
    * ``schedule`` / ``manual``: every open campaign issue (reset after quota, recovery);
    * anything else: nothing.
    """
    name = event.get("name")
    if name == "issues.opened" and isinstance(event.get("issue"), int):
        return [{"issue": event["issue"]}]
    if name in {"issues.labeled", "issues.unlabeled"} and event.get("label") == LABEL:
        return [{"issue": event["issue"]}]
    if name == "issue_comment.created" and event.get("author") in set(trusted) \
            and RECEIPT_MARKER in (event.get("body") or ""):
        try:
            recs = _block(event["body"], RECEIPT_MARKER)
        except (ValueError, json.JSONDecodeError):
            return []
        return [{"issue": r["next_issue"], "predecessor": event["issue"]} for r in recs
                if isinstance(r, dict) and r.get("verdict") == PASS and isinstance(r.get("next_issue"), int)]
    if name in {"schedule", "manual"}:
        return [{"issue": "ALL_OPEN_CANDIDATES"}]
    return []


# ---------------------------------------------------------------- executor
class WriteOutcomeUnknown(Exception):
    """A write whose effect is not known (timeout, lost response).  Never repeated blindly."""


class PreparedOnly(Exception):
    """Raised by a prepare-only port: the write was prepared, not sent."""


@dataclass
class RunResult:
    steps: list[Step] = field(default_factory=list)
    writes: list[tuple[str, int]] = field(default_factory=list)
    stopped: str = ""


def run_starter(*, read_snapshot: Callable[[], dict[str, Any]], add_comment: Callable[[int, str], Any],
                add_label: Callable[[int, str], Any], campaign: dict[str, Any], controller: str,
                max_steps: int = 6) -> RunResult:
    """Drive one issue: read -> step -> at most one write -> read again, until a non-write step.

    A write that raises ``WriteOutcomeUnknown`` is not repeated: the run ends with DEFER and the next wake
    reconciles from GitHub.  Any other exception (a crash) propagates; a fresh controller resumes from GitHub.
    """
    result = RunResult()
    nonces: set[str] = set()
    labelled: set[str] = set()
    for _ in range(max_steps):
        step = next_step(read_snapshot(), campaign=campaign, controller=controller,
                         session_nonces=frozenset(nonces), label_written=frozenset(labelled))
        result.steps.append(step)
        if step.action not in WRITES:
            result.stopped = step.action
            return result
        try:
            if step.action == WRITE_INTENT:
                nonces.add(step.nonce)
                add_comment(step.issue, step.body)
            elif step.action == WRITE_LABEL:
                labelled.add(step.nonce)
                add_label(step.issue, LABEL)
            else:
                add_comment(step.issue, step.body)
            result.writes.append((step.action, step.issue))
        except WriteOutcomeUnknown:
            result.writes.append((step.action + "?", step.issue))
            result.steps.append(Step(DEFER, f"{step.action} outcome unknown: not re-sent; next wake reconciles",
                                     step.issue))
            result.stopped = DEFER
            return result
        except PreparedOnly:
            result.writes.append((step.action + " (prepared)", step.issue))
            result.stopped = "PREPARED"
            return result
    result.stopped = "MAX_STEPS"
    return result


def render_next(manifest: dict[str, Any], *, seq: int, expected_sha256: str) -> dict[str, str]:
    """Title and body of campaign task ``seq`` for the reviewer to create verbatim; refuses a different task."""
    entry = validate_campaign(manifest).get(seq)
    if entry is None:
        raise ValueError(f"campaign has no task {seq}")
    if entry["task_sha256"] != expected_sha256:
        raise ValueError("task_sha256 differs from the pinned body_ref: the next issue is not created")
    return {"title": entry["title"], "body": entry["body"]}


# ---------------------------------------------------------------- CLI (prepare-only)
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Production Starter (prepare-only): print the next step as JSON.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("step", help="decide the next step from a GitHub snapshot JSON")
    s.add_argument("--campaign", required=True)
    s.add_argument("--snapshot", required=True)
    s.add_argument("--controller", required=True)
    s.add_argument("--session-nonce", action="append", default=[],
                   help="nonce of an intent this run wrote (repeat); only then may it add the label")
    s.add_argument("--label-written-nonce", action="append", default=[],
                   help="nonce whose label write this run already sent (never sent again)")
    v = sub.add_parser("validate-campaign")
    v.add_argument("--campaign", required=True)
    r = sub.add_parser("render-next", help="print the pinned next task's exact title and body (for the reviewer)")
    r.add_argument("--campaign", required=True)
    r.add_argument("--seq", type=int, required=True)
    r.add_argument("--task-sha256", required=True)
    args = ap.parse_args(argv)
    with open(args.campaign, encoding="utf-8") as fh:
        campaign = json.load(fh)
    if args.cmd == "render-next":
        try:
            print(json.dumps(render_next(campaign, seq=args.seq, expected_sha256=args.task_sha256),
                             ensure_ascii=False))
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        return 0
    if args.cmd == "validate-campaign":
        entries = validate_campaign(campaign)
        print(json.dumps({"campaign_id": campaign["campaign_id"], "tasks": len(entries),
                          "task_sha256": {k: e["task_sha256"] for k, e in entries.items()}}, indent=2))
        return 0
    with open(args.snapshot, encoding="utf-8") as fh:
        snapshot = json.load(fh)
    step = next_step(snapshot, campaign=campaign, controller=args.controller,
                     session_nonces=frozenset(args.session_nonce), label_written=frozenset(args.label_written_nonce))
    print(json.dumps(step.as_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
