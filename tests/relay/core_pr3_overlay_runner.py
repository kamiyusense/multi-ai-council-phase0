import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
import argparse


def _cleanup_modules():
    for m in list(sys.modules.keys()):
        if m.startswith("phase0_core"):
            del sys.modules[m]

def run_overlay(core_root: Path, relay_root: Path, core_head: str) -> dict:
    PINNED_CORE_HEAD = "494b7296f32dce1c173a7699e4bd2d87f70d31a9"
    if core_head != PINNED_CORE_HEAD:
        raise ValueError(f"core_head mismatch. Expected {PINNED_CORE_HEAD}, got {core_head}")

    core_src = core_root / "src"
    relay_src = relay_root / "src"

    expected_core_files = [
        core_src / "phase0_core/adapter.py",
        core_src / "phase0_core/runner.py",
    ]
    expected_relay_files = [
        relay_src / "providers/core_boundary.py",
        relay_src / "providers/bundle.py",
        relay_src / "relay/core_adapter.py",
    ]

    for p in expected_core_files + expected_relay_files:
        if not p.is_file():
            raise FileNotFoundError(f"Missing required explicit file: {p}")

    old_sys_path = sys.path[:]
    _cleanup_modules()

    try:
        sys.path.insert(0, str(relay_src))
        sys.path.insert(0, str(core_src))

        from phase0_core.runner import CaseRunner
        from phase0_core.adapter import StopController, FanoutGate

        from providers.codex_acp import build_codex_profile
        from providers.claude_acp import build_claude_profile
        from providers.antigravity_acp import build_antigravity_profile
        from providers.bundle import ProviderAdapterBundle
        from providers.core_boundary import build_core_pr3_adapter_map
        from relay.bridge import RelayProviderAdapterBridge

        openai_profile = build_codex_profile("account", {"api_key_present": False})
        anthropic_profile = build_claude_profile("account", {"api_key_present": False})
        google_profile = build_antigravity_profile("account", {"api_key_present": False}, "linux", "amd64")

        valid_raw = json.dumps({
            "schema_version": "phase0-response-v1",
            "answer_state": "ANSWER",
            "conclusion_code": "YES",
            "safety_warning": "ABSENT",
            "safety_reason": None,
            "evidence_refs": [],
            "marker_echoes": {"head": None, "middle": None, "tail": None},
            "answer_text": "Mock yes answer",
        })

        openai_bridge = RelayProviderAdapterBridge(mock_raw_response=valid_raw)
        anthropic_bridge = RelayProviderAdapterBridge(mock_raw_response=valid_raw)
        google_bridge = RelayProviderAdapterBridge(mock_raw_response=valid_raw)

        bundle = ProviderAdapterBundle(
            {
                "openai": openai_profile,
                "anthropic": anthropic_profile,
                "google": google_profile,
            },
            {
                "openai": openai_bridge,
                "anthropic": anthropic_bridge,
                "google": google_bridge,
            }
        )

        adapters_map = build_core_pr3_adapter_map(bundle)

        with tempfile.TemporaryDirectory() as td:
            runner = CaseRunner(
                output_dir=td,
                case_id="mock_test",
                participant_count=3,
                agreement_count=3,
                human_required=True
            )
            report = runner.run_mock_council(
                adapters_map,
                FanoutGate(),
                StopController()
            )

            results_dict = {
                "provider_order": ["openai", "anthropic", "google"],
                "participant_count": report.participant_count,
                "agreement_count": report.agreement_count,
                "formal_consensus": report.formal_consensus,
                "human_required": report.human_required,
                "report_contains_human_decision": "human-final-decision" in report.japanese_summary,
                "raw_sha256": {
                    "openai": hashlib.sha256(openai_bridge.mock_raw_response.encode()).hexdigest(),
                    "anthropic": hashlib.sha256(anthropic_bridge.mock_raw_response.encode()).hexdigest(),
                    "google": hashlib.sha256(google_bridge.mock_raw_response.encode()).hexdigest(),
                },
                "checkpoint_invariants": {
                    "live_turn_executed": report.live_turn_executed,
                    "retry_count": report.retry_count,
                    "fallback_state": report.fallback_state,
                    "no_fail": not report.has_fail,
                    "no_unknown": not report.has_unknown,
                },
                "dispatch_counts": {
                    "openai": openai_bridge.dispatch_count,
                    "anthropic": anthropic_bridge.dispatch_count,
                    "google": google_bridge.dispatch_count,
                },
                "collect_counts": {
                    "openai": openai_bridge.collect_count,
                    "anthropic": anthropic_bridge.collect_count,
                    "google": google_bridge.collect_count,
                },
                "abort_calls": openai_bridge.abort_calls + anthropic_bridge.abort_calls + google_bridge.abort_calls,
                "core_head": core_head,
                "relay_compatibility": "PASS"
            }

            return results_dict

    finally:
        sys.path[:] = old_sys_path
        _cleanup_modules()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-root", required=True)
    parser.add_argument("--relay-root", required=True)
    parser.add_argument("--core-head", required=True)
    args = parser.parse_args()

    res = run_overlay(Path(args.core_root), Path(args.relay_root), args.core_head)
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    main()
