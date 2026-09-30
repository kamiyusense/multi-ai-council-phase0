# Claude AUTO JULES_BACKEND current-carrier compatibility audit

Date: 2026-09-30
Task: Loop 065 — Claude AUTO JULES_BACKEND current-carrier compatibility audit

## Observed Carrier Protocol State
The current carrier protocol was inspected from branch `feature/chat-work-command-bus` (commit `8887c7add17021d35d60beb822b54a93693c0895`).

The carrier protocol (`JULES_CHAT_SEMIAUTO_V2`) strictly requires exactly these keys in the request payload:
- `schema_version` (must be 2)
- `profile` (must be `JULES_CHAT_SEMIAUTO_V2`)
- `command_id`
- `target_repo`
- `target_branch`
- `work_branch`
- `expected_target_head`
- `expected_target_tree`
- `allowed_paths`
- `prompt`
- `created_at`
- `expires_at`
- `retry`
- `fallback`
- `merge_allowed`
- `force_push_allowed`

It strictly rejects any missing or extra keys.

## Mismatch Facts
1.  **Schema Version:** Main's `prepare_jules_semiauto_request()` outputs `schema_version: 1`, while the carrier requires `2`.
2.  **Profile:** Main outputs `JULES_CHAT_SEMIAUTO_V2`, which matches the carrier profile string, but the schema structure is mismatched.
3.  **Missing `work_branch` and Separation Gap:** Main outputs `target_branch`, `expected_target_head`, and `expected_target_tree`, but does not output `work_branch`. The carrier requires `work_branch` to be exactly `jules-work/{command_id}` and requires it to differ from `target_branch`.
4.  **Extra Origin Fields:** Main attempts to include `origin_loop_id`, `origin_round`, `origin_correlation_id`, and `origin_generation`. These fields have been completely removed from the required keys in the carrier protocol. Because the carrier protocol enforces an exact key match, passing these fields will cause a rejection.
5.  **ORIGIN_BINDING_GAP / BLOCKED_UNKNOWN:** Because the carrier request schema (and the updated claim schema v3) provides no validated durable fields for the AUTO origin identity (loop, round, correlation, generation), there is a critical gap. We must not stuff unvalidated fields into the request. This missing origin durability is classified as an explicit `ORIGIN_BINDING_GAP / BLOCKED_UNKNOWN`.
6.  **Numbered Loop Claim / Cross-Binding:** The carrier protocol uses claim schema version 3, which requires `lane_id` and `lane_display` cross-binding, and `expected_target_tree`. Main does not natively output this claim structure or cross-binding.

## Development Constraints and Live Status
- **Development Lane:** This task uses the development worker lane `J-GREEN`. Do not hard-code `J-GREEN` as the future AUTO runtime lane.
- **Live Activation Deferred:** PR #25 is merged, and its bounded standalone Claude Gate proof does not authorize another Claude run. Integrated Claude-verdict -> Jules LIVE remains separately authorized and is not executed here.
- **Migration Boundary:** The smallest safe migration choice is to adjust the main bridge to emit the exact V2 schema (omitting the origin fields if unsupported, or negotiating a carrier update), but this implementation is deferred to a follow-up. Do not expand current carrier authority here.

*Note: The carrier snapshot SHAs recorded above are evidence only. Future work must fresh-read the carrier state again.*
