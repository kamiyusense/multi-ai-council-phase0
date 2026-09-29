from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class FanoutDecision(StrEnum):
    PASS = "PASS"
    BLOCK = "BLOCK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FanoutAssessment:
    decision: FanoutDecision
    reasons: tuple[str, ...]


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("github_token", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


class FanoutGate:
    """Small deterministic fail-closed gate.

    This is intentionally conservative and does not claim comprehensive secret/PII
    detection. UNKNOWN remains a blocking result for later live dispatch.
    """

    def evaluate(
        self,
        text: str,
        *,
        externally_shareable: bool | None,
        contains_private_code: bool | None,
    ) -> FanoutAssessment:
        reasons: list[str] = []
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                reasons.append(f"secret-pattern:{name}")
        if _EMAIL.search(text):
            reasons.append("pii-pattern:email")
        if contains_private_code is True:
            reasons.append("private-code:present")
        if reasons:
            return FanoutAssessment(FanoutDecision.BLOCK, tuple(reasons))
        if externally_shareable is not True or contains_private_code is None:
            return FanoutAssessment(
                FanoutDecision.UNKNOWN,
                ("external-sendability-or-private-code-status-unconfirmed",),
            )
        return FanoutAssessment(FanoutDecision.PASS, ())
