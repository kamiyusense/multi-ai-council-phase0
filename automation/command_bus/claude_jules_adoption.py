"""Serialized fast-forward adoption of one inspected Jules result.

Reuses ``jules_publication.fast_forward_allowed`` for the final gate.  The
only canonical write is a non-force fast-forward of a Claude-AUTO-granted,
non-default target branch.  Adoption is serialized per (target branch, from
HEAD) by a create-only lock record: two controllers can never both advance
the same canonical HEAD, and a candidate built on an older HEAD is never
forced in.  Every write is read back; an ambiguous write is never resent.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .claude_jules_dispatch import EVIDENCE_ROOT, canonical_json, validate_policy
from .jules_publication import PublicationDecision, PublicationState, fast_forward_allowed

LOCK_PROFILE = "CLAUDE_AUTO_ADOPTION_LOCK_V1"
RECEIPT_PROFILE = "CLAUDE_AUTO_ADOPTION_RECEIPT_V1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class AdoptionResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None


class AdoptionRefClient(Protocol):
    def get_branch_head(self, branch: str) -> str | None: ...
    def get_commit_tree(self, sha: str) -> str | None: ...
    def compare(self, base: str, head: str) -> dict[str, Any] | None: ...
    def fast_forward_branch(self, branch: str, expected_old: str, new_sha: str) -> Any: ...


def _slug(branch: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]", "--", branch)
    if not slug or slug.startswith(".") or len(slug) > 120:
        raise ValueError("unsafe target branch for lock path")
    return slug


def lock_path(target_branch: str, from_head: str) -> str:
    if not _SHA40.fullmatch(from_head or ""):
        raise ValueError("invalid from head")
    return f"{EVIDENCE_ROOT}/claude-auto-adoption-locks/{_slug(target_branch)}/{from_head}.json"


def adoption_receipt_path(command_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", command_id or ""):
        raise ValueError("unsafe command id")
    return f"{EVIDENCE_ROOT}/claude-auto-adoption-receipts/{command_id}.json"


_RECEIPT_KEYS = {
    "schema_version", "profile", "command_id", "task_id", "intent_sha256", "origin_loop_id",
    "origin_round", "target_branch", "head_before", "head_after", "tree_after", "inspection_sha256",
    "state", "adopted_at", "merge", "force_push", "retry_count",
}


def validate_adoption_receipt(receipt: Any, *, intent: dict[str, Any], inspection: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed check that a stored receipt is exactly this dispatch's adoption."""
    request = intent["carrier_request"]
    if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_KEYS:
        raise ValueError("adoption receipt keys mismatch")
    expected = {
        "schema_version": 1, "profile": RECEIPT_PROFILE, "state": "ADOPTED",
        "command_id": request["command_id"], "task_id": inspection["task_id"],
        "intent_sha256": intent["intent_sha256"], "origin_loop_id": intent["origin_loop_id"],
        "origin_round": intent["origin_round"], "target_branch": request["target_branch"],
        "head_before": request["expected_target_head"], "head_after": inspection["candidate_head"],
        "tree_after": inspection["candidate_tree"], "inspection_sha256": inspection["inspection_sha256"],
        "merge": False, "force_push": False, "retry_count": 0,
    }
    for key, value in expected.items():
        if receipt[key] != value or type(receipt[key]) is not type(value):
            raise ValueError(f"adoption receipt {key} mismatch")
    if inspection.get("command_id") != request["command_id"] or inspection.get("intent_sha256") != intent["intent_sha256"]:
        raise ValueError("inspection does not bind this dispatch")
    return receipt


class SafeAdoption:
    def __init__(self, *, client: Any, refs: AdoptionRefClient, policy: dict[str, Any]):
        self.client, self.refs = client, refs
        self.policy = validate_policy(policy)
        self.branch = self.policy["data_branch"]

    def adopt(self, *, intent: dict[str, Any], inspection: dict[str, Any], adopted_at: str) -> AdoptionResult:
        request = intent["carrier_request"]
        target, snapshot = request["target_branch"], request["expected_target_head"]
        command_id = request["command_id"]
        try:
            existing = self.client.get(adoption_receipt_path(command_id), self.branch)
        except Exception as exc:
            return AdoptionResult("UNKNOWN", f"receipt pre-read failed: {exc}")
        if existing is not None:
            verified = self.verify_adopted(intent=intent, inspection=inspection)
            if verified.status != "VERIFIED":
                return verified
            return AdoptionResult("NO-OP", "verified adoption receipt already exists", verified.record)
        if target not in self.policy["allowed_target_branches"] or target == self.policy["default_branch"]:
            return AdoptionResult("BLOCKED", "target branch is not granted to Claude AUTO")
        if inspection.get("verdict") != "PASS" or inspection.get("decision") != "ADOPT_CANDIDATE":
            return AdoptionResult("BLOCKED", "only a PASS inspection may be adopted")
        if inspection.get("intent_sha256") != intent["intent_sha256"] or inspection.get("command_id") != command_id:
            return AdoptionResult("BLOCKED", "inspection does not bind this dispatch")
        candidate, candidate_tree = inspection.get("candidate_head"), inspection.get("candidate_tree")
        if not _SHA40.fullmatch(candidate or "") or not _SHA40.fullmatch(candidate_tree or ""):
            return AdoptionResult("UNKNOWN", "inspected candidate identity incomplete")

        try:
            current = self.refs.get_branch_head(target)
            tree = self.refs.get_commit_tree(candidate)
            compare = self.refs.compare(current, candidate) if current else None
        except Exception as exc:
            return AdoptionResult("UNKNOWN", f"fresh canonical readback failed: {exc}")
        if current is None or tree is None or compare is None:
            return AdoptionResult("UNKNOWN", "fresh canonical readback incomplete")
        if current != snapshot:
            if current == candidate:
                return self._restore_receipt(intent, inspection, adopted_at)
            return AdoptionResult("BLOCKED", "STALE_TARGET: canonical moved since the snapshot; do not force an old base")
        if tree != candidate_tree:
            return AdoptionResult("BLOCKED", "candidate tree differs from the inspected tree")
        allowed = set(request["allowed_paths"])
        files = compare.get("files")
        if not isinstance(files, list) or any(f.get("path") not in allowed or f.get("status") not in {"added", "modified"} for f in files):
            return AdoptionResult("BLOCKED", "candidate diff left the allowlist")
        decision = fast_forward_allowed(
            PublicationDecision(PublicationState.PASS, "independent inspection PASS"),
            current_target_head=current, expected_target_head=snapshot, resulting_commit=candidate,
            ancestry_is_fast_forward=(compare.get("merge_base") == current and compare.get("behind_by") == 0
                                      and isinstance(compare.get("ahead_by"), int) and compare["ahead_by"] >= 1),
        )
        if decision.state is not PublicationState.PASS:
            return AdoptionResult(decision.state.value, decision.reason)

        lock = {"schema_version": 1, "profile": LOCK_PROFILE, "target_branch": target, "from_head": snapshot,
                "to_head": candidate, "command_id": command_id, "inspection_sha256": inspection["inspection_sha256"],
                "locked_at": adopted_at}
        lock_state = self._create_once(lock_path(target, snapshot), lock, compare_keys=("target_branch", "from_head", "to_head", "command_id", "inspection_sha256"))
        if lock_state == "COLLISION":
            return AdoptionResult("BLOCKED", "another adoption already owns this canonical HEAD; serialize")
        if lock_state not in {"CREATED", "RECOVERED"}:
            return AdoptionResult("UNKNOWN", "adoption lock not proven by readback")

        try:
            after = self.refs.get_branch_head(target)
        except Exception as exc:
            return AdoptionResult("UNKNOWN", f"pre-write head readback failed: {exc}")
        if after == snapshot:
            try:
                self.refs.fast_forward_branch(target, snapshot, candidate)
            except Exception:
                pass  # ambiguous: readback decides; never resend
            try:
                after = self.refs.get_branch_head(target)
            except Exception as exc:
                return AdoptionResult("UNKNOWN", f"post-write readback failed: {exc}; do not resend")
        if after != candidate:
            return AdoptionResult("UNKNOWN", "fast-forward not proven by readback; do not resend")
        after_tree = self.refs.get_commit_tree(after)
        if after_tree != candidate_tree:
            return AdoptionResult("UNKNOWN", "canonical tree readback mismatch")
        return self._write_receipt(intent, inspection, adopted_at)

    def _receipt(self, intent: dict[str, Any], inspection: dict[str, Any], adopted_at: str) -> dict[str, Any]:
        request = intent["carrier_request"]
        return {"schema_version": 1, "profile": RECEIPT_PROFILE, "command_id": request["command_id"],
                "task_id": inspection["task_id"], "intent_sha256": intent["intent_sha256"],
                "origin_loop_id": intent["origin_loop_id"], "origin_round": intent["origin_round"],
                "target_branch": request["target_branch"], "head_before": request["expected_target_head"],
                "head_after": inspection["candidate_head"], "tree_after": inspection["candidate_tree"],
                "inspection_sha256": inspection["inspection_sha256"], "state": "ADOPTED",
                "adopted_at": adopted_at, "merge": False, "force_push": False, "retry_count": 0}

    def _restore_receipt(self, intent: dict[str, Any], inspection: dict[str, Any], adopted_at: str) -> AdoptionResult:
        """Canonical already equals the inspected candidate but no receipt exists.

        Only provable when our own lock for (target, snapshot) binds exactly this
        candidate and inspection; then the receipt is created without any ref write.
        """
        request = intent["carrier_request"]
        try:
            lock = self.client.get(lock_path(request["target_branch"], request["expected_target_head"]), self.branch)
            record = None if lock is None else json.loads(lock.text)
            tree = self.refs.get_commit_tree(inspection["candidate_head"])
        except Exception as exc:
            return AdoptionResult("UNKNOWN", f"post-adoption recovery readback failed: {exc}")
        expected = {"profile": LOCK_PROFILE, "target_branch": request["target_branch"],
                    "from_head": request["expected_target_head"], "to_head": inspection["candidate_head"],
                    "command_id": request["command_id"], "inspection_sha256": inspection["inspection_sha256"]}
        if not isinstance(record, dict) or any(record.get(k) != v for k, v in expected.items()):
            return AdoptionResult("UNKNOWN", "canonical equals candidate but no matching adoption lock; cannot prove who advanced it")
        if tree != inspection["candidate_tree"]:
            return AdoptionResult("UNKNOWN", "canonical tree does not match the inspected tree")
        return self._write_receipt(intent, inspection, adopted_at, restored=True)

    def _write_receipt(self, intent: dict[str, Any], inspection: dict[str, Any], adopted_at: str,
                       *, restored: bool = False) -> AdoptionResult:
        receipt = self._receipt(intent, inspection, adopted_at)
        state = self._create_once(adoption_receipt_path(receipt["command_id"]), receipt)
        if state == "CREATED":
            reason = "receipt restored from lock + canonical readback; no ref write" if restored else "fast-forward written and read back"
            return AdoptionResult("ADOPTED", reason, receipt)
        if state == "RECOVERED":
            return AdoptionResult("NO-OP", "identical adoption receipt already recorded", receipt)
        return AdoptionResult("UNKNOWN", "canonical advanced but receipt unresolved; recover from readback", receipt)

    def verify_adopted(self, *, intent: dict[str, Any], inspection: dict[str, Any] | None) -> AdoptionResult:
        """Re-verify a stored adoption receipt and the fresh canonical branch."""
        request = intent["carrier_request"]
        try:
            content = self.client.get(adoption_receipt_path(request["command_id"]), self.branch)
            if content is None:
                return AdoptionResult("MISSING", "no adoption receipt")
            if not isinstance(inspection, dict):
                return AdoptionResult("UNKNOWN", "adoption receipt has no verified inspection")
            receipt = validate_adoption_receipt(json.loads(content.text), intent=intent, inspection=inspection)
            current = self.refs.get_branch_head(request["target_branch"])
            compare = self.refs.compare(receipt["head_after"], current) if current else None
            tree = self.refs.get_commit_tree(receipt["head_after"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return AdoptionResult("UNKNOWN", f"adoption receipt invalid: {exc}")
        except Exception as exc:
            return AdoptionResult("UNKNOWN", f"canonical readback failed: {exc}")
        if tree != receipt["tree_after"]:
            return AdoptionResult("UNKNOWN", "adopted commit tree readback mismatch")
        if not isinstance(compare, dict) or compare.get("merge_base") != receipt["head_after"] or compare.get("behind_by") != 0:
            return AdoptionResult("UNKNOWN", "canonical branch no longer contains the adopted head")
        return AdoptionResult("VERIFIED", "adoption receipt and canonical readback agree", receipt)

    def _create_once(self, path: str, record: dict[str, Any], compare_keys: tuple[str, ...] | None = None) -> str:
        def same(other: dict[str, Any]) -> bool:
            if compare_keys is None:
                return other == record
            return all(other.get(key) == record.get(key) for key in compare_keys)
        try:
            existing = self.client.get(path, self.branch)
            if existing is not None:
                return "RECOVERED" if same(json.loads(existing.text)) else "COLLISION"
            try:
                self.client.create(path, canonical_json(record), f"Claude AUTO {record['profile']}", self.branch)
            except Exception:
                pass
            readback = self.client.get(path, self.branch)
            if readback is None:
                return "UNKNOWN"
            return "CREATED" if same(json.loads(readback.text)) else "COLLISION"
        except (json.JSONDecodeError, TypeError, ValueError):
            return "UNKNOWN"
