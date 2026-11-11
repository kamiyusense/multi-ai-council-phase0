# Loop number allocation: evaluation (2026-10-02)

Method in use: read the global claim ledger and the numbered commands (all lanes), take the next unused number, then create-only write `loop_id_claims/<NNN>.json`, then (only after the claim exists) the work branch and one numbered command. The dispatch workflow re-checks the claim against the command.

| Question | Answer | Evidence |
|---|---|---|
| Fail closed on collision? | Yes. The loser reads back the foreign claim, appends **no** command, burns **no** budget slot, re-plans on a new number; the foreign record is never overwritten | `test_cross_lane_isolation`: other lane wins the same number; claude skips numbers claimed by other lanes (+ mutation: collision treated as success fails the test) |
| Safe with retry=0? | Yes. Nothing is resent; ambiguous writes are resolved by readback | `ambiguous_command_write_is_read_back_not_resent`; `lost response after command write` |
| Recoverable from durable state alone? | Yes. After a kill between claim and command, a fresh process resumes the same command: one claim, one slot | `process killed after claim` test; `recovery_reconstruct.py` rebuilds owner/budget/command chain from GitHub only |
| Two lanes choosing the same number at the same instant? | The create is a git push of the same path: one wins atomically, the other is refused and re-reads | cross-lane race test; owner-generation race test passes even with the backend's own guards removed, so git's create-only atomicity is the last line |
| Is a central allocator service needed? | **No, not for correctness.** Cost of the current method is only a retry with a new number on a collision, and unused claimed numbers stay reserved forever (gaps are harmless) | above |
| Residual risks | (1) gaps in numbering are permanent; (2) the method depends on the claim directory being on the carrier branch, so the carrier branch must stay alive and be the single place new claims are written; (3) claims for historical numbers 110/113 are malformed and are quarantined by exact hash (PR #229 content) | `docs/CARRIER_FINAL_RECONCILIATION_20261002.md` |

Recommendation: keep the current method. A central allocator would add a new moving part and a new failure mode for no safety gain.
