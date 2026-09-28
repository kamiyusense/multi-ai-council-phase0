import copy
import hashlib
import json
from typing import Any

from .live_readiness import COMMON_PROOFS, PROVIDER_PROOFS

PROVIDER_ORDER = ["openai", "anthropic", "google"]
_RESULT_KEYS = {
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

def _get_sorted_proof_keys(provider: str) -> list[str]:
    common = sorted(list(COMMON_PROOFS))
    specific = sorted(list(PROVIDER_PROOFS.get(provider, [])))
    return common + specific

def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

def _base_inventory_result() -> dict[str, Any]:
    return {
        "state": "UNRESOLVED",
        "live_ready": False,
        "dispatch_allowed": False,
        "human_approval_required": True,
        "retry_count": 0,
        "fallback_state": "disabled",
        "unresolved_count": 0,
        "unresolved_by_provider": {"openai": 0, "anthropic": 0, "google": 0},
        "inventory": {"openai": {}, "anthropic": {}, "google": {}},
    }

def _build_empty_inventory() -> dict[str, Any]:
    result = _base_inventory_result()
    total_unresolved = 0
    for provider in PROVIDER_ORDER:
        unresolved_for_provider = 0
        keys = _get_sorted_proof_keys(provider)
        for key in keys:
            result["inventory"][provider][key] = {"status": "UNKNOWN", "evidence_ref": None}
            unresolved_for_provider += 1
        result["unresolved_by_provider"][provider] = unresolved_for_provider
        total_unresolved += unresolved_for_provider
    result["unresolved_count"] = total_unresolved
    return result

def _fail_closed() -> dict[str, Any]:
    result = _build_empty_inventory()
    result["packet_sha256"] = _hash_payload(result)
    return result

def build_empty_inventory() -> dict[str, Any]:
    result = _build_empty_inventory()
    result["packet_sha256"] = _hash_payload(result)
    return result

def normalize_inventory(input_inventory: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(input_inventory, dict):
        return _fail_closed()

    try:
        working_copy = copy.deepcopy(input_inventory)
        _canonical_json(working_copy)
    except (TypeError, ValueError, OverflowError):
        return _fail_closed()

    if set(working_copy.keys()) != set(PROVIDER_ORDER):
        return _fail_closed()

    result = _base_inventory_result()
    total_unresolved = 0

    for provider in PROVIDER_ORDER:
        provider_data = working_copy[provider]
        if not isinstance(provider_data, dict):
            return _fail_closed()

        expected_keys = _get_sorted_proof_keys(provider)
        if set(provider_data.keys()) != set(expected_keys):
            return _fail_closed()

        unresolved_for_provider = 0
        for key in expected_keys:
            record = provider_data[key]
            if not isinstance(record, dict) or set(record.keys()) != {"status", "evidence_ref"}:
                return _fail_closed()

            status = record["status"]
            evidence_ref = record["evidence_ref"]

            if status == "UNKNOWN":
                if evidence_ref is not None:
                    return _fail_closed()
                unresolved_for_provider += 1
            elif status == "CONFIRMED":
                if not isinstance(evidence_ref, str) or not evidence_ref.strip():
                    return _fail_closed()
            else:
                return _fail_closed()

            result["inventory"][provider][key] = {"status": status, "evidence_ref": evidence_ref}

        result["unresolved_by_provider"][provider] = unresolved_for_provider
        total_unresolved += unresolved_for_provider

    result["unresolved_count"] = total_unresolved
    if total_unresolved == 0:
        result["state"] = "PROOF_RECORDS_COMPLETE"

    result["packet_sha256"] = _hash_payload(result)
    return result

def render_inventory_ja(inventory_result: dict[str, Any]) -> str:
    lines = [
        "ライブ実行: 禁止",
        "人間承認が必要",
    ]

    if not isinstance(inventory_result, dict):
        lines.append("未解決の証拠総数: UNKNOWN")
        return "\n".join(lines)

    unresolved_count = inventory_result.get("unresolved_count")
    if not isinstance(unresolved_count, int) or isinstance(unresolved_count, bool) or unresolved_count < 0:
        unresolved_count_text = "UNKNOWN"
    else:
        unresolved_count_text = str(unresolved_count)
    lines.append(f"未解決の証拠総数: {unresolved_count_text}")

    inventory = inventory_result.get("inventory")
    if isinstance(inventory, dict):
        for provider in PROVIDER_ORDER:
            lines.append(f"\nプロバイダー: {provider}")
            provider_inventory = inventory.get(provider)
            if isinstance(provider_inventory, dict):
                keys = _get_sorted_proof_keys(provider)
                for key in keys:
                    record = provider_inventory.get(key)
                    if isinstance(record, dict):
                        status = record.get("status")
                        if status == "UNKNOWN":
                            status_str = "未解決"
                        elif status == "CONFIRMED":
                            status_str = "確認済"
                        else:
                            status_str = "不明"
                        lines.append(f"  - [{status_str}] {key}")
                    else:
                        lines.append(f"  - [不明] {key}")
            else:
                lines.append("  - 証拠データなし")

    return "\n".join(lines)

def convert_to_live_readiness_proofs(inventory_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(inventory_result, dict) or set(inventory_result) != _RESULT_KEYS:
        return {}

    inventory = inventory_result.get("inventory")
    if not isinstance(inventory, dict):
        return {}

    normalized = normalize_inventory(inventory)
    if normalized["state"] != "PROOF_RECORDS_COMPLETE":
        return {}

    # A caller/result mutation after normalization must fail closed rather than
    # being trusted as an approval-record source.
    if inventory_result != normalized:
        return {}

    result: dict[str, Any] = {}
    for provider in PROVIDER_ORDER:
        provider_inventory = normalized["inventory"][provider]
        provider_proofs: dict[str, Any] = {}
        for key in _get_sorted_proof_keys(provider):
            record = provider_inventory[key]
            if record["status"] != "CONFIRMED":
                return {}
            provider_proofs[key] = copy.deepcopy(record)
        result[provider] = provider_proofs

    return result
