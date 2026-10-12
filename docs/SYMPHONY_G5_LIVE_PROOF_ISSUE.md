# G5 LIVE candidate Issue — prepared, not created

Title: `G5 proof: record one isolated worker observation note`

Required label: `symphony-g5-observation-proof`

Before a separately approved LIVE run, replace `ISSUE_NUMBER`, `PROOF_BRANCH`,
`PROOF_HEAD` and `ARTIFACT_PATH` with freshly read values. Exactly one open
Issue may carry the required label. Use a new non-default proof branch distinct
from PR #320 and a new empty workspace root. Do not reuse the G4 Issue #336.

## Issue body

Repository: `kamiyusense/multi-ai-council-phase0`.
Proof branch: `PROOF_BRANCH` at starting HEAD `PROOF_HEAD`.
Allowed artifact: `ARTIFACT_PATH` (one new Markdown file only).

Task: Read the branch, HEAD and working tree. Write a brief note in the
allowed artifact with the Issue identifier, the observed starting branch and
HEAD, the file you created, and the local verification you performed. Then
inspect the file, `git status --short` and `git diff --check`. Report the exact
result and any uncertainty. If Official Symphony gives you a continuation
turn, use it to verify the same file and report new facts; do not create a
second artifact merely to fill the turn.

Completion criteria: the allowed new file exists, contains the observed facts,
passes the whitespace check, and no other tracked or untracked path changed.
Expected result: one local workspace artifact and a worker report. The file is
not automatically adopted into PR #320 or main.

Allowed mutations: create or edit `ARTIFACT_PATH` inside the isolated proof
workspace only. Read-only Git and status commands are allowed.

Forbidden mutations: commit, push, merge, rebase, force push, reset, clean,
delete, close the Issue, modify PR #320/main, change Billing/Credits/Overages,
API keys, Secrets or permissions, or use a paid provider/API fallback.

Evidence required: starting and ending HEAD, `git status --short`, artifact
content/hash, `git diff --check`, actual turns/continuations, and any observed
retry/backoff/stall. Mark unobserved behavior `NOT_OBSERVED`.

Stop and report without a blind retry if the branch or allowed path differs,
the workspace contains unrelated changes, a paid route appears, a destructive
mutation would be required, or an external write response is ambiguous.
