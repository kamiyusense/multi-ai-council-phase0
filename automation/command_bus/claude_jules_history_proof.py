"""Offline-only validator for a proposed GitHub Actions issue-label history proof.

STATIC: no I/O, API calls or dispatch. Structural completeness does NOT
establish trusted provenance; verify GitHub run/ref/artifact independently.
"""
from __future__ import annotations
import re
from typing import Any

PROFILE = "CLAUDE_JULES_LABEL_HISTORY_EVIDENCE_V1"
SOURCE = "github-actions-read-only"
MAX_PAGES = 50
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _unknown(reason: str) -> dict[str, Any]:
    return {"status": "UNKNOWN", "reason": reason, "events": None,
            "jules_ever_labeled": None, "page_count": None,
            "provenance_verified": False}


def inspect_history(record: Any, *, repository: str, issue_number: int,
                    expected_head: str) -> dict[str, Any]:
    """Check the shape of every page, never return an authenticated PASS."""
    if not isinstance(record, dict) or record.get("profile") != PROFILE:
        return _unknown("PROFILE_UNKNOWN")
    if record.get("source") != SOURCE:
        return _unknown("SOURCE_UNKNOWN")
    if not _SHA.fullmatch(expected_head) or record.get("head_sha") != expected_head:
        return _unknown("HEAD_MISMATCH")
    if record.get("repository") != repository or record.get("issue_number") != issue_number:
        return _unknown("TARGET_MISMATCH")
    per_page = record.get("per_page")
    if type(per_page) is not int or not 1 <= per_page <= 100:
        return _unknown("PER_PAGE_INVALID")
    pages = record.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        return _unknown("PAGE_COUNT_INVALID")
    labels = record.get("current_labels")
    if not isinstance(labels, list) or any(not isinstance(s, str) for s in labels):
        return _unknown("CURRENT_LABELS_INVALID")
    seen_ids: set[int] = set()
    event_count = 0
    jules_ever_labeled = False
    for idx, page in enumerate(pages):
        if not isinstance(page, dict):
            return _unknown("PAGE_INVALID")
        if type(page.get("page")) is not int or page["page"] != idx + 1:
            return _unknown("PAGE_GAP_OR_ORDER")
        if type(page.get("http_status")) is not int or page["http_status"] != 200:
            return _unknown("PAGE_READ_FAILED")
        events = page.get("events")
        if not isinstance(events, list) or len(events) > per_page:
            return _unknown("EVENTS_INVALID")
        next_page = page.get("next_page")
        if idx < len(pages) - 1:
            if type(next_page) is not int or next_page != idx + 2:
                return _unknown("LINK_INCOMPLETE")
        elif next_page is not None:
            return _unknown("LAST_PAGE_NOT_TERMINAL")
        for event in events:
            if not isinstance(event, dict):
                return _unknown("EVENT_INVALID")
            eid = event.get("id")
            if type(eid) is not int or eid < 1 or eid in seen_ids:
                return _unknown("EVENT_ID_MISSING_OR_DUPLICATE")
            seen_ids.add(eid)
            kind = event.get("event")
            if not isinstance(kind, str):
                return _unknown("EVENT_KIND_INVALID")
            if kind in {"labeled", "unlabeled"}:
                label = event.get("label")
                if not isinstance(label, dict) or not isinstance(label.get("name"), str):
                    return _unknown("EVENT_LABEL_INVALID")
                if kind == "labeled" and label["name"] == "jules":
                    jules_ever_labeled = True
            event_count += 1
    if "jules" in labels and not jules_ever_labeled:
        return _unknown("CURRENT_LABEL_HISTORY_CONFLICT")
    return {"status": "STRUCTURALLY_COMPLETE",
            "reason": "ALL_PAGES_ACCOUNTED_FOR", "events": event_count,
            "jules_ever_labeled": jules_ever_labeled,
            "page_count": len(pages), "provenance_verified": False}
