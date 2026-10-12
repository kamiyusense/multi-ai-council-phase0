# G7 STATIC reuse checkpoint (optional after G6.3)

No scheduler/kernel/store implementation was added or changed. A new fixture
reuses `StaticAutonomousCampaignController`, its attempt reconciliation and
create-only campaign store. Actual run: **37 completed rounds**, **38 unique mock
worker starts**, multiple fresh controller sessions, zero new real model/provider
starts or GitHub writes. One hard UNKNOWN task remains isolated while 35
independent tasks finish; failure creates a corrective task and completes its
parent. A final restart dispatches nothing. Machine evidence:
`docs/evidence/symphony-g63-static/g7-soak.json`.

Three new tests verify this soak, EXHAUSTED versus telemetry UNKNOWN, and stale
HEAD task-local replanning followed by independent task continuation. Existing
attempt recovery/duplicate tests remain in the full regression suite. Mock DONE
is mock evidence only: no G5 terminal, proof artifact or actual Git result is
adopted. This does not establish production multi-task unattended LIVE readiness.

Next: separately qualified production receipt/result seam into the existing
controller, then independently approved bounded Local proof; only afterwards
an approved multi-task campaign. Original Symphony owns production scheduling,
worker continuation/retry/backoff/stall/concurrency/workspace cleanup.
Safety protects continuation.
