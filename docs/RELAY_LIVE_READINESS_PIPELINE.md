# Relay Live Readiness Pipeline

This document outlines the **static, prepare-only layer** implemented in `src/providers/live_readiness_pipeline.py`.

## Purpose
The Live Readiness Pipeline connects the accepted static evidence inventory to the accepted three-provider readiness bundle through one deterministic orchestration layer.

**Important:**
- This pipeline does not authorize or trigger live execution.
- It acts solely as a side-effect-free, deterministic gate.
- It guarantees that live execution is always explicitly blocked (`live_ready=false`, `dispatch_allowed=false`).
- Aggregate states are limited to `BLOCKED_UNKNOWN` or `READY_FOR_HUMAN_APPROVAL`.

## Workflow
1. The pipeline accepts exactly two top-level components: `preflights` and `inventory`.
2. It attempts to normalize the evidence inventory.
3. If normalization is incomplete or missing, it fails closed, outputting `BLOCKED_UNKNOWN` and safe worklist metadata.
4. If normalization is fully complete (`PROOF_RECORDS_COMPLETE`), the pipeline executes `build_live_readiness_bundle()` across all three providers (OpenAI, Anthropic, Google).
5. Output is validated against fixed safety flags and keys. Any mutation or failure strictly causes a fail-closed response.
