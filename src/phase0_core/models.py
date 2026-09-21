from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .states import AnswerState, CapabilityState, ExecutionState, ParticipationState


@dataclass(slots=True)
class RunManifest:
    schema_version: str = "phase0-run-v1"
    case_id: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    base_commit: str = ""
    input_sha256: str = ""
    packet_sha256: str = ""
    providers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PermissionProfile:
    shell: str = "fixed-only"
    git_write: bool = False
    file_write_scope: str = "snapshot-only"
    settings_change: bool = False


@dataclass(slots=True)
class ProviderManifest:
    provider: str
    cli_name: str
    schema_version: str = "phase0-provider-v1"
    cli_version: str | None = None
    auth_route: str | None = None
    requested_model: str | None = None
    configured_model: str | None = None
    executed_model: str | None = None
    executed_model_verified: bool | None = None
    executed_model_verification_source: str | None = None
    retry_count: int = 0
    fallback_state: str = "disabled"
    permission_profile: PermissionProfile = field(default_factory=PermissionProfile)
    timeout_seconds: int | None = None
    execution_state: ExecutionState = ExecutionState.READY
    participation_state: ParticipationState | None = None
    answer_state: AnswerState | None = None
    capability_state: CapabilityState = CapabilityState.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("execution_state", "participation_state", "answer_state", "capability_state"):
            value = data[key]
            data[key] = value.value if hasattr(value, "value") else value
        return data


@dataclass(frozen=True, slots=True)
class MarkerEchoes:
    head: str | None
    middle: str | None
    tail: str | None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    answer_state: AnswerState
    conclusion_code: str
    safety_warning: str
    safety_reason: str | None
    evidence_refs: tuple[str, ...]
    marker_echoes: MarkerEchoes
    answer_text: str
    schema_version: str = "phase0-response-v1"


@dataclass(frozen=True, slots=True)
class ProviderRunResult:
    provider: str
    execution_state: ExecutionState
    participation_state: ParticipationState
    answer_state: AnswerState | None
    response: ProviderResponse | None
    error: str | None
    raw_sha256: str | None
    simulated: bool
