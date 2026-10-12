# G7.3 Operator host — STATIC PASS, LIVE NO-GO

G7.2 provided call-level lifecycle adapters. G7.3 adds a directly callable operator host, an explicit synthetic CLI, real create-only local records and fresh-process receipt recovery. This closes a real IO/process interface gap; it does not increase a soak count or claim production activation.

## Entry point and owners

`OperatorStaticHost(adapter, events=operator_event_file, workspace=approved_workspace)` accepts the exact G7.2 adapter, strict snapshot store and local STATIC Contents implementation. `handle(operation, **inputs)` fresh-restores the original hash-linked campaign and canonical target before a finite record operation. `restore()` returns checkpoint revision/hash and original kernel next-task advice. The upstream/operator chooses tasks; this host has no dispatch/poll/tail loop or child launcher. Official Symphony remains the sole scheduler, worker lifecycle, multi-turn continuation, retry/backoff/stall/concurrency/cleanup owner. No upstream patch or control path changed.

| Call | Existing component/output | Operator ordering |
| --- | --- | --- |
| admission | Original G7.2 subscription-only new-worker reservation and campaign checkpoint | Only an externally selected new lifetime, never per-turn |
| replay | Complete bounded restrictive no-follow JSONL; G5 MAC; bound workspace; original immutable STARTED/TERMINAL | Event file outside worker; partial last line deferred, restart replays safely |
| snapshot | Strict G6.3 full no-follow pre-close inventory, objects, readback and pointer | Before authorized tracker close/cleanup; no close action here |
| settle | G7.2 → G7.1 → G6 fake objects/CAS/immutable verified receipt → original campaign checkpoint | STATIC fake sender only; delayed/missing verification HOLD |
| corrective | Original independently checked failure audit and corrective task | Self-reported worker FAIL is insufficient |
| recover | Original GET-only receipt recovery, no blind resend | A missing checkpoint can be recovered after a verified receipt |
| restore | Fresh original kernel next-task advice | Advisory only; never dispatched by this host |

`LocalStaticContents` implements the existing get/list/create protocol, separated by hashed local branch namespaces. It reuses the snapshot store's content-addressed atomic/fsync objects, publishes create-only pointers, fsyncs ancestors, and rejects overwrite, update, linked inputs and corrupt hashes. This is a synthetic local backend, not the real GitHub attempt/receipt ledger. Private operator directories remain outside model workspaces. There is no new database, queue, scheduler or HTTP mutation client.

The callable host owns the observer process scope. The observer alone holds the MAC key; outputs never carry it or operator/event/snapshot roots. Only a public synthetic fixture MAC is used in this batch. A future real attachment supplies the existing observer/event reader and snapshot root outside an approved workspace after separate activation review; it cannot be enabled with flags. The current host explicitly refuses remote Contents backends. Connecting production durable GitHub stores and real capabilities requires separately reviewed IO wiring, not swapping a config string.

## Material process proof

`python -m automation.command_bus.scripts.symphony_g73_host_fixture run <new-synthetic-root>` is an explicitly synthetic finite CLI. It creates authentic-format signed fixture events, real local synthetic workspace bytes, complete snapshots and original local attempt/receipt/campaign records. The host proves three fake verified receipts, independent failed-check → corrective → next work, a blocked UNKNOWN task with an independent sibling completed, and next-task advice. It starts a separate ordinary Python process with only PATH/PYTHONDONTWRITEBYTECODE, reconstructing synthetic GET context from explicit JSON and disk records. That host replays STARTED/updates/TERMINAL and restores the original receipt as NOOP_DUPLICATE with unchanged checkpoint and zero extra fake objects/ref calls/model dispatch. No pickle, dynamic import or worker-provided executable is accepted.

The recovering process's fake transport permits reads only, even if a wrong operation is invoked. The fixture serializes only synthetic context, not keys or production authority. CLI output retains original G5 `observation_source=LIVE_OBSERVATION` format under a top-level `synthetic=true`; that format marker is not evidence of real worker activity.

New regressions cover host-controlled file permissions, bounded complete lines, authenticated wrong workspace, invalid MAC, linked replacement, roots inside worker workspace, private outputs, separate-process Unicode/local restore, interrupted pointer publication, corruption, and lost checkpoint after a mock receipt. Prior G7.2 scheduler/race tests remain unchanged.

## Future candidate trust packet — prepare only

`prepare_verifier_contract` requires independently supplied `OperatorVerifierPins`: workflow source commit/hash/ID, run/attempt/job IDs, Python/scanner image digests, exact operator-owned test entry point and its byte hash, scanner config byte hash, successful required step identities and timezone-aware expiry. It reconstructs expected Git candidate and compares exact parent, tree, commit bytes, all blobs/files and every Git object before preparing isolated inputs. `inspect_prepared_contract` compares a packet to an operator-held exact expectation; self-rehashes cannot turn worker input into approval.

The contract is PREPARED_NOT_QUALIFIED and contains `real_worker_candidate=NOT_QUALIFIED`, `operator_approval=NONE`, `authority_source=UNSUPPLIED`, `publication_capability=NOT_WIRED`. No candidate code executes via this parser. Sandbox requirements: pinned images, nonroot 65534, read-only root/candidate, no network/socket/credentials/capabilities, no-new-privileges and bounded CPU/memory/pids. Tests must be operator-owned outside candidate, not unrestricted candidate discover; full independent Gitleaks scanner must use pinned operator no-ignore configuration.

Synthetic CI PASS, independent real worker qualification and operator approval are three different states. Existing G6.3 authenticated archive reader must independently check exact workflow/run/attempt/job/step and whole ZIP digest/strict attestation/source/result/scope/head/real candidate bindings. Its current contract pins workflow bytes and run head at the candidate commit; a future independently selected workflow-source commit must have separately validated identical trusted workflow bytes at the candidate/run, or need a separately reviewed provenance adapter. This preparation packet does not resolve that production dispatch/provenance boundary and cannot be passed as VerificationEvidence. Skipped/forged/replayed checks remain rejected by unchanged G6.3/G7.2 readers, rerun in this batch.

## Future publication capability — NOT_WIRED

Existing G7.2 proposal and G6.3 fake sender remain unchanged. A future real sender needs three independently issued inputs, none supplied here: (1) human-issued one-run authorization binding repository/node, fixed nondefault ref, before/after OID, exact plan/object/result/source/scope/worker identity, one CAS and expiry; (2) authoritative fresh branch ownership/permission/rules evidence; (3) operator-only write credential capability with an exact endpoint allowlist and no child exposure. A self-hashed proposal is not any of those. Reviewed real candidate verification is another prerequisite.

Reuse original create-only inspection/intent, target lock and pre-ref fence. Only plan-listed objects may be published and must be hash/readback verified. Immediately refresh task/request/head/default/rules, then one `updateRefs(beforeOid, afterOid, force:false)`; settle by GET and immutable receipt. An uncertain response or consumed fence allows GET-only recovery, never resend. Current host has no production POST/GraphQL mutation client or capability factory. Fake transport proofs keep original G6.3 semantics; no additional sender abstraction was needed.
