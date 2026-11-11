from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .models import MarkerEchoes, ProviderManifest, ProviderResponse
from .states import AnswerState


SAFETY_WARNING_VALUES = {"PRESENT", "ABSENT", "UNKNOWN"}
_PROVIDER_RESPONSE_FIELDS = {
    "schema_version",
    "answer_state",
    "conclusion_code",
    "safety_warning",
    "safety_reason",
    "evidence_refs",
    "marker_echoes",
    "answer_text",
}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


def validate_timeout(value: object) -> ValidationResult:
    if isinstance(value, bool) or not isinstance(value, int):
        return ValidationResult(False, ("timeout_seconds must be a positive finite integer",))
    if value <= 0 or not math.isfinite(float(value)):
        return ValidationResult(False, ("timeout_seconds must be a positive finite integer",))
    return ValidationResult(True)


def validate_provider_manifest(manifest: ProviderManifest, *, live_gate: bool) -> ValidationResult:
    errors: list[str] = []
    if manifest.retry_count != 0:
        errors.append("retry_count must be 0")
    if manifest.fallback_state != "disabled":
        errors.append("fallback_state must be disabled")
    if manifest.permission_profile.git_write:
        errors.append("runtime git_write must be false")
    if manifest.permission_profile.settings_change:
        errors.append("settings_change must be false")
    if live_gate:
        errors.extend(validate_timeout(manifest.timeout_seconds).errors)
        if manifest.auth_route != "subscription":
            errors.append("auth_route must be confirmed subscription for live dispatch")
        if manifest.capability_state.value != "CONFIRMED":
            errors.append("capability_state must be CONFIRMED for live dispatch")
        if not manifest.requested_model or not manifest.configured_model:
            errors.append("requested/configured model must be set")
        elif manifest.requested_model != manifest.configured_model:
            errors.append("requested/configured model mismatch")
    return ValidationResult(not errors, tuple(errors))


def validate_post_execution_model(manifest: ProviderManifest) -> ValidationResult:
    errors: list[str] = []
    if manifest.executed_model_verified is not True:
        errors.append("executed model verification is not confirmed")
    if not manifest.executed_model_verification_source:
        errors.append("executed model verification source is missing")
    if not manifest.requested_model or not manifest.configured_model or not manifest.executed_model:
        errors.append("requested/configured/executed model must all be present")
    elif not (manifest.requested_model == manifest.configured_model == manifest.executed_model):
        errors.append("requested/configured/executed model mismatch")
    return ValidationResult(not errors, tuple(errors))


def parse_provider_response(payload: Mapping[str, Any], *, allowed_conclusion_codes: set[str]) -> ProviderResponse:
    required = _PROVIDER_RESPONSE_FIELDS - {"schema_version"}
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")
    unexpected = sorted(set(payload) - _PROVIDER_RESPONSE_FIELDS)
    if unexpected:
        raise ValueError(f"unexpected fields: {', '.join(unexpected)}")

    try:
        answer_state = AnswerState(payload["answer_state"])
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid answer_state") from exc

    conclusion_code = payload["conclusion_code"]
    if not isinstance(conclusion_code, str) or conclusion_code not in allowed_conclusion_codes:
        raise ValueError("invalid conclusion_code")

    safety_warning = payload["safety_warning"]
    if safety_warning not in SAFETY_WARNING_VALUES:
        raise ValueError("invalid safety_warning")

    safety_reason = payload["safety_reason"]
    if safety_reason is not None and not isinstance(safety_reason, str):
        raise ValueError("invalid safety_reason")

    evidence_refs = payload["evidence_refs"]
    if not isinstance(evidence_refs, list) or not all(isinstance(x, str) for x in evidence_refs):
        raise ValueError("invalid evidence_refs")

    marker_echoes = payload["marker_echoes"]
    if not isinstance(marker_echoes, Mapping):
        raise ValueError("invalid marker_echoes")
    if set(marker_echoes) != {"head", "middle", "tail"}:
        raise ValueError("marker_echoes must contain exactly head/middle/tail")
    for key in ("head", "middle", "tail"):
        if marker_echoes[key] is not None and not isinstance(marker_echoes[key], str):
            raise ValueError(f"invalid marker_echoes.{key}")

    answer_text = payload["answer_text"]
    if not isinstance(answer_text, str):
        raise ValueError("invalid answer_text")

    schema_version = payload.get("schema_version", "phase0-response-v1")
    if schema_version != "phase0-response-v1":
        raise ValueError("unsupported schema_version")

    return ProviderResponse(
        schema_version=schema_version,
        answer_state=answer_state,
        conclusion_code=conclusion_code,
        safety_warning=safety_warning,
        safety_reason=safety_reason,
        evidence_refs=tuple(evidence_refs),
        marker_echoes=MarkerEchoes(
            head=marker_echoes["head"],
            middle=marker_echoes["middle"],
            tail=marker_echoes["tail"],
        ),
        answer_text=answer_text,
    )
