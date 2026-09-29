"""Post-signature policy gate for the one-off GitHub-hosted OIDC proof.

The input arrives on stdin only from the signature-verifying Node process.
Never call this module with an unverified JWT payload as authority evidence.
It prints only a bounded decision, never claims or token material.
"""
from __future__ import annotations

import json
import os
import sys
import time

from .github_oidc_claims_policy import (
    GitHubOidcExpectedContext,
    evaluate_github_oidc_claims_policy,
)

REPOSITORY = "kamiyusense/multi-ai-council-phase0"
REPOSITORY_ID = "1378815294"
OWNER_ID = "20355232"
BRANCH_REF = "refs/heads/feature/github-oidc-claims-policy-v1"
WORKFLOW_REF = f"{REPOSITORY}/.github/workflows/github-oidc-proof.yml@{BRANCH_REF}"
AUDIENCE = "urn:phase0:github-oidc-proof:kamiyusense/multi-ai-council-phase0"
SUBJECT = (
    "repo:kamiyusense@20355232/"
    "multi-ai-council-phase0@1378815294:ref:"
    "refs/heads/feature/github-oidc-claims-policy-v1"
)


def expected_from_runner(env: dict[str, str]) -> GitHubOidcExpectedContext:
    """Bound runner context to the reviewed repository, workflow and first run."""
    fixed = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_ID": REPOSITORY_ID,
        "GITHUB_REPOSITORY_OWNER_ID": OWNER_ID,
        "GITHUB_REF": BRANCH_REF,
        "GITHUB_REF_TYPE": "branch",
        "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
        "GITHUB_WORKFLOW": "Phase 0 bounded OIDC identity proof",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_RUN_ATTEMPT": "1",
        "RUNNER_ENVIRONMENT": "github-hosted",
    }
    for key, value in fixed.items():
        if env.get(key) != value:
            raise ValueError(f"runner context mismatch: {key}")
    sha = env.get("GITHUB_SHA")
    if sha != env.get("GITHUB_WORKFLOW_SHA"):
        raise ValueError("workflow SHA differs from triggering SHA")
    return GitHubOidcExpectedContext(
        audience=AUDIENCE,
        subject=SUBJECT,
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
        repository_owner_id=OWNER_ID,
        ref=BRANCH_REF,
        sha=sha,
        workflow_ref=WORKFLOW_REF,
        workflow_sha=sha,
        event_name="push",
        run_id=env.get("GITHUB_RUN_ID", ""),
        repository_visibility="private",
        job_workflow_ref=WORKFLOW_REF,
        job_workflow_sha=sha,
    )


def evaluate_verified_claims(claims: dict, env: dict[str, str], *, now_epoch: int) -> bool:
    expected = expected_from_runner(env)
    return evaluate_github_oidc_claims_policy(
        claims, expected, now_epoch=now_epoch,
    ).status == "MATCH"


def diagnose_verified_claims(claims: dict, env: dict[str, str], *, now_epoch: int) -> str:
    """Return only a fixed stage, never raw claims or exception text."""
    try:
        expected = expected_from_runner(env)
    except (ValueError, TypeError, KeyError) as exc:
        reason = str(exc)
        if any(name in reason for name in ("RUN_ID", "RUN_ATTEMPT")):
            return "RUN_ID"
        if any(name in reason for name in ("GITHUB_REF", "GITHUB_SHA", "WORKFLOW_SHA", "triggering SHA")):
            return "REF_SHA"
        if "GITHUB_REPOSITORY" in reason:
            return "REPOSITORY"
        return "WORKFLOW"
    if not isinstance(claims, dict):
        return "ISSUER"
    decision = evaluate_github_oidc_claims_policy(claims, expected, now_epoch=now_epoch)
    if decision.status == "MATCH":
        return "PASS"
    reason = decision.reason
    checks = (
        ("ISSUER", ("iss",), ("OIDC claim mismatch: iss",)),
        ("AUDIENCE", ("aud",), ("OIDC claim mismatch: aud",)),
        ("TIME", ("nbf", "iat", "exp"), ("OIDC temporal", "OIDC nbf", "OIDC token", "OIDC exp")),
        ("REPOSITORY", ("sub", "repository", "repository_id", "repository_owner_id", "repository_visibility"), ()),
        ("WORKFLOW", ("workflow_ref", "job_workflow_ref", "job_workflow_sha"),
         ("unexpected job workflow identity",)),
        ("REF_SHA", ("ref", "sha", "workflow_sha"), ()),
        ("RUN_ID", ("run_id", "run_attempt"), ()),
    )
    for stage, fields, fragments in checks:
        if any(fragment in reason for fragment in fragments):
            return stage
        if any(reason.endswith(": " + field) for field in fields):
            return stage
        if reason.startswith("required OIDC claims are missing: "):
            missing = set(reason.split(": ", 1)[1].split(","))
            if missing.intersection(fields):
                return stage
    return "COMPLETE"



def safe_failure_code(
    stage: str, claims: object, env: dict[str, str], *, now_epoch: int,
) -> str:
    """Expose only the first known mismatch category, never raw values."""
    generic = f"OIDC_{stage}_REJECTED"
    if stage not in {"WORKFLOW", "REF_SHA"}:
        return generic
    try:
        expected = expected_from_runner(env)
    except (ValueError, TypeError, KeyError) as exc:
        reason = str(exc)
        if stage == "WORKFLOW":
            if reason == "runner context mismatch: GITHUB_WORKFLOW_REF":
                return "OIDC_WORKFLOW_RUNNER_REF_REJECTED"
            if reason == "runner context mismatch: GITHUB_WORKFLOW":
                return "OIDC_WORKFLOW_RUNNER_NAME_REJECTED"
        if stage == "REF_SHA" and reason == "workflow SHA differs from triggering SHA":
            return "OIDC_REF_SHA_RUNNER_WORKFLOW_SHA_REJECTED"
        return generic
    if not isinstance(claims, dict):
        return generic
    reason = evaluate_github_oidc_claims_policy(
        claims, expected, now_epoch=now_epoch,
    ).reason
    if stage == "WORKFLOW":
        if reason == "OIDC claim mismatch: workflow_ref":
            return "OIDC_WORKFLOW_CLAIM_REF_REJECTED"
        if reason == "OIDC claim mismatch: job_workflow_ref":
            return "OIDC_WORKFLOW_JOB_REF_CLAIM_REJECTED"
        if reason == "OIDC claim mismatch: job_workflow_sha":
            return "OIDC_WORKFLOW_JOB_SHA_CLAIM_REJECTED"
        if reason.startswith("required OIDC claims are missing: "):
            missing = set(reason.split(": ", 1)[1].split(","))
            if missing.intersection({"job_workflow_ref", "job_workflow_sha"}):
                return "OIDC_WORKFLOW_JOB_IDENTITY_MISSING_REJECTED"
        if reason == "unexpected job workflow identity; explicit ref and sha are required":
            return "OIDC_WORKFLOW_UNEXPECTED_JOB_IDENTITY_REJECTED"
    if stage == "REF_SHA" and reason == "OIDC claim mismatch: workflow_sha":
        return "OIDC_REF_SHA_CLAIM_WORKFLOW_SHA_REJECTED"
    return generic


def main() -> int:
    claims: object = {}
    now_epoch = int(time.time())
    try:
        claims = json.load(sys.stdin)
        stage = diagnose_verified_claims(claims, os.environ, now_epoch=now_epoch)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        stage = "COMPLETE"
    accepted = stage == "PASS"
    code = "NONE" if accepted else safe_failure_code(stage, claims, os.environ, now_epoch=now_epoch)
    sys.stdout.write(json.dumps({
        "status": "PASS" if accepted else "BLOCKED",
        "terminal_stage": "COMPLETE" if accepted else stage,
        "safe_error_code": code,
    }))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
