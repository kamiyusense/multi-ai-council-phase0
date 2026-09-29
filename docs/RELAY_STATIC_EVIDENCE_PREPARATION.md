# Static-to-Live Gap Audit: Evidence Preparation

| gap_id | preparation_status | evidence_refs | observed_static_controls | still_missing | blocker_state |
|--------|--------------------|---------------|--------------------------|---------------|---------------|
| common_timeout | MISSING_STATIC_EVIDENCE | NONE | None | exact finite timeout values that are actually part of the Relay/provider control path | BLOCKED_UNKNOWN |
| common_min_permissions | PARTIAL_STATIC_EVIDENCE | src/providers/policy.py::dangerous_permission_bypass<br>src/providers/preflight.py::for key in ("dangerous_permission_bypass", "hide_claude_auth"): | Policy object tracks `dangerous_permission_bypass` and preflight validation enforces it is False for anthropic. | An exact whole-path minimum permission profile is not proven merely from ProviderPolicy defaults/static preflight. | BLOCKED_UNKNOWN |
| common_sensitive_fanout | MISSING_STATIC_EVIDENCE | NONE | None | explicit secret/PII/private-code fan-out filtering, redaction, sanitization, allowlist/denylist, or payload-boundary controls | BLOCKED_UNKNOWN |

## Findings

**Checked-in static controls observed:**
- Provider policy definitions and static preflight checks track some dangerous configuration bypass flags (e.g. `dangerous_permission_bypass` for Claude).

**Missing static definitions:**
- Explicit and finite timeout configurations for the relay/provider path.
- Explicit secret, PII, or private-code fan-out filtering, redaction, or sanitization controls in the request path.

**Live/runtime proof still required:**
- An exact minimum permission profile for the whole live path, verified across the real end-to-end execution.

**Explicit Assertions:**
- This audit is repository-only and performs zero external/read-only/live evidence acquisition.
- Static evidence preparation != real blocker resolved.
- No provider/model turn is authorized.
- No permission/auth/billing/settings state is changed.
