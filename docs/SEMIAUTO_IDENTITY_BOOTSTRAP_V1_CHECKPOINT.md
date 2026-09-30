# ChatGPT Semi-Auto Identity Bootstrap Checkpoint

This implements the prepare-only bootstrap boundary for the first adoption cycle.
It solves the circular dependency between the Control Tower registry requiring durable records and the first durable records requiring a stable registry lane.

## State Machine
The explicit state machine for first adoption is:
1. `PLACEHOLDER` registry ->
2. bootstrap PREPARE-ONLY bundle ->
3. separately authorized real durable proof ->
4. collector COLLECTED/accepted transition ->
5. explicit registry promotion ->
6. normal adopted path

**Note:** All steps after prepare-only (steps 3-6) are strictly NOT_WIRED / not executed in this task. No live writes or registry promotion occurred.
