"""Cross-wake durable LIVE budget for the GitHub-native Jules start (the ``jules`` label).

Why: ``GhLiveWritePort`` counts labels per instance, i.e. per Routine wake.  A per-wake counter is not a
budget: N wakes could each send ``max_labels``.  This module is the global, durable part.

**Ledger.** The existing create-only slot ledger (``CLAUDE_AUTO_LIVE_BUDGET_SLOT_V1`` records, one file per slot
``slot-NN.json`` on a data branch; 9/10 used on 2026-10-10).  One slot is consumed BEFORE the label write and is
never released: an unknown outcome still consumes it.  The cap is not a constant here: it comes from a
human-approved ``CLAUDE_JULES_LIVE_BUDGET_DECLARATION_V1`` file on the default branch, so raising it needs a
human Merge, and records written under a smaller cap still count.  A V3 declaration adds ``rolling_24h_limit``:
at most that many slots acquired in any 24 hours (Jules' daily task limit is a rolling 24 hours); a full window is
``RATE_LIMITED`` with the time it frees, a temporary wait, never a human decision.

**Which GitHub guarantee this relies on, and which it does not.**

* Reservation correctness is decided by READBACK, never by the write's response: a slot is ours only if the
  slot file read back afterwards is byte-for-byte our record.  A lost response, a timeout or a crash between
  write and readback leaves the slot either ours (next wake: ``RECOVERED``) or someone else's; it is never
  re-sent blindly and never counted as free.
* Two controllers racing for the same slot: the slot file is created by a non-force ``git push`` of a single-
  file commit on the tip each controller read (``GitLiveClient.create``).  Git's ref update carries the old
  value and the server rejects a non-fast-forward, so at most one of the two commits lands; the loser's
  readback shows the winner's record and it moves on (and finds the cap).  This is the git protocol contract;
  is exercised here against a local bare git remote with two independent clones racing for the same slot
  (``test_claude_jules_durable_budget_git``), not against GitHub itself.  Whether a budget creates slots by
  itself is decided by its human-approved declaration (V2 ``slot_create``); a V1 declaration never creates.
  A provable loser (the slot reads back as another controller's record) re-reads and tries the next slot,
  bounded by the cap; every read and readback drops the client's cached branch tip first.
* Per issue: a slot is bound (``command_id`` + ``intent_sha256``) to one repository, campaign, issue, task,
  correlation, generation, task digest and expected head.  The same activation finding its own slot is
  ``RECOVERED`` (restart), any other binding is ``COLLISION``.  Two controllers holding the same RECOVERED slot
  for the same issue still consume ONE slot; whether the Jules app starts twice on a duplicate label add is
  UNKNOWN, so the starter's intent lease remains the per-issue election.

Nothing here sends anything: ``client`` is injected (tests use an in-memory fake; production would use
``GitLiveClient``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

from . import claude_jules_production_starter as st
from .claude_jules_dispatch import canonical_json, sha256_of

DECLARATION_PROFILE = "CLAUDE_JULES_LIVE_BUDGET_DECLARATION_V1"
DECLARATION_PROFILE_V2 = "CLAUDE_JULES_LIVE_BUDGET_DECLARATION_V2"   # + campaign_id, slot_create
DECLARATION_PROFILE_V3 = "CLAUDE_JULES_LIVE_BUDGET_DECLARATION_V3"   # + rolling_24h_limit
SLOT_PROFILE = "CLAUDE_AUTO_LIVE_BUDGET_SLOT_V1"
SLOT_CREATE_ENABLED = False          # default when the declaration does not decide (V1); a V2 declaration decides
_DECL_KEYS = {"profile", "budget_id", "repository", "data_branch", "ledger_prefix", "cap", "approved_by",
              "approval_ref"}
_DECL_KEYS_V2 = _DECL_KEYS | {"campaign_id", "slot_create"}
_DECL_KEYS_V3 = _DECL_KEYS_V2 | {"rolling_24h_limit"}
_SLOT_KEYS = {"schema_version", "profile", "slot", "cap", "command_id", "intent_sha256", "origin_loop_id",
              "acquired_at", "counts_as_used", "retry_count", "slot_sha256"}
_SLOT_FILE = re.compile(r"^slot-([0-9]{2,4})\.json$")
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:#@-]{0,199}$")

ACQUIRED, RECOVERED, EXHAUSTED, COLLISION, UNKNOWN, DISABLED, RATE_LIMITED = (
    "ACQUIRED", "RECOVERED", "EXHAUSTED", "COLLISION", "UNKNOWN", "DISABLED", "RATE_LIMITED")
USABLE = {ACQUIRED, RECOVERED}


class BudgetUnknown(Exception):
    """The ledger cannot be verified: no new LIVE start."""


@dataclass(frozen=True)
class Reservation:
    status: str
    reason: str
    record: dict[str, Any] | None = None
    retry_after: str | None = None          # RATE_LIMITED: when the oldest start in the window leaves it


def validate_declaration(decl: Any, *, repository: str) -> list[str]:
    v1 = isinstance(decl, dict) and set(decl) == _DECL_KEYS and decl.get("profile") == DECLARATION_PROFILE
    v2 = isinstance(decl, dict) and set(decl) == _DECL_KEYS_V2 and decl.get("profile") == DECLARATION_PROFILE_V2
    v3 = isinstance(decl, dict) and set(decl) == _DECL_KEYS_V3 and decl.get("profile") == DECLARATION_PROFILE_V3
    if not (v1 or v2 or v3):
        return ["budget declaration is not a CLAUDE_JULES_LIVE_BUDGET_DECLARATION_V1/V2/V3 record"]
    problems = []
    if v3:
        limit = decl["rolling_24h_limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 9999:
            problems.append("budget rolling_24h_limit must be an integer 1..9999")
    if v2 or v3:
        if not isinstance(decl["campaign_id"], str) or not decl["campaign_id"].strip():
            problems.append("budget declaration campaign_id missing")
        if not isinstance(decl["slot_create"], bool):
            problems.append("budget declaration slot_create must be true or false")
    if decl["repository"] != repository:
        problems.append("budget declaration is for another repository")
    cap = decl["cap"]
    if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= 9999:
        problems.append("budget cap must be an integer 1..9999")
    for key in ("budget_id", "data_branch", "ledger_prefix", "approved_by", "approval_ref"):
        if not isinstance(decl[key], str) or not decl[key].strip():
            problems.append(f"budget declaration {key} missing")
    if isinstance(decl["data_branch"], str) and decl["data_branch"] in {"main", "master"}:
        problems.append("the budget ledger must live on a data branch, not the default branch")
    if isinstance(decl["ledger_prefix"], str) and not decl["ledger_prefix"].endswith("/"):
        problems.append("ledger_prefix must end with /")
    return problems


def activation_of(task: dict[str, Any], *, repository: str, campaign_id: str, issue: int) -> dict[str, Any]:
    """Everything one start is bound to (point 1-7 of the pre-send boundary)."""
    return {"repository": repository, "campaign_id": campaign_id, "issue": issue, "task_id": task["task_id"],
            "correlation_id": task["correlation_id"], "generation": task["generation"],
            "task_sha256": st.task_sha256(task), "expected_target_head": task["expected_target_head"],
            "route": st.ROUTE}


def command_id(activation: dict[str, Any]) -> str:
    cid = (f"starter:{activation['campaign_id']}:{activation['correlation_id']}:g{activation['generation']}"
           f":#{activation['issue']}")
    if not _SAFE.fullmatch(cid):
        raise ValueError("activation identity has unsafe characters")
    return cid


def origin_of(authorization: dict[str, Any]) -> str:
    """Per-authorization tag on every slot it consumes, so its own maximum is counted durably too."""
    return f"auth:{authorization['campaign_id']}:{sha256_of(authorization['approval_ref'])[:16]}"


class DurableBudget:
    def __init__(self, client: Any, declaration: dict[str, Any], *, repository: str,
                 create_enabled: bool | None = None):
        problems = validate_declaration(declaration, repository=repository)
        if problems:
            raise ValueError("; ".join(problems))
        if create_enabled is None:      # the human-approved declaration decides; V1 never creates
            create_enabled = declaration.get("slot_create", SLOT_CREATE_ENABLED) is True
        self.client, self.decl, self.create_enabled = client, declaration, create_enabled
        self.cap, self.prefix, self.branch = declaration["cap"], declaration["ledger_prefix"], declaration["data_branch"]
        # V3: at most this many starts in any 24 hours, counted from the slots' own acquired_at (Jules' daily task
        # limit is a rolling 24 hours too); None = the total cap only
        self.rolling_limit = declaration.get("rolling_24h_limit")

    def path(self, slot: int) -> str:
        return f"{self.prefix}slot-{slot:02d}.json" if slot < 100 else f"{self.prefix}slot-{slot:04d}.json"

    def _fresh(self) -> None:
        """Drop any cached branch tip: a ledger read or readback is never served from a stale cache."""
        invalidate = getattr(self.client, "invalidate", None)
        if callable(invalidate):
            invalidate(self.branch)

    def _validate(self, record: Any, path: str) -> dict[str, Any]:
        if not isinstance(record, dict) or set(record) != _SLOT_KEYS or record.get("profile") != SLOT_PROFILE:
            raise BudgetUnknown(f"{path}: not a budget slot record")
        if record["schema_version"] != 1 or record["counts_as_used"] is not True or record["retry_count"] != 0:
            raise BudgetUnknown(f"{path}: slot invariants violated")
        if record["slot_sha256"] != sha256_of({k: v for k, v in record.items() if k != "slot_sha256"}):
            raise BudgetUnknown(f"{path}: slot digest mismatch")
        if path != self.path(record["slot"]):
            raise BudgetUnknown(f"{path}: slot number does not match its file")
        if isinstance(record["cap"], bool) or not isinstance(record["cap"], int) or record["cap"] > self.cap:
            raise BudgetUnknown(f"{path}: written under a cap larger than the declared {self.cap}")
        return record

    def slots(self) -> list[dict[str, Any]]:
        """Every consumed slot, verified.  Anything unexpected is UNKNOWN, never "free"."""
        self._fresh()
        try:
            contents = list(self.client.list(self.prefix, self.branch))
        except Exception as exc:          # noqa: BLE001 - every read failure is UNKNOWN
            raise BudgetUnknown(f"budget ledger unreadable: {exc}") from exc
        records = []
        for c in contents:
            name = c.path[len(self.prefix):] if c.path.startswith(self.prefix) else c.path
            if not _SLOT_FILE.fullmatch(name):
                raise BudgetUnknown(f"unexpected file in the budget ledger: {c.path}")
            try:
                records.append(self._validate(json.loads(c.text), c.path))
            except (ValueError, TypeError) as exc:
                raise BudgetUnknown(f"{c.path}: unreadable ({exc})") from exc
        records.sort(key=lambda r: r["slot"])
        if [r["slot"] for r in records] != list(range(1, len(records) + 1)):
            raise BudgetUnknown("budget ledger slots are not contiguous")
        if len({r["command_id"] for r in records}) != len(records):
            raise BudgetUnknown("one command consumed two budget slots")
        if len(records) > self.cap:
            raise BudgetUnknown(f"budget ledger holds {len(records)} slots, over the declared cap {self.cap}")
        return records

    def usage(self, origin: str | None = None) -> dict[str, Any]:
        slots = self.slots()
        return {"used": len(slots), "cap": self.cap, "remaining": self.cap - len(slots),
                "by_origin": sum(1 for s in slots if origin and s["origin_loop_id"] == origin)}

    def reserve(self, activation: dict[str, Any], *, origin: str, max_for_origin: int, now: str) -> Reservation:
        """The slot for this exact activation, or why not.  Never sends twice; readback decides."""
        try:
            cid, intent = command_id(activation), sha256_of(activation)
        except (ValueError, KeyError) as exc:
            return Reservation(UNKNOWN, f"activation identity invalid: {exc}")
        for _ in range(self.cap + 1):              # bounded: each pass is one fresh read and at most one create
            res = self._reserve_once(cid, intent, origin=origin, max_for_origin=max_for_origin, now=now)
            if res is not None:
                return res
        return Reservation(UNKNOWN, "the budget ledger kept changing; the next wake re-reads it")

    def _reserve_once(self, cid: str, intent: str, *, origin: str, max_for_origin: int,
                      now: str) -> Reservation | None:
        """One fresh read and at most one create.  None = a DIFFERENT controller provably took this slot number
        (its record is what reads back), so ours did not land and the next slot may be tried."""
        try:
            slots = self.slots()
        except BudgetUnknown as exc:
            return Reservation(UNKNOWN, str(exc))
        mine = [s for s in slots if s["command_id"] == cid]
        if mine:
            if mine[0]["intent_sha256"] != intent:
                return Reservation(COLLISION, f"slot {mine[0]['slot']} holds this command for another activation")
            if mine[0]["origin_loop_id"] != origin:
                return Reservation(COLLISION, f"slot {mine[0]['slot']} was reserved under another authorization")
            return Reservation(RECOVERED, f"slot {mine[0]['slot']}/{self.cap} already reserved for this activation",
                               mine[0])
        if len(slots) >= self.cap:
            return Reservation(EXHAUSTED, f"LIVE budget exhausted ({len(slots)}/{self.cap}); no further start")
        if sum(1 for s in slots if s["origin_loop_id"] == origin) >= max_for_origin:
            return Reservation(EXHAUSTED, f"this authorization's {max_for_origin} activation(s) are used up")
        if self.rolling_limit is not None:
            try:
                since = st._ts(now) - timedelta(hours=24)
                recent = sorted(st._ts(s["acquired_at"]) for s in slots if st._ts(s["acquired_at"]) > since)
            except (TypeError, ValueError) as exc:
                return Reservation(UNKNOWN, f"slot time unreadable ({exc}); no start")
            if len(recent) >= self.rolling_limit:
                free_at = st._fmt(recent[len(recent) - self.rolling_limit] + timedelta(hours=24))
                return Reservation(RATE_LIMITED, f"{len(recent)} starts in the last 24 hours (limit "
                                   f"{self.rolling_limit}); the next start is possible after {free_at}",
                                   retry_after=free_at)
        if not self.create_enabled:
            return Reservation(DISABLED, "slot creation is not enabled by the budget declaration; an approved "
                                         "pre-written slot record is required")
        record = {"schema_version": 1, "profile": SLOT_PROFILE, "slot": len(slots) + 1, "cap": self.cap,
                  "command_id": cid, "intent_sha256": intent, "origin_loop_id": origin, "acquired_at": now,
                  "counts_as_used": True, "retry_count": 0}
        record["slot_sha256"] = sha256_of(record)
        path = self.path(record["slot"])
        try:
            self.client.create(path, canonical_json(record), f"Jules LIVE budget slot {record['slot']}/{self.cap}",
                               self.branch)
        except Exception:               # noqa: BLE001 - the response is not the truth; readback decides
            pass
        self._fresh()
        try:
            back = self.client.get(path, self.branch)
        except Exception as exc:        # noqa: BLE001
            return Reservation(UNKNOWN, f"slot {record['slot']} readback failed ({exc}); not re-sent")
        if back is None:
            return Reservation(UNKNOWN, f"slot {record['slot']} not visible on readback; not re-sent")
        try:
            other = json.loads(back.text)
        except (ValueError, TypeError):
            return Reservation(UNKNOWN, f"slot {record['slot']} unreadable on readback")
        if other == record:
            return Reservation(ACQUIRED, f"slot {record['slot']}/{self.cap} reserved", record)
        if isinstance(other, dict) and other.get("command_id") == cid:
            return None                 # ours under an earlier timestamp (a racing twin of this wake): re-read
        return None                     # another controller won this slot number: re-read, try the next one

    def rate_limited_until(self, now: str) -> str | None:
        """When the rolling 24-hour limit is reached: the time a start is possible again, else None.  Read before
        any intent is written, so a full window never turns into repeated start attempts."""
        if self.rolling_limit is None:
            return None
        try:
            slots = self.slots()
            since = st._ts(now) - timedelta(hours=24)
            recent = sorted(st._ts(s["acquired_at"]) for s in slots if st._ts(s["acquired_at"]) > since)
        except (BudgetUnknown, TypeError, ValueError):
            return None                 # unknown here is decided at reserve(), which never starts on UNKNOWN
        if len(recent) < self.rolling_limit:
            return None
        return st._fmt(recent[len(recent) - self.rolling_limit] + timedelta(hours=24))

    def holds(self, record: dict[str, Any]) -> bool:
        """After the label: the slot still holds exactly our record (the ledger was not rewritten)."""
        try:
            self._fresh()
            back = self.client.get(self.path(record["slot"]), self.branch)
            return back is not None and json.loads(back.text) == record
        except Exception:               # noqa: BLE001
            return False


def prepared_slot_record(activation: dict[str, Any], *, slot: int, cap: int, origin: str, now: str) -> str:
    """The exact slot record a separately approved step may commit (prepare-only helper; sends nothing)."""
    record = {"schema_version": 1, "profile": SLOT_PROFILE, "slot": slot, "cap": cap,
              "command_id": command_id(activation), "intent_sha256": sha256_of(activation), "origin_loop_id": origin,
              "acquired_at": now, "counts_as_used": True, "retry_count": 0}
    record["slot_sha256"] = sha256_of(record)
    return canonical_json(record)


def pre_label_problems(issue: dict[str, Any], *, repository: str, campaign: dict[str, Any], trusted: set[str],
                       base_head: Callable[[], str],
                       changed_paths: Callable[[str, str], list[str] | None] | None = None
                       ) -> tuple[list[str], dict[str, Any] | None]:
    """Fresh-issue checks right before a label (points 3-7, 15-18).  Any problem means no label."""
    problems: list[str] = []
    task, err = st._task_of(issue.get("body") or "")
    if task is None:
        return [f"issue #{issue.get('number')}: no valid task block ({err})"], None
    meta = task.get("campaign") or {}
    if not isinstance(meta, dict) or meta.get("campaign_id") != campaign["campaign_id"]:
        problems.append("task is not in this campaign")
    if issue.get("label_events_complete") is not True:
        problems.append("label history is not complete")
    if any(e.get("event") == "labeled" and e.get("label") == st.LABEL for e in issue.get("label_events") or []) \
            or st.LABEL in (issue.get("labels") or []):
        problems.append(f"issue #{issue.get('number')} already had the {st.LABEL!r} label")
    from .claude_closed_loop_protocol import RECEIPT_MARKER, _block
    for c in issue.get("comments") or []:
        if c.get("author") in trusted and RECEIPT_MARKER in (c.get("body") or ""):
            try:
                recs = _block(c["body"], RECEIPT_MARKER)
            except (ValueError, json.JSONDecodeError):
                problems.append("a review receipt is unreadable")
                continue
            if any(r.get("correlation_id") == task["correlation_id"] for r in recs if isinstance(r, dict)):
                problems.append("a review receipt already exists for this correlation (terminal or in review)")
    try:
        _, starts = st.starter_records(issue.get("comments") or [], trusted)
    except (ValueError, json.JSONDecodeError):
        problems.append("a starter record is unreadable")
        starts = []
    if starts:
        problems.append("a start receipt already exists")
    try:
        head = base_head()
    except Exception as exc:              # noqa: BLE001
        head = None
        problems.append(f"base head unreadable ({exc})")
    if head is not None and not st._SHA40.fullmatch(str(head)):
        problems.append("base head unreadable")
    expected = str(task.get("expected_target_head") or "")
    if not st._SHA40.fullmatch(expected):
        problems.append("task expected_target_head invalid")
    elif head is not None and st._SHA40.fullmatch(str(head)) and head != expected:
        # the base moved since the snapshot (TOCTOU): re-evaluate the same base policy on the fresh head
        policy = campaign["policy"].get("base_policy", "descendant_untouched")
        allowed = {p.get("path") for p in task.get("allowed_paths") or []}
        try:
            changed = changed_paths(expected, head) if changed_paths else None
        except Exception:                 # noqa: BLE001
            changed = None
        if policy == "exact":
            problems.append("base branch moved (exact base policy)")
        elif changed is None:
            problems.append("base branch moved and its changed paths are unknown")
        elif set(changed) & allowed:
            problems.append("base branch changed an allowed path since the task was prepared")
    if issue.get("state") != "OPEN":
        problems.append("issue is not open")
    act = activation_of(task, repository=repository, campaign_id=campaign["campaign_id"], issue=issue["number"]) \
        if not problems else None
    return problems, act
