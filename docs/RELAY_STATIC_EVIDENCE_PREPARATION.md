# Static-to-Live Gap Audit: Evidence Preparation

This is a **PREPARED/static repository-evidence audit only**. It acquires no
external/read-only/live evidence and does not resolve any real live blocker.

| gap_id | preparation_status | evidence_refs | observed_static_controls | still_missing | blocker_state |
| --- | --- | --- | --- | --- | --- |
| common_timeout | PARTIAL_STATIC_EVIDENCE | src/relay/envelope.py::def validate_timeout(timeout_seconds: Any) -> None:<br>src/relay/envelope.py::timeout_seconds: int \| None = None<br>src/relay/lifecycle.py::timeout_seconds=envelope.timeout_seconds | Relay validates a supplied timeout as a positive non-bool integer or allows None; the static/mock lifecycle forwards the envelope value into the prompt path and handles TimeoutError with cancel/close behavior. | provider-specific exact finite timeout values selected for the real live control path, plus evidence that real provider processes enforce those values | BLOCKED_UNKNOWN |
| common_min_permissions | PARTIAL_STATIC_EVIDENCE | src/providers/policy.py::dangerous_permission_bypass: bool = False<br>src/providers/policy.py::"allowDangerouslySkipPermissions": False<br>src/providers/preflight.py::dangerous_permission_bypass | ProviderPolicy rejects dangerous permission bypass in static safety checks; Claude session metadata pins allowDangerouslySkipPermissions to false; Claude preflight requires dangerous_permission_bypass false. | an exact whole-path minimum permission profile across the real provider/runtime path; these Claude/static controls alone do not establish the complete profile | BLOCKED_UNKNOWN |
| common_sensitive_fanout | MISSING_STATIC_EVIDENCE | NONE | The reviewed Relay payload validator rejects selected control-plane override keys, but that generic override validation is not treated as evidence of secret/PII/private-code filtering, redaction, sanitization, or fan-out policy. | explicit secret/PII/private-code fan-out filtering, redaction, sanitization, or an equivalent validated allowlist/denylist at the real request boundary | BLOCKED_UNKNOWN |

## Findings

### Static controls observed

- `common_timeout`: input shape and forwarding/cancel behavior have useful
  static/mock evidence. This does **not** select a production timeout and does
  not prove real provider enforcement.
- `common_min_permissions`: some dangerous-permission bypass controls are
  fail-closed in ProviderPolicy/Claude preflight. This is not a complete
  minimum-permission profile.
- `common_sensitive_fanout`: the generic Relay payload override validator is
  intentionally **not** counted as secret/PII/private-code filtering evidence.

### Still missing

- exact provider-specific finite timeout values and real enforcement evidence;
- exact minimum permission profile for the whole live path;
- explicit sensitive-data fan-out filtering/redaction/sanitization policy and
  proof at the real request boundary.

## Fixed safety boundary

- This audit is repository-only and performs zero external/read-only/live
  evidence acquisition.
- Static evidence preparation != real blocker resolved.
- Every audited blocker remains `BLOCKED_UNKNOWN`.
- No provider/model turn is authorized.
- No permission/auth/billing/settings state is changed.
- The first real provider/model turn remains separately human-approved.
