# Phase 0 Static Core Known Limitations

Current static/mock implementation intentionally does not resolve these live boundaries:

- real Codex / Claude / agy process lifecycle
- exact provider timeout values
- exact minimum provider permission profiles
- subscription-auth verification per provider
- executed-model verification per provider
- provider-only network restriction feasibility
- agy / Antigravity ACP or custom transport choice
- final secret/PII/private-code detector patterns
- final marker format and completeness policy
- exactly-once external delivery semantics

Additional static limitations:

- JSON Schema files are contract artifacts; runtime validation currently uses deterministic standard-library validators rather than a JSON Schema dependency.
- secret masking/detection is deliberately incomplete and therefore cannot be used alone to authorize a future live fan-out.
- mock execution proves orchestration behavior, not provider/backend behavior.
- a simulated completion is never evidence of real delivery.

All safety-relevant UNKNOWN values remain blocking for live dispatch.
