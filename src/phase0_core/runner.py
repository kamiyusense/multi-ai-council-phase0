from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .adapter import ProviderAdapter
from .evidence import capture_then_parse, sha256_bytes, write_json
from .fanout import FanoutDecision, FanoutGate
from .stop import StopController
from .workspace import ensure_within


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
    ) -> dict[str, Any]:
        root = self._case_root(case_id)
        root.mkdir(parents=True, exist_ok=False)
        input_dir = root / "input"
        input_dir.mkdir()
        (input_dir / "user_input.txt").write_text(user_input, encoding="utf-8")
        (input_dir / "packet.txt").write_text(packet, encoding="utf-8")
        write_json(
            input_dir / "hashes.json",
            {
                "input_sha256": sha256_bytes(user_input.encode()),
                "packet_sha256": sha256_bytes(packet.encode()),
            },
        )

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
