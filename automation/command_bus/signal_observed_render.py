from typing import Any
from automation.command_bus.signal_observed_jules import map_jules_session_state_to_observed_signal
from automation.command_bus.signal_observed_github import (
    map_result_pr_head_to_observed_state,
    map_exact_head_github_run_to_observed_check,
)
from automation.command_bus.loop_status_issue import replace_managed_block

OBSERVED_START = "<!-- phase0-observed-signal:start -->"
OBSERVED_END = "<!-- phase0-observed-signal:end -->"


def _safe_str(val: Any) -> str:
    """Safely format string without echoing raw multi-line or injection inputs."""
    if val is None:
        return "None"
    s = str(val).strip().replace("\n", " ").replace("\r", " ")
    return s


def observed_human_attention(observed_jules: str, observed_pr: str, observed_ci: str) -> str:
    """Pure observed hint: does a person need to look? NEEDED / NOT_NEEDED / UNKNOWN.

    Derived only from already-mapped observed facts. It is not an authority
    decision and never approves, merges or answers anything.
    """
    # With no result PR, CI is UNKNOWN by construction and carries no signal.
    facts = (observed_jules, observed_pr) if observed_pr == "NO_RESULT_PR" else (observed_jules, observed_pr, observed_ci)
    # A direct observed NEEDS_INPUT/FAIL or exact-head CI FAIL is already
    # enough to require attention; an unrelated UNKNOWN must not suppress it.
    if observed_jules in ("NEEDS_INPUT", "FAIL") or observed_ci == "FAIL":
        return "NEEDED"
    if "UNKNOWN" in facts:
        return "UNKNOWN"
    if observed_jules in ("DISPATCHED", "IN_PROGRESS") or observed_ci == "VERIFYING":
        return "NOT_NEEDED"
    if observed_jules == "SESSION_COMPLETE":
        # Finished work waits for a person's review of the result PR (or its absence).
        return "NEEDED"
    return "UNKNOWN"


def render_observed_signal_section(snapshot: Any) -> str:
    """
    Renders the pure markdown facts for Observed Signal state.
    Requires a dictionary snapshot.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a dict")

    # Extract required fields, ignoring everything else
    jules_state = snapshot.get("jules_session_state")
    pr_head_sha = snapshot.get("result_pr_head")
    workflow_head_sha = snapshot.get("workflow_head_sha")
    workflow_status = snapshot.get("workflow_status")
    workflow_conclusion = snapshot.get("workflow_conclusion")

    # Map raw facts via existing mappers
    observed_jules = map_jules_session_state_to_observed_signal(jules_state)
    observed_pr = map_result_pr_head_to_observed_state(pr_head_sha)
    observed_ci = map_exact_head_github_run_to_observed_check(
        pr_head_sha, workflow_head_sha, workflow_status, workflow_conclusion
    )

    # Do not blindly render CI PASS if PR doesn't exist
    if observed_pr == "NO_RESULT_PR":
        observed_ci = "UNKNOWN"

    if observed_pr == "UNKNOWN":
        observed_ci = "UNKNOWN"

    # Build safe output
    lines = [
        "## 📡 Observed Signal",
        "",
        "**NOTE:** This section displays raw unverified observations. It does NOT prove durable runtime ownership, takeover, or overall success.",
        "",
        f"- **Jules Session**: `{_safe_str(observed_jules)}`",
        f"- **Result PR**: `{_safe_str(observed_pr)}`",
        f"- **Exact-Head CI**: `{_safe_str(observed_ci)}`",
        f"- **Human attention (observed hint)**: `{observed_human_attention(observed_jules, observed_pr, observed_ci)}`",
    ]

    return "\n".join(lines)


def render_observed_signal_body(existing_body: str, snapshot: Any) -> str:
    """
    Idempotently appends or replaces the Observed Signal block in the existing issue body.
    Original verified Runtime and Development blocks remain byte-for-byte preserved.
    """
    section_content = render_observed_signal_section(snapshot)
    if not isinstance(existing_body, str):
        existing_body = ""

    return replace_managed_block(
        existing_body,
        start=OBSERVED_START,
        end=OBSERVED_END,
        content=section_content
    )
