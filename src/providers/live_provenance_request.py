import copy
import hashlib
import json
import re
from typing import Any

_EXPECTED_INPUT_KEYS = {"approval_receipt", "durable_locator"}
_EXPECTED_LOCATOR_KEYS = {
    "source_kind",
    "repository_full_name",
    "ref",
    "path",
    "expected_record_sha256",
}
_EXPECTED_RECEIPT_KEYS = {
    "state",
    "live_ready",
    "dispatch_allowed",
    "execution_authorized",
    "provenance_verified",
    "retry_count",
    "fallback_state",
    "decision",
    "scope",
    "one_shot",
    "approval_packet_sha256",
    "snapshot_packet_sha256",
    "next_action",
    "approval_record_sha256",
}

def _canonical_json(data: Any) -> str:
    return json.dumps(
        data,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )

def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )

def _base_request() -> dict[str, Any]:
    return {
        "state": "BLOCKED_UNKNOWN",
        "live_ready": False,
        "dispatch_allowed": False,
        "execution_authorized": False,
        "provenance_verified": False,
        "retry_count": 0,
        "fallback_state": "disabled",
        "next_action": "RESOLVE_BLOCKERS",
        "approval_record_sha256": None,
        "approval_packet_sha256": None,
        "snapshot_packet_sha256": None,
        "durable_locator_sha256": None,
        "expected_record_sha256": None,
    }

def _finalize_request(request: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in request.items()
        if key != "provenance_request_sha256"
    }
    request["provenance_request_sha256"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return request

def _fail_closed() -> dict[str, Any]:
    return _finalize_request(_base_request())

def _valid_locator(locator: Any) -> bool:
    if not isinstance(locator, dict) or set(locator) != _EXPECTED_LOCATOR_KEYS:
        return False
    if locator["source_kind"] != "GITHUB_DURABLE_RECORD":
        return False

    repo = locator["repository_full_name"]
    if not isinstance(repo, str) or not repo:
        return False
    if repo.count("/") != 1:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return False
    owner, name = repo.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        return False

    ref = locator["ref"]
    if not isinstance(ref, str) or not ref:
        return False
    # Reject whitespace/control characters, backslash, leading/trailing slash, repeated //, "..", "@{", and leading "-"
    if re.search(r"[\s\x00-\x1f\x7f\\]", ref):
        return False
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", ref):
        return False
    if ref.startswith("/") or ref.endswith("/") or "//" in ref:
        return False
    if ".." in ref or "@{" in ref or ref.startswith("-") or ref == "@":
        return False
    ref_segments = ref.split("/")
    if any(
        segment in {"", "."}
        or segment.startswith(".")
        or segment.endswith(".")
        or segment.endswith(".lock")
        for segment in ref_segments
    ):
        return False

    path = locator["path"]
    if not isinstance(path, str) or not path:
        return False
    # reject absolute paths, backslash, empty/dot/dotdot segments, control chars, repeated //, and traversal. Require a .json suffix
    if re.search(r"[\x00-\x1f\x7f\\]", path):
        return False
    if path.startswith("/") or "//" in path:
        return False
    segments = path.split("/")
    if any(seg in ("", ".", "..") for seg in segments):
        return False
    if not path.endswith(".json"):
        return False

    if not _is_sha256(locator["expected_record_sha256"]):
        return False

    return True

def _valid_approval_receipt(receipt: Any) -> bool:
    if not isinstance(receipt, dict) or set(receipt) != _EXPECTED_RECEIPT_KEYS:
        return False

    if receipt["state"] != "STRUCTURALLY_VALID_APPROVAL_RECORD":
        return False
    if receipt["decision"] != "APPROVE_FIRST_LIVE_POC":
        return False
    if receipt["scope"] != "FIRST_LIVE_POC_ONLY":
        return False
    if type(receipt["one_shot"]) is not bool or receipt["one_shot"] is not True:
        return False
    if receipt["next_action"] != "VERIFY_DURABLE_HUMAN_PROVENANCE":
        return False
    if receipt["live_ready"] is not False:
        return False
    if receipt["dispatch_allowed"] is not False:
        return False
    if receipt["execution_authorized"] is not False:
        return False
    if receipt["provenance_verified"] is not False:
        return False
    if type(receipt["retry_count"]) is not int or receipt["retry_count"] != 0:
        return False
    if receipt["fallback_state"] != "disabled":
        return False

    if not _is_sha256(receipt["approval_packet_sha256"]):
        return False
    if not _is_sha256(receipt["snapshot_packet_sha256"]):
        return False
    if not _is_sha256(receipt["approval_record_sha256"]):
        return False

    payload = {
        key: value
        for key, value in receipt.items()
        if key != "approval_record_sha256"
    }
    expected_hash = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    if receipt["approval_record_sha256"] != expected_hash:
        return False

    return True

def build_live_provenance_request(input_data: Any) -> dict[str, Any]:
    if not isinstance(input_data, dict) or set(input_data) != _EXPECTED_INPUT_KEYS:
        return _fail_closed()

    try:
        safe_input = copy.deepcopy(input_data)
        _canonical_json(safe_input)
    except (TypeError, ValueError, OverflowError):
        return _fail_closed()

    receipt = safe_input["approval_receipt"]
    locator = safe_input["durable_locator"]

    if not _valid_approval_receipt(receipt):
        return _fail_closed()
    if not _valid_locator(locator):
        return _fail_closed()

    request = _base_request()
    request["state"] = "PROVENANCE_VERIFICATION_REQUIRED"
    request["next_action"] = "READBACK_DURABLE_HUMAN_PROVENANCE"
    request["approval_record_sha256"] = receipt["approval_record_sha256"]
    request["approval_packet_sha256"] = receipt["approval_packet_sha256"]
    request["snapshot_packet_sha256"] = receipt["snapshot_packet_sha256"]
    request["durable_locator_sha256"] = hashlib.sha256(
        _canonical_json(locator).encode("utf-8")
    ).hexdigest()
    request["expected_record_sha256"] = locator["expected_record_sha256"]

    return _finalize_request(request)

def render_provenance_request_ja(request: Any) -> str:
    state = "BLOCKED_UNKNOWN"
    action = "RESOLVE_BLOCKERS"

    if isinstance(request, dict):
        candidate_state = request.get("state")
        if candidate_state in {
            "BLOCKED_UNKNOWN",
            "PROVENANCE_VERIFICATION_REQUIRED",
        }:
            state = candidate_state

        candidate_action = request.get("next_action")
        if candidate_action in {
            "RESOLVE_BLOCKERS",
            "READBACK_DURABLE_HUMAN_PROVENANCE",
        }:
            action = candidate_action

    state_ja = {
        "BLOCKED_UNKNOWN": "ブロッカー解消待ち・不明",
        "PROVENANCE_VERIFICATION_REQUIRED": "永続記録からの人間由来検証が必要",
    }[state]
    action_ja = {
        "RESOLVE_BLOCKERS": "ブロッカーの解消が必要",
        "READBACK_DURABLE_HUMAN_PROVENANCE": "永続的な人間由来を読み出し検証する",
    }[action]

    return "\n".join(
        [
            "状態: STATIC / PREPARED",
            "ライブ実行: 禁止",
            "人間由来: 未検証",
            "execution: 未認可",
            f"記録状態: {state_ja}",
            f"次アクション: {action_ja}",
            "durable readback is required",
        ]
    )
