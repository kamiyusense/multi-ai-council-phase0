import copy
import hashlib
import json
import re
from typing import Any



_EXPECTED_INPUT_KEYS = {"approval_packet", "approval_record"}
_EXPECTED_RECORD_KEYS = {
    "decision",
    "scope",
    "one_shot",
    "recorded_at",
    "target_approval_packet_sha256",
    "target_snapshot_packet_sha256",
}
_ALLOWED_DECISIONS = {"APPROVE_FIRST_LIVE_POC", "REJECT", "DEFER"}


def _canonical_json(data: Any) -> str:
    return json.dumps(
        data,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )


def _is_sha256(val: Any) -> bool:
    return isinstance(val, str) and len(val) == 64 and val.islower() and all(c in "0123456789abcdef" for c in val)


def _base_receipt() -> dict[str, Any]:
    return {
        "state": "BLOCKED_UNKNOWN",
        "live_ready": False,
        "dispatch_allowed": False,
        "execution_authorized": False,
        "provenance_verified": False,
        "retry_count": 0,
        "fallback_state": "disabled",
        "decision": "UNKNOWN",
        "scope": "UNKNOWN",
        "one_shot": False,
        "approval_packet_sha256": None,
        "snapshot_packet_sha256": None,
        "next_action": "RESOLVE_BLOCKERS",
        "approval_record_sha256": None,
    }


def _fail_closed(receipt: dict[str, Any]) -> dict[str, Any]:
    receipt["state"] = "BLOCKED_UNKNOWN"
    receipt["next_action"] = "RESOLVE_BLOCKERS"
    return _finalize_receipt(receipt)


def _finalize_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in receipt.items()
        if key != "approval_record_sha256"
    }
    receipt["approval_record_sha256"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return receipt


def _is_valid_iso8601_offset(val: Any) -> bool:
    if not isinstance(val, str) or not val:
        return False
    # Basic deterministic regex for timezone-aware ISO-8601 without reading current time
    # e.g., 2026-09-21T12:00:00Z or 2026-09-21T12:00:00+09:00
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
    return bool(re.match(pattern, val))


def build_live_approval_receipt(input_data: Any) -> dict[str, Any]:
    receipt = _base_receipt()

    if type(input_data) is not dict or set(input_data) != _EXPECTED_INPUT_KEYS:
        return _fail_closed(receipt)

    try:
        safe_input = copy.deepcopy(input_data)
        _canonical_json(safe_input)
    except (TypeError, ValueError, OverflowError):
        return _fail_closed(receipt)

    packet = safe_input["approval_packet"]
    record = safe_input["approval_record"]

    # Re-validate the packet structurally via the builder pattern
    # It must equal a newly built approval packet based on its own snapshot.
    # Note: `build_live_readiness_approval_packet` expects explicit input shape: {"provider_configs": ..., "inventory": ...}
    # We must ensure the `approval_packet` itself structurally matches an accepted Loop 050 packet.
    if type(packet) is not dict:
        return _fail_closed(receipt)

    expected_packet_keys = {
        "state", "live_ready", "dispatch_allowed", "human_approval_required", "approval_granted",
        "retry_count", "fallback_state", "next_action", "snapshot_state", "snapshot_packet_sha256",
        "preflight_states", "inventory_state", "unresolved_count", "provider_states",
        "blocking_providers", "approval_packet_sha256"
    }
    if set(packet) != expected_packet_keys:
        return _fail_closed(receipt)

    # Check fixed ready conditions
    if packet["state"] != "READY_FOR_HUMAN_APPROVAL" or packet["next_action"] != "REQUEST_HUMAN_APPROVAL":
        return _fail_closed(receipt)
    if packet["approval_granted"] is not False or packet["live_ready"] is not False or packet["dispatch_allowed"] is not False:
        return _fail_closed(receipt)
    if packet["human_approval_required"] is not True:
        return _fail_closed(receipt)
    if type(packet["retry_count"]) is not int or packet["retry_count"] != 0:
        return _fail_closed(receipt)
    if packet["fallback_state"] != "disabled":
        return _fail_closed(receipt)
    if packet["snapshot_state"] != "READY_FOR_HUMAN_APPROVAL":
        return _fail_closed(receipt)

    preflights = packet["preflight_states"]
    if type(preflights) is not dict or len(preflights) != 3 or any(v not in {"PASS", "UNKNOWN"} for v in preflights.values()):
        return _fail_closed(receipt)

    if packet["inventory_state"] != "PROOF_RECORDS_COMPLETE" or packet["unresolved_count"] != 0:
        return _fail_closed(receipt)

    providers = packet["provider_states"]
    if type(providers) is not dict or len(providers) != 3 or any(v != "READY_FOR_HUMAN_APPROVAL" for v in providers.values()):
        return _fail_closed(receipt)

    if packet["blocking_providers"] != []:
        return _fail_closed(receipt)

    if not _is_sha256(packet["snapshot_packet_sha256"]):
        return _fail_closed(receipt)

    # Recompute approval packet hash
    packet_payload = {k: v for k, v in packet.items() if k != "approval_packet_sha256"}
    expected_approval_hash = hashlib.sha256(_canonical_json(packet_payload).encode("utf-8")).hexdigest()
    if packet["approval_packet_sha256"] != expected_approval_hash:
        return _fail_closed(receipt)

    # Validate the record
    if type(record) is not dict or set(record) != _EXPECTED_RECORD_KEYS:
        return _fail_closed(receipt)

    decision = record["decision"]
    scope = record["scope"]
    one_shot = record["one_shot"]
    recorded_at = record["recorded_at"]
    target_approval_hash = record["target_approval_packet_sha256"]
    target_snapshot_hash = record["target_snapshot_packet_sha256"]

    if decision not in _ALLOWED_DECISIONS:
        return _fail_closed(receipt)
    if scope != "FIRST_LIVE_POC_ONLY":
        return _fail_closed(receipt)
    if type(one_shot) is not bool:
        return _fail_closed(receipt)
    if decision == "APPROVE_FIRST_LIVE_POC" and one_shot is not True:
        return _fail_closed(receipt)
    if not _is_valid_iso8601_offset(recorded_at):
        return _fail_closed(receipt)

    if target_approval_hash != packet["approval_packet_sha256"] or target_snapshot_hash != packet["snapshot_packet_sha256"]:
        return _fail_closed(receipt)

    # Valid structural record applies
    receipt["decision"] = decision
    receipt["scope"] = scope
    receipt["one_shot"] = one_shot
    receipt["approval_packet_sha256"] = target_approval_hash
    receipt["snapshot_packet_sha256"] = target_snapshot_hash

    if decision == "APPROVE_FIRST_LIVE_POC":
        receipt["state"] = "STRUCTURALLY_VALID_APPROVAL_RECORD"
        receipt["next_action"] = "VERIFY_DURABLE_HUMAN_PROVENANCE"
    else:
        receipt["state"] = "NON_APPROVAL_DECISION"
        receipt["next_action"] = "NO_LIVE_ACTION"

    return _finalize_receipt(receipt)


def render_approval_receipt_ja(receipt: Any) -> str:
    state = "BLOCKED_UNKNOWN"
    decision = "UNKNOWN"
    next_action = "RESOLVE_BLOCKERS"
    scope = "UNKNOWN"
    one_shot = False

    if isinstance(receipt, dict):
        candidate_state = receipt.get("state")
        if candidate_state in {"BLOCKED_UNKNOWN", "STRUCTURALLY_VALID_APPROVAL_RECORD", "NON_APPROVAL_DECISION"}:
            state = candidate_state

        candidate_decision = receipt.get("decision")
        if candidate_decision in _ALLOWED_DECISIONS:
            decision = candidate_decision

        candidate_action = receipt.get("next_action")
        if candidate_action in {"RESOLVE_BLOCKERS", "VERIFY_DURABLE_HUMAN_PROVENANCE", "NO_LIVE_ACTION"}:
            next_action = candidate_action

        candidate_scope = receipt.get("scope")
        if candidate_scope == "FIRST_LIVE_POC_ONLY":
            scope = candidate_scope

        candidate_one_shot = receipt.get("one_shot")
        if type(candidate_one_shot) is bool:
            one_shot = candidate_one_shot

    state_ja = {
        "BLOCKED_UNKNOWN": "ブロッカー解消待ち・不明",
        "STRUCTURALLY_VALID_APPROVAL_RECORD": "構造的に有効な承認記録（準備・静的確認のみ）",
        "NON_APPROVAL_DECISION": "非承認の決定",
    }[state]

    action_ja = {
        "RESOLVE_BLOCKERS": "ブロッカーの解消が必要",
        "VERIFY_DURABLE_HUMAN_PROVENANCE": "永続的な人間由来の証明が必要",
        "NO_LIVE_ACTION": "ライブアクションなし",
    }[next_action]

    decision_ja = {
        "APPROVE_FIRST_LIVE_POC": "初回ライブPOC承認",
        "REJECT": "拒否",
        "DEFER": "保留",
        "UNKNOWN": "不明",
    }[decision]

    scope_ja = {
        "FIRST_LIVE_POC_ONLY": "初回ライブPOC限定",
        "UNKNOWN": "不明",
    }[scope]

    lines = [
        "状態: STATIC / PREPARED",
        "ライブ実行: 禁止",
        "人間由来の証明: 未検証",
        "実行認可: 未認可",
        f"記録状態: {state_ja}",
        f"決定: {decision_ja}",
        f"スコープ: {scope_ja}",
        f"単発実行: {'はい' if one_shot else 'いいえ'}",
        f"次アクション: {action_ja}",
    ]

    return "\n".join(lines)
