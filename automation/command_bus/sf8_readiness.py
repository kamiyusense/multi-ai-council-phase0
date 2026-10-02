"""Machine-checkable SF-8 readiness gates (pure; reads nothing, writes nothing).

DURABLE promotion candidate is READY only when every required check passed and
every check that concerns real runtime state passed with LIVE evidence. A STATIC
fixture/mock pass never counts as LIVE. This only produces a report: it does not
promote the registry, publish runtime state, or touch Issue #33.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

REQUIRED_CHECKS = (
    "stable_identity",
    "prepared_persistence",
    "canonical_receipt",
    "provider_authentication",
    "owner_authority_authentication",
    "publisher_accepted",
    "collector_readback",
    "registration_ready",
    "negative_stale_mismatch_tests",
    "recovery_test",
)
# Test-shaped checks may be satisfied statically; all others concern real state.
STATIC_ALLOWED = frozenset({"negative_stale_mismatch_tests", "recovery_test"})
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@#-]{0,191}$")


@dataclass(frozen=True)
class CheckResult:
    status: str  # PASS | FAIL | UNKNOWN | NOT_RUN | BLOCKED
    scope: str  # STATIC | LIVE
    evidence_ref: str


@dataclass(frozen=True)
class PromotionCandidateAssessment:
    status: str  # READY | NOT_READY
    reasons: tuple[str, ...]


def assess_durable_promotion_candidate(checks: Mapping[str, CheckResult]) -> PromotionCandidateAssessment:
    reasons: list[str] = []
    if not isinstance(checks, Mapping):
        return PromotionCandidateAssessment("NOT_READY", ("checks must be a mapping",))
    for name in checks:
        if name not in REQUIRED_CHECKS:
            reasons.append(f"{name}: unknown check")
    for name in REQUIRED_CHECKS:
        result = checks.get(name)
        if not isinstance(result, CheckResult):
            reasons.append(f"{name}: missing")
            continue
        if result.status != "PASS":
            reasons.append(f"{name}: {result.status}")
            continue
        if not isinstance(result.evidence_ref, str) or not _REF.fullmatch(result.evidence_ref):
            reasons.append(f"{name}: evidence reference missing or unsafe")
        elif result.scope not in {"STATIC", "LIVE"}:
            reasons.append(f"{name}: invalid scope")
        elif result.scope != "LIVE" and name not in STATIC_ALLOWED:
            reasons.append(f"{name}: STATIC pass is not LIVE evidence")
    return PromotionCandidateAssessment("NOT_READY" if reasons else "READY", tuple(reasons))


def issue33_migration_ready(preflight_status: str) -> str:
    """Map an existing control-tower live-preflight status to YES / NO / UNKNOWN."""
    if preflight_status == "READY":
        return "YES"
    if preflight_status in {"NOT_WIRED", "BLOCKED"}:
        return "NO"
    return "UNKNOWN"
