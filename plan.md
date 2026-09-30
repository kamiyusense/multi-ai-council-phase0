1.  **Create `docs/RELAY_CLAUDE_PERMISSIONS_READONLY_CHECKLIST.md`**:
    *   This document will serve as a PREPARED/static read-only inspection plan for the Anthropic/Claude `claude_permissions` gap.
    *   It will contain the required explicit distinctions between static policy/meta checks and actual runtime execution proof.
    *   It will include the "Current State Table" strictly matching `provider_id=anthropic`, `gap_id=claude_permissions`, and containing the specific fields (`static_policy_bypass_state`, `static_session_meta_state`, `new_session_effective_state`, `load_session_effective_state`, `observed_permission_mode_state`, `bypass_absence_state`, `readonly_inspection_state`, `evidence_provenance_state`, `blocker_state`).
    *   It will state that zero external/read-only permission evidence is acquired and the gap remains `BLOCKED_UNKNOWN`.
    *   It will enumerate the future conceptual read-only evidence fields.
    *   It will declare failure cases (e.g. true/enabled dangerous bypass fails closed).

2.  **Create `tests/relay/test_claude_permissions_readonly_checklist.py`**:
    *   Write a unit test similar to `test_claude_account_auth_readonly_checklist.py` that verifies the structural integrity and semantic requirements of `RELAY_CLAUDE_PERMISSIONS_READONLY_CHECKLIST.md`.
    *   It will assert table contents, exact wording for explicit distinctions, forbidden secrets, fail-closed semantics, conceptual evidence record fields, and that no live evidence is claimed.
    *   It will also test the updates in `docs/RELAY_STATIC_CHECKPOINT.md`.

3.  **Update `docs/RELAY_STATIC_CHECKPOINT.md`**:
    *   Append a section "## Claude Permissions Read-Only Checklist Static Checkpoint" confirming the PREPARED status, that zero external evidence was acquired, and that `claude_permissions` remains unresolved/BLOCKED_UNKNOWN.

4.  **Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done**:
    *   Call `pre_commit_instructions` tool to get instructions on required validations (like formatting, tests, etc.).
    *   Run `PYTHONPATH=src python -m unittest discover -s tests -t . -v`, `python -m compileall -q src tests`, and `git diff --check`.
    *   Verify the changes meet all strict boundaries and do not affect canonical branches or source code.

5.  **Submit the changes**:
    *   Use `submit` with the isolated working branch name (`jules-work/relay-dev-loop-069-claude-permissions-readonly-checklist`).
