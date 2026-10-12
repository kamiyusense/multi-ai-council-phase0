# G5.1 Local LIVE — fresh single-run plan (NOT EXECUTED)

Status: PREPARED ONLY. Separate explicit approval is required for one new LIVE.
This G5.1 STATIC batch has LIVE/provider/model/AppServer starts = 0. It grants
no G6 adoption, task-success/campaign-COMPLETE authority or extra model launch.
Do not reuse G4 #336, G5 #341, their campaigns, branches or proof workspaces.

1. Fresh-read PR #320 exact HEAD/Draft state, main, both exact-head CI workflows,
   the G5.1 STATIC final checkpoint, label `symphony-g5-observation-proof`,
   consumed Issues and absence of a new campaign collision. Preserve fresh refs.
   Check WSL Ubuntu, git/gh/python/Codex ChatGPT login, pinned upstream clean
   tree, existing processes/worktrees and port conflicts. Confirm G5.1 patch.
2. Before any new worker, inspect selector-name presence only: no OPENAI_API_KEY,
   CODEX_API_KEY, AZURE_OPENAI_API_KEY, OPENAI_BASE_URL or OPENAI_API_BASE route;
   no paid/custom/metered fallback/credits/overage. Unreadable quota is UNKNOWN,
   not EXHAUSTED. Paid-route possibility blocks launch. Never change keys,
   Secrets, permissions, Billing, login or provider/model settings as fallback.
3. Read current `SYMPHONY_G5_LIVE_PROOF_ISSUE.md` and create exactly one new proof
   Issue with the required label under that separate approval. Record/read back
   number, exact body, label and OPEN state. Ambiguous create: read back only.
4. Create a fresh non-default proof branch at fresh current main, separate from
   PR #320/main/G4; preserve starting HEAD. Prepare an empty isolated workspace
   root. Worker may create only the approved artifact: no commit/push/merge,
   Issue close or main mutation. No automatic Git result adoption.
5. Fresh-read separate ledger branch `codex/symphony-g5-proof-ledger`; preserve
   existing create-only records and check new campaign/task/generation identity.
   Bind exactly one new Issue, expected proof HEAD, runner generation and allowed
   artifact path per current bridge config. No second scheduler/dispatch gate.
6. Generate >=32 random key bytes locally. Keep key/event JSONL outside model
   workspace in private parent directory (0700), regular event/key files (0600).
   Never log/display/commit the key or pass it to Codex. Parent helper and observer
   only share it. The Codex child wrapper removes all nine selectors:
   SYMPHONY_G5_OBSERVER_KEY_HEX, SYMPHONY_G5_OBSERVER_EVENTS, GITHUB_TOKEN, GH_TOKEN,
   OPENAI_API_KEY, CODEX_API_KEY, AZURE_OPENAI_API_KEY, OPENAI_BASE_URL,
   OPENAI_API_BASE. Verify names only, never values. Pre-create the event file.
7. On a clean checkout of openai/symphony at
   `be10a1b79df723d6d7612b5651c8522704dafb2e`, first `git apply --check`, then apply
   the fresh PR patch. Verify only the three observation files differ. Do not
   commit/push upstream. Do not change its lifecycle/scheduler/continuation code.
8. Start observer sidecar first, verify config/event readiness, then launch
   Official Symphony exactly once. Let its normal tracker select the new Issue.
   Keep internal continuation/retry/backoff/stall/concurrency authority intact;
   new LIVE launch retry=0. Do not artificially trigger retries or stalls.
9. Read back real signed STARTED/MAC acceptance, durable INTENT/STARTED, Issue,
   lifetime run ID/workspace fingerprint/expected HEAD. Missing observation does
   not justify an immediate worker kill/relaunch. Observe and preserve failure.
10. Let Codex work normally. Preserve allowed artifact content/hash, starting and
    ending HEAD, full git status, diff check and unrelated mutation count before
    closing. Only verified completion permits operator Issue close under the
    separate approval. Read back closure; ambiguous close is readback-only.
11. Wait for actual Orchestrator lifecycle observation: natural DOWN may say
    WORKER_COMPLETED; tracker terminal explicit stop must say WORKER_STOPPED.
    Both are conservative UNKNOWN/RECOVERABLE_UNKNOWN in the ledger. Read exact
    signed terminal, matching lifetime/workspace and create-only durable record.
    Wait for the asynchronous writer/sidecar to finish before parent cleanup.
    No unsigned process/Issue state substitute, task DONE or G6 connection.
12. After real terminal readback, start no more model work. Restart only the
    observer once against the same event file. Verify both STARTED and TERMINAL
    are NOOP_DUPLICATE, ledger/event hashes unchanged, additional worker/model
    dispatch = 0. Never restart Symphony for this replay.
13. Preserve logs/observations/hashes/replay/workspace verification. Stop and
    verify relevant Symphony/AppServer/observer processes and ports; read back
    new Issue, proof/ledger/PR/main refs and workspace changes. No destructive
    Git cleanup. Normal upstream cleanup semantics stay intact.
14. Save sanitized results with normal commits/fast-forward push only to PR #320,
    tests and exact-head Symphony/Blue CI. PASS requires real signed/durable start
    and terminal plus both duplicate replays and all mutation/route boundaries.
    No terminal: FAIL/STARTED_UNRESOLVED; ambiguity: UNKNOWN. Preserve the result,
    no second LIVE. Naturally absent retry/backoff/stall is NOT_OBSERVED.

Stop before step 3/any execution until a new single-run Local LIVE authorization.
This document is a plan, not a submitted task or consumed authorization.
G6 remains separately gated: durable result -> fresh canonical HEAD validation
-> safe, explicitly authorized Git result adoption. No G6 LIVE here.
