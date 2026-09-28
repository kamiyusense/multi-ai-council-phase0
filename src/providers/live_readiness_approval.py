import copy
import hashlib
import json
from typing import Any

from .live_readiness_snapshot import build_live_readiness_snapshot

PROVIDER_ORDER = ("openai", "anthropic", "google")

_ALLOWED_STATES = frozenset({"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"})
_PREFLIGHT_STATUSES = frozenset({"PASS", "UNKNOWN"})
_INVENTORY_STATES = frozenset(
    {"BLOCKED_UNKNOWN", "UNRESOLVED", "PROOF_RECORDS_COMPLETE"}
)

def _canonical_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True)

def _is_sha256(val: Any) -> bool:
    return isinstance(val, str) and len(val) == 64 and val.isalnum() and val.islower()

def _valid_provider_states(states: Any) -> bool:
    if not isinstance(states, dict) or set(states) != set(PROVIDER_ORDER):
        return False
    return all(states[p] in _ALLOWED_STATES for p in PROVIDER_ORDER)

def _valid_blocking_providers(blocking: Any) -> bool:
    if not isinstance(blocking, list):
        return False
    expected = [p for p in PROVIDER_ORDER if p in blocking]
    return blocking == expected

def _valid_preflight_snapshot_contents(snapshots: Any) -> bool:
    if snapshots == {}:
        return True
    if not isinstance(snapshots, dict) or set(snapshots) != set(PROVIDER_ORDER):
        return False
    for p in PROVIDER_ORDER:
        snap = snapshots[p]
        if not isinstance(snap, dict):
            return False
        if set(snap) != {
            "static_configuration_status", "live_readiness", "reasons", "provider_id",
            "external_agent", "pinned_version", "retry_count", "fallback_state", "live_ready"
        }:
            return False
        if snap["static_configuration_status"] not in _PREFLIGHT_STATUSES:
            return False
        if snap["live_readiness"] != "BLOCKED":
            return False
        if not isinstance(snap["reasons"], list) or not all(isinstance(r, str) for r in snap["reasons"]):
            return False
        if snap["provider_id"] != p:
            return False
        if type(snap["external_agent"]) is not str or type(snap["pinned_version"]) is not str:
            return False
        if type(snap["retry_count"]) is not int or snap["retry_count"] != 0:
            return False
        if snap["fallback_state"] != "disabled":
            return False
        if snap["live_ready"] is not False:
            return False
    return True

def _valid_unresolved_by_provider(counts: Any) -> bool:
    if not isinstance(counts, dict) or set(counts) != set(PROVIDER_ORDER):
        return False
    return all(type(counts[p]) is int and counts[p] >= 0 for p in PROVIDER_ORDER)

def _finalize_approval(base: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in base.items() if k != "approval_packet_sha256"}
    base["approval_packet_sha256"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return base

def _fail_closed_approval() -> dict[str, Any]:

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
        "blocking_providers": [],
        "approval_packet_sha256": None,
    }

def build_live_readiness_approval_packet(input_data: Any) -> dict[str, Any]:
    base = _fail_closed_approval()

    try:
        safe_input = copy.deepcopy(input_data)
        _canonical_json(safe_input)
    except (TypeError, ValueError, OverflowError):
        return _finalize_approval(base)

    try:
        snapshot = build_live_readiness_snapshot(safe_input)
        safe_snapshot = copy.deepcopy(snapshot)
        _canonical_json(safe_snapshot)
    except Exception:
        return _finalize_approval(base)

    if not isinstance(safe_snapshot, dict):
        return _finalize_approval(base)


    # Validate snapshot fields
    expected_keys = {
        "state", "live_ready", "dispatch_allowed", "human_approval_required",
        "retry_count", "fallback_state", "preflight_states", "preflight_snapshots",
        "preflight_packet_sha256", "inventory_state", "unresolved_count",
        "unresolved_by_provider", "inventory_packet_sha256", "provider_states",
        "blocking_providers", "bundle_packet_sha256", "pipeline_packet_sha256",
        "snapshot_packet_sha256"
    }

    if set(safe_snapshot.keys()) != expected_keys:
        return _finalize_approval(base)

    if safe_snapshot["state"] not in _ALLOWED_STATES:
        return _finalize_approval(base)
    if safe_snapshot["live_ready"] is not False:
        return _finalize_approval(base)
    if safe_snapshot["dispatch_allowed"] is not False:
        return _finalize_approval(base)
    if safe_snapshot["human_approval_required"] is not True:
        return _finalize_approval(base)
    if type(safe_snapshot["retry_count"]) is not int or safe_snapshot["retry_count"] != 0:
        return _finalize_approval(base)
    if safe_snapshot["fallback_state"] != "disabled":
        return _finalize_approval(base)

    preflight_states = safe_snapshot["preflight_states"]
    preflight_snapshots = safe_snapshot["preflight_snapshots"]
    preflight_hash = safe_snapshot["preflight_packet_sha256"]

    if preflight_states != {}:
        if not isinstance(preflight_states, dict) or set(preflight_states) != set(PROVIDER_ORDER):
            return _finalize_approval(base)
        if any(preflight_states[p] not in _PREFLIGHT_STATUSES for p in PROVIDER_ORDER):
            return _finalize_approval(base)
        if not _valid_preflight_snapshot_contents(preflight_snapshots):
            return _finalize_approval(base)
        if not _is_sha256(preflight_hash):
            return _finalize_approval(base)
    else:
        if preflight_snapshots != {} or preflight_hash is not None:
            return _finalize_approval(base)

    inventory_state = safe_snapshot["inventory_state"]
    if inventory_state not in _INVENTORY_STATES:
        return _finalize_approval(base)

    unresolved_count = safe_snapshot["unresolved_count"]
    if type(unresolved_count) is not int or unresolved_count < -1:
        return _finalize_approval(base)

    unresolved_by_provider = safe_snapshot["unresolved_by_provider"]
    inventory_hash = safe_snapshot["inventory_packet_sha256"]

    if inventory_state == "BLOCKED_UNKNOWN":
        if unresolved_count != -1 or unresolved_by_provider != {} or inventory_hash is not None:
            return _finalize_approval(base)
    else:
        if not _valid_unresolved_by_provider(unresolved_by_provider):
            return _finalize_approval(base)
        if sum(unresolved_by_provider[p] for p in PROVIDER_ORDER) != unresolved_count:
            return _finalize_approval(base)
        if not _is_sha256(inventory_hash):
            return _finalize_approval(base)

    provider_states = safe_snapshot["provider_states"]
    blocking_providers = safe_snapshot["blocking_providers"]
    bundle_hash = safe_snapshot["bundle_packet_sha256"]

    if provider_states != {}:
        if not _valid_provider_states(provider_states):
            return _finalize_approval(base)
        if not _is_sha256(bundle_hash):
            return _finalize_approval(base)
    else:
        if bundle_hash is not None:
            return _finalize_approval(base)


    if not _valid_blocking_providers(blocking_providers):
        return _finalize_approval(base)

    if provider_states != {}:
        expected_blocking = [p for p in PROVIDER_ORDER if provider_states[p] != "READY_FOR_HUMAN_APPROVAL"]
        if blocking_providers != expected_blocking:
            return _finalize_approval(base)


    pipeline_hash = safe_snapshot["pipeline_packet_sha256"]
    if safe_snapshot["state"] == "BLOCKED_UNKNOWN" and provider_states == {}:
        if pipeline_hash is not None:
            return _finalize_approval(base)
    else:
        if not _is_sha256(pipeline_hash):
            return _finalize_approval(base)

    snapshot_hash = safe_snapshot["snapshot_packet_sha256"]
    if not _is_sha256(snapshot_hash):
        return _finalize_approval(base)

    # Recompute and verify snapshot hash
    snapshot_payload = {k: v for k, v in safe_snapshot.items() if k != "snapshot_packet_sha256"}
    recomputed_hash = hashlib.sha256(_canonical_json(snapshot_payload).encode("utf-8")).hexdigest()
    if recomputed_hash != snapshot_hash:
        return _finalize_approval(base)

    # Check cross-field semantics
    if safe_snapshot["state"] == "READY_FOR_HUMAN_APPROVAL":
        if inventory_state != "PROOF_RECORDS_COMPLETE" or unresolved_count != 0:
            return _finalize_approval(base)
        if not _valid_provider_states(provider_states):
            return _finalize_approval(base)
        if any(provider_states[p] != "READY_FOR_HUMAN_APPROVAL" for p in PROVIDER_ORDER):
            return _finalize_approval(base)
        if blocking_providers != []:
            return _finalize_approval(base)
# Populate final packet
    base["snapshot_state"] = safe_snapshot["state"]
    base["snapshot_packet_sha256"] = snapshot_hash
    base["preflight_states"] = copy.deepcopy(preflight_states)
    base["inventory_state"] = inventory_state
    base["unresolved_count"] = unresolved_count
    base["provider_states"] = copy.deepcopy(provider_states)
    base["blocking_providers"] = copy.deepcopy(blocking_providers)

    if safe_snapshot["state"] == "READY_FOR_HUMAN_APPROVAL":
        base["state"] = "READY_FOR_HUMAN_APPROVAL"
        base["next_action"] = "REQUEST_HUMAN_APPROVAL"
    else:
        base["state"] = "BLOCKED_UNKNOWN"
        base["next_action"] = "RESOLVE_BLOCKERS"

    payload = {k: v for k, v in base.items() if k != "approval_packet_sha256"}
    base["approval_packet_sha256"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()

    return base

def render_approval_summary_ja(packet: Any) -> str:
    aggregate_state = "BLOCKED_UNKNOWN"
    next_action = "RESOLVE_BLOCKERS"
    unresolved = -1
    states: dict[str, str] = {}
    blocking: list[str] = list(PROVIDER_ORDER)
    preflight_states: dict[str, str] = {}

    if isinstance(packet, dict):
        candidate_state = packet.get("state")
        if candidate_state in _ALLOWED_STATES:
            aggregate_state = candidate_state

        candidate_action = packet.get("next_action")
        if candidate_action in {"RESOLVE_BLOCKERS", "REQUEST_HUMAN_APPROVAL"}:
            next_action = candidate_action

        unresolved_candidate = packet.get("unresolved_count")
        if type(unresolved_candidate) is int and unresolved_candidate >= -1:
            unresolved = unresolved_candidate

        candidate_preflights = packet.get("preflight_states")
        if (
            isinstance(candidate_preflights, dict)
            and set(candidate_preflights) == set(PROVIDER_ORDER)
            and all(
                candidate_preflights[p] in _PREFLIGHT_STATUSES
                for p in PROVIDER_ORDER
            )
        ):
            preflight_states = {
                p: candidate_preflights[p] for p in PROVIDER_ORDER
            }

        candidate_states = packet.get("provider_states")
        if _valid_provider_states(candidate_states):
            states = {p: candidate_states[p] for p in PROVIDER_ORDER}

        candidate_blocking = packet.get("blocking_providers")
        if _valid_blocking_providers(candidate_blocking):
            blocking = list(candidate_blocking)

    lines = [
        "ライブ実行: 禁止",
        "人間承認が必要: 承認未完了",
        f"全体状態: {aggregate_state}",
        f"次アクション: {next_action}",
    ]

    if preflight_states:
        lines.append("事前確認状態:")
        for provider in PROVIDER_ORDER:
            lines.append(f"  - {provider}: {preflight_states[provider]}")

    lines.append(f"未解決の証明数: {unresolved}")

    if states:
        lines.append("プロバイダー状態:")
        for provider in PROVIDER_ORDER:
            lines.append(f"  - {provider}: {states[provider]}")

    if blocking:
        lines.append(f"ブロック中のプロバイダー: {', '.join(blocking)}")

    return "\n".join(lines)
