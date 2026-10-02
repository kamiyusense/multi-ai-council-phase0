"""Machine-checkable SF-8 readiness gates (pure; reads nothing, writes nothing).

The full DURABLE assessment remains a post-adoption verification gate: READY
requires every required check to pass, and every runtime-state check must carry
LIVE evidence. The separate pre-adoption gate can only reach
READY_FOR_HUMAN_APPROVAL; it never authorizes a registry write and deliberately
defers the two checks that can only become true after adoption
(stable_identity and registration_ready).

A STATIC fixture/mock pass never counts as LIVE unless the check is explicitly
listed in STATIC_ALLOWED. These helpers only produce reports: they do not
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
POST_ADOPTION_CHECKS = ("stable_identity", "registration_ready")
PRE_ADOPTION_CHECKS = tuple(
    name for name in REQUIRED_CHECKS if name not in POST_ADOPTION_CHECKS
)
STATIC_ALLOWED = frozenset({"negative_stale_mismatch_tests", "recovery_test"})
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@#-]{0,191}$")


@dataclass(frozen=True)
class CheckResult:
    status: str
    scope: str
    evidence_ref: str


@dataclass(frozen=True)
class PromotionCandidateAssessment:
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PreAdoptionAssessment:
    status: str
    reasons: tuple[str, ...]
    deferred_checks: tuple[str, ...] = POST_ADOPTION_CHECKS
    human_approval_required: bool = True
    registry_write_allowed: bool = False


def _assessment_reasons(
    checks: Mapping[str, CheckResult],
    required_names: tuple[str, ...],
) -> tuple[str, ...]:
    if not isinstance(checks, Mapping):
        return ("checks must be a mapping",)
    reasons: list[str] = []
    for name in checks:
        if name not in REQUIRED_CHECKS:
            reasons.append(f"{name}: unknown check")
    for name in required_names:
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
    return tuple(reasons)


def assess_durable_promotion_candidate(
    checks: Mapping[str, CheckResult],
) -> PromotionCandidateAssessment:
    """Strict post-adoption/full verification gate."""
    reasons = _assessment_reasons(checks, REQUIRED_CHECKS)
    return PromotionCandidateAssessment("NOT_READY" if reasons else "READY", reasons)


def assess_pre_adoption_readiness(
    checks: Mapping[str, CheckResult],
) -> PreAdoptionAssessment:
    """Technical pre-adoption gate; never authorizes a registry write."""
    reasons = _assessment_reasons(checks, PRE_ADOPTION_CHECKS)
    return PreAdoptionAssessment(
        "NOT_READY" if reasons else "READY_FOR_HUMAN_APPROVAL",
        reasons,
    )


def issue33_migration_ready(preflight_status: str) -> str:
    """Map an existing control-tower live-preflight status to YES / NO / UNKNOWN."""
    if preflight_status == "READY":
        return "YES"
    if preflight_status in {"NOT_WIRED", "BLOCKED"}:
        return "NO"
    return "UNKNOWN"
