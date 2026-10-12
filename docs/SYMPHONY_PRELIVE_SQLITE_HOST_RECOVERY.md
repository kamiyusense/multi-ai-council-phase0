# PRELIVE SQLite host recovery — PR #382

Result: **ISOLATED_READONLY_RECOVERY_PASS**, **SAME_PROCESS_SUBSCRIPTION_READONLY_PASS**.
The production connection remains **PRELIVE_BLOCKED / INSTALLATION_NOT_ACTIVATED / LIVE_NO_GO**.

## Confirmed root cause

The installed WSL binary is `codex-cli 0.162.0-alpha.17.2`, a statically linked
ELF, so a missing system SQLite shared library is not the cause. Existing Windows
`state_5.sqlite` has 58 common migration versions whose checksums differ from
Linux-created state. Version 59 exists only in the new Linux state. This is not a
corruption finding or authority to modify the existing database.

Pinned official SQL blob `7063ce11a45be508749bfe70de23bc64ac2a03d0`
(`codex-rs/state/migrations/0001_threads.sql`) proves the first migration's
SHA-384 checksum matches the existing Windows DB with CRLF, and the installed
Linux-created DB with LF. Only migration metadata was read from the original DB,
using `mode=ro&immutable=1`; WAL was deliberately excluded, so this is a main-file
snapshot comparison, not a complete live-DB health assessment.

Two new synthetic databases contain identical empty table schemas and migration
metadata. Replacing only version 1's checksum with the existing Windows checksum
reproduces the same initialization error. The matching Linux checksum control
initializes and returns account/config. No original database was rewritten,
re-created or copied. Real private SQLite files never enter Git/evidence.

Both new ext4 and new drvfs state directories initialize successfully; synthetic
WAL/integrity checks also pass on both. The evidence does not support blaming
WSL/Windows filesystem support or permissions generally. The initial 15-second
isolated attempt timed out; bounded 60-second follow-ups took approximately
27–32 seconds. That early timeout is preserved, not reclassified as PASS.

## Verified reversible recovery

The official per-process `-c sqlite_home=...` override places SQLite state in a
new directory while keeping `CODEX_HOME`, authentication and configuration as-is.
The repository read-only probe now accepts an optional **empty, private (0700),
owned, absolute, nonsymlink** SQLite directory. It creates no directory itself,
rejects existing database contents before process launch, and cannot transfer
this diagnostic override to model work. No persistent setting was changed.

The installed `config/read` returns `model_provider: null` for the built-in
OpenAI default. The previous parser refused this actual wire shape. The repair
accepts only the complete observed default shape, with independently read
ChatGPT account and `requiresOpenaiAuth: true`. Empty/partial config stays blocked;
custom providers, API endpoint overrides, unknown ChatGPT endpoints, paid tiers
and fallback flags remain rejected. Later model admission still requires fresh
same-session reads and the existing actual `thread/start` provider binding.

The final real transport executes `initialize`, `initialized`,
`account/read(refreshToken=false)`, `config/read(includeLayers=false)` in one
process. It returns `CHATGPT_ACCOUNT`, compatible config and subscription route.
No thread/model/turn, quota query, login or token refresh is requested. The
result is expressly **NOT_ADMISSION**. Original auth/config hashes were compared
in memory only; both were unchanged. All six original DB sizes/mtime were unchanged
over this final probe (metadata preservation, not full DB-byte equality proof).

## GitHub read-only investigation and remaining boundaries

Fresh main moved during diagnosis from `c989aeb08018684ed092c6ce9b78a434903e4b8c`
to `5e035302bad19250b0c47790be9f1fdd727afaf1`; this task never wrote main.
Repo access metadata includes admin/push. Actions defaults are `read`, PR-review
approval is disabled. These do not grant reviewed runtime authority. Protection,
rulesets and effective branch-rule APIs return 403 with a plan/public-visibility
feature restriction; policy remains UNKNOWN. No paid upgrade/settings change.
Both installed operator YAML jobs remain hard-OFF, contents-read, no id-token.

Human decisions remain: approve a durable, separate operator SQLite location;
review the production installation/candidate and narrow runtime credential;
resolve protection-policy evidence; and separately approve a bounded LIVE.
The default shared Windows storage remains incompatible and was intentionally
not repaired in place. This batch proves read-only host recovery, not worker
runtime installation, candidate qualification, actual sending or LIVE readiness.

## Validation and evidence

Nine new regression tests cover the observed null default, independent account
binding, API/proxy/paid-route negative cases, isolated path preservation,
existing DB/symlink/private-directory rejection and process cleanup. Existing
security/production focused tests also pass. Full regression and exact-head CI
results are recorded in the append-only PR completion receipt.

Original production-connection manifests/checkpoints and historical evidence
remain byte-identical. The two superseded source files are verified at original
HEAD `0d32c7fa345b8eea73deae1505ec2c59ed7116e7`; the new host-recovery manifest
separately seals repaired current source and evidence. It never converts old
PRELIVE_BLOCKED evidence to READY.

Evidence: `docs/evidence/symphony-production-connection/host-recovery/`.
Official configuration references: https://learn.chatgpt.com/docs/config-file/config-reference
and https://learn.chatgpt.com/docs/config-file/config-advanced.
