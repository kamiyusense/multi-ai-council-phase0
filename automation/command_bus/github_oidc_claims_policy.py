"""Pure GitHub Actions OIDC claims policy.

This module is NOT a JWT verifier and does not request OIDC tokens.

It is intended to run only after a future cryptographic layer has already
verified the token signature against GitHub's OIDC issuer keys. It then applies
the repository's exact-context policy to the verified claims.

The function returns a policy decision only. It never returns provider or owner
authority proof and never writes GitHub state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_ISSUER = "https://token.actions.githubusercontent.com"
_SHA40 = "0123456789abcdef"


@dataclass(frozen=True)
class GitHubOidcExpectedContext:
    audience: str
    subject: str
    repository: str
    repository_id: str
    repository_owner_id: str
    ref: str
    sha: str
    workflow_ref: str
    workflow_sha: str
    event_name: str
    run_id: str
    repository_visibility: str
    job_workflow_ref: str | None = None


@dataclass(frozen=True)
class GitHubOidcClaimsPolicyDecision:
    status: str
    reason: str


def evaluate_github_oidc_claims_policy(
    claims: dict[str, Any],
    expected: GitHubOidcExpectedContext,
    *,
    now_epoch: int,
) -> GitHubOidcClaimsPolicyDecision:
    """Apply exact context checks to already-signature-verified claims.

    This function deliberately does not parse or verify a JWT. A caller-supplied
    claims dict is not trustworthy merely because this policy returns MATCH.
    """
    try:
        if not isinstance(claims, dict):
            raise ValueError("claims must be an object")
        if not isinstance(expected, GitHubOidcExpectedContext):
            raise ValueError("expected OIDC context is required")
        if isinstance(now_epoch, bool) or not isinstance(now_epoch, int) or now_epoch < 0:
            raise ValueError("now_epoch must be a non-negative integer")

        _validate_expected(expected)

        exact = {
            "iss": _ISSUER,
            "aud": expected.audience,
            "sub": expected.subject,
            "repository": expected.repository,
            "repository_id": expected.repository_id,
            "repository_owner_id": expected.repository_owner_id,
            "ref": expected.ref,
            "sha": expected.sha,
            "workflow_ref": expected.workflow_ref,
            "workflow_sha": expected.workflow_sha,
            "event_name": expected.event_name,
            "run_id": expected.run_id,
            "run_attempt": "1",
            "runner_environment": "github-hosted",
            "repository_visibility": expected.repository_visibility,
        }
        if expected.job_workflow_ref is not None:
            exact["job_workflow_ref"] = expected.job_workflow_ref

        missing = [key for key in exact if key not in claims]
        if missing:
            raise ValueError(
                "required OIDC claims are missing: " + ",".join(sorted(missing))
            )

        for key, value in exact.items():
            if claims.get(key) != value:
                raise ValueError(f"OIDC claim mismatch: {key}")

        if expected.job_workflow_ref is None and "job_workflow_ref" in claims:
            raise ValueError(
                "unexpected job_workflow_ref; explicit job_workflow_ref is required"
            )

        for field in ("nbf", "iat", "exp"):
            value = claims.get(field)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"OIDC temporal claim must be an integer: {field}")

        nbf = claims["nbf"]
        iat = claims["iat"]
        exp = claims["exp"]
        if nbf > iat:
            raise ValueError("OIDC nbf must not follow iat")
        if iat > now_epoch:
            raise ValueError("OIDC token was issued in the future")
        if now_epoch < nbf:
            raise ValueError("OIDC token is not valid yet")
        if now_epoch >= exp:
            raise ValueError("OIDC token is expired")
        if exp <= iat:
            raise ValueError("OIDC exp must follow iat")

        jti = claims.get("jti")
        if not isinstance(jti, str) or not jti or len(jti) > 256:
            raise ValueError("OIDC jti is missing or invalid")

        return GitHubOidcClaimsPolicyDecision(
            "MATCH",
            "verified claims match the exact approved workflow context",
        )
    except (ValueError, TypeError, KeyError) as exc:
        return GitHubOidcClaimsPolicyDecision("BLOCKED", str(exc))


def _validate_expected(expected: GitHubOidcExpectedContext) -> None:
    for field in (
        "audience",
        "subject",
        "repository",
        "repository_id",
        "repository_owner_id",
        "ref",
        "workflow_ref",
        "event_name",
        "run_id",
        "repository_visibility",
    ):
        value = getattr(expected, field)
        if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
            raise ValueError(f"expected OIDC context field is invalid: {field}")

    if expected.repository.count("/") != 1:
        raise ValueError("expected repository must be owner/name")
    if not expected.repository_id.isdigit():
        raise ValueError("expected repository_id must be numeric")
    if not expected.repository_owner_id.isdigit():
        raise ValueError("expected repository_owner_id must be numeric")
    if not expected.run_id.isdigit():
        raise ValueError("expected run_id must be numeric")
    if expected.repository_visibility not in {"public", "private", "internal"}:
        raise ValueError("unexpected repository visibility policy")

    for field in ("sha", "workflow_sha"):
        value = getattr(expected, field)
        if (
            len(value) != 40
            or any(ch not in _SHA40 for ch in value)
        ):
            raise ValueError(f"expected {field} must be a lowercase full SHA")

    if expected.job_workflow_ref is not None:
        value = expected.job_workflow_ref
        if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
            raise ValueError("expected job_workflow_ref is invalid")
