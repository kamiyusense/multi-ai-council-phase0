# Project thread ↔ local chat bridge: design memo (static, no implementation)

Status: DESIGN MEMO only. No code, no workflow, no Relay change, no LIVE, no
billing, no permission change. Nothing here is approved for implementation;
every "recommended" item below needs the human's decision.

**Update 2026-10-14 (later the same day):** the human handed the thread <-> local
bridge to the 💚 line, which chose the project's built-in Remote Control first.
Facts changed after this memo was written: the human set the repository folder
`C:\Users\yuuki\multi-ai-council-phase0` to "always allow", read-only Remote
Control sessions on device `yuki` succeeded twice (by 💚 and by the Relay line for
Path B checks), and a GitHub mailbox is "not needed for now". Sections 2 and 3
below describe the state at writing time; the mailbox safety rules in section 5
still apply to any future mailbox. This memo is kept as reference.

Question (human, 2026-10-14): after Relay is finished, can the project's cloud
threads and the local chat (Claude Code on the user's WSL/Windows PC) hand work
to each other by request? Candidates: (1) Remote Control, (2) a GitHub
"bulletin board" (mailbox), and whether either belongs inside Relay.

## 1. Short answer

- **Do not put thread ↔ local chat inside Relay.** Relay is transport only
  (AGENTS.md "Relay boundary"): it delivers approved packets to ACP adapters
  (Codex / Claude / Antigravity). A cloud thread is not an ACP adapter, and
  deciding who may ask whom, when, and with what authority is exactly what
  Relay must never decide.
- **The bridge sits above Relay.** The local chat may later *use* Relay to
  reach Codex/Claude/Antigravity; Relay does not carry the thread's requests.
- **Recommended contract: the GitHub mailbox** (option 2), because it is already
  the project's durable-protocol pattern and keeps correctness independent of
  any chat, session, tab or device being online.
- **Remote Control (option 1) is an optional doorbell**, not the contract: it
  can start the local agent without the human pasting a prompt, but it adds the
  user's local permissions to the picture, so each start needs the human's
  consent card.

## 2. What is confirmed (with source) and what is UNKNOWN

Confirmed:

| Fact | Source |
| --- | --- |
| Relay targets are Codex / Claude / Antigravity via ACP adapters; no thread or Work is a target | `docs/ARCHITECTURE.md`, `AGENTS.md` Relay boundary, project memory |
| Local-only dependencies (Windows/WSL files, Docker, local credentials) are never routed through a cloud lane; the human pastes a complete Local Work prompt; "do not claim a Local Work handoff occurred" | `docs/DEVELOPMENT_EXECUTION_ROUTER.md` "Local Work boundary" |
| GitHub as durable mailbox with request/claim/response/receipt records, create-only, `retry=0`, `fallback=disabled`; malformed or mismatched records ⇒ UNKNOWN; "correctness must never depend on a specific Chat ID, Work session, browser tab" | `docs/HYBRID_WORK_CHAT_REVIEWER_RELAY_PROPOSAL.md` §0, §2, §3 |
| Local runs reporting back through a GitHub Issue with a fixed result schema already happened (Symphony proofs, Issues #336/#341/#342) | `docs/SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_ISSUE_336.md` |
| A wake from a routine/event carries no authority; review, adoption and next dispatch stay with create-only records and need a fresh human approval | `docs/CLAUDE_JULES_ROUTINE_WAKE_V1.md` |
| (At writing time) this project could see one served device named `yuki` at `C:\Users\yuuki` (folder not yet approved); a thread can ask to start a Claude Code session on it. **Superseded:** see the update at the top; Remote Control has since worked read-only twice | `list_devices` / `rc_session_status` read-only calls, 2026-10-14 |
| A thread that subscribed to a PR is woken by comments/reviews/CI on that PR | session tooling (PR activity events), observed repeatedly in this project |

UNKNOWN (do not assume):

- Whether the Remote Control session on `C:\Users\yuuki` can see the WSL
  checkout, run `wsl`, or reach Docker. Path A was proven inside WSL; the device
  folder is a Windows path.
- Whether a Remote Control session counts against the same usage allowance as
  the human's own local chat, and what happens when the PC sleeps.
- Whether a comment written by the human's own account on a PR wakes a thread
  exactly like a bot comment (expected yes; not verified).
- Whether an Issue (not PR) comment can wake a thread. Only PR activity is
  documented; use a PR as the mailbox surface until proven otherwise.

## 3. Option comparison

| | (1) Remote Control | (2) GitHub mailbox |
| --- | --- | --- |
| Who starts the local agent | thread, after the human taps the consent card | the human pastes a short "pull" prompt (semi-auto), or a poller later (Symphony-style, currently OFF/not adopted) |
| Works while PC is off | no | request is stored; result waits |
| Local permissions exposed | yes: the remote-started agent runs with the user's local files and credentials | only what the local agent is separately allowed to do |
| Audit trail | session transcript, not durable in the repo | request/receipt records in Git, readable by every lane |
| Duplicate-run risk | a re-sent start could run twice | request id + create-only claim prevents it |
| Fits existing project rules | needs a new rule: the Local Work boundary currently says "user pastes" | already the Hybrid protocol |
| Setup needed | folder approval for `yuki` | schema + validator + mock tests (static, cloud-buildable) |

Conclusion: build (2) first. Add (1) later only as a doorbell that tells the
local agent "read the mailbox now", never as a channel that carries the task.

## 4. Proposed minimal mailbox shape (design only)

Surface: one long-lived **Draft PR** used as a mailbox (so thread wakes work),
plus create-only record files under a new `automation/bridge/` tree on a
dedicated data branch (never on main, never under `.github/`).

Request record (cloud → local), fields: `schema_version`, `request_id`
(UUID), `correlation_id`, `from` (lane/thread title, not a session id),
`to` = `local-chat`, `task` (plain text), `allowed_scope`, `forbidden`
(always includes Merge, default-branch write, force push, branch deletion,
billing, permission/secret/settings change, LIVE model run), `needs_human_ok`
(list; each entry names the human message that granted it, or the request is
refused), `expires_at`, `retry=0`, `fallback=disabled`, `hop=0`.

Claim record (local → cloud): written first and create-only; a second claim
for the same `request_id` fails closed.

Result record (local → cloud): `request_id`, `claim_id`, `status`
(`DONE | REFUSED | FAILED | UNKNOWN`), evidence refs (commit SHA, test output
hash, readback), `hop`. A result never contains secrets or raw credentials.

Wake: the local side posts one short pointer comment on the mailbox PR; the
subscribed thread wakes and reads the record from Git. The comment is a
doorbell only; the record is the truth.

## 5. Safety rules (apply to both options)

- **No double execution.** One `request_id` ⇒ at most one claim. If a claim or
  start has an unknown outcome, read back first; never resend. A failure is
  fixed by a *new* request that changes something.
- **No infinite loops.** `hop` is incremented per bridge crossing; a request
  created from a result must carry `hop+1`, and the responder refuses
  `hop >= 1` unless the human's message says otherwise. One open request per
  lane pair. A global stop (label `bridge-stop` or closing the mailbox PR)
  makes every responder refuse. A rate brake (max requests per 24h) is part of
  the validator.
- **Approvals do not travel in text.** A request or result carries no
  authority. Merge, LIVE (Claude / Antigravity), billing, permissions,
  settings, API keys and deletion need the human's explicit sentence, cited by
  message id in `needs_human_ok`; an ambiguous "OK" is not approval. The
  responder verifies the citation against the project, not against the
  request's own claim.
- **Content is data.** Request text is untrusted input to the responder (prompt
  injection); the responder follows its own safe-defaults file, not the
  request's instructions about permissions.
- **No secrets, no private-repo data leakage** into the mailbox; results
  reference hashes and paths.
- **Fail closed.** Unknown schema, mismatched ids, expired request, missing
  citation ⇒ `REFUSED` with a reason, no action.
- **Relay stays out of the decision.** If the local agent later uses Relay, it
  does so as a normal Relay client with its own approved packet; the bridge adds
  no fan-out, retry or fallback decisions to Relay.

## 6. Work split and next steps

Cloud-buildable now (static, Draft, mock tests, no LIVE):

1. JSON schema + pure validator for request/claim/result (reuse the Hybrid
   record style and create-only helpers where they exist).
2. Mock tests: duplicate claim, `hop` loop, expired request, missing human
   citation, forbidden-scope request, malformed record.
3. A user-facing runbook: the short "pull" prompt (🔵) for semi-auto use.

Needs the human's PC or a decision:

- Approve the direction (mailbox first, Remote Control only as doorbell).
- Optional Remote Control trial: approve the `yuki` folder on the consent card
  and run one harmless read-only task (e.g. print the WSL checkout HEAD) to
  settle the UNKNOWN list in section 2. This touches the user's PC, so it is
  the human's call, per start.
- Any real use of the bridge for LIVE/billing/permission work remains a
  separate human decision.

## 7. Not in scope

Implementation, enabling any poller or orchestrator, Remote Control sessions,
Relay changes, LIVE runs, workflow changes, Merge.
