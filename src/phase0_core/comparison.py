from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from .models import ProviderResponse


class MatchState(StrEnum):
    EXACT = "EXACT"
    DIFFERENT = "DIFFERENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    conclusion_match_state: MatchState
    evidence_match_state: MatchState
    agreement_count: int
    participant_count: int
    agreement_code: str | None
    safety_block: bool
    human_required: bool
    formal_consensus: bool = False


def _match_state(values: list[object]) -> MatchState:
    if not values:
        return MatchState.UNKNOWN
    if len(values) == 1:
        return MatchState.UNKNOWN
    return MatchState.EXACT if all(value == values[0] for value in values[1:]) else MatchState.DIFFERENT


def compare_responses(responses: dict[str, ProviderResponse]) -> ComparisonResult:
    if not responses:
        return ComparisonResult(
            conclusion_match_state=MatchState.UNKNOWN,
            evidence_match_state=MatchState.UNKNOWN,
            agreement_count=0,
            participant_count=0,
            agreement_code=None,
            safety_block=False,
            human_required=True,
        )

    safety_block = any(response.safety_warning in {"PRESENT", "UNKNOWN"} for response in responses.values())
    codes = [response.conclusion_code for response in responses.values()]
    evidence = [response.evidence_refs for response in responses.values()]
    counts = Counter(codes)
    agreement_code, agreement_count = counts.most_common(1)[0]

    return ComparisonResult(
        conclusion_match_state=_match_state(codes),
        evidence_match_state=_match_state(evidence),
        agreement_count=agreement_count,
        participant_count=len(responses),
        agreement_code=agreement_code,
        safety_block=safety_block,
        human_required=True,
        formal_consensus=False,
    )
