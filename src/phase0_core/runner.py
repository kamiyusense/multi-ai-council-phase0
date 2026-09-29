from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .adapter import ProviderAdapter
from .comparison import compare_responses
from .evidence import capture_then_parse, diff_snapshots, persist_raw, sha256_bytes, snapshot_tree, write_json
from .fanout import FanoutDecision, FanoutGate
from .models import ProviderManifest, ProviderResponse, ProviderRunResult, RunManifest
from .reporting import render_japanese_summary
from .states import AnswerState, ExecutionState, ParticipationState
from .stop import StopController
from .validators import parse_provider_response
from .workspace import ensure_within, validate_snapshot_tree


class ExecutionMode(StrEnum):
    STATIC = "STATIC"
    MOCK = "MOCK"
    LIVE = "LIVE"


@dataclass(slots=True)
class CaseRunner:
    runs_root: Path
    fanout_gate: FanoutGate
    stop_controller: StopController

    def _case_root(self, case_id: str) -> Path:
        if not case_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in case_id):
            raise ValueError("invalid case_id")
        return ensure_within(self.runs_root, self.runs_root / case_id)

    def prepare_case(
        self,
        *,
        case_id: str,
        user_input: str,
        packet: str,
        providers: tuple[str, ...],
        externally_shareable: bool | None,
        contains_private_code: bool | None,
        base_commit: str = "UNKNOWN",
    ) -> dict[str, Any]:
        root = self._case_root(case_id)
        root.mkdir(parents=True, exist_ok=False)
        input_dir = root / "input"
        input_dir.mkdir()
        (input_dir / "user_input.txt").write_text(user_input, encoding="utf-8")
        (input_dir / "packet.txt").write_text(packet, encoding="utf-8")
        input_sha = sha256_bytes(user_input.encode())
        packet_sha = sha256_bytes(packet.encode())
        write_json(input_dir / "hashes.json", {"input_sha256": input_sha, "packet_sha256": packet_sha})

        manifest = RunManifest(
            case_id=case_id,
            base_commit=base_commit,
            input_sha256=input_sha,
            packet_sha256=packet_sha,
            providers={provider: f"providers/{provider}/manifest.json" for provider in providers},
        )
        write_json(root / "run_manifest.json", manifest.to_dict())

        assessment = self.fanout_gate.evaluate(
            user_input + "\n" + packet,
            externally_shareable=externally_shareable,
            contains_private_code=contains_private_code,
        )
        write_json(root / "evidence" / "fanout_gate.json", {"decision": assessment.decision.value, "reasons": assessment.reasons})

        # Critical ordering rule: provider snapshot directories do not exist before PASS.
        if assessment.decision is not FanoutDecision.PASS:
            return {"case_root": root, "fanout": assessment, "prepared": False}

        for provider in providers:
            provider_root = ensure_within(root, root / "providers" / provider)
            (provider_root / "snapshot").mkdir(parents=True)
        return {"case_root": root, "fanout": assessment, "prepared": True}

    def execute_with_adapter(
        self,
        *,
        adapter: ProviderAdapter,
        case_context: dict[str, Any],
        raw_path: Path,
        mode: ExecutionMode,
    ) -> dict[str, Any]:
        if mode is ExecutionMode.LIVE:
            raise RuntimeError("live provider execution is disabled in the static core")
        self.stop_controller.require_dispatch_allowed()
        prepared = adapter.prepare(case_context)
        preflight = adapter.preflight(prepared)
        if not preflight.get("ok"):
            return {"state": "BLOCKED", "preflight": preflight}
        handle = adapter.dispatch(prepared)
        raw = adapter.collect(handle)

        def parse(saved_raw: bytes) -> dict[str, Any]:
            try:
                return json.loads(saved_raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {"_invalid_json": True}

        parsed = capture_then_parse(raw_path, raw, parse)
        return {"state": "SIMULATED" if mode is ExecutionMode.MOCK else "STATIC", "parsed": parsed, "handle": handle}

    def run_mock_council(
        self,
        *,
        case_id: str,
        user_input: str,
        packet: str,
        adapters: dict[str, ProviderAdapter],
        allowed_conclusion_codes: set[str],
        externally_shareable: bool | None,
        contains_private_code: bool | None,
        base_commit: str = "UNKNOWN",
    ) -> dict[str, Any]:
        if not adapters:
            raise ValueError("at least one mock adapter is required")
        prepared = self.prepare_case(
            case_id=case_id,
            user_input=user_input,
            packet=packet,
            providers=tuple(adapters),
            externally_shareable=externally_shareable,
            contains_private_code=contains_private_code,
            base_commit=base_commit,
        )
        root: Path = prepared["case_root"]
        if not prepared["prepared"]:
            write_json(root / "evidence" / "checkpoint.json", {
                "PASS": [],
                "FAIL": [],
                "UNKNOWN": ["fan-out not confirmed PASS"],
                "live_turn_executed": False,
            })
            return {"case_root": root, "provider_results": {}, "comparison": None, "report": None}

        responses: dict[str, ProviderResponse] = {}
        provider_results: dict[str, ProviderRunResult] = {}
        for provider, adapter in adapters.items():
            provider_root = root / "providers" / provider
            snapshot_root = provider_root / "snapshot"
            provider_manifest = ProviderManifest(provider=provider, cli_name="mock")
            write_json(provider_root / "manifest.json", provider_manifest.to_dict())
            violations = validate_snapshot_tree(snapshot_root)
            if violations:
                result = ProviderRunResult(
                    provider=provider,
                    execution_state=ExecutionState.ERROR_UNKNOWN,
                    participation_state=ParticipationState.NONPARTICIPANT,
                    answer_state=None,
                    response=None,
                    error=f"unsafe snapshot: {violations}",
                    raw_sha256=None,
                    simulated=True,
                )
                provider_manifest.execution_state = result.execution_state
                provider_manifest.participation_state = result.participation_state
                provider_results[provider] = result
                write_json(provider_root / "manifest.json", provider_manifest.to_dict())
                write_json(provider_root / "provider_state.json", self._result_to_dict(result))
                continue

            before = snapshot_tree(snapshot_root)
            write_json(provider_root / "fs_before.json", {k: asdict(v) for k, v in before.items()})
            raw_path = provider_root / "response.raw"
            raw_sha: str | None = None
            try:
                execution = self.execute_with_adapter(
                    adapter=adapter,
                    case_context={"case_id": case_id, "packet_sha256": sha256_bytes(packet.encode())},
                    raw_path=raw_path,
                    mode=ExecutionMode.MOCK,
                )
                if execution["state"] == "BLOCKED":
                    raise RuntimeError("provider mock preflight blocked")
                raw_sha = sha256_bytes(raw_path.read_bytes())
                parsed = execution["parsed"]
                if parsed.get("_invalid_json"):
                    raise ValueError("invalid JSON provider output")
                response = parse_provider_response(parsed, allowed_conclusion_codes=allowed_conclusion_codes)
                result = ProviderRunResult(
                    provider=provider,
                    execution_state=ExecutionState.COMPLETE,
                    participation_state=ParticipationState.PARTICIPANT,
                    answer_state=response.answer_state,
                    response=response,
                    error=None,
                    raw_sha256=raw_sha,
                    simulated=True,
                )
                responses[provider] = response
            except TimeoutError as exc:
                if raw_path.exists() and raw_sha is None:
                    raw_sha = sha256_bytes(raw_path.read_bytes())
                result = ProviderRunResult(
                    provider=provider,
                    execution_state=ExecutionState.TIMEOUT,
                    participation_state=ParticipationState.NONPARTICIPANT,
                    answer_state=None,
                    response=None,
                    error=str(exc),
                    raw_sha256=raw_sha,
                    simulated=True,
                )
            except ValueError as exc:
                # If bytes existed, they were persisted before parsing/validation.
                if raw_path.exists() and raw_sha is None:
                    raw_sha = sha256_bytes(raw_path.read_bytes())
                result = ProviderRunResult(
                    provider=provider,
                    execution_state=ExecutionState.INVALID_OUTPUT,
                    participation_state=ParticipationState.NONPARTICIPANT,
                    answer_state=None,
                    response=None,
                    error=str(exc),
                    raw_sha256=raw_sha,
                    simulated=True,
                )
            except Exception as exc:  # deterministic failure isolation; never retry
                if raw_path.exists() and raw_sha is None:
                    raw_sha = sha256_bytes(raw_path.read_bytes())
                result = ProviderRunResult(
                    provider=provider,
                    execution_state=ExecutionState.ERROR_UNKNOWN,
                    participation_state=ParticipationState.NONPARTICIPANT,
                    answer_state=None,
                    response=None,
                    error=str(exc),
                    raw_sha256=raw_sha,
                    simulated=True,
                )
            finally:
                after = snapshot_tree(snapshot_root)
                write_json(provider_root / "fs_after.json", {k: asdict(v) for k, v in after.items()})
                write_json(provider_root / "fs_diff.json", diff_snapshots(before, after).to_dict())

            provider_manifest.execution_state = result.execution_state
            provider_manifest.participation_state = result.participation_state
            provider_manifest.answer_state = result.answer_state
            provider_results[provider] = result
            write_json(provider_root / "manifest.json", provider_manifest.to_dict())
            write_json(provider_root / "provider_state.json", self._result_to_dict(result))

        comparison = compare_responses(responses)
        comparison_payload = {
            "conclusion_match_state": comparison.conclusion_match_state.value,
            "evidence_match_state": comparison.evidence_match_state.value,
            "agreement_count": comparison.agreement_count,
            "participant_count": comparison.participant_count,
            "agreement_code": comparison.agreement_code,
            "safety_block": comparison.safety_block,
            "human_required": comparison.human_required,
            "formal_consensus": comparison.formal_consensus,
        }
        write_json(root / "comparison" / "parsed.json", {
            provider: self._response_to_dict(response) for provider, response in responses.items()
        })
        write_json(root / "comparison" / "differences.json", comparison_payload)
        report = render_japanese_summary(responses, comparison, provider_results)
        report_path = root / "comparison" / "summary_ja.md"
        report_path.write_text(report, encoding="utf-8")
        pass_items = ["mock-pipeline-completed"]
        fail_items: list[str] = []
        unknown_items: list[str] = []
        for provider, provider_result in sorted(provider_results.items()):
            state = provider_result.execution_state
            if state is ExecutionState.COMPLETE:
                pass_items.append(f"{provider}:COMPLETE")
            elif state is ExecutionState.ERROR_UNKNOWN:
                unknown_items.append(f"{provider}:ERROR_UNKNOWN")
            else:
                fail_items.append(f"{provider}:{state.value}")

        write_json(root / "evidence" / "checkpoint.json", {
            "PASS": pass_items,
            "FAIL": fail_items,
            "UNKNOWN": unknown_items,
            "provider_states": {k: v.execution_state.value for k, v in provider_results.items()},
            "live_turn_executed": False,
            "retry_count": 0,
            "fallback_state": "disabled",
        })
        return {
            "case_root": root,
            "provider_results": provider_results,
            "comparison": comparison,
            "report": report,
        }

    @staticmethod
    def _response_to_dict(response: ProviderResponse) -> dict[str, Any]:
        return {
            "schema_version": response.schema_version,
            "answer_state": response.answer_state.value,
            "conclusion_code": response.conclusion_code,
            "safety_warning": response.safety_warning,
            "safety_reason": response.safety_reason,
            "evidence_refs": list(response.evidence_refs),
            "marker_echoes": asdict(response.marker_echoes),
            "answer_text": response.answer_text,
        }

    @classmethod
    def _result_to_dict(cls, result: ProviderRunResult) -> dict[str, Any]:
        return {
            "provider": result.provider,
            "execution_state": result.execution_state.value,
            "participation_state": result.participation_state.value,
            "answer_state": result.answer_state.value if result.answer_state else None,
            "response": cls._response_to_dict(result.response) if result.response else None,
            "error": result.error,
            "raw_sha256": result.raw_sha256,
            "simulated": result.simulated,
        }
