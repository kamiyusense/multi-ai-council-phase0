from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

PINNED_CORE_HEAD = "494b7296f32dce1c173a7699e4bd2d87f70d31a9"
_PROVIDER_ORDER = ("openai", "anthropic", "google")
_MODULE_PREFIXES = ("phase0_core", "providers", "relay", "src")

def _namespace_matches(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _MODULE_PREFIXES)

def _remove_overlay_modules() -> dict[str, Any]:
    saved = {
        name: module
        for name, module in list(sys.modules.items())
        if _namespace_matches(name)
    }
    for name in saved:
        sys.modules.pop(name, None)
    return saved

def _restore_overlay_modules(saved: dict[str, Any]) -> None:
    for name in list(sys.modules):
        if _namespace_matches(name):
            sys.modules.pop(name, None)
    sys.modules.update(saved)

def _validate_inputs(core_root: Path, relay_root: Path, core_head: str) -> None:
    if core_head != PINNED_CORE_HEAD:
        raise ValueError(f"core_head must be exactly {PINNED_CORE_HEAD}")
    for path in (
        core_root / "src/phase0_core/__init__.py",
        core_root / "src/phase0_core/adapter.py",
        core_root / "src/phase0_core/fanout.py",
        core_root / "src/phase0_core/runner.py",
        core_root / "src/phase0_core/stop.py",
        relay_root / "src/providers/core_boundary.py",
        relay_root / "src/providers/bundle.py",
        relay_root / "src/providers/codex_acp.py",
        relay_root / "src/providers/claude_acp.py",
        relay_root / "src/providers/antigravity_acp.py",
        relay_root / "src/relay/core_adapter.py",
        relay_root / "src/relay/bridge.py",
    ):
        if not path.is_file():
            raise FileNotFoundError(f"Missing required explicit file: {path}")

def _safe_profiles():
    from providers.antigravity_acp import build_antigravity_profile
    from providers.claude_acp import build_claude_profile
    from providers.codex_acp import build_codex_profile

    return {
        "openai": build_codex_profile("account", {"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False, "custom_model_provider_configured": False, "arbitrary_codex_config_present": False}),
        "anthropic": build_claude_profile("account", {"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False, "dangerous_permission_bypass": False, "hide_claude_auth": False}),
        "google": build_antigravity_profile("account", {"api_key_present": False, "gateway_configured": False, "external_cloud_configured": False, "cloud_billing_selected": False, "overages_enabled": False, "adc_present": False, "vertex_selected": False}, "linux", "x86_64"),
    }

def _provider_states_from_checkpoint(checkpoint: dict[str, Any]) -> dict[str, str]:
    if not isinstance(checkpoint, dict):
        raise TypeError("checkpoint must be a dictionary")
    states = {provider_id: "COMPLETE" for provider_id in _PROVIDER_ORDER}
    seen: set[str] = set()
    for bucket in ("FAIL", "UNKNOWN"):
        entries = checkpoint.get(bucket)
        if not isinstance(entries, list):
            raise ValueError(f"checkpoint {bucket} must be a list")
        for entry in entries:
            if not isinstance(entry, str) or entry.count(":") != 1:
                raise ValueError(f"malformed checkpoint state entry: {entry!r}")
            provider_id, state = entry.split(":", 1)
            # Skip non-provider entries like "core:STOP_REQUESTED"
            if provider_id not in _PROVIDER_ORDER:
                continue
            if provider_id not in states or not state or provider_id in seen:
                raise ValueError(f"invalid checkpoint state entry: {entry!r}")
            states[provider_id] = state
            seen.add(provider_id)
    return states

def _valid_raw_response() -> str:
    return json.dumps(
        {
            "schema_version": "phase0-response-v1",
            "answer_state": "ANSWER",
            "conclusion_code": "YES",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "Mock yes answer",
        },
        separators=(",", ":"),
        sort_keys=True,
    )

def _google_unknown_raw_response() -> str:
    return json.dumps(
        {
            "schema_version": "phase0-response-v1",
            "answer_state": "ANSWER",
            "conclusion_code": "UNKNOWN",
            "safety_warning": "UNKNOWN",
            "safety_reason": "Policy mock reason",
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "",
        },
        separators=(",", ":"),
        sort_keys=True,
    )

def run_matrix(core_root: Path, relay_root: Path, core_head: str) -> dict[str, Any]:
    _validate_inputs(core_root, relay_root, core_head)

    scenario_order = ["safety_unknown_google", "fanout_unknown", "stop_before_dispatch"]
    results = {
        "core_head": core_head,
        "matrix_state": "PASS",
        "scenario_order": scenario_order,
        "per_scenario": {}
    }

    raw_text_valid = _valid_raw_response()
    raw_bytes_valid = raw_text_valid.encode("utf-8")
    raw_sha_valid = hashlib.sha256(raw_bytes_valid).hexdigest()

    raw_text_google_unknown = _google_unknown_raw_response()
    raw_bytes_google_unknown = raw_text_google_unknown.encode("utf-8")
    raw_sha_google_unknown = hashlib.sha256(raw_bytes_google_unknown).hexdigest()

    def run_scenario(scenario: str) -> dict[str, Any]:
        old_sys_path = list(sys.path)
        saved_modules = _remove_overlay_modules()
        try:
            core_src = core_root / "src"
            relay_src = relay_root / "src"
            sys.path[:0] = [str(core_src), str(relay_root), str(relay_src)]
            importlib.invalidate_caches()

            from phase0_core.fanout import FanoutGate
            from phase0_core.runner import CaseRunner
            from phase0_core.stop import StopController
            from providers.bundle import ProviderAdapterBundle
            from providers.core_boundary import build_core_pr3_adapter_map
            from relay.bridge import RelayProviderAdapterBridge

            profiles = _safe_profiles()
            bridges = {}
            for provider_id in _PROVIDER_ORDER:
                b = RelayProviderAdapterBridge(mock_raw_response=raw_text_valid)
                if scenario == "safety_unknown_google" and provider_id == "google":
                    b.mock_raw_response = raw_text_google_unknown
                bridges[provider_id] = b

            bundle = ProviderAdapterBundle(profiles, bridges)
            adapters = build_core_pr3_adapter_map(bundle)

            stop_controller = StopController()
            fanout = FanoutGate()

            if scenario == "stop_before_dispatch":
                stop_controller.request_stop("stop_before_dispatch mock reason")

            with tempfile.TemporaryDirectory() as td:
                runner = CaseRunner(Path(td), fanout, stop_controller)

                kwargs = {
                    "case_id": "relay-core-pr3-overlay",
                    "user_input": "shareable overlay fixture question",
                    "packet": "relay overlay fixture packet",
                    "adapters": adapters,
                    "allowed_conclusion_codes": {"YES", "NO", "UNKNOWN"},
                    "externally_shareable": True,
                    "contains_private_code": False,
                    "base_commit": core_head,
                }

                if scenario == "fanout_unknown":
                    kwargs["externally_shareable"] = None

                res = runner.run_mock_council(**kwargs)

                comparison = res.get("comparison")

                raw_sha256 = {}
                raw_exactness = {}
                for provider_id in _PROVIDER_ORDER:
                    path = res["case_root"] / "providers" / provider_id / "response.raw"
                    if path.exists():
                        actual = path.read_bytes()
                        raw_sha256[provider_id] = hashlib.sha256(actual).hexdigest()
                        if scenario == "safety_unknown_google" and provider_id == "google":
                            raw_exactness[provider_id] = actual == raw_bytes_google_unknown
                        else:
                            raw_exactness[provider_id] = actual == raw_bytes_valid
                    else:
                        raw_sha256[provider_id] = None
                        raw_exactness[provider_id] = False

                checkpoint_path = res["case_root"] / "evidence" / "checkpoint.json"
                if checkpoint_path.exists():
                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                else:
                    checkpoint = {}

                return {
                    "provider_states": _provider_states_from_checkpoint(checkpoint) if comparison else None,
                    "comparison": {
                        "participant_count": comparison.participant_count,
                        "agreement_count": comparison.agreement_count,
                        "human_required": comparison.human_required,
                        "formal_consensus": comparison.formal_consensus,
                        "safety_block": getattr(comparison, "safety_block", None),
                    } if comparison else None,
                    "checkpoint": {
                        "live_turn_executed": checkpoint.get("live_turn_executed"),
                        "retry_count": checkpoint.get("retry_count"),
                        "fallback_state": checkpoint.get("fallback_state"),
                        "FAIL": checkpoint.get("FAIL", []),
                        "UNKNOWN": checkpoint.get("UNKNOWN", []),
                    },
                    "raw_evidence": {
                        "existence": {p: (res["case_root"] / "providers" / p / "response.raw").exists() for p in _PROVIDER_ORDER},
                        "hashes": raw_sha256,
                        "exactness": raw_exactness,
                    },
                    "dispatch_counts": {p: bridges[p].dispatch_count for p in _PROVIDER_ORDER},
                    "collect_counts": {p: bridges[p].collect_count for p in _PROVIDER_ORDER},
                    "abort_counts": {p: len(bridges[p].abort_calls) for p in _PROVIDER_ORDER},
                    "providers_dir_exists": (res["case_root"] / "providers").exists()
                }

        finally:
            sys.path[:] = old_sys_path
            _restore_overlay_modules(saved_modules)
            importlib.invalidate_caches()

    for scen in scenario_order:
        s_res = run_scenario(scen)

        if scen == "safety_unknown_google":
            assert s_res["checkpoint"]["FAIL"] == []
            assert s_res["checkpoint"]["UNKNOWN"] == ["google:ERROR_UNKNOWN"]
            assert s_res["checkpoint"]["live_turn_executed"] is False
            assert s_res["checkpoint"]["retry_count"] == 0
            assert s_res["checkpoint"]["fallback_state"] == "disabled"
            assert s_res["comparison"]["participant_count"] == 3
            assert s_res["comparison"]["agreement_count"] == 3
            assert s_res["comparison"]["human_required"] is True
            assert s_res["comparison"]["formal_consensus"] is False
            assert s_res["comparison"]["safety_block"] is True
            assert set(s_res["dispatch_counts"].values()) == {1}
            assert set(s_res["collect_counts"].values()) == {1}
            assert set(s_res["abort_counts"].values()) == {0}

        elif scen == "fanout_unknown":
            assert s_res["comparison"] is None
            assert s_res["providers_dir_exists"] is False
            assert set(s_res["dispatch_counts"].values()) == {0}
            assert set(s_res["collect_counts"].values()) == {0}
            assert s_res["checkpoint"]["live_turn_executed"] is False
            assert s_res["checkpoint"]["UNKNOWN"] == ["core:FANOUT_UNKNOWN"]
            assert "retry_count" not in s_res["checkpoint"] or s_res["checkpoint"]["retry_count"] is None
            assert "fallback_state" not in s_res["checkpoint"] or s_res["checkpoint"]["fallback_state"] is None

        elif scen == "stop_before_dispatch":
            assert set(s_res["dispatch_counts"].values()) == {0}
            assert set(s_res["collect_counts"].values()) == {0}
            assert s_res["comparison"]["human_required"] is True
            assert s_res["comparison"]["formal_consensus"] is False
            assert s_res["checkpoint"]["UNKNOWN"] == ["core:STOP_REQUESTED"]
            assert s_res["checkpoint"]["live_turn_executed"] is False
            assert s_res["checkpoint"]["retry_count"] == 0
            assert s_res["checkpoint"]["fallback_state"] == "disabled"

        results["per_scenario"][scen] = s_res

    return results

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-root", required=True)
    parser.add_argument("--relay-root", required=True)
    parser.add_argument("--core-head", required=True)
    args = parser.parse_args()
    result = run_matrix(
        Path(args.core_root),
        Path(args.relay_root),
        args.core_head,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))

if __name__ == "__main__":
    main()
