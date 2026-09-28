import copy
import hashlib
import json
from typing import Any

from .live_readiness import evaluate_live_readiness


PROVIDER_ORDER = ["openai", "anthropic", "google"]


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


def _fail_closed(base: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if payload is not None:
        base["evidence"] = copy.deepcopy(payload)
    base_json = json.dumps(base, sort_keys=True, separators=(",", ":"))
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

    for provider in PROVIDER_ORDER:
        entry = providers_input[provider]

        try:
            result = evaluate_live_readiness(
                provider,
                entry["preflight"],
                entry["proofs"],
            )
        except Exception:
            return _fail_closed(base, providers_input)

        if not isinstance(result, dict):
            return _fail_closed(base, providers_input)

        if result.get("live_ready") is not False:
            return _fail_closed(base, providers_input)

        if result.get("dispatch_allowed") is not False:
            return _fail_closed(base, providers_input)

        if result.get("retry_count") != 0:
            return _fail_closed(base, providers_input)

        if result.get("fallback_state") != "disabled":
            return _fail_closed(base, providers_input)

        if "state" not in result:
            return _fail_closed(base, providers_input)

        state = result["state"]
        provider_states[provider] = state
        if state != "READY_FOR_HUMAN_APPROVAL":
            blocking_providers.append(provider)

    base["provider_states"] = provider_states
    base["blocking_providers"] = blocking_providers
    base["evidence"] = copy.deepcopy(providers_input)

    if not blocking_providers:
        base["state"] = "READY_FOR_HUMAN_APPROVAL"

    return _fail_closed(base, None) # None because we already set evidence


def render_live_readiness_summary_ja(result: dict[str, Any]) -> str:
    lines = [
        "ライブ実行: 禁止",
        "人間承認が必要",
        f"全体状態: {result.get('state', 'UNKNOWN')}"
    ]

    states = result.get("provider_states", {})
    if states:
        lines.append("プロバイダー状態:")
        for provider in PROVIDER_ORDER:
            lines.append(f"  - {provider}: {states.get(provider, 'UNKNOWN')}")

    return "\n".join(lines)
