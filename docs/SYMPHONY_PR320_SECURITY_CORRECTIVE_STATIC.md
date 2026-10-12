# PR #320 security corrective STATIC result

**SECURITY_CORRECTIVE_STATIC_PASS / CLAUDE_REVIEW_PENDING / MERGE_NO_GO / LIVE_NO_GO**.
Specification: https://github.com/kamiyusense/multi-ai-council-phase0/pull/320#issuecomment-6116132890
Independent review: https://github.com/kamiyusense/multi-ai-council-phase0/pull/320#issuecomment-6116105999

## HIGH-1: operation ownership at atomic create boundary

The independent race was reproduced locally before the implementation: both
intent writers and both campaign checkpoint writers received ACCEPTED for one
identical logical record. All four new red tests failed (including environment
and account negatives). All subprocess/account/model results in these tests
are mocks; no real provider, worker, GitHub create or credential was used.

New records retain the existing V1 protocol with a validated optional extension
`write_claim_version: 1` and a fresh 32-byte `write_claim_nonce`. Nonce creation
is internal, per operation, not a caller writer ID or timestamp. The complete
written bytes, including nonce, must match readback for ACCEPTED. Foreign
content is CONFLICT even after a successful create response. Lost replies are
resolved once within the original invocation, without resend. A process-bound
once-only path fence rejects repeated/concurrent calls and copied/forked writer
objects. Different processes construct fresh stores and fresh operation claims.
The short lock covers only nonce/path reservation, not network I/O or other tasks.
Campaign generation regression is rejected before create.

Atomic create-only backend semantics are a prerequisite. A nonce alone is not
a distributed leader lease, secret capability, or protection against malicious
backend changes/explicit sharing of operation memory. Restart restores existing
evidence, never inherits dispatch permission from a nonce. Existing revision,
intent/checkpoint-before-runner ordering, and stopped/fenced generation recovery
remain necessary. A two-controller fixture records exactly one simulated start.

Old ownerless V1 records stay readable and are never rewritten. New STARTED,
TERMINAL, retired and observation records use the existing predecessor digest
of the actual prior bytes. Campaign `state_digest` continues hashing logical
state, preserving the old chain; claim metadata is compared in exact create
readback, not used as task/result authority. Legacy intent -> new start/terminal
and legacy checkpoint -> new generation tests pass. All 174 old evidence files
are byte-for-byte identical to the starting HEAD.

## MEDIUM-1: parent/worker authority separation

Only the explicit OS/locale/config-directory environment names in
`symphony_subscription_boundary.py` reach the child. PATH, HOME/CODEX_HOME,
Windows system/user directories, temporary directories and locale remain.
GitHub/enterprise tokens, observer MAC key/event path, OIDC selectors, SSH agent,
cloud/other API credentials, unknown equivalent auth names and metered routing
selectors do not enter the model child. Parent environment remains unchanged;
controller helpers can still use their own approved credentials. Case-insensitive
Windows key matching retains known OS keys and catches metered selector aliases.
This does not claim OS filesystem/sandbox credential isolation is LIVE-proven.

## MEDIUM-2: fresh account/config before model dispatch

Both runner prepare and dispatch reject ambient metered selectors and configured
paid fallback. The exact built-in JSONL transport is additionally LIVE-OFF by
default and cannot accept caller-provided account dictionaries as admission.
After initialize, before thread/model dispatch, it obtains same-process fresh
`account/read` with `refreshToken:false` and effective `config/read`. The existing
pure `src/relay/codex_account_readonly.py` parser is loaded at a fixed trusted
source path, avoiding unrelated relay package/provider import side effects.

Only verified CHATGPT_ACCOUNT with requiresOpenaiAuth:true and the default
OpenAI runtime route is compatible. Missing/UNKNOWN/API-key/custom endpoint,
paid tier/fallback, mismatched thread provider, read error or evidence ageing
past 60 seconds before turn/start cannot start a model. Unreadable quota is not
EXHAUSTED: no quota RPC, login/refresh, fallback or retry is added. Account/config
responses stay in memory; those notifications are excluded from saved events;
error evidence uses exception class only. A compatible subscription route is
not LIVE authorization. Tests using a valid route and `live_enabled=True` are
explicitly fake transports, not production login/proof.

The deployed app-server protocol/version and real sandbox behavior remain
NOT_OBSERVED: supported account/config/thread-provider fields are mandatory,
and unsupported/missing fields fail closed. This STATIC batch queried no real
app-server, subscription account or provider. Official protocol reference:
https://github.com/openai/codex/tree/main/codex-rs/app-server

## Validation and descendant impact

Starting #320: `8c53c505a21318c6133da0bef85af18ae3711103`.
Tested main: `bf18c9d92e8b94c574fed6e9c5603758b3c23816`.
Final source code: 220 focused tests PASS; 1,979 full command-bus tests PASS,
1 Windows-only bootstrap/ACL skip. New correction fixture: 20 tests.
Blue mock reconcile, 32-loop bridge and delivery boundary PASS (real calls0).
AST, compileall, YAML parse and diff check PASS. The unchanged G5 observer
patch (SHA-256 `404b4001d279351c8b800816142862ee47dfd209615b0f9211fbe6ccc5170f3b`)
passes git apply --check against clean archived official pin
`be10a1b79df723d6d7612b5651c8522704dafb2e`; no patch applied upstream.
No scheduler, continuation, retry/backoff, stall recovery, concurrency policy
or workspace lifecycle behavior was changed.

Virtual source trees (before final Protocol annotation alignment/evidence-only
files) were constructed with merge-tree and isolated three-way indices, without
merge commits/remote refs. Full suites:

| Virtual configuration | Exact tested tree | Tests | Result |
|---|---|---:|---|
| main + corrected320 | 17a9a2d5b572268febdb6359c664cdb61b2af12e | 2,606 | PASS/skip1 |
| previous + unchanged343 | b47864f642bd04dab09bcd8304bf9c88fd97bee1 | 2,847 | PASS/skip1 |
| previous + unchanged364 | 7b5e9caf97093d1479b10be51e9b17c1eba71729 | 2,861 | PASS/skip1 |

The only subsequent source adjustment declared the already-tested optional
live_enabled parameter in AppServer Protocol; concrete transport/test bodies
were unchanged. Focused/full tests on final #320 source passed afterward.
Downstream historical validators passed (51/101 historical +21 current operator
files) using read-only Git history. Their immutable source manifests are not
resealed. These local runs do not update actual #343/#364 heads or prove new
exact-head child CI. Actual child heads remain 794488c3 and215d962d. Approved
future parent synchronization and fresh child CI/review are still required;
no rebase, retarget, merge or write to those branches occurred. Final remote
HEAD, CI runs/artifacts/digests and source readback are recorded in a new PR320
comment after the ordinary FF push. They are not self-referenced in this commit.

## Remaining boundaries

Claude independent re-review of the six source/test paths is pending. HIGH-1
needs review of nonce/fence + atomic backend assumptions; MEDIUM-1/2 need review
of the allowlist and exact-session fail-closed route before any LIVE wiring.
Rules/protection API GET403 remains UNKNOWN. LOW items from the original review
are outside this targeted correction; executable trust/default-branch identity
and effective OS/network/filesystem boundaries still require independent review.
Merge, installation activation, LIVE, OIDC, actual adoption, Git Database POST,
updateRefs, staging refs, Secrets/settings/permissions/billing changes are all0.

Changed source/docs/evidence + raw/decompressed test logs secret scan: PASS (exit0),
29 files, fixed gitleaks image, no ignore/baseline changes or network.
Log SHA-256 `e4ca78e279920a7c055988a3ffba353f462add8a1638e738c0c5f2129b3162bd`. Unchanged historical evidence is separately
verified against all 174 original Git blob bytes.
