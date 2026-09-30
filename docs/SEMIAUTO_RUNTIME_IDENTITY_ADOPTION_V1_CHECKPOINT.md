# ChatGPT Semi-Auto Identity Source Adoption Checkpoint

This adopts the static identity source for the ChatGPT Semi-Auto lane.
The canonical durable loop ID is strictly defined as `chatgpt-semi-auto-v1`.

## STATIC ID SOURCE ADOPTED vs registry promotion/live durable records = NOT_WIRED

The identity source is adopted and validated statically.
Canonical identity injection is statically wired into the Semi-Auto prepare path so callers can no longer choose or supply the durable loop_id.
This explicitly does NOT promote the live Control Tower registry entry.
No live runtime durable records have been written or authorized.
The Control Tower registry explicitly remains `PLACEHOLDER` and fails the static gate.
Issue #33 was not mutated and no live runtime proof occurred.
