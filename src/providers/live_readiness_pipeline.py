import copy
import hashlib
import json
from typing import Any

from .live_readiness_bundle import PROVIDER_ORDER, build_live_readiness_bundle
from .live_readiness_inventory import convert_to_live_readiness_proofs, normalize_inventory


_ALLOWED_STATES = {"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"}
_INVENTORY_STATES = {"UNRESOLVED", "PROOF_RECORDS_COMPLETE"}
_INVENTORY_RESULT_KEYS = {
    "state",
    "live_ready",
    "dispatch_allowed",
    "human_approval_required",
    "retry_count",
    "fallback_state",
    "unresolved_count",
    "unresolved_by_provider",
    "inventory",
    "packet_sha256",
}
_BUNDLE_RESULT_KEYS = {
    "state",
    "live_ready",
    "dispatch_allowed",
    "human_approval_required",
    "retry_count",
    "fallback_state",
    "provider_order",
    "provider_states",
    "blocking_providers",
    "evidence",
    "packet_sha256",
}


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _valid_inventory_result(result: Any) -> bool:
    if not isinstance(result, dict) or set(result) != _INVENTORY_RESULT_KEYS:
        return False
    if result["state"] not in _INVENTORY_STATES:
        return False
    if result["live_ready"] is not False or result["dispatch_allowed"] is not False:
        return False
    if result["human_approval_required"] is not True:
        return False
    if result["retry_count"] != 0 or result["fallback_state"] != "disabled":
        return False
    count = result["unresolved_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return False
    by_provider = result["unresolved_by_provider"]
    if not isinstance(by_provider, dict) or set(by_provider) != set(PROVIDER_ORDER):
        return False
    if any(
        not isinstance(by_provider[p], int)
        or isinstance(by_provider[p], bool)
        or by_provider[p] < 0
        for p in PROVIDER_ORDER
    ):
        return False
    if sum(by_provider[p] for p in PROVIDER_ORDER) != count:
        return False
    if not isinstance(result["inventory"], dict) or set(result["inventory"]) != set(PROVIDER_ORDER):
        return False
    if not _is_sha256(result["packet_sha256"]):
        return False
    if result["state"] == "PROOF_RECORDS_COMPLETE" and count != 0:
        return False
    if result["state"] == "UNRESOLVED" and count == 0:
        return False
    return True


def _valid_bundle_result(result: Any) -> bool:
    if not isinstance(result, dict) or set(result) != _BUNDLE_RESULT_KEYS:
        return False
    if result["state"] not in _ALLOWED_STATES:
        return False
    if result["live_ready"] is not False or result["dispatch_allowed"] is not False:
        return False
    if result["human_approval_required"] is not True:
        return False
    if result["retry_count"] != 0 or result["fallback_state"] != "disabled":
        return False
    if result["provider_order"] != PROVIDER_ORDER:
        return False

    states = result["provider_states"]
    if not isinstance(states, dict) or set(states) != set(PROVIDER_ORDER):
        return False
    if any(states[p] not in _ALLOWED_STATES for p in PROVIDER_ORDER):
        return False

    blockers = result["blocking_providers"]
    if not isinstance(blockers, list):
        return False
    expected_blockers = [
        p for p in PROVIDER_ORDER if states[p] != "READY_FOR_HUMAN_APPROVAL"
    ]
    if blockers != expected_blockers:
        return False

    expected_state = (
        "READY_FOR_HUMAN_APPROVAL"
        if not expected_blockers
        else "BLOCKED_UNKNOWN"
    )
    if result["state"] != expected_state:
        return False
    if not _is_sha256(result["packet_sha256"]):
        return False
    try:
        _canonical_json(result["evidence"])
    except (TypeError, ValueError, OverflowError):
        return False
    return True


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

    try:
        safe_input = copy.deepcopy(input_data)
        _canonical_json(safe_input)
    except (TypeError, ValueError, OverflowError):
        return _fail_closed(base)

    preflights = safe_input["preflights"]
    inventory = safe_input["inventory"]

    if not isinstance(preflights, dict) or set(preflights.keys()) != set(PROVIDER_ORDER):
        return _fail_closed(base)
    if any(not isinstance(preflights[p], dict) for p in PROVIDER_ORDER):
        return _fail_closed(base)

    try:
        normalized_inventory = normalize_inventory(inventory)
    except Exception:
        return _fail_closed(base)

    if not _valid_inventory_result(normalized_inventory):
        return _fail_closed(base)

    inv_state = normalized_inventory["state"]
    base["inventory_state"] = inv_state
    base["unresolved_count"] = normalized_inventory["unresolved_count"]
    base["unresolved_by_provider"] = copy.deepcopy(normalized_inventory["unresolved_by_provider"])
    base["inventory_packet_sha256"] = normalized_inventory["packet_sha256"]

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

    if not _valid_bundle_result(bundle_result):
        return _fail_closed(base)

    base["state"] = bundle_result["state"]
    base["provider_states"] = copy.deepcopy(bundle_result["provider_states"])
    base["blocking_providers"] = list(bundle_result["blocking_providers"])
    base["bundle_packet_sha256"] = bundle_result["packet_sha256"]

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
        if (
            isinstance(unresolved_candidate, int)
            and not isinstance(unresolved_candidate, bool)
            and unresolved_candidate >= 0
        ):
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
