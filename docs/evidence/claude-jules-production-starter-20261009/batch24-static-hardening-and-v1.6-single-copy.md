# Batch 24: STATIC hardening of GitHub reads, Windows-safe probe, single-copy Reviewer v1.6 candidate

Date: 2026-10-10 JST. STATIC only. No Jules start, no `jules` label, no Routine / trigger / schedule change,
no Run now, no Merge, no API key, no billing / usage-credit / permission change, no new LIVE connection.

## Fresh readback at start (GitHub MCP + git fetch)

| Item | Value |
|---|---|
| main HEAD | `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0` (unchanged since batch 15) |
| PR #340 | OPEN, Draft, head `119e2efad561193c3465481c1fd8ac6d46187375` |
| CI on that head | run `38020080910` offline-validation **success** |
| Issue #338 | OPEN, labels `[]`, not started |
| LIVE ledger | 9/10 used, slot 10 unused (no change in this batch) |
| Overlapping work | Draft PR #344 (codex) touches `claude_jules_cli_transport.py` only: no shared file with this batch |

## 1. GitHub GET hardening (`automation/command_bus/claude_jules_starter_gh.py`)

`gh_get` still pages with the page number only and always re-requests `repos/{owner}/{repo}/...`
(the cloud proxy refuses `repositories/{id}/...`). New fail-closed rules (`ReadFailed`, never "complete"):

* next page must be exactly `page + 1` (a skip would hide events; a repeat would loop);
* `rel="last"` announced earlier must not move and must be reached;
* an item id seen twice means the list moved while paging;
* HTTP status from the final status line of `--include` output (fallback `(HTTP nnn)` on stderr);
  403 keeps `status=403` and is never `NotFound`; 404 is `NotFound` only on page 1;
* paths that are not `repos/...` (numeric `repositories/`, absolute URLs, `search/`) are never requested;
* subprocess decoding is `utf-8` with `errors="replace"`; error text carries the exception type only.

Also:

* `read_issue`: a 404 on comments/events of an issue that exists is `ReadFailed`, not "no history".
* `repo_preflight`: one authenticated `GET repos/{repo}` (full_name match, `private=true`) before any Layer 4
  decision. `gh auth status` is never consulted. Blocked -> `REPO_ACCESS_BLOCKED`, exit 3, zero further reads.
* `find_duplicate_issue`: Layer 3 / Layer 4 guard (open same title, or any same correlation_id / fingerprint).
  The LIVE port refuses `create_issue` on a fresh listing (`DUPLICATE`); the prepare-only port reports it.
* `--out`: full UTF-8 report in the file, stdout is ONE ASCII line (no `head` truncation, no cp932 failure).

## 2. Tick robustness (`claude_jules_loop.py`)

* a read failure on one candidate -> `DEFER READ_UNKNOWN` for that task only; independent tasks continue;
* a write followed by a failed readback -> `WRITE_READBACK_UNKNOWN`: no further start and no new issue in that
  tick (state UNKNOWN), the next wake recovers from GitHub;
* an unreadable in-flight task -> `READ_UNKNOWN` defer instead of a crash;
* an unreadable merge state is never MERGED (never unlocks merge-dependent work).
* `main_tick`: any remaining `TransientRead` -> outcome `DEFER`, never a traceback that looks like a start.

## 3. Windows-safe read-only probe (`readonly_label_history_probe.py`, profile V2)

Previous blob `fdc3b40f35aee7b32d25b58ba25dd681117d55e0` (the one the cloud session ran) is in git history.
V2: UTF-8 subprocess decoding with replacement; same fail-closed paging rules; full JSON written to `--out`
(default: a new temp file); stdout is one short ASCII line with the file path and its SHA-256; token redaction
kept; GET only; no retry; incomplete history -> `ever_labeled_jules: null` (UNKNOWN). Not re-run in the cloud.

## 4. Reviewer v1.6: one paste-ready file

| File | SHA-256 |
|---|---|
| `routine-prompt-v1.6.CANDIDATE.txt` (paste this, from the **Raw** view) | `c0f47b55b9eba645a941a26bf5ff3c9eb15c87dbb42d3f05033db9bc54f994be` |
| `routine-prompt-v1.5.1-to-v1.6.diff` (mechanical diff) | `2644ffb85ab8c80856440831c585b7fa9b1d327c215b093d0b6a555e5da23b85` |
| `routine-prompt-v1.6.manifest.json` | `1ddd4f7aeefab98bc0609e6784eae118cb078d389c5799b5cd8da40c98830f86` |
| `build_routine_prompt_v1_6.py` (deterministic builder, `--check`) | `eb1f60c526c232f9d1b3fd92c373cb387eee2f519d0212a908cb39fe3b3c08d9` |

Built from v1.5.1 blob `83068a713f0a4c4a8681d4e1c7f71f34714562f1` by 3 declared line replacements
(version id; "other wake: see WAKE ROUTING"; the label rule's single LAYER 4 exception) and 3 insertions
(WAKE ROUTING + separate LAYER 4 write rule; LAYER 4 after the receipt section; one LAYER4 report line).
LAYERS 1, 2, 3 and the RECEIPT section are byte-identical to v1.5.1 (tested). Layer 3 keeps its PASS permission
to create ONE unlabeled next-task issue; LAYER 4 never creates that issue and only starts Jules through the
deterministic command with a human-merged, unexpired authorization file. Without it LAYER 4 is prepare-only.
The earlier `routine-prompt-v1.6-full-prepare-only.CANDIDATE.txt` now says SUPERSEDED (old text in git history).

## 5. Tests (local, this container, Python 3.11)

* new `test_claude_jules_starter_gh_hardening.py` 26, `test_readonly_label_history_probe.py` 8,
  `test_routine_prompt_v1_6.py` 11: all PASS; also PASS with `PYTHONIOENCODING=cp932`.
* regression proof: the new pagination / tick / probe tests FAIL against the batch-23 code (checked by swapping
  the old files in), and PASS on the new code.
* full suite: see the checkpoint (`checkpoint-batch24.json`) and the exact-head CI run.

Not tested here: a real Windows host (UNKNOWN; covered by mock + cp932 env only); a real cloud run of the V2
probe (not needed, not done).

## 6. Route B (GitHub Actions backup)

Unchanged STATIC design from batch 20 (`claude_jules_history_proof.py`, provenance never self-verified).
No workflow added or enabled.

## Boundaries still closed (need a human)

PR #340 Merge; applying v1.6 to the Routine; `pull_request.closed` trigger; recovery schedule; the LIVE
authorization file; slot 10 / first start on #338; usage-credit confirmation.
