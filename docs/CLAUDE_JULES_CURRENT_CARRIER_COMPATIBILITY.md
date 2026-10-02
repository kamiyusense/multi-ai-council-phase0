# Claude Jules Current Carrier Compatibility Audit Evidence

This document records the exact state of the carrier branch and target branch used for the static compatibility audit. These are evidence snapshots of the read-only carrier and target branches, and are not a future authority.

## Carrier Snapshot (origin/feature/chat-work-command-bus)
- **Carrier commit SHA:** `49948fab8de5748d81d81f1537645493b4323058`
- **automation/command_bus/jules_api_request.py blob SHA:** `1aebad3469c2bfa629e97fd109541c236dc2244a`
- **automation/command_bus/loop_id_claim.py blob SHA:** `d7aba1adfa60b0341d7db6df1b92b8c39bd8c822`

## Target Snapshot (feature/claude-auto-current-jules-protocol)
- **Target HEAD SHA:** `2457a6b9b4aa3582fc7eda526c739e1ae54952dc`
- **Target tree SHA:** `c9be2e0480b5e52204089410b3583a0b4b1537de`
- **automation/command_bus/claude_loop.py blob SHA:** `879c29141194a180a26ca6725bbec9c266c279eb`

## Analysis Result
The real target-side bridge proof correctly outputs `origin_loop_id`, `origin_round`, `origin_correlation_id`, and `origin_generation`. However, the exact current carrier validator rejects this output due to "request keys mismatch" (unsupported origin fields) in `schema_version` 1 (or 2) since they are strictly missing from the carrier's `REQUIRED_KEYS` and `V3_REQUIRED_KEYS`. AUTO origin identity is structurally incompatible with the current carrier logic.
