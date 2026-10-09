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

PLAN_MARKER = "<!-- claude-jules-plan v1"
PLAN_PROFILE = "CLAUDE_JULES_PLAN_V1"

# step actions.  Stop classes: CONTINUE (a write step), DEFER (temporary, re-checked), ISOLATE (this task only),
# HARD_STOP (a provider-execution boundary: no new Jules starts; other safe work may continue).
WRITE_INTENT, WRITE_LABEL, WRITE_START_RECEIPT = "WRITE_INTENT", "WRITE_LABEL", "WRITE_START_RECEIPT"
NO_OP, IGNORE, DEFER, ISOLATE, HARD_STOP = "NO_OP", "IGNORE", "DEFER", "ISOLATE", "HARD_STOP"
BLOCKED = ISOLATE                      # earlier name of ISOLATE
WRITES = {WRITE_INTENT, WRITE_LABEL, WRITE_START_RECEIPT}

# Typed operations.  A task declares what it does; the starter decides on the declared operations and the risk
# class of each path, never on a word appearing in the text.
SAFE_OPERATIONS = frozenset({"code_edit", "bug_fix", "refactor", "test_add", "test_fix", "fixture_add", "mock_add",
                             "docs_update", "evidence_update", "safety_test_add", "safety_static_fix"})
HUMAN_OPERATIONS = frozenset({
    "merge", "auto_merge_enable", "default_branch_write", "force_push", "branch_delete", "history_rewrite",
    "destructive_delete", "billing_change", "credits_change", "overages_change", "api_key_create",
    "api_key_change", "api_key_display", "secret_expose", "settings_change", "permission_change",
    "dispatch_scope_expand", "safety_guard_disable", "external_model_execution", "paid_provider_execution"})
# what a task may do to a safety-boundary file: fix, test, document, strengthen; never widen or disable
SAFETY_BOUNDARY_OPERATIONS = frozenset({"bug_fix", "refactor", "test_add", "test_fix", "fixture_add", "mock_add",
                                        "docs_update", "safety_test_add", "safety_static_fix"})
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
    "max_label_attempts": 5,             # each attempt only after the lease and a label-never-present readback
    "jules_ack_timeout_minutes": 30,
    "read_retry": {"attempts": 3, "backoff_seconds": [0, 5, 30]},
    "allowed_task_kinds": ["proof", "code_change"],
    "on_quota_unknown": "proceed",        # "proceed" or "defer"; unknown alone never ends a campaign
    "base_policy": "descendant_untouched",  # or "exact"
    # The control plane itself (workflows, the Claude x Jules modules, the reviewer) is never a Jules task.
    # Risk classes by path.  execution_config: what runs automation or holds permissions -> a human decides.
    # safety_boundary: the guards themselves -> allowed only to fix / test / strengthen, with the full suite.
    # Everything else is ordinary development.
    "path_classes": {
        "execution_config": [".github/", ".claude/", ".mcp.json"],
        "safety_boundary": [
            "automation/command_bus/claude_jules_provider_route.py",
            "automation/command_bus/claude_jules_production_starter.py",
            "automation/command_bus/claude_jules_task_planner.py",
            "automation/command_bus/claude_jules_loop.py",
            "automation/command_bus/claude_closed_loop_review.py",
            "automation/command_bus/claude_closed_loop_protocol.py",
            "automation/command_bus/jules_carrier_current/",
            "automation/command_bus/tests/test_jules_route_separation.py",
        ],
    },
    "defer_escalate_minutes": 240,        # a DEFER older than this, with no independent work left, is escalated
    "heartbeat_minutes": 360,             # loop checkpoint at least this often while anything is pending
}

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
    scope: str = "task"                  # task / campaign / global / provider_execution
    body: str | None = None              # comment body for WRITE_INTENT / WRITE_START_RECEIPT
    nonce: str | None = None
    retry_after: str | None = None
    checks: tuple[str, ...] = ()
    code: str = ""                       # machine reason (DEFER / ISOLATE ledger key)
    human_required: bool = False         # only a human can clear it (merge, human-boundary operation, ...)
    dependency: tuple[str, ...] = ()     # task ids this task waits for

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "reason": self.reason, "issue": self.issue, "scope": self.scope,
                "body": self.body, "nonce": self.nonce, "retry_after": self.retry_after, "checks": list(self.checks),
                "code": self.code, "human_required": self.human_required, "dependency": list(self.dependency)}


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
    classes = policy.get("path_classes")
    if not isinstance(classes, dict) or set(classes) != {"execution_config", "safety_boundary"} or any(
            not isinstance(v, list) or not all(isinstance(x, str) and x for x in v) for v in classes.values()):
        problems.append("policy path_classes invalid")
    elif ".github/" not in classes["execution_config"]:
        problems.append("policy path_classes must keep .github/ as execution_config")
    for key in ("defer_escalate_minutes", "heartbeat_minutes"):
        value = policy.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            problems.append(f"policy {key} invalid")
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
                   external_predecessor: dict[str, Any] | None, manifest_ref: dict[str, str],
                   objectives: list[dict[str, Any]] | None = None) -> dict[str, Any]:
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
    if objectives:
        manifest["objectives"] = objectives
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
    for o in manifest.get("objectives") or []:
        if not isinstance(o, dict) or not isinstance(o.get("objective_id"), str) or not o["objective_id"]:
            raise ValueError("objective needs objective_id")
        prefixes = o.get("scope_prefixes")
        if not isinstance(prefixes, list) or not prefixes or not all(isinstance(x, str) and x for x in prefixes):
            raise ValueError(f"objective {o['objective_id']} needs scope_prefixes")
        if any(path_class(x, manifest["policy"]) == "execution_config" for x in prefixes):
            raise ValueError(f"objective {o['objective_id']} scope includes execution configuration")
        ops = o.get("allowed_operations")
        if not isinstance(ops, list) or not ops or not set(ops) <= SAFE_OPERATIONS:
            raise ValueError(f"objective {o['objective_id']} allowed_operations must be safe operations")
        if not isinstance(o.get("approved_by"), str) or not o["approved_by"] or not isinstance(
                o.get("approved_at"), str):
            raise ValueError(f"objective {o['objective_id']} is not approved")
    if not entries and not manifest.get("objectives"):
        raise ValueError("campaign has no tasks and no objectives")
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


# ---------------------------------------------------------------- operation and path classification
_IMPERATIVE = (
    ("merge", r"\bmerge\s+(?:this|the|that|a|these|all)\s+(?:prs?|pull\s+requests?)\b"),
    ("auto_merge_enable", r"\b(?:enable|turn\s+on)\s+auto[\s-]?merge\b"),
    ("default_branch_write", r"\b(?:push|commit)\s+(?:directly\s+)?(?:to|into)\s+(?:main|master|the\s+default\s+branch)\b"),
    ("force_push", r"\bforce[\s-]?push\b|\bpush\s+--force\b"),
    ("branch_delete", r"\bdelete\s+(?:the\s+|a\s+|this\s+)?(?:remote\s+)?branch(?:es)?\b"),
    ("history_rewrite", r"\brewrite\s+(?:the\s+)?(?:git\s+)?history\b"),
    ("destructive_delete", r"\brm\s+-rf\b|\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[a-z]*f"),
    ("billing_change", r"\b(?:change|increase|raise|enable|disable|turn\s+(?:on|off))\s+(?:the\s+)?(?:billing|credits|"
                       r"usage\s+credits|overages?|spending\s+limits?)\b"),
    ("api_key_change", r"\b(?:create|generate|rotate|change|regenerate|display|print|show|reveal|expose)\s+"
                       r"(?:the\s+|an?\s+|our\s+)?(?:[a-z_]+\s+)?api[\s_-]?keys?\b"),
    ("settings_change", r"\bchange\s+(?:the\s+)?(?:repository|repo|account|github)\s+(?:settings|permissions)\b"),
    ("safety_guard_disable", r"\b(?:disable|remove|bypass|turn\s+off)\s+(?:the\s+)?(?:[a-z-]+\s+){0,3}(?:guard|safety\s+"
                             r"check|hard\s+stop)s?\b"),
)
_NEGATED = re.compile(r"(?:\bnot|\bnever|\bno|n't|\bwithout|\brefuses?\s+to|\bprevents?|\bforbids?|\bblocks?|"
                      r"\brejects?|\bcannot|\bmust\s+not)\b[^.;:\n]{0,40}$", re.I)


def requested_human_operations(task: dict[str, Any]) -> set[str]:
    """Human-boundary operations the task text *asks to perform* (imperative, not negated).

    This only cross-checks the declared ``operations``.  A word such as "billing" or "API key" in a description
    of a safety test is not a request.  "Merge the pull request" is, but "the guard refuses to merge the PR" is not.
    """
    found: set[str] = set()
    for text in _strings({k: v for k, v in task.items() if k not in {"next_task", "campaign"}}):
        for op, pattern in _IMPERATIVE:
            for m in re.finditer(pattern, text, re.I):
                if not _NEGATED.search(text[:m.start()]):
                    found.add(op)
    return found


def path_class(path: str, policy: dict[str, Any]) -> str:
    for cls in ("execution_config", "safety_boundary"):
        if any(path == pre or path.startswith(pre) for pre in policy["path_classes"][cls]):
            return cls
    return "ordinary"


def declared_operations(task: dict[str, Any]) -> Any:
    ops = task.get("operations")
    if ops is None:
        return ["code_edit"] if task.get("kind") == "code_change" else ["docs_update"]
    return ops


def classify_task(task: dict[str, Any], policy: dict[str, Any]) -> tuple[str, str, bool] | None:
    """None when the task's operations and paths may start without a human; else (code, reason, human_required)."""
    ops = declared_operations(task)
    if not isinstance(ops, list) or not ops or not all(isinstance(o, str) for o in ops):
        return "METADATA", "task operations malformed", False
    unknown = set(ops) - SAFE_OPERATIONS - HUMAN_OPERATIONS
    if unknown:
        return "UNKNOWN_OPERATION", f"unknown operations {sorted(unknown)}: the planner must classify them", False
    if human := set(ops) & HUMAN_OPERATIONS:
        return "HUMAN_OPERATION", f"task performs human-boundary operations {sorted(human)}", True
    if implied := requested_human_operations(task):
        return ("CLASSIFICATION_MISMATCH", f"task text asks for {sorted(implied)} but declares {sorted(ops)}: "
                "a human must confirm", True)
    full_suite = any("discover" in c for c in task.get("test_commands") or [])
    for p in task.get("allowed_paths") or []:
        cls = path_class(str(p.get("path", "")), policy)
        if cls == "execution_config":
            return "PROTECTED_PATH", f"{p['path']} configures automation or permissions: a human decides", True
        if cls == "safety_boundary":
            if not set(ops) <= SAFETY_BOUNDARY_OPERATIONS or task.get("safety_intent") not in {"preserve",
                                                                                              "strengthen"} \
                    or not full_suite:
                return ("SAFETY_BOUNDARY_TERMS", f"{p['path']} is a safety boundary: allowed only to fix / test / "
                        "strengthen (safety_intent preserve|strengthen) with the full test suite", False)
    return None


# ---------------------------------------------------------------- planner-created issues
def task_fingerprint(objective_id: str, signal_id: str, paths: Iterable[str]) -> str:
    """Identity of the *problem* a task solves: the same problem is never planned twice."""
    return hashlib.sha256(canonical({"objective": objective_id, "signal": signal_id,
                                     "paths": sorted(paths)}).encode()).hexdigest()[:16]


_PLAN_KEYS = {"profile", "campaign_id", "objective_id", "signal_id", "task_id", "task_sha256", "fingerprint",
              "evidence_refs", "depends_on", "created_at"}


def render_planned_issue(task: dict[str, Any], intro: str, plan: dict[str, Any]) -> str:
    """One issue body holding the task block and its plan record, so creation is a single atomic write."""
    if set(plan) != _PLAN_KEYS or plan["profile"] != PLAN_PROFILE or plan["task_sha256"] != task_sha256(task):
        raise ValueError("plan record malformed")
    return f"{render_task_issue(task, intro)}\n{PLAN_MARKER}\n{canonical(plan)}\n-->\n"


def plan_record_of(body: str) -> dict[str, Any] | None:
    try:
        plans = _block(body or "", PLAN_MARKER)
    except (ValueError, json.JSONDecodeError):
        return None
    if len(plans) != 1 or not isinstance(plans[0], dict) or set(plans[0]) != _PLAN_KEYS \
            or plans[0].get("profile") != PLAN_PROFILE:
        return None
    return plans[0]


def verify_planned_issue(cand: dict[str, Any], task: dict[str, Any],
                         campaign: dict[str, Any]) -> tuple[str, str] | None:
    policy = campaign["policy"]
    if cand.get("author") not in set(policy["trusted_writers"]):
        return "UNTRUSTED_AUTHOR", "planner issue was not created by a trusted writer"
    plan = plan_record_of(cand.get("body") or "")
    if plan is None:
        return "METADATA", "planner issue must hold exactly one readable plan record"
    meta = task["campaign"]
    if plan["task_sha256"] != task_sha256(task):
        return "EDITED", "task differs from its plan record (edited after planning)"
    objective = {o["objective_id"]: o for o in campaign.get("objectives") or []}.get(meta.get("objective_id"))
    if objective is None or plan["objective_id"] != objective["objective_id"]:
        return "OUT_OF_SCOPE", "task is not under an approved objective"
    paths = [p["path"] for p in task.get("allowed_paths") or []]
    if not paths or any(not any(x.startswith(pre) for pre in objective["scope_prefixes"]) for x in paths):
        return "OUT_OF_SCOPE", "task paths are outside the objective's approved scope"
    if not set(declared_operations(task)) <= set(objective["allowed_operations"]):
        return "OUT_OF_SCOPE", "task operations are not approved for this objective"
    fp = task_fingerprint(objective["objective_id"], meta.get("signal_id") or "", paths)
    if meta.get("fingerprint") != fp or plan["fingerprint"] != fp:
        return "METADATA", "task fingerprint does not match its problem identity"
    if not plan["evidence_refs"]:
        return "METADATA", "planned task has no evidence"
    if list(task.get("depends_on") or []) != list(plan["depends_on"]):
        return "EDITED", "dependencies differ from the plan record"
    return None


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
        return Step(HARD_STOP, "policy invalid: " + "; ".join(problems), scope="provider_execution",
                    code="POLICY_INVALID", human_required=True)
    try:
        entries = validate_campaign(campaign)
    except (ValueError, json.JSONDecodeError) as exc:
        return Step(HARD_STOP, f"campaign manifest invalid: {exc}", scope="campaign", code="MANIFEST_INVALID",
                    human_required=True)
    if (rp := route_problem(snapshot.get("route_observation"))) is not None:
        if rp[0] == HARD_STOP:
            return Step(HARD_STOP, rp[1], scope="provider_execution", code="PAID_ROUTE", human_required=True)
        return Step(DEFER, rp[1], scope="provider_execution", code="ROUTE_UNKNOWN")
    trusted = set(policy["trusted_writers"])
    now = _ts(snapshot["now"])
    cand = snapshot.get("candidate") or {}
    number = cand.get("number")
    checks: list[str] = ["policy", "manifest", "route"]

    def iso(code: str, reason: str, human: bool = False) -> Step:
        return Step(ISOLATE, reason, number, code=code, human_required=human)

    def defer(code: str, reason: str, **kw: Any) -> Step:
        return Step(DEFER, reason, number, code=code, **kw)

    if not cand or cand.get("state") == "MISSING":
        return iso("ISSUE_MISSING", "issue missing or deleted")
    if not isinstance(cand.get("comments"), list) or not isinstance(cand.get("label_events"), list) \
            or not isinstance(cand.get("labels"), list):
        return defer("READ_UNKNOWN", "issue comments / labels / label history not read (UNKNOWN): nothing starts")
    task, problem = _task_of(cand.get("body") or "")
    if task is None:
        if problem == "not a closed-loop task issue":
            return Step(IGNORE, problem, number)
        return iso("METADATA", problem)
    meta = task.get("campaign")
    if not isinstance(meta, dict) or meta.get("profile") != STARTER_META_PROFILE:
        return iso("NO_STARTER_METADATA", "task has no starter metadata: a human must decide how to start it", True)
    if meta.get("campaign_id") != campaign["campaign_id"]:
        return Step(IGNORE, "issue belongs to another campaign", number)
    source = meta.get("source", "manifest")
    if source == "manifest":
        entry = entries.get(meta.get("seq"))
        if entry is None:
            return iso("METADATA", f"seq {meta.get('seq')!r} is not in the campaign manifest")
        if task_sha256(task) != entry["task_sha256"]:
            return iso("EDITED", "task differs from the prepared task (edited after preparation)")
        if cand.get("title") != entry["title"]:
            return iso("EDITED", "issue title differs from the prepared task")
        identity_sha = entry["task_sha256"]
    elif source == "planner":
        if (problem := verify_planned_issue(cand, task, campaign)) is not None:
            return iso(problem[0], problem[1])
        identity_sha = task_sha256(task)
    else:
        return iso("METADATA", f"unknown task source {source!r}")
    checks.append("task_identity")
    if snapshot.get("repository") != policy["repository"] or campaign.get("repository") != policy["repository"]:
        return iso("WRONG_REPOSITORY", "wrong repository")
    if task.get("route") not in (None, ROUTE):
        return iso("ROUTE", f"task asks for route {task.get('route')!r}; only {ROUTE} may start")
    if task.get("kind", "proof") not in policy["allowed_task_kinds"]:
        return iso("TASK_KIND", f"task kind {task.get('kind')!r} is not allowed by policy")
    if task.get("expected_target_branch") != policy["base_branch"]:
        return iso("TARGET_BRANCH", "task targets a branch other than the policy base branch")
    if (problem := classify_task(task, policy)) is not None:
        return iso(*problem)
    if task.get("max_corrective_rounds", 0) > policy["max_corrective_rounds"]:
        return iso("CORRECTIVE_BUDGET", "task corrective budget exceeds policy")
    event_gen = (snapshot.get("event") or {}).get("generation")
    if event_gen is not None and event_gen != task["generation"]:
        return Step(NO_OP, f"wake for generation {event_gen}, task is generation {task['generation']}", number,
                    code="OLD_GENERATION")
    checks.append("task_policy")

    try:
        intents, receipts = starter_records(cand.get("comments") or [], trusted)
    except (ValueError, json.JSONDecodeError) as exc:
        return Step(NO_OP, f"starter record unreadable ({exc}); nothing is written over it", number,
                    code="RECORD_UNREADABLE")
    intents = [i for i in intents if i["correlation_id"] == task["correlation_id"]]
    receipts = [r for r in receipts if r["correlation_id"] == task["correlation_id"]]
    if receipts:
        return Step(NO_OP, "already started (terminal start receipt exists)", number, code="STARTED")
    lease = timedelta(minutes=policy["intent_lease_minutes"])
    cur = current_intent(intents, lease)
    labels = set(cand.get("labels") or [])
    ever_labeled = any(e.get("event") == "labeled" and e.get("label") == LABEL for e in cand.get("label_events") or [])
    if LABEL in labels or ever_labeled:
        if cur is not None and LABEL in labels:
            body = render_start_receipt({
                "profile": START_RECEIPT_PROFILE, "campaign_id": campaign["campaign_id"], "seq": meta.get("seq"),
                "task_id": task["task_id"], "correlation_id": task["correlation_id"],
                "generation": task["generation"], "issue": number, "task_sha256": identity_sha,
                "attempt": cur["attempt"], "intent_comment": cur["_comment"], "controller": controller,
                "label": LABEL, "outcome": "STARTED", "created_at": _fmt(now)})
            return Step(WRITE_START_RECEIPT, "label observed after the intent: record the start", number,
                        body=body, checks=tuple(checks + ["label_observed"]))
        if cur is not None:
            return iso("LABEL_REMOVED", "label was added and later removed: never re-added (a second Jules task)",
                       True)
        return iso("LABELED_OUTSIDE", "issue was labeled outside the starter; not started again", True)
    if cand.get("state") != "OPEN":
        return iso("ISSUE_CLOSED", "issue is closed")
    checks.append("not_started")

    states = snapshot.get("task_states")
    deps = tuple(task.get("depends_on") or ())
    if deps:
        if not isinstance(states, dict):
            return defer("DEPENDENCY_UNKNOWN", "dependency states not read (UNKNOWN)", dependency=deps)
        for dep in deps:
            state = states.get(dep)
            if state == "MERGED":
                continue
            if state == "PASS_UNMERGED":
                return defer("MERGE_WAIT", f"needs {dep} merged into {policy['base_branch']} (PASS, waiting for a "
                             "human Merge)", dependency=deps, human_required=True)
            if state == "ISOLATED":
                return iso("DEPENDENCY_ISOLATED", f"dependency {dep} is isolated")
            return defer("DEPENDENCY_PENDING", f"dependency {dep} is {state or 'unknown'}", dependency=deps)
    allowed = {p["path"] for p in task["allowed_paths"]}
    for pending in snapshot.get("pending_merge") or []:
        overlap = allowed & set(pending.get("paths") or [])
        if pending.get("task_id") != task["task_id"] and overlap:
            return defer("PATH_CONFLICT_PENDING_MERGE", f"{sorted(overlap)} are changed by {pending['task_id']}, "
                         "which waits for a Merge", dependency=(pending["task_id"],), human_required=True)
    checks.append("dependencies")

    pred_correlation = pred_head = None
    if source == "manifest":
        pred_meta = meta.get("predecessor")
        pred = snapshot.get("predecessor")
        if not isinstance(pred_meta, dict) or not pred_meta.get("correlation_id"):
            return iso("METADATA", "task names no predecessor")
        if not pred:
            return defer("PREDECESSOR_PENDING", "predecessor issue not read yet")
        if pred_meta.get("issue") is not None and pred.get("number") != pred_meta["issue"]:
            return iso("PREDECESSOR_MISMATCH", "predecessor issue number differs from the task metadata")
        pred_task, problem = _task_of(pred.get("body") or "")
        if pred_task is None or pred_task.get("correlation_id") != pred_meta["correlation_id"] \
                or pred_task.get("task_id") != pred_meta.get("task_id"):
            return iso("PREDECESSOR_MISMATCH", "predecessor issue does not hold the expected predecessor task")
        try:
            pred_receipts = _trusted_pass_receipts(pred, pred_meta["correlation_id"], trusted)
        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            return Step(NO_OP, f"predecessor receipt unreadable ({exc}); UNKNOWN, nothing starts", number,
                        code="RECORD_UNREADABLE")
        passes = [r for r in pred_receipts if r["verdict"] == PASS]
        if len(passes) > 1:
            return iso("DUPLICATE_RECEIPT", "more than one PASS receipt for the predecessor (UNKNOWN)", True)
        if not passes:
            if any(r["verdict"] == "BLOCKED" or r["decision"] == "TASK_BLOCKED" for r in pred_receipts):
                return iso("PREDECESSOR_ISOLATED", "predecessor is isolated; its successor does not start")
            return defer("PREDECESSOR_PENDING", "predecessor has no PASS receipt yet")
        receipt = passes[0]
        if receipt["decision"] != "ADOPT_RECORDED" or receipt["next_issue"] != number:
            return iso("PREDECESSOR_MISMATCH",
                       "the predecessor PASS receipt does not name this issue as its next issue")
        if receipt["task_id"] != pred_meta.get("task_id") or receipt["generation"] != pred_task.get("generation"):
            return iso("PREDECESSOR_MISMATCH", "predecessor receipt identity mismatch")
        if pred.get("pr_head") is not None and pred["pr_head"] != receipt["pr_head_sha"]:
            return iso("PREDECESSOR_MISMATCH", "predecessor PR head changed after PASS")
        pred_correlation, pred_head = pred_meta["correlation_id"], receipt["pr_head_sha"]
        checks.append("predecessor_pass")
    else:
        dup = [k for k in snapshot.get("known_tasks") or [] if k.get("fingerprint") == meta.get("fingerprint")
               and isinstance(k.get("issue"), int) and isinstance(number, int) and k["issue"] < number
               and k.get("state") not in {"ISOLATED", "CLOSED"}]
        if dup:
            return iso("DUPLICATE", f"the same problem is already task #{dup[0]['issue']}")
        checks.append("objective")


    base_head = snapshot.get("base_head")
    if not _SHA40.fullmatch(str(base_head or "")):
        return defer("BASE_UNKNOWN", "base branch head not read (UNKNOWN)")
    if base_head != task["expected_target_head"]:
        changed = snapshot.get("base_changed_paths")
        if policy["base_policy"] == "exact":
            return iso("STALE_BASE", "stale task: base branch moved (exact base policy)")
        if changed is None:
            return defer("BASE_UNKNOWN", "base branch moved and the changed paths are not known (UNKNOWN)")
        if set(changed) & allowed:
            return iso("STALE_BASE", "stale task: base branch changed an allowed path; re-prepare the task")
    checks.append("base")

    rounds = campaign.get("max_rounds", policy.get("max_campaign_rounds"))
    if rounds is not None and isinstance(meta.get("seq"), int) and meta["seq"] > rounds:
        return Step(DEFER, "campaign round limit reached; a human may extend it", number, scope="campaign",
                    code="ROUND_LIMIT", human_required=True)
    active = [a for a in snapshot.get("active_tasks") or [] if a.get("correlation_id") != task["correlation_id"]]
    if len(active) >= policy["max_concurrent_tasks"]:
        return Step(DEFER, f"{len(active)} Jules task(s) still running (limit {policy['max_concurrent_tasks']})",
                    number, scope="global", code="CONCURRENCY")
    quota = snapshot.get("quota") or {"state": QUOTA_UNKNOWN}
    if quota.get("state") == QUOTA_EXHAUSTED:
        reset = quota.get("reset_at")
        if not reset or now < _ts(reset):
            return Step(DEFER, "Jules quota confirmed exhausted: new starts wait for the reset", number,
                        scope="provider_execution", retry_after=reset, code="QUOTA_EXHAUSTED")
    elif quota.get("state") != QUOTA_OK and policy["on_quota_unknown"] == "defer":
        return Step(DEFER, "quota UNKNOWN and policy defers on unknown", number, scope="provider_execution",
                    code="QUOTA_UNKNOWN")
    checks.append("capacity")

    def intent_body(attempt: int, supersedes: int | None) -> tuple[str, str]:
        nonce = uuid.uuid4().hex
        return render_intent({
            "profile": INTENT_PROFILE, "campaign_id": campaign["campaign_id"], "seq": meta.get("seq"),
            "task_id": task["task_id"], "correlation_id": task["correlation_id"], "generation": task["generation"],
            "issue": number, "task_sha256": identity_sha, "predecessor_correlation_id": pred_correlation,
            "predecessor_pr_head": pred_head, "attempt": attempt, "supersedes": supersedes,
            "controller": controller, "nonce": nonce, "policy_version": policy["policy_version"], "route": ROUTE,
            "created_at": _fmt(now)}), nonce

    if cur is None:
        if intents:
            return Step(NO_OP, "intent records exist but none is a valid first attempt (UNKNOWN)", number,
                        code="RECORD_UNREADABLE")
        body, nonce = intent_body(1, None)
        return Step(WRITE_INTENT, "all start conditions hold: record the intent", number, body=body, nonce=nonce,
                    checks=tuple(checks))
    if cur["nonce"] in session_nonces:
        if cur["nonce"] in label_written:
            return defer("WRITE_UNCONFIRMED", "label write outcome unknown and not visible: never re-sent in this run")
        return Step(WRITE_LABEL, "this controller owns the current intent: add the label once", number,
                    nonce=cur["nonce"], checks=tuple(checks + ["intent_owned"]))
    if now < _ts(cur["_at"]) + lease:
        return defer("LEASE_HELD", f"intent attempt {cur['attempt']} by {cur['controller']} is within its lease",
                     retry_after=_fmt(_ts(cur["_at"]) + lease))
    if cur["attempt"] >= policy["max_label_attempts"]:
        # Repeated invisible label writes point at the write path (GitHub, permissions), not at this task, so the
        # task is not thrown away: it keeps waiting with an exponential backoff, visibly escalated to a human.
        # Retrying stays duplicate-safe: every attempt first proves the label was never present.
        backoff = min(lease * 2 ** (cur["attempt"] - policy["max_label_attempts"] + 1), timedelta(hours=24))
        if now < _ts(cur["_at"]) + backoff:
            return defer("WRITE_PATH_UNHEALTHY", f"{cur['attempt']} label attempts without a visible label: "
                         "retrying with backoff; a human should check the GitHub write path",
                         retry_after=_fmt(_ts(cur["_at"]) + backoff), human_required=True)
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
