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
    )


def evaluate_verified_claims(claims: dict, env: dict[str, str], *, now_epoch: int) -> bool:
    expected = expected_from_runner(env)
    return evaluate_github_oidc_claims_policy(
        claims, expected, now_epoch=now_epoch,
    ).status == "MATCH"


def main() -> int:
    try:
        claims = json.load(sys.stdin)
        accepted = evaluate_verified_claims(claims, os.environ, now_epoch=int(time.time()))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        accepted = False
    sys.stdout.write(json.dumps({"status": "PASS" if accepted else "BLOCKED"}))
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
