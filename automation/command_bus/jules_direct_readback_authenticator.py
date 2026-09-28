"""Direct-readback authenticator for Jules provider verification sources.

This module performs no network I/O itself. Production callers must inject:
- a JulesSessionReader that performs an authenticated fresh Jules GET Session;
- a TargetReader that performs a fresh GitHub PR readback;
- a Clock.

The authenticator never trusts verification_state by itself. It independently
re-reads provider and target state, validates exact bindings, and only then
returns VerifiedSourceAttestation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from .runtime_verifier_sources import (
    VerifiedSourceAttestation,
    validate_provider_verification_source,
)

_RUNNING_JULES_STATES = {"QUEUED", "PLANNING", "IN_PROGRESS"}


class JulesSessionReader(Protocol):
    def read_session(self, session_id: str) -> dict[str, Any] | None: ...


class JulesTargetReader(Protocol):
    def read_target(self, repository: str, pr_number: int) -> dict[str, Any] | None: ...


class JulesAuthenticatorClock(Protocol):
    def now(self) -> str: ...


class JulesDirectReadbackAuthenticator:
    """Authenticate a normalized Jules provider source by direct fresh readback."""

    def __init__(
        self,
        *,
        session_reader: JulesSessionReader | None,
        target_reader: JulesTargetReader | None,
        clock: JulesAuthenticatorClock | None,
    ):
        self.session_reader = session_reader
        self.target_reader = target_reader
        self.clock = clock

    def authenticate(
        self,
        source: dict[str, Any],
        *,
        expected: dict[str, Any],
    ) -> VerifiedSourceAttestation | None:
        try:
            validate_provider_verification_source(source)
            if (
                self.session_reader is None
                or self.target_reader is None
                or self.clock is None
            ):
                return None
            if source.get("verification_state") != "VERIFIED":
                return None
            if not isinstance(expected, dict):
                return None
            for key, value in expected.items():
                if source.get(key) != value:
                    return None

            source_ref = source["source_ref"]
            prefix = "jules-session:"
            if not isinstance(source_ref, str) or not source_ref.startswith(prefix):
                return None
            session_id = source_ref[len(prefix):]
            if not session_id or "/" in session_id:
                return None

            now = _time(self.clock.now())
            observed = _time(source["observed_at"])
            expires = _time(source["expires_at"])
            if now < observed or now >= expires:
                return None

            session = self.session_reader.read_session(session_id)
            if not isinstance(session, dict):
                return None
            if session.get("name") != f"sessions/{session_id}":
                return None
            if "id" in session and session.get("id") != session_id:
                return None
            if session.get("createTime") != source["observed_at"]:
                return None

            state = session.get("state")
            if source["provider_state"] == "RUNNING":
                if state not in _RUNNING_JULES_STATES:
                    return None
            else:
                return None

            source_context = session.get("sourceContext")
            if not isinstance(source_context, dict):
                return None
            provider_source = source_context.get("source")
            expected_provider_source = f"sources/github/{source['expected_repo']}"
            if provider_source != expected_provider_source:
                return None
            github_context = source_context.get("githubRepoContext")
            if not isinstance(github_context, dict):
                return None
            starting_branch = github_context.get("startingBranch")
            if not isinstance(starting_branch, str) or not starting_branch:
                return None

            target = self.target_reader.read_target(
                source["expected_repo"],
                source["expected_pr"],
            )
            normalized = _normalize_target(target)
            if normalized is None:
                return None
            if normalized["repo"] != source["expected_repo"]:
                return None
            if normalized["pr"] != source["expected_pr"]:
                return None
            if normalized["head"] != source["expected_target_head"]:
                return None
            if normalized["branch"] != starting_branch:
                return None
            if normalized["state"] != "open" or normalized["merged"] is not False:
                return None

            required_proofs = {
                source_ref,
                f"github-pr:{source['expected_pr']}",
                f"github-head:{source['expected_target_head']}",
            }
            if not required_proofs.issubset(set(source["proof_refs"])):
                return None

            return VerifiedSourceAttestation(
                source["verification_kind"],
                source["source_id"],
                source["source_ref"],
                source["observed_at"],
            )
        except (KeyError, TypeError, ValueError):
            return None


def _normalize_target(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    repo_value = raw.get("repo", raw.get("repository"))
    if isinstance(repo_value, dict):
        repo = repo_value.get("full_name")
    else:
        repo = repo_value

    head_value = raw.get("head")
    if isinstance(head_value, dict):
        head = head_value.get("sha")
        branch = head_value.get("ref")
    else:
        head = head_value
        branch = raw.get("branch")

    pr = raw.get("pr", raw.get("pr_number", raw.get("number")))
    state = raw.get("state")
    merged = raw.get("merged")
    if (
        not isinstance(repo, str)
        or isinstance(pr, bool)
        or not isinstance(pr, int)
        or not isinstance(head, str)
        or not isinstance(branch, str)
        or not isinstance(state, str)
        or not isinstance(merged, bool)
    ):
        return None
    return {
        "repo": repo,
        "pr": pr,
        "head": head,
        "branch": branch,
        "state": state,
        "merged": merged,
    }


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed
