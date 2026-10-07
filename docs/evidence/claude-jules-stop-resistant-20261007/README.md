# Stop-resistant STATIC continuation evidence — 2026-10-07

This batch preserves the existing implementation branch and the LIVE-proven
safety engine. The North Star remains long-running durable autonomous
development. Local fakes and a local bare-git remote are evidence of STATIC
behavior, not evidence of unattended production Claude/Jules execution.

## Fresh starting state

- Main: `4007f0c334c31ee73c68e3a9becd35b2ea5f9b6d`
- Implementation: `4b77407ccee4f80cb3ca31f46b79875b30bccc35`
- Implementation tree: `a53c222eb9ca7c06fec425c86178ff7d6d730515`
- 13 commits after Chat handover `3985961242e553e785c06b07624a929491216591`;
  48 commits ahead of main, zero behind. All 1501 source blobs and the tree
  were verified while materializing the fresh snapshot. No history rewrite.
- #325 remains an open Draft documentation PR from
  `docs/autonomous-loop-north-star-v2`. Its North Star, handover and original
  design checkpoint were imported here while retaining their history.
- #322 remains open and UNKNOWN/unadopted; #220 remains open Draft. No merge.
- Data branch: `5227589bbeeb1db5619b6f3ffff3fed8634428cb`.
- Live target: `53f2caf67280ca1b4c019f325aea5fb9502f1114`.
- Loop A budget 6/10; a-003 owner generation 2 SEMI_AUTO.

## Verification artifacts

| Artifact | Observed result |
| --- | --- |
| `full-regression-final.log.gz` | 1827 tests, OK, one skipped |
| `focused-final.log.gz` | 142 tests, OK; controller, contracts, owner and real local bare-git adapters |
| `contracts-final.log.gz` | 84 tests, OK; common gate, executor, origin binding and request split |
| `mixed-campaign-trace.json` | Seven mock commands over nine restored wakes; four adoptions; timeout task isolated |
| `round-ceiling-audit.txt` | Remaining standalone legacy state/proof defaults and tests recorded for audit |
| `checkpoint.json` | Commit/tree, hashes, exact-head CI and final boundaries |
| `exact-head-actions-code.log.gz` | Exact target `de1e7d5`: 1827 tests, OK, one skipped; compileall/diff check green |
| `exact-head-code-readback.json` | Actions run/job/step readback and carrier identity |

Logs are losslessly gzip-compressed, with deterministic gzip metadata.
Full test stdout includes simulated provider counters from mocked tests;
those are not calls to any LIVE service. No provider/model execution or new
Jules session occurred in this batch. Python compileall and diff check passed.

The mixed trace is captured by executing
`test_claude_jules_campaign_continuation.py::test_mixed_campaign_continues_seven_rounds_across_restarts`
and recording actual `run_until_boundary` results and durable fake records.
It covers corrective failure, lost test evidence, retained UNKNOWN plus new
same-head PASS, mid-campaign canonical movement, new dispatch from a fresh
snapshot, duplicate result delivery, settled task timeout, independent
continuation past round six and a duplicate final wake with no writes.
Other regression cases cover config drift, consumed slots without receipts,
bounded recovery counters across restarts, skewed same-head timestamps,
lost result events, RUNNING/UNKNOWN timeout observations and corrupt records.

## Historical failures retained

- [37548786637](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/37548786637):
  the eight-round regression exposed the legacy verdict six-round ceiling.
- [37549079790](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/37549079790):
  fresh readback confirmed FAILURE on the older handover target: 1791 tests,
  one failure, one skipped; round seven had an invalid verdict round.
- The first local full run in this batch exposed an old test expectation
  that timeout alone may start independent provider work. The production
  adapter now waits for settlement evidence; the expectation was corrected,
  and the final complete regression passed. No failure run was removed.

## Remaining production boundaries

- No new Routine, production event trigger, Claude turn or Jules dispatch.
- No semantic-review authority is synthesized by wake-resume.
- Provider-terminal settlement now has a STATIC contract and a read-only
  adapter (`claude_jules_settlement.py`, batch 2 below): only recorded,
  REST-verified readbacks of the accepted Jules session can say SETTLED or
  RUNNING. Producing such a readback is a provider GET and stays a separately
  approved action; without records the production answer is still UNKNOWN
  (WAIT). Positive SETTLED continuation is still proven with mocks only.
- Routine-level concurrency/idempotency and a real long-running multi-round
  LIVE proof remain unproven. v1 concurrency remains one.
- Policy/config cannot silently change mid-stream. A future explicit
  append-only configuration migration protocol would need its own contract.
- Existing LIVE approval cap remains ten. A 30-round campaign configuration
  does not grant 30 LIVE dispatches; it must respect existing authority.
- Merge and all LIVE operations require separate explicit authorization.

The checkpoint reports STATIC completion of this batch, not completion of
the North Star product. Safe future work includes a STATIC settlement-source
adapter contract and mock event transport; production connection is separate.

Exact code-head validation succeeded in
[37563334683](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/37563334683)
for `de1e7d5116736b3b01a33f01376d83fac9122380` (tree
`2592232d892a6c9628cada387e660528a2f57835`). The log confirms the requested
checkout and 1827 tests with one skip; all workflow steps passed. The final
checkpoint-only commit receives its own distinct append-only validation
request. Its final SHA and Actions result are reported in Draft #329 after
readback, avoiding a self-referential checkpoint commit hash.

## Batch 2 (2026-10-07, STATIC): settlement source and wake transport

See [batch2-settlement-and-wake-transport.md](batch2-settlement-and-wake-transport.md).

## Batch 3 (2026-10-07, STATIC): authentic settlement, reasoned recovery, long campaign

See [batch3-authentic-settlement-recovery-long-campaign.md](batch3-authentic-settlement-recovery-long-campaign.md):
settlement is now checked against the readback job's own Actions log (the
batch-2 record could be forged with a valid digest), opt-in recovery policy v1
with durable `RECOVERY_DECISION` records, a 20-task / 23-dispatch simulated
campaign, two-thread race tests, the #324 interpreter fix ported, and
approval-ready proposals for merge, a one-GET provider trial, the Routine and a
staged long LIVE proof. Nothing LIVE was run.
