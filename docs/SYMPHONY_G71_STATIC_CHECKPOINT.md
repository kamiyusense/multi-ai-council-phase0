# G7.1 verified receipt → durable campaign → next task (STATIC)

Work order: PR343 comment 6094216888. Fresh starting PR343 HEAD
`7da022aa24e82df6b23ccea8fc6d8da3c451a57a`; main
`4bb5cd72ee0d9912376b0bb3b989cbb028806392`. Current starting refs and the
work-order body digest are preserved in `docs/evidence/symphony-g71-static/`.
Final exact commit and independently read-back CI belong to the final PR checkpoint.

## What changed

`symphony_g71_campaign.py` adds a STATIC receipt/checkpoint seam around the
unchanged G6 bridge, attempt store, campaign store and kernel. It accepts an
already observed worker result; it has no timer, scheduling loop, worker launcher,
HTTP sender or LIVE capability. Official Symphony retains polling, selection,
continuation, retries, backoff, stall recovery, concurrency and workspace cleanup.
No Official source or observer patch changed.

Restore the durable campaign before inspection. Validate controller revision and
generation, task/attempt/runner/worker/workspace/head/scope against the restored
attempt. G6 performs independent result inspection and mock intent/target-lock/
object/readback/fence/beforeOid CAS/ref/tree/blob verification. Only its matching
immutable receipt permits `apply_receipt_to_campaign` to record DONE. Failures
use its existing task-local `apply_decision_to_campaign`. Save the normal
hash-linked checkpoint, then restore and compare its digest/revision before
advertising continuation readiness. Readiness means persisted state available
for existing planning, not task success or launch approval. A conflict/unknown
checkpoint never advertises readiness. Replayed verified receipts are NOOP.

`recover_receipt` reads receipt/object evidence only and may save a missing
campaign checkpoint; it never creates Git objects or updates refs. Quota gates
apply to new worker admission, not already observed result recovery. The new
cost compatibility helper reuses the subscription route inspector, checks only
selector names, rejects all API/custom-base/metered/paid routes, and treats quota
telemetry unavailable or unconfirmed exhaustion as UNKNOWN. Explicit confirmed
exhaustion pauses new dispatch. The helper never authorizes dispatch; integration
with an approved production launcher remains NOT_WIRED. Existing configurable
campaign/corrective/recovery policy is passed through without a one-turn limit.

## Actual STATIC evidence

New suite: **28 tests**. The four-task fixture chains simulated STARTED and
WORKER_STOPPED/UNKNOWN, secure full snapshot of real local synthetic bytes,
RESULT manifest, independently mocked pinned CI/artifact verification, fresh
scope/task/target, mock atomic publication, receipt, checkpoint and next task.
A succeeds; B's stale result triggers replan and is found invalid on the fresh
request, so B alone is blocked; C publishes in the mock but loses reply and
candidate readback, so C remains UNKNOWN/blocked; D succeeds on the fresh mock
HEAD. Existing kernel selects each task. C's uncertain target lock is never
cleared or reused on the old HEAD; D uses a new canonical HEAD. No receipt is
invented for C. Historical A receipt still replays after later target advances.

The configurable longer fixture observes **42 distinct mock worker lifetimes**,
42 distinct attempts, **40 verified mock completions**, two isolated tasks and
**43 fresh seam/controller sessions**. Final receipt replay adds zero mock
object/ref writes or model dispatch. This is a credential-free fixture driver
using existing kernel decisions, not a production autonomous campaign. Existing
37-round controller/corrective fixture and 28 G6.3 K/L/M fault cases remain.

Negatives cover missing/rebound/forged evidence, all attempt bindings, stale
controller revision/generation, expiry, competing target claim, after-intent/
objects/fence/ref/campaign-apply/checkpoint crashes, lost replies, delayed
terminal, partial or competing checkpoints, candidate corruption, unknown rules,
snapshot/artifact tampering, worker verifier spoof, and paid/quota boundaries.
Signed observer replay is independently simulated with fixture-only keys and
both STARTED and TERMINAL become NOOP. Raw append-only stores refuse duplicate
creates; receiver-level replay consumes duplicates without writing.

Focused/full actual test logs, existing and new fault matrices, four-task and
42-task byte evidence, historical hashes and actual artifact GET digest are
saved alongside this document. All model/provider LIVE, real worker launches,
real result adoption, Git Database trial writes, updateRefs mutations, paid/API
fallback, default writes and merges are **0**. Authorized development commit/push
and checkpoint publication are separate from runtime writes.

## Recovery playbook

1. Restore the complete campaign hash chain and the original worker attempt.
2. Reject stale controller revision/generation before any mock publication.
3. With a receipt, independently validate chain/object bytes; repair/checkpoint
   missing campaign state. A second replay is NOOP with no Git writes/dispatch.
4. With a fence but no proven receipt, use G6 GET-only recovery. Candidate ref and
   complete object readback permit receipt completion; old/unknown ref stays
   UNKNOWN. Never resend/re-arm/erase the fence or claim success from a response.
5. After campaign-apply crash, discard in-memory state and reconstruct from the
   receipt. After a checkpoint crash, restore the checkpoint and replay NOOP.
6. Isolate unresolved/invalid task scope; let the existing planner continue safe
   independent work. A common locked old target HEAD cannot be silently reused.
7. Confirmed quota exhaustion pauses new model work; receipt/readback recovery
   continues. Telemetry unavailable does not establish exhaustion.

## G6.4 preparation and remaining limits

Existing credential-free isolated CI additionally builds a trusted **synthetic**
candidate from fixed `value.py` bytes, validates Git object SHA and syntax, and
runs G7.1 tests in the same pinned nonroot/read-only/no-network sandbox. The
existing independent Gitleaks scan checks those identical clean bytes and a
false-secret negative fixture. Qualification emits a separate SYNTHETIC
protocol, never a real worker-candidate attestation. Workflow bytes/run/attempt/
steps/artifact/digests are checked after this development push. Safe GET of a
previous official artifact was actually exercised with all ZIP members checked.

Real WSL no-follow/dir-fd/fsync primitives and snapshot tests were exercised on
synthetic local files. Local Docker isolation remains NOT_RUN; no integration or
settings changed. Exact-head GitHub CI independently checks actual isolation.
Rulesets and target protection still return 403 → UNKNOWN. Real sender capability,
actual independent worker-candidate attestation, real Git Database determinism
and one-CAS write qualification remain unqualified. STATIC PASS is not LIVE PASS.

Old evidence/manifests/ledgers are preserved byte-exact. G7.1's validator reads
only the two superseded workflow files at immutable G6.3 HEAD; every other
historical indexed file stays checked in place. New bytes have their own manifest.
See [minimum later one-run readiness](SYMPHONY_G71_LOCAL_LIVE_READINESS.md).
