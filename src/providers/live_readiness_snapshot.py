import copy
import hashlib
import json
from typing import Any

from src.providers.live_readiness_pipeline import PROVIDER_ORDER, build_live_readiness_pipeline
from src.providers.preflight import validate_provider_static
from src.providers.policy import ANTIGRAVITY_POLICY, CLAUDE_POLICY, CODEX_POLICY

_ALLOWED_STATES = {"BLOCKED_UNKNOWN", "READY_FOR_HUMAN_APPROVAL"}
_INVENTORY_STATES = {"BLOCKED_UNKNOWN", "UNRESOLVED", "PROOF_RECORDS_COMPLETE"}
_PREFLIGHT_STATUSES = {"PASS", "UNKNOWN"}

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


def _finalize_snapshot(base: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in base.items() if k != "snapshot_packet_sha256"}
    base["snapshot_packet_sha256"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    return base


def _fail_closed(base: dict[str, Any]) -> dict[str, Any]:
    base.update(
        {
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
        }
    )
    return _finalize_snapshot(base)


def _valid_preflight_snapshot(provider: str, snapshot: Any) -> bool:
    required_keys = {
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
    if not isinstance(snapshot, dict) or set(snapshot) != required_keys:
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


def _valid_pipeline_result(result: Any) -> bool:
    required_keys = {
        "state",
        "live_ready",
        "dispatch_allowed",
        "human_approval_required",
        "retry_count",
        "fallback_state",
        "inventory_state",
        "unresolved_count",
        "unresolved_by_provider",
        "inventory_packet_sha256",
        "provider_states",
        "blocking_providers",
        "bundle_packet_sha256",
        "pipeline_packet_sha256",
    }
    if not isinstance(result, dict) or set(result) != required_keys:
        return False
    if result["state"] not in _ALLOWED_STATES:
        return False
    if result["live_ready"] is not False or result["dispatch_allowed"] is not False:
        return False
    if result["human_approval_required"] is not True:
        return False
    if type(result["retry_count"]) is not int or result["retry_count"] != 0:
        return False
    if result["fallback_state"] != "disabled":
        return False

    inventory_state = result["inventory_state"]
    if inventory_state not in _INVENTORY_STATES:
        return False

    unresolved_count = result["unresolved_count"]
    if type(unresolved_count) is not int or unresolved_count < -1:
        return False

    unresolved_by_provider = result["unresolved_by_provider"]
    inventory_hash = result["inventory_packet_sha256"]

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
        if (
            sum(unresolved_by_provider[p] for p in PROVIDER_ORDER)
            != unresolved_count
        ):
            return False
        if not _is_sha256(inventory_hash):
            return False
        if inventory_state == "UNRESOLVED" and unresolved_count <= 0:
            return False
        if (
            inventory_state == "PROOF_RECORDS_COMPLETE"
            and unresolved_count != 0
        ):
            return False

    provider_states = result["provider_states"]
    blocking = result["blocking_providers"]
    bundle_hash = result["bundle_packet_sha256"]

    if not _valid_blocking_providers(blocking):
        return False

    if provider_states == {}:
        if result["state"] != "BLOCKED_UNKNOWN":
            return False
        if blocking != list(PROVIDER_ORDER):
            return False
        if bundle_hash is not None:
            return False
    else:
        if not _valid_provider_states(provider_states):
            return False
        expected_blocking = [
            provider
            for provider in PROVIDER_ORDER
            if provider_states[provider] != "READY_FOR_HUMAN_APPROVAL"
        ]
        if blocking != expected_blocking:
            return False
        if not _is_sha256(bundle_hash):
            return False
        expected_state = (
            "READY_FOR_HUMAN_APPROVAL"
            if not expected_blocking
            else "BLOCKED_UNKNOWN"
        )
        if result["state"] != expected_state:
            return False

    if result["state"] == "READY_FOR_HUMAN_APPROVAL":
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
        if blocking != []:
            return False
        if not _is_sha256(inventory_hash) or not _is_sha256(bundle_hash):
            return False

    return _is_sha256(result["pipeline_packet_sha256"])


def build_live_readiness_snapshot(input_data: Any) -> dict[str, Any]:
    base = _base_snapshot_result()

    if not isinstance(input_data, dict) or set(input_data) != {"provider_configs", "inventory"}:
        return _fail_closed(base)

    try:
        safe_input = copy.deepcopy(input_data)
        _canonical_json(safe_input)
    except (TypeError, ValueError, OverflowError):
        return _fail_closed(base)

    provider_configs = safe_input["provider_configs"]
    inventory = safe_input["inventory"]

    if not isinstance(provider_configs, dict) or set(provider_configs) != set(PROVIDER_ORDER):
        return _fail_closed(base)

    common_evidence = {
        "api_key_present",
        "gateway_configured",
        "external_cloud_configured",
    }
    expected_evidence = {
        "openai": common_evidence
        | {"custom_model_provider_configured", "arbitrary_codex_config_present"},
        "anthropic": common_evidence
        | {"dangerous_permission_bypass", "hide_claude_auth"},
        "google": common_evidence
        | {
            "cloud_billing_selected",
            "overages_enabled",
            "adc_present",
            "vertex_selected",
        },
    }

    for provider in PROVIDER_ORDER:
        config = provider_configs[provider]
        if not isinstance(config, dict) or set(config) != {
            "auth_kind",
            "route_evidence",
            "platform",
            "architecture",
            "provider_meta",
        }:
            return _fail_closed(base)
        if not isinstance(config["auth_kind"], str):
            return _fail_closed(base)

        route_evidence = config["route_evidence"]
        if not isinstance(route_evidence, dict):
            return _fail_closed(base)
        if set(route_evidence) != expected_evidence[provider]:
            return _fail_closed(base)
        if any(type(value) is not bool for value in route_evidence.values()):
            return _fail_closed(base)

        if provider == "openai":
            if (
                config["platform"] is not None
                or config["architecture"] is not None
                or config["provider_meta"] is not None
            ):
                return _fail_closed(base)
        elif provider == "anthropic":
            if (
                config["platform"] is not None
                or config["architecture"] is not None
                or not isinstance(config["provider_meta"], dict)
            ):
                return _fail_closed(base)
        else:
            if (
                not isinstance(config["platform"], str)
                or not config["platform"]
                or not isinstance(config["architecture"], str)
                or not config["architecture"]
                or config["provider_meta"] is not None
            ):
                return _fail_closed(base)

    preflights: dict[str, Any] = {}
    preflight_states: dict[str, str] = {}

    for provider in PROVIDER_ORDER:
        config = provider_configs[provider]
        try:
            raw_preflight = validate_provider_static(
                provider_id=provider,
                auth_kind=config["auth_kind"],
                route_evidence=config["route_evidence"],
                platform=config["platform"],
                architecture=config["architecture"],
                provider_meta=config["provider_meta"],
            )
            preflight = copy.deepcopy(raw_preflight)
            _canonical_json(preflight)
        except Exception:
            return _fail_closed(base)

        if not _valid_preflight_snapshot(provider, preflight):
            return _fail_closed(base)

        preflights[provider] = preflight
        preflight_states[provider] = preflight["static_configuration_status"]

    base["preflight_states"] = copy.deepcopy(preflight_states)
    base["preflight_snapshots"] = copy.deepcopy(preflights)
    base["preflight_packet_sha256"] = hashlib.sha256(
        _canonical_json(base["preflight_snapshots"]).encode("utf-8")
    ).hexdigest()

    try:
        raw_pipeline_result = build_live_readiness_pipeline(
            {
                "preflights": copy.deepcopy(preflights),
                "inventory": copy.deepcopy(inventory),
            }
        )
        pipeline_result = copy.deepcopy(raw_pipeline_result)
        _canonical_json(pipeline_result)
    except Exception:
        return _fail_closed(base)

    if not _valid_pipeline_result(pipeline_result):
        return _fail_closed(base)

    base["state"] = pipeline_result["state"]
    base["inventory_state"] = pipeline_result["inventory_state"]
    base["unresolved_count"] = pipeline_result["unresolved_count"]
    base["unresolved_by_provider"] = copy.deepcopy(
        pipeline_result["unresolved_by_provider"]
    )
    base["inventory_packet_sha256"] = pipeline_result["inventory_packet_sha256"]
    base["provider_states"] = copy.deepcopy(pipeline_result["provider_states"])
    base["blocking_providers"] = list(pipeline_result["blocking_providers"])
    base["bundle_packet_sha256"] = pipeline_result["bundle_packet_sha256"]
    base["pipeline_packet_sha256"] = pipeline_result["pipeline_packet_sha256"]

    return _finalize_snapshot(base)


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
        if type(unresolved_candidate) is int and unresolved_candidate >= -1:
            unresolved = unresolved_candidate

        candidate_preflights = result.get("preflight_states")
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

        candidate_states = result.get("provider_states")
        if _valid_provider_states(candidate_states):
            states = {p: candidate_states[p] for p in PROVIDER_ORDER}

        candidate_blocking = result.get("blocking_providers")
        if _valid_blocking_providers(candidate_blocking):
            blocking = list(candidate_blocking)

    lines = [
        "ライブ実行: 禁止",
        "人間承認が必要",
        f"全体状態: {aggregate_state}",
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
