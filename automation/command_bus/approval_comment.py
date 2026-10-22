"""Signature rule and human approval comments (docs/RELAY_TOWER_DIRECTION_V4.md section 2).

AI writers post under the owner's account, so the author alone cannot tell a human from an AI.  Every AI write
carries a signature; a human approval is an unsigned, unedited comment whose whole body is the approval word,
written by the owner after the target last changed, and used once.

Pure functions only: nothing here reads or writes GitHub.  ``judge_approval`` decides one already-fetched
comment; ``check_ai_write`` is the pre-write check every AI writer in this repository calls before posting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = ["SignaturePolicy", "load_policy", "has_signature", "is_bare_approval", "judge_approval",
           "check_ai_write", "AiWriteRefused"]

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "config" / "ai_signatures.json"
_PERIOD = "。"


@dataclass(frozen=True)
class SignaturePolicy:
    owner_user_id: int
    approval_word: str
    markers: tuple[str, ...]
    agents: tuple[str, ...]


class AiWriteRefused(ValueError):
    """An AI write that must not be posted (unsigned, or a bare approval word)."""


def load_policy(path: Path | str = DEFAULT_POLICY_PATH) -> SignaturePolicy:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("ai_signatures: unsupported schema_version")
    owner = raw.get("owner_user_id")
    word = raw.get("approval_word")
    markers = tuple(s.get("marker") for s in raw.get("signatures") or [])
    agents = tuple(raw.get("agents") or [])
    if isinstance(owner, bool) or not isinstance(owner, int) or owner <= 0:
        raise ValueError("ai_signatures: owner_user_id must be a positive integer")
    if not isinstance(word, str) or not word.strip():
        raise ValueError("ai_signatures: approval_word is required")
    if not markers or not all(isinstance(m, str) and m.strip() for m in markers):
        raise ValueError("ai_signatures: every signature needs a non-empty marker")
    if not agents or not all(isinstance(a, str) and a.strip() for a in agents):
        raise ValueError("ai_signatures: agents must be non-empty names")
    return SignaturePolicy(owner, word.strip(), markers, agents)


def has_signature(text: str, policy: SignaturePolicy) -> bool:
    folded = (text or "").casefold()
    return any(m.casefold() in folded for m in policy.markers)


def _bare(text: str, word: str) -> bool:
    value = (text or "").strip()
    if value.endswith(_PERIOD):
        value = value[: -len(_PERIOD)].rstrip()
    return value == word


def is_bare_approval(body: str, policy: SignaturePolicy) -> bool:
    """The whole body is the approval word; surrounding whitespace/newlines and one trailing 。 are allowed."""
    return _bare(body, policy.approval_word)


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def judge_approval(comment: Mapping[str, Any], *, target_last_changed_at: str, used_comment_ids: Iterable[Any],
                   policy: SignaturePolicy) -> tuple[bool, str]:
    """Decide whether one comment is a human approval of a target.

    ``comment`` uses GitHub's issue-comment fields: ``id``, ``user.id``, ``body``, ``created_at``,
    ``updated_at``.  ``target_last_changed_at`` is when the approved target (proposal or PR head) last
    changed; an approval written before it no longer matches the target.  Anything missing or malformed is
    not an approval (fail closed).
    """
    user = comment.get("user") if isinstance(comment.get("user"), Mapping) else {}
    user_id = user.get("id")
    if isinstance(user_id, bool) or user_id != policy.owner_user_id:
        return False, "NOT_OWNER"
    body = comment.get("body")
    if not isinstance(body, str) or not is_bare_approval(body, policy):
        return False, "NOT_BARE_APPROVAL"
    if has_signature(body, policy):
        return False, "SIGNED"
    created, updated = _ts(comment.get("created_at")), _ts(comment.get("updated_at"))
    if created is None or updated is None:
        return False, "TIME_UNKNOWN"
    if updated != created:
        return False, "EDITED"
    changed = _ts(target_last_changed_at)
    if changed is None:
        return False, "TARGET_TIME_UNKNOWN"
    if created <= changed:
        return False, "BEFORE_TARGET_CHANGE"
    comment_id = comment.get("id")
    if comment_id is None or isinstance(comment_id, bool):
        return False, "ID_UNKNOWN"
    if comment_id in set(used_comment_ids):
        return False, "ALREADY_USED"
    return True, "APPROVED"


def check_ai_write(body: str, policy: SignaturePolicy) -> str:
    """Pre-write check for AI writers: refuse an unsigned body or any line that is a bare approval word."""
    if not isinstance(body, str) or not body.strip():
        raise AiWriteRefused("empty body")
    if not has_signature(body, policy):
        raise AiWriteRefused("AI write without a signature")
    if any(_bare(line, policy.approval_word) for line in body.splitlines()):
        raise AiWriteRefused("AI write contains the approval word on its own line")
    return body
