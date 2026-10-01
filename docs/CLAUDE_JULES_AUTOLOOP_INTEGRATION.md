# Claude × Jules AUTO loop — STATIC/mock integration (2026-10-01)

> 日本語要約: ClaudeがControllerとして「次の仕事の決定 → Jules命令の保存 →
> Jules結果の受信 → 独立検品 → 小修正 or Jules修正依頼 → 安全な反映 → 次の仕事」
> を回す仕組みを、既存部品の組み合わせで実装し、模擬環境（fake GitHub / fake Jules）
> で一周させた。実際のJules投入・LIVE実行・Merge・設定変更は一切していない。
> LIVE実証に必要な人間の承認事項は
> [LIVE proof plan](CLAUDE_JULES_AUTOLOOP_LIVE_PROOF_PLAN.md) に列挙した。

Status: **STATIC/mock complete; LIVE = NOT AUTHORIZED / adapters NOT_WIRED.**
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

- New: `test_claude_jules_autoloop_e2e.py` (22 mock E2E scenarios),
  `test_claude_jules_dispatch_contract.py`, `test_claude_jules_result_inspection.py`;
  compatibility test switched to the reviewed bundle.
- Full suite: `python -m unittest discover -s automation/command_bus/tests -t .`
  → see the checkpoint JSON for the exact count; compileall and `git diff --check` PASS.
- Mutation spot checks (remove re-fence, session check, exact-head test binding,
  lane grant, small-repair path, controller fence, dedup) each made a test fail.
  Removing the adoption `current != snapshot` check alone does not, because
  `fast_forward_allowed` repeats it (defence in depth).

## 7. Not done / UNKNOWN

- Production adapters are NOT_WIRED: a GitHub transport implementing
  `GitHubContentsClient` + ref operations, and a `ResultFactsCollector` that
  runs the real test suite and records Claude's review. In a Claude Code
  session Claude itself performs these via its tools.
- Event wake mechanism for LIVE is UNKNOWN until chosen (see the LIVE plan);
  the normalizer accepts any ingress that supplies the PR payload.
- Jules failure/no-PR completion produces no PR event; the loop then stays in
  `WAIT` (safe) and needs a human or a later observer.
- An owner RENEW while a dispatch intent is half-written stops that intent
  (exact generation is required for the irreversible command write).
- No LIVE Claude → Jules → Claude cycle has run.
