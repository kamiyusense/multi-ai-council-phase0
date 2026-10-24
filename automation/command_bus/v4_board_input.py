"""V4 board input (docs/RELAY_TOWER_DIRECTION_V4.md, step S5).

Reads comments on the board Issue and folds them into the durable board record:

* **Proposals** are AI comments carrying ``<!-- v4-proposal {"proposal_id": ..., "summary_ja": ...} -->`` and an AI
  signature.  They start PENDING.
* **Approvals** are owner comments judged by ``approval_comment.judge_approval``. An approval attaches to the
  one PENDING proposal written before it.  None or several pending is not guessed: the comment is used up and
  recorded as NO_PENDING_PROPOSAL / AMBIGUOUS.  A proposal edited after its approval becomes
  CHANGED_AFTER_APPROVAL.
* **Resume commands** (for example ``続けて OK claude``, section 6) are owner comments judged by
  ``approval_comment.judge_owner_command``.  The latest one per AI is kept.

Checkboxes in the Issue body are not read: GitHub does not record who ticked a box, and AI writers post under
the owner's account, so a tick cannot be told apart from an AI edit.  Every input that matters is a comment.

Pure functions only.  Every comment id that was judged as an owner input is kept in ``used_comment_ids`` so a
re-run never applies it twice.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Iterable, Mapping

from .approval_comment import SignaturePolicy, has_signature, is_bare_approval, judge_approval, judge_owner_command

__all__ = ["PROPOSAL_MARKER", "empty_record", "validate_record", "fold_comments", "InputError"]

PROPOSAL_MARKER = "<!-- v4-proposal"
_PROPOSAL_ID = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")
_RECORD_KEYS = {"schema_version", "board_issue", "proposals", "resume", "used_comment_ids", "rejected"}
_MAX_REJECTED = 20


class InputError(ValueError):
    """Malformed record (fail closed: nothing is written)."""


def empty_record(board_issue: int) -> dict[str, Any]:
    return {"schema_version": 1, "board_issue": board_issue, "proposals": {}, "resume": {},
            "used_comment_ids": [], "rejected": []}


def validate_record(record: Any, board_issue: int) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS or record["schema_version"] != 1:
        raise InputError("RECORD_SHAPE")
    if record["board_issue"] != board_issue:
        raise InputError("RECORD_BOARD_MISMATCH")
    if not isinstance(record["proposals"], dict) or not isinstance(record["resume"], dict) \
            or not isinstance(record["used_comment_ids"], list) or not isinstance(record["rejected"], list):
        raise InputError("RECORD_SHAPE")
    return record


def _proposal(comment: Mapping[str, Any], policy: SignaturePolicy) -> dict[str, Any] | None:
    body = comment.get("body") or ""
    if PROPOSAL_MARKER not in body or not has_signature(body, policy):
        return None
    start = body.index(PROPOSAL_MARKER) + len(PROPOSAL_MARKER)
    end = body.find("-->", start)
    try:
        data = json.loads(body[start:end]) if end != -1 else None
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("proposal_id"), str) \
            or not _PROPOSAL_ID.fullmatch(data["proposal_id"]) or not isinstance(data.get("summary_ja"), str) \
            or not 1 <= len(data["summary_ja"]) <= 200:
        return None
    return data


def _reject(record: dict[str, Any], comment: Mapping[str, Any], reason: str) -> None:
    record["rejected"] = (record["rejected"] + [{"comment_id": comment.get("id"), "at": comment.get("created_at"),
                                                 "reason": reason}])[-_MAX_REJECTED:]


def fold_comments(record: Mapping[str, Any], comments: Iterable[Mapping[str, Any]], *,
                  resume_phrases: Mapping[str, str], policy: SignaturePolicy) -> dict[str, Any]:
    """Return a new record with the board comments applied (oldest first).  ``record`` is not modified."""
    out = copy.deepcopy(dict(record))
    used = set(out["used_comment_ids"])
    ordered = sorted(comments, key=lambda c: (str(c.get("created_at")), c.get("id") or 0))
    by_id = {c.get("id"): c for c in ordered}
    for comment in ordered:
        cid = comment.get("id")
        found = _proposal(comment, policy)
        if found is not None:
            pid = found["proposal_id"]
            if pid not in out["proposals"]:
                out["proposals"][pid] = {"comment_id": cid, "summary_ja": found["summary_ja"],
                                         "created_at": comment.get("created_at"),
                                         "updated_at": comment.get("updated_at"), "state": "PENDING"}
            continue
        if cid in used or (comment.get("user") or {}).get("id") != policy.owner_user_id \
                or has_signature(comment.get("body") or "", policy):
            continue
        if is_bare_approval(comment.get("body") or "", policy):
            pending = [pid for pid, p in out["proposals"].items()
                       if p["state"] == "PENDING" and str(p["created_at"]) < str(comment.get("created_at"))]
            used.add(cid)
            if len(pending) != 1:
                _reject(out, comment, "NO_PENDING_PROPOSAL" if not pending else "AMBIGUOUS")
                continue
            proposal = out["proposals"][pending[0]]
            source = by_id.get(proposal["comment_id"], {})
            ok, reason = judge_approval(comment, target_last_changed_at=source.get("updated_at") or "",
                                        used_comment_ids=used - {cid}, policy=policy)
            if ok:
                proposal.update(state="APPROVED", approved_by_comment=cid, approved_at=comment.get("created_at"),
                                updated_at=source.get("updated_at"))
            else:
                _reject(out, comment, reason)
            continue
        ok, reason, phrase = judge_owner_command(comment, phrases=resume_phrases, used_comment_ids=used,
                                                 policy=policy)
        if reason == "NOT_COMMAND":
            continue
        used.add(cid)
        if ok and phrase is not None:
            out["resume"][resume_phrases[phrase]] = {"comment_id": cid, "at": comment.get("created_at")}
        else:
            _reject(out, comment, reason)
    for proposal in out["proposals"].values():
        source = by_id.get(proposal["comment_id"])
        if proposal["state"] == "APPROVED" and source is not None and source.get("updated_at") != proposal["updated_at"]:
            proposal["state"] = "CHANGED_AFTER_APPROVAL"
    out["used_comment_ids"] = sorted(used, key=str)
    return out
