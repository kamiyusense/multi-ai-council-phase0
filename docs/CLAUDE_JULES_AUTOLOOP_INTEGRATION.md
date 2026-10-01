# Claude × Jules AUTO loop — STATIC/mock integration (2026-10-01)

> 日本語要約: ClaudeがControllerとして「次の仕事の決定 → Jules命令の保存 →
> Jules結果の受信 → 独立検品 → 小修正 or Jules修正依頼 → 安全な反映 → 次の仕事」
> を回す仕組みを、既存部品の組み合わせで実装し、模擬環境（fake GitHub / fake Jules）
> で一周させた。実際のJules投入・LIVE実行・Merge・設定変更は一切していない。
> LIVE実証に必要な人間の承認事項は
> [LIVE proof plan](CLAUDE_JULES_AUTOLOOP_LIVE_PROOF_PLAN.md) に列挙した。

Status: **STATIC/mock complete; stage 6/7 production adapters implemented and tested on real git
(LIVE preparation stopped by the session's safety gate, see §8); no LIVE dispatch has run.**
Branch: `claude/claude-jules-autoloop-integration` (base
`feature/claude-auto-current-jules-protocol` @ `83b499a`).

## 1. Shape

```text
ClaudeJulesAutoLoop.step()            # re-derives position from GitHub records only
  ├─ owner fence (loop_owner chain: live AUTO lease held by this holder)
  ├─ next task: roadmap order, or corrective derived from an inspection
  ├─ prepare: verdict → prepare_next_action → carrier V2 request → v3 claim
  │           → origin binding → immutable dispatch intent (digest-bound)
  ├─ no-write preflight: policy grants, human live authorization, fence, target HEAD/tree
  ├─ dispatch (create-only + readback each): intent → claim → jules-work branch
  │           → origin binding → re-fence/re-read target → ONE command file → receipt
  │           (the existing carrier workflow then submits to Jules exactly once)
  ├─ ingress (separate, no Claude work): GitHub PR event → normalize → create-only inbox
  ├─ lineage: command/work branch + workflow session + head-ref session + PR footer + fresh PR head
  ├─ independent inspection (Claude's own compare, tests on exact head/tree, semantic review)
  ├─ decision: ADOPT / CLAUDE_SMALL_REPAIR / JULES_CORRECTIVE(_REDUCED) / INVESTIGATE / STOP_HUMAN
  ├─ adoption: lock(target, from_head) → non-force fast-forward → readback → receipt
  └─ next round (≤ max_rounds ≤ 6) or COMPLETE / STOP
```

## 2. Reused parts (no re-implementation)

| Need | Reused |
| --- | --- |
| Verdict, prepare-only executor request | `claude_loop.make_structured_verdict`, `prepare_next_action` |
| Current carrier V2 request | `claude_loop.prepare_jules_semiauto_request` |
| Request + binding bundle | `prepare_jules_semiauto_bundle` from `compare/green-ab-1-work@be683df`, independently reviewed and hardened (now also validates request and claim with the carrier validators; that branch's own test used a claim the carrier would reject) |
| Carrier request/claim validation | byte-exact copies of the carrier's `jules_api_request.py` / `loop_id_claim.py` in `jules_carrier_current/` (blob SHAs pinned and tested; the branch-local `jules_api_request.py` is an older divergent schema) |
| Origin identity | `CLAUDE_AUTO_ORIGIN_BINDING_V1` + `ClaudeJulesOriginBindingStore` |
| Durable records | `GitHubContentsClient` create-only + readback pattern |
| Owner/generation fencing | `LoopOwnerGitHubBackend.read_chain` / `validate_owner_chain` |
| Fast-forward gate | `jules_publication.fast_forward_allowed` |
| Dispatch transport to Jules | existing `.github/workflows/jules-chat-semiauto.yml` (unchanged) |
| Task prompt contract | carrier `docs/JULES_TASK_PROMPT_SPEC.md` 12-section order |

Prior-art ideas borrowed as small primitives only (no framework added):
GitHub webhook HMAC-SHA256 validation and delivery handling (GitHub docs);
CloudEvents `source + id`; Trigger.dev / Standard Webhooks idempotency key
(first create-only record wins); the Blue Work roadmap's deterministic result
identity `jules-result-pr<PR>-<HEAD>`. Temporal/Inngest durability is achieved
with the existing GitHub records, not an orchestrator. No OSS code was copied.

## 3. New modules

| Module | Stage | Role |
| --- | --- | --- |
| `claude_jules_task_prompt.py` | 8 | task spec schema, 12-section prompt, corrective spec |
| `claude_jules_dispatch.py` | 2–3 | policy, owner fence, dispatch intent, create-only dispatcher, Loop-number selection |
| `claude_jules_result_event.py` | 4 | signature check, PR-event normalizer, durable inbox, lineage |
| `claude_jules_inspection.py` | 5–6 | 10-point independent inspection, vacuous-test detector, repair decision, small-repair gate |
| `claude_jules_adoption.py` | 7 | serialized non-force fast-forward with readback and receipt |
| `claude_jules_autoloop.py` | 8–9 | resumable controller (`step`, `run_until_boundary`), roadmap planner |
| `claude_jules_live_adapter.py` | 6 | production `GitHubContentsClient` + refs over git (single-file create-only commits, non-force pushes, fresh `ls-remote` heads, git compare) and a repository-scoped read-only REST reader |
| `claude_jules_live_budget.py` | 6–8 | create-only LIVE budget ledger: fixed total of 10 real dispatches, slot taken before the command write, never released |
| `claude_jules_live.py` | 6–7 | live facts collector (workflow run + session, fresh PR, tests on exact head in a worktree, Claude review record), PR poll wake adapter, CLI |
| `config/claude_jules_autoloop_policy.json` | — | committed policy: **grants nothing**, no live authorization |
| `config/claude_jules_autoloop_roadmap.proposed.json` | 10 | proposed one-task docs-only LIVE proof roadmap |

## 4. Durable records (all create-only, never updated)

Carrier branch (unchanged contract): `loop_id_claims/<NNN>.json`,
`jules_api_requests/<command_id>.json`; ref `jules-work/<command_id>`.

Claude data branch (`policy.data_branch`), under `automation/command_bus/evidence/`:
`claude-auto-dispatch-intents/<loop>-r<round>-g<gen>-a<attempt>.json`,
`claude-auto-origin-bindings/<command_id>.json`,
`claude-auto-dispatch-receipts/<command_id>.json`,
`claude-auto-result-events/jules-result-pr<PR>-<HEAD>.json`,
`claude-auto-inspections/<command_id>/<HEAD>.json`,
`claude-auto-adoption-locks/<target>/<from_head>.json`,
`claude-auto-adoption-receipts/<command_id>.json`,
`claude-auto-task-specs/<task_id>.json`.

Recovery: construct `ClaudeJulesAutoLoop` with the same policy/roadmap and call
`step`; it needs no session memory (proved by tests that build a new
controller instance for every step).

## 5. Safety invariants and where they are enforced

- `retry=0` / `fallback=disabled`: every record, intent digest, carrier validators.
- `round ≤ max_rounds ≤ 6`: policy, verdict, controller.
- Terminal receipt replay prevention: dispatch receipt / adoption receipt pre-read → NO-OP.
  An adoption receipt is never trusted by existence: it is re-validated against
  the intent and inspection and the canonical branch is re-read; otherwise UNKNOWN.
- Stored result events and inspections are re-validated (digest, identity) on
  every read; a tampered record stops the loop UNKNOWN.
- Exact target HEAD/tree: preflight and again immediately before the command
  write; adoption requires the canonical HEAD to still equal the snapshot.
- Carrier head movement (other controllers committing) is **not** treated as
  an anomaly; only target HEAD/tree are pinned.
- Ownership: never acts while SEMI_AUTO owns the loop; stale generation,
  released/terminal, expired or future lease → BLOCKED; target branches and
  Jules lanes must be explicitly granted (the committed policy grants none,
  so J-GREEN is not usable merely because it exists).
- Ambiguous writes are read back; a different record at the path is a
  collision; nothing is ever resent.
- Inspection never uses Jules' summary, the PR body or Actions badges;
  missing evidence → UNKNOWN/INVESTIGATE, never PASS.
- Adoption: non-force fast-forward of a granted non-default branch only;
  serialized per canonical HEAD; no Merge, no default-branch write.

## 6. Tests (this branch, cloud container, Python 3.11.15)

- New: `test_claude_jules_handover.py` (8), `test_claude_jules_live_adapter.py` (15, real git remote),
  `test_claude_jules_autoloop_e2e.py` (29 mock E2E scenarios),
  `test_claude_jules_dispatch_contract.py` (14), `test_claude_jules_result_inspection.py` (16);
  compatibility test switched to the reviewed bundle.
- PR #220 review fixes are covered by negative tests: malformed / wrong-command /
  wrong-head / wrong-intent adoption receipts, canonical no longer containing the
  adopted head, crash after a successful fast-forward (receipt restored with no
  second ref write), canonical at the candidate without a Claude lock (UNKNOWN),
  tampered stored inspection and result event (STOP UNKNOWN), fresh PR head ref
  or footer mismatch (BLOCKED).
- Full suite: `python -m unittest discover -s automation/command_bus/tests -t .`
  → see the checkpoint JSON for the exact count; compileall and `git diff --check` PASS.
- Mutation spot checks (remove re-fence, session check, exact-head test binding,
  lane grant, small-repair path, controller fence, dedup) each made a test fail.
  Removing the adoption `current != snapshot` check alone does not, because
  `fast_forward_allowed` repeats it (defence in depth).

## 7. Stage 6/7 live wiring (implemented 2026-10-02)

- Writes: one commit adding exactly one file per record (matches the carrier
  workflow's "exactly one added file" rule), pushed without force. A push that
  git rejects wrote nothing and is rebuilt on the new tip (max 3); any other
  push failure is ambiguous and resolved only by readback.
- Ref heads are read fresh with `git ls-remote`; compare is computed with git
  (merge base → head, like GitHub's compare).
- Dispatch evidence: the run on the command commit is read through REST. The
  job-log storage host is blocked by this container's network policy, so the
  accepted session id may instead come from a Claude-recorded
  `CLAUDE_AUTO_DISPATCH_OBSERVATION_V1` bound to that exact run and job
  (Claude reads the log through its GitHub tool). Lineage still cross-checks it
  against the PR head ref and footer.
- Wake: `poll` lists PRs whose base is each outstanding work branch and feeds
  them through the same normalizer/inbox (`poll-<PR>-<HEAD>` delivery id, same
  result id as a webhook). The loop waits with `AWAITING_CLAUDE_REVIEW` until
  Claude's create-only review record for the exact head/tree exists.
- Failure handling: no result PR within 6 h → `STOP NO_RESULT_TIMEOUT` (slot stays
  used); evidence read failures → `STOP UNKNOWN`; budget 10/10 → no further
  dispatch, checked before any write and again right before the command write.
- Tests: `test_claude_jules_live_adapter.py` (14) runs the unchanged controller
  against a real bare git remote: dispatch, poll, review wait, inspection,
  real fast-forward adoption, budget exhaustion, slot race, blocked job log,
  timeout. A read-only check against real GitHub normalized Jules PR #223
  correctly (session id equal in head ref, footer and workflow log).

## 8. SEMI_AUTO ⇄ AUTO controller handover (design correction, 2026-10-02)

The goal is **one** Jules development whose controller can change, not a
separate Claude lane. ChatGPT (SEMI_AUTO) normally commands a stream (a lane
working on one target branch); Claude (AUTO) may take the same stream over and
must hand it back. Lanes (❤️💛💚💙) are not Claude-only; the policy's lane list
only says which existing lanes Claude may command *while it owns the stream*.

`claude_jules_handover.py` reuses the existing `loop_owner` chain (ACQUIRE /
RENEW / HANDOFF with generation fencing, create-only through
`LoopOwnerGitHubBackend`); the controller's existing fence already refuses
any dispatch unless the latest generation is a live AUTO lease held by Claude.

- **Takeover (SEMI_AUTO → AUTO)** only when all hold: any SEMI_AUTO lease has
  expired; the stream's last durable activity (carrier claims, result PRs,
  owner events) is ≥ 2 h old; no Jules work is in flight (every stream
  command has a result PR or is past the 6 h result deadline, and no open
  result PR changed within 2 h). Time alone never transfers ownership. The
  current ChatGPT loop writes no owner events; then the first AUTO generation is
  an ACQUIRE made under the same stall/in-flight rules.
- **Handback (AUTO → SEMI_AUTO)** by the AUTO holder only at a boundary (no
  Claude dispatch outstanding), so Claude does not keep running when it is
  not needed. **Reclaim**: SEMI_AUTO may take back a stream whose AUTO lease
  expired without a handback (for example, the Claude environment ended).
- Two Claude instances racing for the same generation: the create-only
  generation path lets exactly one win; the other is BLOCKED.
- CLI: `observe | takeover | handback | reclaim` (`--write` to append).
- Tests: 8 mock tests (decision matrix and a full
  SEMI_AUTO → AUTO → task adopted → SEMI_AUTO round trip, session loss and
  reclaim, takeover refused while ChatGPT's Jules task is in flight) and a
  real-git round trip. Read-only check on the real carrier (2026-10-02 03:5x JST):
  ❤️ J-RED and 💛 J-YELLOW streams both have Jules work in flight, so takeover
  is correctly BLOCKED for both.

## 8a. Reusing the shared carrier without interfering (2026-10-02)

The user chose to keep the existing carrier `feature/chat-work-command-bus`
and its workflow (no new carrier, no gate/setting change). Two ways a Claude
write there could disturb the ChatGPT lanes, and how each is closed:

- **Cancelled pending runs.** The carrier workflow has one concurrency group;
  GitHub keeps one pending run per group and cancels an older pending run when
  a newer one queues. `CarrierQuietGuard` therefore lets Claude write a claim
  or command only when no carrier run is unfinished (queued / in progress /
  waiting / requested / pending, read through REST) and the carrier's latest
  commit is at least 5 minutes old (another controller may be between its
  claim and its command). Busy → `WAIT CARRIER_BUSY` with nothing written; a
  half-written dispatch resumes from the same intent. Unreadable → `UNKNOWN`.
  It is checked in the no-write preflight, before the claim and before the
  budget slot and command. `carrier --file since.txt` lists any carrier run
  cancelled since a time, as an after-the-fact interference check.
- **Global Loop numbers.** Claude uses the same create-only claim rule as the
  ChatGPT lanes (`if exists choose a new number`); a lost race is a
  `COLLISION` receipt and a re-plan, never an overwrite.

Stream ownership for an isolated test target: a stream that nobody ever owned
or commanded may be ACQUIRED by AUTO directly (`takeover` → `new-stream`).
The AUTO holder can `renew` its own live lease between dispatches (a RENEW
bumps the generation, so it is refused while an intent is half-written).

Read-only check on real GitHub (2026-10-02 04:3x JST): the guard returned
`WAIT CARRIER_BUSY: carrier changed 41s ago`; no carrier run was cancelled
on 2026-10-01/02.

## 8b. LIVE proof (2026-10-02 04:3x-05:4x JST, 4 of 10 dispatches)

Approved by the user in the project thread (shared carrier reused; Loop A total
LIVE budget 10, retry=0, fallback=disabled; no merge). Target: isolated branch
`claude/autoloop-live-target`; lane label J-GREEN; stream owned by AUTO from an
ACQUIRE (gen 1) to a HANDOFF back to SEMI_AUTO (gen 2).

| Loop | Task | Jules session | Result PR | Claude's inspection | Outcome |
|---|---|---|---|---|---|
| 128 | live proof note | 16228878555691005955 | #230 | PASS | adopted (fc2ad82) |
| 129 | budget summary helper | 9613854744580982311 | #231 | FAIL_MAJOR: mixed-type slot numbers leaked `TypeError`, no test | corrective ordered |
| 130 | corrective for 129 | 10117650476672833427 | #232 | PASS (all edge cases rechecked by running the code) | adopted (2eb310c) |
| 131 | operator quickstart | 12222938286641699709 | #233 | PASS | adopted (53f2caf) |

The roadmap then reported `COMPLETE`. Adoption is a non-force fast-forward of
the isolated target only; nothing was merged and `main` was not written. No
carrier run was cancelled during the proof and no other controller's claim,
command or branch was touched. Bugs found by the live run and fixed here: the
carrier guard now ignores Claude's own claim commit for the quiet window, and a
superseded failed candidate no longer counts as an outstanding dispatch
(it blocked the handback).

## 8c. Follow-up check, integration and merge preparation (2026-10-02 06:3x JST)

- Read-only state (GitHub records): owner = SEMI_AUTO generation 2
  (`chatgpt-semiauto-controller`, lease to 2026-10-02 08:30 UTC, handed back by
  Claude after Loop 131); outstanding Claude dispatches 0; LIVE slots used 4 of
  10 (slot-01..04); last adopted result = `53f2caf` (Loop 131, PR 233);
  `poll` returned no new result; the carrier was quiet.
- **No further LIVE test was started.** The stream belongs to SEMI_AUTO, and
  Claude does not take it over: the takeover rule needs an expired SEMI_AUTO
  lease, a stall of at least 2 hours and nothing in flight. It reported
  `BLOCKED` (the four result PRs 230-233 are still open and recent), and the
  loop's own owner fence reported `STOP BLOCKED: loop is owned by SEMI_AUTO`.
  A new test can start after the lease expires (08:30 UTC) and the stream is
  idle, or when the human hands the stream to AUTO.
- **Integration:** `claude/autoloop-live-target` (merge-base `f8d3043`) differed
  only by the three adopted commits (4 added files); the PR branch had only
  documentation/evidence and the two LIVE-found fixes on top. Merge-tree was
  clean. The live target was merged into this PR branch with a normal merge
  commit (non-default branch, no force). The merged files are byte-identical
  to the adopted candidates (`git rev-parse` of each blob). The superseded
  Loop 129 candidate (PR 231) is intentionally not included. Full suite
  933 tests OK, `git diff --check` and `compileall` clean, secret-pattern scan
  of `automation/` and `docs/` found nothing.
- **Merge preparation / human decisions (not done here):**
  1. PR 220 is a draft against `feature/claude-auto-current-jules-protocol`;
     marking it ready and merging are human-only.
  2. `config/claude_jules_autoloop_policy.live.json` carries a live
     authorization that expires 2026-10-02 15:00 UTC and names the isolated
     target; harmless when expired, but a human may prefer to drop the two
     `*.live.json` files before merging.
  3. Jules PRs 230-233 and the `jules-work/*` branches are still open; close
     them after the merge decision (not touched here).
  4. The shared carrier workflow lists only one concurrency group; the quiet
     guard reduces but cannot remove the chance of colliding with another
     controller's pending run, so run Claude AUTO only while ChatGPT's lanes
     are idle.

## 9. Not done / UNKNOWN

- LIVE is no longer blocked: after the user's explicit approval the isolated
  branches were created and the proof above ran (4 of 10).
- Remaining UNKNOWN / not done:
  - Wake mechanism is the in-session `poll`; no scheduled routine was created.
  - A Jules run that ends without a PR produces no event; the loop waits and
    stops with `NO_RESULT_TIMEOUT` after 6 h (the slot stays used).
  - The `## Session` body in the first proof note is the snapshot commit, not
    the Jules session id (the task did not specify it); noted, not failed.
  - PR #220 is still a draft and must be merged by a human (not done here).
  - An owner RENEW while a dispatch intent is half-written is refused (the
    exact generation is required for the irreversible command write).
