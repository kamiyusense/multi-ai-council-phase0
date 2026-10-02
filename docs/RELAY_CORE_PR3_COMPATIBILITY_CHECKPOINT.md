# Relay Core PR #3 Compatibility Checkpoint

- Relay target head parent: 723641270070e46b26262bd4d55e257f52a53cd2
- Pinned Core PR #3 head: 494b7296f32dce1c173a7699e4bd2d87f70d31a9
- Fresh-read Core source checked: `src/phase0_core/adapter.py` and the relevant `execute_with_adapter` / mock-provider isolation path in `src/phase0_core/runner.py`.
- Exact adapter contract checked: `provider_id`, `prepare`, `preflight`, `dispatch`, `collect`, `abort`, `classify`.
- Core LIVE behavior remains hard-disabled.
- Static/mock compatibility boundary returns a new deterministic map ordered `openai`, `anthropic`, `google`; construction performs no adapter execution.
- Core runner behavior verified for this checkpoint: timeout/error isolation is handled by Core without automatic `adapter.abort()`; Relay compatibility tests therefore do not invent a hidden abort/retry/fallback path.
- Raw provider bytes are preserved at the Relay collect boundary before classification.
- Candidate evidence is static/mock only; independent exact-head validation is required before acceptance.
- Real cross-branch Core + Relay integration/merge is not performed here.
- Live provider execution remains BLOCKED.
