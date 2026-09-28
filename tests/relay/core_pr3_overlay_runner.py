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
_MODULE_PREFIXES = ("phase0_core", "providers", "relay")


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


def _required_paths(core_root: Path, relay_root: Path) -> tuple[Path, ...]:
    return (
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
    )


def _validate_inputs(core_root: Path, relay_root: Path, core_head: str) -> None:
    if core_head != PINNED_CORE_HEAD:
        raise ValueError(
            f"core_head mismatch. Expected {PINNED_CORE_HEAD}, got {core_head}"
        )
    if not isinstance(core_root, Path) or not isinstance(relay_root, Path):
        raise TypeError("core_root and relay_root must be pathlib.Path values")
    for path in _required_paths(core_root, relay_root):
        if not path.is_file():
            raise FileNotFoundError(f"Missing required explicit file: {path}")


def _safe_profiles():
    from providers.antigravity_acp import build_antigravity_profile
    from providers.claude_acp import build_claude_profile
    from providers.codex_acp import build_codex_profile

    return {
        "openai": build_codex_profile(
            "account",
            {
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "custom_model_provider_configured": False,
                "arbitrary_codex_config_present": False,
            },
        ),
        "anthropic": build_claude_profile(
            "account",
            {
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "dangerous_permission_bypass": False,
                "hide_claude_auth": False,
            },
        ),
        "google": build_antigravity_profile(
            "account",
            {
                "api_key_present": False,
                "gateway_configured": False,
                "external_cloud_configured": False,
                "cloud_billing_selected": False,
                "overages_enabled": False,
                "adc_present": False,
                "vertex_selected": False,
            },
            "linux",
            "x86_64",
        ),
    }


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


def run_overlay(core_root: Path, relay_root: Path, core_head: str) -> dict[str, Any]:
    """Run pinned Core PR #3 against current Relay static/mock adapters only."""

    _validate_inputs(core_root, relay_root, core_head)

    old_sys_path = list(sys.path)
    saved_modules = _remove_overlay_modules()
    try:
        core_src = core_root / "src"
        relay_src = relay_root / "src"
        sys.path[:0] = [str(core_src), str(relay_src)]
        importlib.invalidate_caches()

        from phase0_core.fanout import FanoutGate
        from phase0_core.runner import CaseRunner
        from phase0_core.stop import StopController
        from providers.bundle import ProviderAdapterBundle
        from providers.core_boundary import build_core_pr3_adapter_map
        from relay.bridge import RelayProviderAdapterBridge

        raw_text = _valid_raw_response()
        raw_bytes = raw_text.encode("utf-8")
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()

        profiles = _safe_profiles()
        bridges = {
            provider_id: RelayProviderAdapterBridge(mock_raw_response=raw_text)
            for provider_id in _PROVIDER_ORDER
        }
        bundle = ProviderAdapterBundle(profiles, bridges)
        adapters = build_core_pr3_adapter_map(bundle)

        if tuple(adapters) != _PROVIDER_ORDER:
            raise RuntimeError("overlay adapter order mismatch")

        with tempfile.TemporaryDirectory() as td:
            runner = CaseRunner(Path(td), FanoutGate(), StopController())
            result = runner.run_mock_council(
                case_id="relay-core-pr3-overlay",
                user_input="shareable overlay fixture question",
                packet="relay overlay fixture packet",
                adapters=adapters,
                allowed_conclusion_codes={"YES", "NO", "UNKNOWN"},
                externally_shareable=True,
                contains_private_code=False,
                base_commit=core_head,
            )

            comparison = result["comparison"]
            report = result["report"]
            if comparison is None or report is None:
                raise RuntimeError("Core overlay did not produce comparison/report")

            if comparison.participant_count != 3:
                raise RuntimeError("Core overlay participant_count mismatch")
            if comparison.agreement_count != 3:
                raise RuntimeError("Core overlay agreement_count mismatch")
            if comparison.formal_consensus is not False:
                raise RuntimeError("Core overlay must not claim formal consensus")
            if comparison.human_required is not True:
                raise RuntimeError("Core overlay must require human final decision")
            if "最終判断: 人間" not in report:
                raise RuntimeError("Core overlay Japanese report lost human-final wording")

            raw_sha256: dict[str, str] = {}
            for provider_id in _PROVIDER_ORDER:
                path = result["case_root"] / "providers" / provider_id / "response.raw"
                actual = path.read_bytes()
                if actual != raw_bytes:
                    raise RuntimeError(f"{provider_id} raw evidence changed")
                raw_sha256[provider_id] = hashlib.sha256(actual).hexdigest()
                if raw_sha256[provider_id] != raw_sha:
                    raise RuntimeError(f"{provider_id} raw evidence hash mismatch")

            checkpoint_path = result["case_root"] / "evidence" / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint.get("live_turn_executed") is not False:
                raise RuntimeError("Core overlay unexpectedly claims a live turn")
            if checkpoint.get("retry_count") != 0:
                raise RuntimeError("Core overlay retry_count changed")
            if checkpoint.get("fallback_state") != "disabled":
                raise RuntimeError("Core overlay fallback_state changed")
            if checkpoint.get("FAIL") != []:
                raise RuntimeError("Core overlay checkpoint contains FAIL")
            if checkpoint.get("UNKNOWN") != []:
                raise RuntimeError("Core overlay checkpoint contains UNKNOWN")

            dispatch_counts = {
                provider_id: bridges[provider_id].dispatch_count
                for provider_id in _PROVIDER_ORDER
            }
            collect_counts = {
                provider_id: bridges[provider_id].collect_count
                for provider_id in _PROVIDER_ORDER
            }
            abort_counts = {
                provider_id: len(bridges[provider_id].abort_calls)
                for provider_id in _PROVIDER_ORDER
            }
            if set(dispatch_counts.values()) != {1}:
                raise RuntimeError("Core overlay dispatch count mismatch")
            if set(collect_counts.values()) != {1}:
                raise RuntimeError("Core overlay collect count mismatch")
            if set(abort_counts.values()) != {0}:
                raise RuntimeError("Core overlay unexpectedly aborted a provider")

            return {
                "core_head": core_head,
                "relay_compatibility": "PASS",
                "provider_order": list(_PROVIDER_ORDER),
                "participant_count": comparison.participant_count,
                "agreement_count": comparison.agreement_count,
                "formal_consensus": comparison.formal_consensus,
                "human_required": comparison.human_required,
                "report_contains_human_final": True,
                "raw_sha256": raw_sha256,
                "checkpoint": {
                    "live_turn_executed": checkpoint["live_turn_executed"],
                    "retry_count": checkpoint["retry_count"],
                    "fallback_state": checkpoint["fallback_state"],
                    "fail_count": len(checkpoint["FAIL"]),
                    "unknown_count": len(checkpoint["UNKNOWN"]),
                },
                "dispatch_counts": dispatch_counts,
                "collect_counts": collect_counts,
                "abort_counts": abort_counts,
            }
    finally:
        sys.path[:] = old_sys_path
        _restore_overlay_modules(saved_modules)
        importlib.invalidate_caches()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-root", required=True)
    parser.add_argument("--relay-root", required=True)
    parser.add_argument("--core-head", required=True)
    args = parser.parse_args()
    result = run_overlay(
        Path(args.core_root),
        Path(args.relay_root),
        args.core_head,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
