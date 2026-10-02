import copy
import hashlib
import json
from typing import Any

from .live_readiness import evaluate_live_readiness


PROVIDER_ORDER = ["openai", "anthropic", "google"]
_ALLOWED_STATES = {"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"}
_GATE_RESULT_KEYS = {
    "state",
    "live_ready",
    "dispatch_allowed",
    "human_approval_required",
    "retry_count",
    "fallback_state",
}


def _base_blocked_result() -> dict[str, Any]:
    return {
        "state": "BLOCKED_UNKNOWN",
        "live_ready": False,
        "dispatch_allowed": False,
        "human_approval_required": True,
        "retry_count": 0,
        "fallback_state": "disabled",
        "provider_order": list(PROVIDER_ORDER),
        "provider_states": {},
        "blocking_providers": list(PROVIDER_ORDER),
        "evidence": {},
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fail_closed(base: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if payload is not None:
        try:
            evidence = copy.deepcopy(payload)
            _canonical_json(evidence)
        except (TypeError, ValueError, OverflowError):
            evidence = {}
        base["evidence"] = evidence
    base_json = _canonical_json(base)
    base["packet_sha256"] = hashlib.sha256(base_json.encode("utf-8")).hexdigest()
    return base


def build_live_readiness_bundle(providers_input: dict[str, Any]) -> dict[str, Any]:
    base = _base_blocked_result()

    if not isinstance(providers_input, dict):
        return _fail_closed(base)

    if set(providers_input.keys()) != set(PROVIDER_ORDER):
        return _fail_closed(base, providers_input)

    provider_states = {}
    blocking_providers = []

    for provider in PROVIDER_ORDER:
        entry = providers_input[provider]
        if not isinstance(entry, dict) or set(entry.keys()) != {"preflight", "proofs"}:
            return _fail_closed(base, providers_input)

    try:
        normalized_input = copy.deepcopy(providers_input)
        _canonical_json(normalized_input)
    except (TypeError, ValueError, OverflowError):
        return _fail_closed(base)

    for provider in PROVIDER_ORDER:
        entry = normalized_input[provider]

        try:
            result = evaluate_live_readiness(
                provider,
                entry["preflight"],
                entry["proofs"],
            )
        except Exception:
            return _fail_closed(base, normalized_input)

        if not isinstance(result, dict):
            return _fail_closed(base, normalized_input)
        if set(result) != _GATE_RESULT_KEYS:
            return _fail_closed(base, normalized_input)
        if result["state"] not in _ALLOWED_STATES:
            return _fail_closed(base, normalized_input)
        if result["live_ready"] is not False:
            return _fail_closed(base, normalized_input)
        if result["dispatch_allowed"] is not False:
            return _fail_closed(base, normalized_input)
        if result["human_approval_required"] is not True:
            return _fail_closed(base, normalized_input)
        if result["retry_count"] != 0:
            return _fail_closed(base, normalized_input)
        if result["fallback_state"] != "disabled":
            return _fail_closed(base, normalized_input)

        state = result["state"]
        provider_states[provider] = state
        if state != "READY_FOR_HUMAN_APPROVAL":
            blocking_providers.append(provider)

    base["provider_states"] = provider_states
    base["blocking_providers"] = blocking_providers
    base["evidence"] = normalized_input

    if not blocking_providers:
        base["state"] = "READY_FOR_HUMAN_APPROVAL"

    return _fail_closed(base, None) # None because we already set evidence


def render_live_readiness_summary_ja(result: dict[str, Any]) -> str:
    aggregate_state = "BLOCKED_UNKNOWN"
    states: dict[str, str] = {}

    if isinstance(result, dict):
        candidate_state = result.get("state")
        if candidate_state in _ALLOWED_STATES:
            aggregate_state = candidate_state

        candidate_states = result.get("provider_states")
        if isinstance(candidate_states, dict):
            for provider in PROVIDER_ORDER:
                candidate = candidate_states.get(provider)
                if candidate in _ALLOWED_STATES:
                    states[provider] = candidate

    lines = [
        "ライブ実行: 禁止",
        "人間承認が必要",
        f"全体状態: {aggregate_state}",
    ]

    if states:
        lines.append("プロバイダー状態:")
        for provider in PROVIDER_ORDER:
            lines.append(f"  - {provider}: {states.get(provider, 'BLOCKED_UNKNOWN')}")

    return "\n".join(lines)
