# Jules result PR cleanup manifest (2026-10-02)

Read-only inventory. **Nothing was closed, merged or deleted.** A human may use it
to clean up in one pass. Classification is by blob comparison of each PR's own
diff (PR base..head) against the current branches; re-run before acting.

Reference heads: carrier `7c83ae9`, main `9f3e0f6`, Relay #4 `f6072c1`, #217 `a3e3c2e`,
#220 `044389e`, signal-observed-v1 `900ab2c` (includes the merged #234). Classification below was made against the earlier #217 `568a30d`; the files named for #217 should be re-checked before closing anything.

Classes: A adopted as-is · B contained identically elsewhere · C superseded by a modified version · D useful, not yet adopted · E not adopted · F UNKNOWN.

| PR | head | class | replaced / carried by | note |
|---|---|---|---|---|
| #200 BWJ-1 pure wake identity and event classifier | `e7d7f09` | B | #203 / #217 (identical 2/2 in #203) | BWJ-1 classifier |
| #202 feat: Add minimal Jules Session state to Observed Signal sta | `439ac1d` | B | feature/signal-observed-v1, #234 (identical 2/2) | Observed Signal Jules state |
| #204 feat(signal): add pure github workflow run to observed check | `94e7a46` | C | feature/signal-observed-v1 `signal_observed_github.py` (same files, different content) | completeness of supersession UNKNOWN: Signal Reviewer must confirm before closing |
| #205 feat(signal): exact PR-head to workflow check identity bindi | `005f014` | C | feature/signal-observed-v1 (same files, different content) | same as #204 |
| #206 Add exact-head binding for GitHub workflow run observation | `ef6174b` | C | feature/signal-observed-v1 (same files, different content) | same as #204 |
| #207 Implement BWJ-2 Blue Cloud Work wake prepare adapter | `26f6312` | B | #203 (identical 2/2); #217 modified 1 of 2 | BWJ-2 |
| #208 feat(automation): Add minimal pure mapper for observed PR he | `dc72514` | B | feature/signal-observed-v1, #234 (identical 2/2) | observed PR-head mapper |
| #209 test: implement mock static integration test for BWJ-3 webho | `66d3665` | B | #203 / #217 (identical) | BWJ-3 static round trip |
| #210 feat(relay): add isolated acp v1 initialize wire primitive | `2d5d66e` | C | Relay #4 (same files, reworked) | ACP initialize wire |
| #211 Loop 109: Implement acp_open_session_wire for ACP session/ne | `0d17bc5` | C | Relay #4 (same files, reworked) | ACP session/new wire |
| #213 Loop 111: Implement local fake ACP prompt wire | `8dd4583` | C | Relay #4 (same files, reworked) | ACP prompt local fake wire |
| #214 feat: implement static Observed Signal display renderer | `20edfeb` | C | feature/signal-observed-v1 (2 of 3 files identical; renderer reworked in #234) | observed renderer |
| #215 feat: add pure decision helper for same-session feedback eli | `cd5781f` | B | feature/signal-observed-v1 / #234 (2 of 3 identical; 3rd is a shared nav file) | feedback decision helper |
| #216 Bind official Claude ACP executable name to static provider  | `e999b56` | B | Relay #4 (identical 4/4) | Claude ACP binary binding |
| #218 feat(relay): Implement bounded fake ACP agent_message_chunk  | `ab922dc` | C | Relay #4 (same files, reworked) | fake ACP agent_message_chunk |
| #219 Add pure preparation seam for same-session feedback message  | `0f38ba8` | B | feature/signal-observed-v1 / #234 (2 of 3 identical; 3rd is a shared nav file) | feedback request prep |
| #221 Extend mock ACP text update wire primitive to handle bounded | `fc20f67` | C | Relay #4 (same files, reworked) | bounded text chunks |
| #222 test: Add static E2E success fixture for Observed Signal | `1ba5a5c` | B | feature/signal-observed-v1 (identical 2/2) | observed static E2E fixture |
| #223 feat: pure MOCK-only conversion of local-fake ACP text to ph | `db6348b` | C | Relay #4 (1 of 2 identical) | ACP→phase0 mapper |
| #224 Add end-to-end ACP mock test to pure classify regression tes | `f6072c1` | B | Relay #4 (identical) | ACP mock E2E |
| #225 Verify static E2E adoption of CanonicalOwnerReceiptGitHubBac | `edb7620` | B | feature/signal-observed-v1 / #234 (identical) | receipt reuse verification |
| #226 fix: safely format jules readback output without backtick ex | `6eeea69` | D | adopted into the reconciliation candidate (this PR); carrier still lacks it | workflow fix; ACCEPT, see contract doc §4 |
| #227 feat(command_bus): Implement bounded Jules Session GET reade | `b4c5608` | C | #217 (repaired Loop125 reader) and #234 (`jules_session_api_reader`) | reader duplicated three ways; #234 chosen by Signal, #217 by Blue; do not merge #227 |
| #228 Add mock tests for RelayCoreAdapter lifecycle | `199739d` | C | Relay #4 (same file, reworked) | Relay core lifecycle mock |
| #229 tests: Quarantine historical malformed claim records by exac | `54a4e85` | D | not on carrier; included in the evidence stack only | test-only quarantine; ACCEPT, see contract doc §4. Land on carrier |
| #230 Add Claude AUTO live proof note | `fc2ad82` | B | #220 (identical) | Loop 128 proof note |
| #231 feat: Add summarize_budget_slots to budget summary | `de325fc` | E | #232 supersedes (rejected for TypeError leak) | Loop 129; keep as evidence of the FAIL_MAJOR inspection |
| #232 Add pure helper summarize_budget_slots with unit tests | `2eb310c` | B | #220 (identical 2/2) | Loop 130 corrective, accepted |
| #233 docs: add Claude AUTO loop operator quickstart | `53f2caf` | B | #220 (identical) | Loop 131 quickstart |

Not Jules result PRs (lane PRs, each owned elsewhere): #4 Relay, #203 Blue (ancestor of #217, so #217 contains it), #217 Blue four-lane, #220 Claude×Jules Loop A, #234 Signal batch. #201 and #212 are already merged.

## Suggested cleanup order (human, after the merges in the reconciliation document)

1. Close class B PRs once their carrier lane PR is merged (#200 #202 #207 #208 #209 #215 #216 #219 #222 #224 #225 #230 #232 #233).
2. Close class C PRs after the owning lane confirms the supersession (#204-#206 need the Signal Reviewer; #210 #211 #213 #218 #221 #223 #228 need the Relay owner; #214; #227).
3. Keep #226 and #229 open until both are on the carrier.
4. Keep #231 (rejected evidence) until the Loop A evidence is archived, then close.
5. Only then delete `jules-work/*` branches and their `-<session>` children; keep `claude/claude-jules-autoloop-data` and `claude/autoloop-live-target` (ledger and proof).
