# Relay Live Readiness Bundle

This document and the associated `src/providers/live_readiness_bundle.py` module constitute a **static prepare-only human-approval packaging machinery**.

**Important:** This module does not authorize live provider execution, nor does it resolve any real live blockers. It solely implements a side-effect-free, deterministic gate that summarizes per-provider readiness output into an approval packet.

- Current real-world proof inventory remains `BLOCKED/UNKNOWN`.
- Synthetic `READY` fixtures resolve nothing and must never be presented as real proof.
- The first live provider turn remains completely dependent on a separate, explicit user approval.
- Every generated bundle output strictly enforces `live_ready=false`, `dispatch_allowed=false`, `retry_count=0`, and `fallback_state=disabled`.

## Bundle Rules
1. Exact mapping of three providers: `openai`, `anthropic`, and `google`. No extra or missing providers are allowed.
2. The bundle reaches `READY_FOR_HUMAN_APPROVAL` *only* if all three providers independently reach `READY_FOR_HUMAN_APPROVAL` according to the static `live_readiness.py` gate.
3. If any provider fails, or if the input is malformed, the entire bundle defaults to `BLOCKED_UNKNOWN`.
4. Outputs are fully deterministic and contain a canonical SHA-256 digest of the payload.
5. All caller input is deep-copied to ensure immutability and prevent post-evaluation tampering.
