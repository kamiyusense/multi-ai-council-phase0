import copy
import hashlib
import json
from datetime import datetime
from typing import Any

PROVIDER_ORDER = ("openai", "anthropic", "google")

_EXPECTED_INPUT_KEYS = {"approval_packet", "approval_record"}
_EXPECTED_PACKET_KEYS = {
    "state",
    "live_ready",
    "dispatch_allowed",
    "human_approval_required",
    "approval_granted",
    "retry_count",
    "fallback_state",
    "next_action",
    "snapshot_state",
    "snapshot_packet_sha256",
    "preflight_states",
    "inventory_state",
    "unresolved_count",
    "provider_states",
    "blocking_providers",
    "approval_packet_sha256",
}
_EXPECTED_RECORD_KEYS = {
    "decision",
    "scope",
    "one_shot",
    "recorded_at",
    "target_approval_packet_sha256",
    "target_snapshot_packet_sha256",
}
_ALLOWED_DECISIONS = {
    "APPROVE_FIRST_LIVE_POC",
    "REJECT",
    "DEFER",
}
_ALLOWED_PREFLIGHT_STATES = {"PASS", "UNKNOWN"}


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


def _fail_closed() -> dict[str, Any]:
    return _finalize_receipt(_base_receipt())


def _is_valid_iso8601_offset(value: Any) -> bool:
    if not isinstance(value, str) or not value or "T" not in value:
        return False

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False

    return True


def _valid_exact_provider_map(
    value: Any,
    *,
    allowed_values: set[str],
) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(PROVIDER_ORDER)
        and all(value[provider] in allowed_values for provider in PROVIDER_ORDER)
    )


def _valid_ready_approval_packet(packet: Any) -> bool:
    if not isinstance(packet, dict) or set(packet) != _EXPECTED_PACKET_KEYS:
        return False

    if packet["state"] != "READY_FOR_HUMAN_APPROVAL":
        return False
    if packet["next_action"] != "REQUEST_HUMAN_APPROVAL":
        return False
    if packet["snapshot_state"] != "READY_FOR_HUMAN_APPROVAL":
        return False

    if packet["live_ready"] is not False:
        return False
    if packet["dispatch_allowed"] is not False:
        return False
    if packet["human_approval_required"] is not True:
        return False
    if packet["approval_granted"] is not False:
        return False
    if type(packet["retry_count"]) is not int or packet["retry_count"] != 0:
        return False
    if packet["fallback_state"] != "disabled":
        return False

    if not _valid_exact_provider_map(
        packet["preflight_states"],
        allowed_values=_ALLOWED_PREFLIGHT_STATES,
    ):
        return False

    if packet["inventory_state"] != "PROOF_RECORDS_COMPLETE":
        return False
    if type(packet["unresolved_count"]) is not int or packet["unresolved_count"] != 0:
        return False

    if not _valid_exact_provider_map(
        packet["provider_states"],
        allowed_values={"READY_FOR_HUMAN_APPROVAL"},
    ):
        return False

    if packet["blocking_providers"] != []:
        return False

    snapshot_hash = packet["snapshot_packet_sha256"]
    approval_hash = packet["approval_packet_sha256"]
    if not _is_sha256(snapshot_hash) or not _is_sha256(approval_hash):
        return False

    payload = {
        key: value
        for key, value in packet.items()
        if key != "approval_packet_sha256"
    }
    expected_hash = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return approval_hash == expected_hash


def _valid_approval_record(
    record: Any,
    *,
    packet: dict[str, Any],
) -> bool:
    if not isinstance(record, dict) or set(record) != _EXPECTED_RECORD_KEYS:
        return False

    decision = record["decision"]
    if decision not in _ALLOWED_DECISIONS:
        return False

    if record["scope"] != "FIRST_LIVE_POC_ONLY":
        return False

    one_shot = record["one_shot"]
    if type(one_shot) is not bool:
        return False
    if decision == "APPROVE_FIRST_LIVE_POC" and one_shot is not True:
        return False

    if not _is_valid_iso8601_offset(record["recorded_at"]):
        return False

    target_approval_hash = record["target_approval_packet_sha256"]
    target_snapshot_hash = record["target_snapshot_packet_sha256"]
    if not _is_sha256(target_approval_hash):
        return False
    if not _is_sha256(target_snapshot_hash):
        return False

    if target_approval_hash != packet["approval_packet_sha256"]:
        return False
    if target_snapshot_hash != packet["snapshot_packet_sha256"]:
        return False

    return True


def build_live_approval_receipt(input_data: Any) -> dict[str, Any]:
    if not isinstance(input_data, dict) or set(input_data) != _EXPECTED_INPUT_KEYS:
        return _fail_closed()

    try:
        safe_input = copy.deepcopy(input_data)
        _canonical_json(safe_input)
    except (TypeError, ValueError, OverflowError):
        return _fail_closed()

    packet = safe_input["approval_packet"]
    record = safe_input["approval_record"]

    if not _valid_ready_approval_packet(packet):
        return _fail_closed()
    if not _valid_approval_record(record, packet=packet):
        return _fail_closed()

    decision = record["decision"]
    receipt = _base_receipt()
    receipt["decision"] = decision
    receipt["scope"] = "FIRST_LIVE_POC_ONLY"
    receipt["one_shot"] = record["one_shot"]
    receipt["approval_packet_sha256"] = packet["approval_packet_sha256"]
    receipt["snapshot_packet_sha256"] = packet["snapshot_packet_sha256"]

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
    action = "RESOLVE_BLOCKERS"
    scope = "UNKNOWN"
    one_shot = False

    if isinstance(receipt, dict):
        candidate_state = receipt.get("state")
        if candidate_state in {
            "BLOCKED_UNKNOWN",
            "STRUCTURALLY_VALID_APPROVAL_RECORD",
            "NON_APPROVAL_DECISION",
        }:
            state = candidate_state

        candidate_decision = receipt.get("decision")
        if candidate_decision in _ALLOWED_DECISIONS:
            decision = candidate_decision

        candidate_action = receipt.get("next_action")
        if candidate_action in {
            "RESOLVE_BLOCKERS",
            "VERIFY_DURABLE_HUMAN_PROVENANCE",
            "NO_LIVE_ACTION",
        }:
            action = candidate_action

        if receipt.get("scope") == "FIRST_LIVE_POC_ONLY":
            scope = "FIRST_LIVE_POC_ONLY"

        candidate_one_shot = receipt.get("one_shot")
        if type(candidate_one_shot) is bool:
            one_shot = candidate_one_shot

    state_ja = {
        "BLOCKED_UNKNOWN": "ブロッカー解消待ち・不明",
        "STRUCTURALLY_VALID_APPROVAL_RECORD": "承認記録の構造のみ確認済み（人間由来は未検証）",
        "NON_APPROVAL_DECISION": "非承認の決定",
    }[state]
    decision_ja = {
        "APPROVE_FIRST_LIVE_POC": "初回ライブPOCの承認記録候補",
        "REJECT": "拒否",
        "DEFER": "保留",
        "UNKNOWN": "不明",
    }[decision]
    action_ja = {
        "RESOLVE_BLOCKERS": "ブロッカーの解消が必要",
        "VERIFY_DURABLE_HUMAN_PROVENANCE": "永続記録から人間由来を別途検証する",
        "NO_LIVE_ACTION": "ライブ操作を行わない",
    }[action]
    scope_ja = {
        "FIRST_LIVE_POC_ONLY": "初回ライブPOC限定",
        "UNKNOWN": "不明",
    }[scope]

    return "\n".join(
        [
            "状態: STATIC / PREPARED",
            "ライブ実行: 禁止",
            "人間由来の証明: 未検証",
            "実行認可: 未認可",
            f"記録状態: {state_ja}",
            f"決定: {decision_ja}",
            f"スコープ: {scope_ja}",
            f"単発記録: {'はい' if one_shot else 'いいえ'}",
            f"次アクション: {action_ja}",
        ]
    )
