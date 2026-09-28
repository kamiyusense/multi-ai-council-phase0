import copy
import hashlib
import json
from typing import Any

from src.providers.live_readiness_pipeline import PROVIDER_ORDER, build_live_readiness_pipeline
from src.providers.preflight import validate_provider_static
from src.providers.policy import CODEX_POLICY, CLAUDE_POLICY, ANTIGRAVITY_POLICY

_ALLOWED_STATES = {"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"}
_INVENTORY_STATES = {"BLOCKED_UNKNOWN", "UNRESOLVED", "PROOF_RECORDS_COMPLETE"}

_POLICIES = {
    "openai": CODEX_POLICY,
    "anthropic": CLAUDE_POLICY,
    "google": ANTIGRAVITY_POLICY,
}


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _base_snapshot_result() -> dict[str, Any]:
    return {
        "state": "BLOCKED_UNKNOWN",
        "live_ready": False,
        "dispatch_allowed": False,
        "human_approval_required": True,
        "retry_count": 0,
        "fallback_state": "disabled",
        "preflight_states": {},
        "preflight_snapshots": {},
        "preflight_packet_sha256": None,
        "inventory_state": "BLOCKED_UNKNOWN",
        "unresolved_count": -1,
        "unresolved_by_provider": {},
        "inventory_packet_sha256": None,
        "provider_states": {},
        "blocking_providers": list(PROVIDER_ORDER),
        "bundle_packet_sha256": None,
        "pipeline_packet_sha256": None,
        "snapshot_packet_sha256": None,
    }


def _fail_closed(base: dict[str, Any]) -> dict[str, Any]:
    base["state"] = "BLOCKED_UNKNOWN"
    base["live_ready"] = False
    base["dispatch_allowed"] = False
    base["human_approval_required"] = True
    base["retry_count"] = 0
    base["fallback_state"] = "disabled"
    base["preflight_states"] = {}
    base["preflight_snapshots"] = {}
    base["preflight_packet_sha256"] = None
    base["provider_states"] = {}
    base["blocking_providers"] = list(PROVIDER_ORDER)
    base_json = _canonical_json({k: v for k, v in base.items() if k != "snapshot_packet_sha256"})
    base["snapshot_packet_sha256"] = hashlib.sha256(base_json.encode("utf-8")).hexdigest()
    return base


def build_live_readiness_snapshot(input_data: Any) -> dict[str, Any]:
    base = _base_snapshot_result()

    if not isinstance(input_data, dict) or set(input_data.keys()) != {"provider_configs", "inventory"}:
        return _fail_closed(base)

    provider_configs = input_data["provider_configs"]
    inventory = input_data["inventory"]

    if not isinstance(provider_configs, dict) or set(provider_configs.keys()) != set(PROVIDER_ORDER):
        return _fail_closed(base)

    try:
        safe_configs = copy.deepcopy(provider_configs)
        safe_inventory = copy.deepcopy(inventory)
        _canonical_json(safe_configs)
        _canonical_json(safe_inventory)
    except (TypeError, ValueError, OverflowError):
        return _fail_closed(base)

    # First loop: Strictly validate the structure of the entire provider_configs input
    for provider in PROVIDER_ORDER:
        config = safe_configs[provider]
        if not isinstance(config, dict) or set(config.keys()) != {"auth_kind", "route_evidence", "platform", "architecture", "provider_meta"}:
            return _fail_closed(base)

        if not isinstance(config["auth_kind"], str):
            return _fail_closed(base)

        ev = config["route_evidence"]
        if not isinstance(ev, dict):
            return _fail_closed(base)

        common = {"api_key_present", "gateway_configured", "external_cloud_configured"}
        if provider == "openai":
            if set(ev.keys()) != (common | {"custom_model_provider_configured", "arbitrary_codex_config_present"}):
                return _fail_closed(base)
            if config["platform"] is not None or config["architecture"] is not None or config["provider_meta"] is not None:
                return _fail_closed(base)
        elif provider == "anthropic":
            if set(ev.keys()) != (common | {"dangerous_permission_bypass", "hide_claude_auth"}):
                return _fail_closed(base)
            if config["platform"] is not None or config["architecture"] is not None or not isinstance(config["provider_meta"], dict):
                return _fail_closed(base)
        elif provider == "google":
            if set(ev.keys()) != (common | {"cloud_billing_selected", "overages_enabled", "adc_present", "vertex_selected"}):
                return _fail_closed(base)
            if not isinstance(config["platform"], str) or not config["platform"] or not isinstance(config["architecture"], str) or not config["architecture"]:
                return _fail_closed(base)
            if config["provider_meta"] is not None:
                return _fail_closed(base)

        for k, v in ev.items():
             if type(v) is not bool:
                  return _fail_closed(base)

    # Second loop: Execute validate_provider_static sequentially
    preflights: dict[str, Any] = {}
    preflight_states: dict[str, str] = {}

    for provider in PROVIDER_ORDER:
        config = safe_configs[provider]
        try:
            preflight = validate_provider_static(
                provider_id=provider,
                auth_kind=config["auth_kind"],
                route_evidence=config["route_evidence"],
                platform=config["platform"],
                architecture=config["architecture"],
                provider_meta=config["provider_meta"]
            )
        except Exception:
            return _fail_closed(base)

        req_keys = {
            "static_configuration_status", "live_readiness", "reasons", "provider_id",
            "external_agent", "pinned_version", "retry_count", "fallback_state", "live_ready"
        }
        if not isinstance(preflight, dict) or set(preflight.keys()) != req_keys:
            return _fail_closed(base)
        if preflight["static_configuration_status"] not in ("PASS", "UNKNOWN"):
            return _fail_closed(base)
        if preflight["live_readiness"] != "BLOCKED":
            return _fail_closed(base)
        if preflight["provider_id"] != provider:
            return _fail_closed(base)
        if preflight["retry_count"] != 0 or preflight["fallback_state"] != "disabled" or preflight["live_ready"] is not False:
            return _fail_closed(base)
        if not isinstance(preflight["reasons"], list):
            return _fail_closed(base)

        policy = _POLICIES[provider]
        if preflight["external_agent"] != policy.external_agent:
             return _fail_closed(base)
        if preflight["pinned_version"] != policy.pinned_version:
             return _fail_closed(base)

        # FAIL CLOSED IMMEDIATELY ON UNKNOWN TO AVOID POLLUTING PREFLIGHTS OR PIPELINE
        # We must NOT fail_closed on UNKNOWN. UNKNOWN is a valid state that simply means live execution will be BLOCKED.
        # It must be recorded and passed to the pipeline so humans can see what is missing.
        preflights[provider] = preflight
        preflight_states[provider] = preflight["static_configuration_status"]

    base["preflight_states"] = preflight_states
    base["preflight_snapshots"] = copy.deepcopy(preflights)
    base["preflight_packet_sha256"] = hashlib.sha256(_canonical_json(preflights).encode("utf-8")).hexdigest()

    try:
        pipeline_result = build_live_readiness_pipeline({"preflights": copy.deepcopy(preflights), "inventory": safe_inventory})
    except Exception:
        return _fail_closed(base)

    pl_req_keys = {
        "state", "live_ready", "dispatch_allowed", "human_approval_required", "retry_count",
        "fallback_state", "inventory_state", "unresolved_count", "unresolved_by_provider",
        "inventory_packet_sha256", "provider_states", "blocking_providers", "bundle_packet_sha256",
        "pipeline_packet_sha256"
    }
    if not isinstance(pipeline_result, dict) or set(pipeline_result.keys()) != pl_req_keys:
        return _fail_closed(base)

    if pipeline_result["state"] not in _ALLOWED_STATES:
         return _fail_closed(base)
    if pipeline_result["live_ready"] is not False or pipeline_result["dispatch_allowed"] is not False or pipeline_result["human_approval_required"] is not True or pipeline_result["retry_count"] != 0 or pipeline_result["fallback_state"] != "disabled":
         return _fail_closed(base)

    if pipeline_result["inventory_state"] not in _INVENTORY_STATES:
         return _fail_closed(base)

    unresolved_count = pipeline_result["unresolved_count"]
    if not isinstance(unresolved_count, int) or isinstance(unresolved_count, bool) or unresolved_count < -1:
        return _fail_closed(base)

    ubp = pipeline_result["unresolved_by_provider"]
    if not isinstance(ubp, dict):
        return _fail_closed(base)
    if ubp:
        if set(ubp.keys()) != set(PROVIDER_ORDER):
            return _fail_closed(base)
        if any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in ubp.values()):
            return _fail_closed(base)

    ps = pipeline_result["provider_states"]
    if not isinstance(ps, dict):
        return _fail_closed(base)
    if ps:
        if set(ps.keys()) != set(PROVIDER_ORDER):
            return _fail_closed(base)
        if any(v not in _ALLOWED_STATES for v in ps.values()):
            return _fail_closed(base)

    bp = pipeline_result["blocking_providers"]
    if not isinstance(bp, list) or len(bp) > 3 or len(set(bp)) != len(bp):
        return _fail_closed(base)
    expected_bp_order = [p for p in PROVIDER_ORDER if p in bp]
    if bp != expected_bp_order:
        return _fail_closed(base)

    inv_hash = pipeline_result["inventory_packet_sha256"]
    if inv_hash is not None and not _is_sha256(inv_hash):
        return _fail_closed(base)

    bun_hash = pipeline_result["bundle_packet_sha256"]
    if bun_hash is not None and not _is_sha256(bun_hash):
        return _fail_closed(base)

    pip_hash = pipeline_result["pipeline_packet_sha256"]
    if not _is_sha256(pip_hash):
        return _fail_closed(base)

    if pipeline_result["state"] == "READY_FOR_HUMAN_APPROVAL":
        if pipeline_result["inventory_state"] != "PROOF_RECORDS_COMPLETE":
            return _fail_closed(base)
        if unresolved_count != 0:
            return _fail_closed(base)
        if not ps:
            return _fail_closed(base)
        if any(v != "READY_FOR_HUMAN_APPROVAL" for v in ps.values()):
            return _fail_closed(base)
        if bp != []:
            return _fail_closed(base)
        if inv_hash is None or bun_hash is None:
            return _fail_closed(base)

    base["state"] = pipeline_result["state"]
    base["inventory_state"] = pipeline_result["inventory_state"]
    base["unresolved_count"] = pipeline_result["unresolved_count"]
    base["unresolved_by_provider"] = copy.deepcopy(pipeline_result["unresolved_by_provider"])
    base["inventory_packet_sha256"] = pipeline_result["inventory_packet_sha256"]
    base["provider_states"] = copy.deepcopy(pipeline_result["provider_states"])
    base["blocking_providers"] = copy.deepcopy(pipeline_result["blocking_providers"])
    base["bundle_packet_sha256"] = pipeline_result["bundle_packet_sha256"]
    base["pipeline_packet_sha256"] = pipeline_result["pipeline_packet_sha256"]

    base_json = _canonical_json({k: v for k, v in base.items() if k != "snapshot_packet_sha256"})
    base["snapshot_packet_sha256"] = hashlib.sha256(base_json.encode("utf-8")).hexdigest()
    return base


def render_snapshot_summary_ja(result: Any) -> str:
    aggregate_state = "BLOCKED_UNKNOWN"
    unresolved = -1
    states: dict[str, str] = {}
    blocking: list[str] = list(PROVIDER_ORDER)
    preflight_states: dict[str, str] = {}

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

        candidate_preflights = result.get("preflight_states")
        if isinstance(candidate_preflights, dict):
             for provider in PROVIDER_ORDER:
                  candidate = candidate_preflights.get(provider)
                  if candidate in ("PASS", "UNKNOWN"):
                       preflight_states[provider] = candidate

    lines = [
        "ライブ実行: 禁止",
        "人間承認が必要",
        f"全体状態: {aggregate_state}"
    ]

    if preflight_states:
        lines.append("事前確認状態:")
        for provider in PROVIDER_ORDER:
            lines.append(f"  - {provider}: {preflight_states.get(provider, 'UNKNOWN')}")

    lines.append(f"未解決の証明数: {unresolved}")

    if states:
        lines.append("プロバイダー状態:")
        for provider in PROVIDER_ORDER:
            lines.append(f"  - {provider}: {states.get(provider, 'BLOCKED_UNKNOWN')}")

    if blocking:
        lines.append(f"ブロック中のプロバイダー: {', '.join(blocking)}")

    return "\n".join(lines)
