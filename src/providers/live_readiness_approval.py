import copy
import hashlib
import json
from typing import Any

from .live_readiness_snapshot import build_live_readiness_snapshot
from .policy import ANTIGRAVITY_POLICY, CLAUDE_POLICY, CODEX_POLICY

PROVIDER_ORDER = ("openai", "anthropic", "google")

_ALLOWED_STATES = frozenset({"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"})
_PREFLIGHT_STATUSES = frozenset({"PASS", "UNKNOWN"})
_INVENTORY_STATES = frozenset(
    {"BLOCKED_UNKNOWN", "UNRESOLVED", "PROOF_RECORDS_COMPLETE"}
)
_EXPECTED_SNAPSHOT_KEYS = {
    "state",
    "live_ready",
    "dispatch_allowed",
    "human_approval_required",
    "retry_count",
    "fallback_state",
    "preflight_states",
    "preflight_snapshots",
    "preflight_packet_sha256",
    "inventory_state",
    "unresolved_count",
    "unresolved_by_provider",
    "inventory_packet_sha256",
    "provider_states",
    "blocking_providers",
    "bundle_packet_sha256",
    "pipeline_packet_sha256",
    "snapshot_packet_sha256",
}
_POLICIES = {
    "openai": CODEX_POLICY,
    "anthropic": CLAUDE_POLICY,
    "google": ANTIGRAVITY_POLICY,
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


def _valid_explicit_input_shape(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"provider_configs", "inventory"}:
        return False
    provider_configs = value["provider_configs"]
    inventory = value["inventory"]
    if not isinstance(provider_configs, dict) or set(provider_configs) != set(PROVIDER_ORDER):
        return False
    if not isinstance(inventory, dict) or set(inventory) != set(PROVIDER_ORDER):
        return False
    return all(
        isinstance(provider_configs[p], dict) and isinstance(inventory[p], dict)
        for p in PROVIDER_ORDER
    )


def _valid_preflight_states(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(PROVIDER_ORDER)
        and all(value[p] in _PREFLIGHT_STATUSES for p in PROVIDER_ORDER)
    )


def _valid_preflight_snapshots(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != set(PROVIDER_ORDER):
        return False

    expected_keys = {
        "static_configuration_status",
        "live_readiness",
        "reasons",
        "provider_id",
        "external_agent",
        "pinned_version",
        "retry_count",
        "fallback_state",
        "live_ready",
    }

    for provider in PROVIDER_ORDER:
        snapshot = value[provider]
        if not isinstance(snapshot, dict) or set(snapshot) != expected_keys:
            return False
        if snapshot["static_configuration_status"] not in _PREFLIGHT_STATUSES:
            return False
        if snapshot["live_readiness"] != "BLOCKED":
            return False
        reasons = snapshot["reasons"]
        if not isinstance(reasons, list) or any(
            not isinstance(reason, str) for reason in reasons
        ):
            return False
        if snapshot["provider_id"] != provider:
            return False

        policy = _POLICIES[provider]
        if snapshot["external_agent"] != policy.external_agent:
            return False
        if snapshot["pinned_version"] != policy.pinned_version:
            return False
        if type(snapshot["retry_count"]) is not int or snapshot["retry_count"] != 0:
            return False
        if snapshot["fallback_state"] != "disabled":
            return False
        if snapshot["live_ready"] is not False:
            return False

    return True


def _valid_provider_counts(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(PROVIDER_ORDER)
        and all(type(value[p]) is int and value[p] >= 0 for p in PROVIDER_ORDER)
    )


def _valid_provider_states(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(PROVIDER_ORDER)
        and all(value[p] in _ALLOWED_STATES for p in PROVIDER_ORDER)
    )


def _valid_blocking_providers(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > len(PROVIDER_ORDER):
        return False
    if len(set(value)) != len(value):
        return False
    if any(provider not in PROVIDER_ORDER for provider in value):
        return False
    return value == [provider for provider in PROVIDER_ORDER if provider in value]


def _valid_snapshot(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict) or set(snapshot) != _EXPECTED_SNAPSHOT_KEYS:
        return False
    if snapshot["state"] not in _ALLOWED_STATES:
        return False
    if snapshot["live_ready"] is not False or snapshot["dispatch_allowed"] is not False:
        return False
    if snapshot["human_approval_required"] is not True:
        return False
    if type(snapshot["retry_count"]) is not int or snapshot["retry_count"] != 0:
        return False
    if snapshot["fallback_state"] != "disabled":
        return False

    preflight_states = snapshot["preflight_states"]
    preflight_snapshots = snapshot["preflight_snapshots"]
    preflight_hash = snapshot["preflight_packet_sha256"]
    if preflight_states == {}:
        if preflight_snapshots != {} or preflight_hash is not None:
            return False
    else:
        if not _valid_preflight_states(preflight_states):
            return False
        if not _valid_preflight_snapshots(preflight_snapshots):
            return False
        if any(
            preflight_states[p]
            != preflight_snapshots[p]["static_configuration_status"]
            for p in PROVIDER_ORDER
        ):
            return False
        if not _is_sha256(preflight_hash):
            return False
        expected_preflight_hash = hashlib.sha256(
            _canonical_json(preflight_snapshots).encode("utf-8")
        ).hexdigest()
        if preflight_hash != expected_preflight_hash:
            return False

    inventory_state = snapshot["inventory_state"]
    unresolved_count = snapshot["unresolved_count"]
    unresolved_by_provider = snapshot["unresolved_by_provider"]
    inventory_hash = snapshot["inventory_packet_sha256"]

    if inventory_state not in _INVENTORY_STATES:
        return False
    if type(unresolved_count) is not int or unresolved_count < -1:
        return False

    if inventory_state == "BLOCKED_UNKNOWN":
        if (
            unresolved_count != -1
            or unresolved_by_provider != {}
            or inventory_hash is not None
        ):
            return False
    else:
        if not _valid_provider_counts(unresolved_by_provider):
            return False
        if sum(unresolved_by_provider[p] for p in PROVIDER_ORDER) != unresolved_count:
            return False
        if not _is_sha256(inventory_hash):
            return False
        if inventory_state == "UNRESOLVED" and unresolved_count <= 0:
            return False
        if inventory_state == "PROOF_RECORDS_COMPLETE" and unresolved_count != 0:
            return False

    provider_states = snapshot["provider_states"]
    blockers = snapshot["blocking_providers"]
    bundle_hash = snapshot["bundle_packet_sha256"]

    if not _valid_blocking_providers(blockers):
        return False

    if provider_states == {}:
        if snapshot["state"] != "BLOCKED_UNKNOWN":
            return False
        if blockers != list(PROVIDER_ORDER):
            return False
        if bundle_hash is not None:
            return False
    else:
        if not _valid_provider_states(provider_states):
            return False
        expected_blockers = [
            provider
            for provider in PROVIDER_ORDER
            if provider_states[provider] != "READY_FOR_HUMAN_APPROVAL"
        ]
        if blockers != expected_blockers:
            return False
        if not _is_sha256(bundle_hash):
            return False
        expected_state = (
            "READY_FOR_HUMAN_APPROVAL"
            if not expected_blockers
            else "BLOCKED_UNKNOWN"
        )
        if snapshot["state"] != expected_state:
            return False

    pipeline_hash = snapshot["pipeline_packet_sha256"]
    pure_fail_closed = (
        preflight_states == {}
        and inventory_state == "BLOCKED_UNKNOWN"
        and provider_states == {}
    )
    if pure_fail_closed:
        if pipeline_hash is not None:
            return False
    elif not _is_sha256(pipeline_hash):
        return False

    if snapshot["state"] == "READY_FOR_HUMAN_APPROVAL":
        if not _valid_preflight_states(preflight_states):
            return False
        if not _valid_preflight_snapshots(preflight_snapshots):
            return False
        if inventory_state != "PROOF_RECORDS_COMPLETE":
            return False
        if unresolved_count != 0:
            return False
        if not _valid_provider_states(provider_states):
            return False
        if any(
            provider_states[p] != "READY_FOR_HUMAN_APPROVAL"
            for p in PROVIDER_ORDER
        ):
            return False
        if blockers != []:
            return False
        if not _is_sha256(inventory_hash) or not _is_sha256(bundle_hash):
            return False
        if not _is_sha256(pipeline_hash):
            return False

    snapshot_hash = snapshot["snapshot_packet_sha256"]
    if not _is_sha256(snapshot_hash):
        return False
    snapshot_payload = {
        key: value
        for key, value in snapshot.items()
        if key != "snapshot_packet_sha256"
    }
    expected_snapshot_hash = hashlib.sha256(
        _canonical_json(snapshot_payload).encode("utf-8")
    ).hexdigest()
    return snapshot_hash == expected_snapshot_hash


def _base_approval() -> dict[str, Any]:
    return {
        "state": "BLOCKED_UNKNOWN",
        "live_ready": False,
        "dispatch_allowed": False,
        "human_approval_required": True,
        "approval_granted": False,
        "retry_count": 0,
        "fallback_state": "disabled",
        "next_action": "RESOLVE_BLOCKERS",
        "snapshot_state": "BLOCKED_UNKNOWN",
        "snapshot_packet_sha256": None,
        "preflight_states": {},
        "inventory_state": "BLOCKED_UNKNOWN",
        "unresolved_count": -1,
        "provider_states": {},
        "blocking_providers": list(PROVIDER_ORDER),
        "approval_packet_sha256": None,
    }


def _finalize_approval(packet: dict[str, Any]) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in packet.items()
        if key != "approval_packet_sha256"
    }
    packet["approval_packet_sha256"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return packet


def build_live_readiness_approval_packet(input_data: Any) -> dict[str, Any]:
    packet = _base_approval()

    if not _valid_explicit_input_shape(input_data):
        return _finalize_approval(packet)

    try:
        safe_input = copy.deepcopy(input_data)
        _canonical_json(safe_input)
    except (TypeError, ValueError, OverflowError):
        return _finalize_approval(packet)

    try:
        raw_snapshot = build_live_readiness_snapshot(safe_input)
        snapshot = copy.deepcopy(raw_snapshot)
        _canonical_json(snapshot)
    except Exception:
        return _finalize_approval(packet)

    if not _valid_snapshot(snapshot):
        return _finalize_approval(packet)

    packet["state"] = snapshot["state"]
    packet["next_action"] = (
        "REQUEST_HUMAN_APPROVAL"
        if snapshot["state"] == "READY_FOR_HUMAN_APPROVAL"
        else "RESOLVE_BLOCKERS"
    )
    packet["snapshot_state"] = snapshot["state"]
    packet["snapshot_packet_sha256"] = snapshot["snapshot_packet_sha256"]
    packet["preflight_states"] = copy.deepcopy(snapshot["preflight_states"])
    packet["inventory_state"] = snapshot["inventory_state"]
    packet["unresolved_count"] = snapshot["unresolved_count"]
    packet["provider_states"] = copy.deepcopy(snapshot["provider_states"])
    packet["blocking_providers"] = list(snapshot["blocking_providers"])

    return _finalize_approval(packet)


def render_approval_summary_ja(packet: Any) -> str:
    state = "BLOCKED_UNKNOWN"
    action = "RESOLVE_BLOCKERS"
    unresolved = -1
    preflight_states: dict[str, str] = {}
    provider_states: dict[str, str] = {}
    blockers = list(PROVIDER_ORDER)

    if isinstance(packet, dict):
        candidate_state = packet.get("state")
        candidate_action = packet.get("next_action")
        if candidate_state in _ALLOWED_STATES:
            state = candidate_state
        if candidate_action in {"RESOLVE_BLOCKERS", "REQUEST_HUMAN_APPROVAL"}:
            action = candidate_action

        count = packet.get("unresolved_count")
        if type(count) is int and count >= -1:
            unresolved = count

        candidate_preflights = packet.get("preflight_states")
        if _valid_preflight_states(candidate_preflights):
            preflight_states = {
                provider: candidate_preflights[provider]
                for provider in PROVIDER_ORDER
            }

        candidate_provider_states = packet.get("provider_states")
        if _valid_provider_states(candidate_provider_states):
            provider_states = {
                provider: candidate_provider_states[provider]
                for provider in PROVIDER_ORDER
            }

        candidate_blockers = packet.get("blocking_providers")
        if _valid_blocking_providers(candidate_blockers):
            blockers = list(candidate_blockers)

    action_ja = {
        "RESOLVE_BLOCKERS": "ブロッカー解消が必要",
        "REQUEST_HUMAN_APPROVAL": "人間承認を要求可能（未承認）",
    }[action]

    lines = [
        "ライブ実行: 禁止",
        "人間承認が必要: 承認未完了",
        f"全体状態: {state}",
        f"次アクション: {action_ja}",
    ]

    if preflight_states:
        lines.append("事前確認状態:")
        for provider in PROVIDER_ORDER:
            lines.append(f"  - {provider}: {preflight_states[provider]}")

    lines.append(f"未解決の証明数: {unresolved}")

    if provider_states:
        lines.append("プロバイダー状態:")
        for provider in PROVIDER_ORDER:
            lines.append(f"  - {provider}: {provider_states[provider]}")

    if blockers:
        lines.append(f"ブロック中のプロバイダー: {', '.join(blockers)}")

    return "\n".join(lines)
