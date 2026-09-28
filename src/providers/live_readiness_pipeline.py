import copy
import hashlib
import json
from typing import Any

from .live_readiness_bundle import PROVIDER_ORDER, build_live_readiness_bundle
from .live_readiness_inventory import convert_to_live_readiness_proofs, normalize_inventory


_ALLOWED_STATES = {"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"}


def _base_pipeline_result() -> dict[str, Any]:
    return {
        "state": "BLOCKED_UNKNOWN",
        "live_ready": False,
        "dispatch_allowed": False,
        "human_approval_required": True,
        "retry_count": 0,
        "fallback_state": "disabled",
        "inventory_state": "BLOCKED_UNKNOWN",
        "unresolved_count": -1,
        "unresolved_by_provider": {},
        "inventory_packet_sha256": None,
        "provider_states": {},
        "blocking_providers": list(PROVIDER_ORDER),
        "bundle_packet_sha256": None,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fail_closed(base: dict[str, Any]) -> dict[str, Any]:
    base["state"] = "BLOCKED_UNKNOWN"
    base["live_ready"] = False
    base["dispatch_allowed"] = False
    base["human_approval_required"] = True
    base["retry_count"] = 0
    base["fallback_state"] = "disabled"
    base["provider_states"] = {}
    base["blocking_providers"] = list(PROVIDER_ORDER)
    base_json = _canonical_json(base)
    base["pipeline_packet_sha256"] = hashlib.sha256(base_json.encode("utf-8")).hexdigest()
    return base


def build_live_readiness_pipeline(input_data: dict[str, Any]) -> dict[str, Any]:
    base = _base_pipeline_result()

    if not isinstance(input_data, dict):
        return _fail_closed(base)

    if set(input_data.keys()) != {"preflights", "inventory"}:
        return _fail_closed(base)

    preflights = input_data["preflights"]
    inventory = input_data["inventory"]

    if not isinstance(preflights, dict) or set(preflights.keys()) != set(PROVIDER_ORDER):
        return _fail_closed(base)

    try:
        normalized_inventory = normalize_inventory(inventory)
    except Exception:
        return _fail_closed(base)

    if not isinstance(normalized_inventory, dict):
        return _fail_closed(base)

    inv_state = normalized_inventory.get("state", "BLOCKED_UNKNOWN")
    base["inventory_state"] = inv_state
    base["unresolved_count"] = normalized_inventory.get("unresolved_count", -1)
    base["unresolved_by_provider"] = normalized_inventory.get("unresolved_by_provider", {})
    base["inventory_packet_sha256"] = normalized_inventory.get("packet_sha256")

    if inv_state != "PROOF_RECORDS_COMPLETE":
        return _fail_closed(base)

    try:
        proofs = convert_to_live_readiness_proofs(normalized_inventory)
    except Exception:
        return _fail_closed(base)

    if not isinstance(proofs, dict) or not proofs:
        return _fail_closed(base)

    bundle_input: dict[str, Any] = {}
    for provider in PROVIDER_ORDER:
        provider_preflight = preflights[provider]
        if provider not in proofs:
            return _fail_closed(base)
        bundle_input[provider] = {
            "preflight": copy.deepcopy(provider_preflight),
            "proofs": copy.deepcopy(proofs[provider])
        }

    try:
        bundle_result = build_live_readiness_bundle(bundle_input)
    except Exception:
        return _fail_closed(base)

    if not isinstance(bundle_result, dict):
        return _fail_closed(base)
    if set(bundle_result.keys()) != {
        "state", "live_ready", "dispatch_allowed", "human_approval_required",
        "retry_count", "fallback_state", "provider_order", "provider_states",
        "blocking_providers", "evidence", "packet_sha256"
    }:
        return _fail_closed(base)

    b_state = bundle_result["state"]
    if b_state not in _ALLOWED_STATES:
        return _fail_closed(base)
    if bundle_result["live_ready"] is not False:
        return _fail_closed(base)
    if bundle_result["dispatch_allowed"] is not False:
        return _fail_closed(base)
    if bundle_result["human_approval_required"] is not True:
        return _fail_closed(base)
    if bundle_result["retry_count"] != 0:
        return _fail_closed(base)
    if bundle_result["fallback_state"] != "disabled":
        return _fail_closed(base)
    if bundle_result["provider_order"] != PROVIDER_ORDER:
        return _fail_closed(base)

    p_states = bundle_result["provider_states"]
    if not isinstance(p_states, dict):
        return _fail_closed(base)

    base["state"] = b_state
    base["provider_states"] = p_states
    base["blocking_providers"] = bundle_result.get("blocking_providers", list(PROVIDER_ORDER))
    base["bundle_packet_sha256"] = bundle_result.get("packet_sha256")

    base_json = _canonical_json(base)
    base["pipeline_packet_sha256"] = hashlib.sha256(base_json.encode("utf-8")).hexdigest()
    return base


def render_pipeline_summary_ja(result: dict[str, Any]) -> str:
    aggregate_state = "BLOCKED_UNKNOWN"
    unresolved = -1
    states: dict[str, str] = {}
    blocking: list[str] = list(PROVIDER_ORDER)

    if isinstance(result, dict):
        candidate_state = result.get("state")
        if candidate_state in _ALLOWED_STATES:
            aggregate_state = candidate_state

        unresolved_candidate = result.get("unresolved_count")
        if isinstance(unresolved_candidate, int):
            unresolved = unresolved_candidate

        candidate_states = result.get("provider_states")
        if isinstance(candidate_states, dict):
            for provider in PROVIDER_ORDER:
                candidate = candidate_states.get(provider)
                if candidate in _ALLOWED_STATES:
                    states[provider] = candidate

        candidate_blocking = result.get("blocking_providers")
        if isinstance(candidate_blocking, list):
            blocking = [str(p) for p in candidate_blocking if p in PROVIDER_ORDER]

    lines = [
        "ライブ実行: 禁止",
        "人間承認が必要",
        f"全体状態: {aggregate_state}",
        f"未解決の証明数: {unresolved}"
    ]

    if states:
        lines.append("プロバイダー状態:")
        for provider in PROVIDER_ORDER:
            lines.append(f"  - {provider}: {states.get(provider, 'BLOCKED_UNKNOWN')}")

    if blocking:
        lines.append(f"ブロック中のプロバイダー: {', '.join(blocking)}")

    return "\n".join(lines)
