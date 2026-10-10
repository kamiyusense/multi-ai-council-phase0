# Batch 22: existing Reviewer cloud issue-history evidence and independent readback

Date: 2026-10-10 JST. Read-only verification only; NO new cloud probe,
NO new Jules start, no permission/usage/billing changes.

## Session evidence (user-shared Claude transcript)

The existing Routine `Claude closed-loop reviewer v1 (Jules PR wake)` was run
manually, creating a cloud session with the repository attached. The first
wake had no diagnostic token and did no write. A direct follow-up user
instruction in the SAME cloud session requested only a read-only GET probe.

Claude reported:
- `gh 2.89.0`, `python3 3.11.17`
- `gh auth status` exit 1 (GH_TOKEN invalid), but authenticated repository
  GET returned HTTP 200, private=true. This is the important observation.
- Script read from the exact commit
  `f74f7bd7f6066aa599378d70f921cb1519b0845a`,
  blob SHA `fdc3b40f35aee7b32d25b58ba25dd681117d55e0`.
- Script executed **once**: `python3 -I <temp-path> --issues 335,338 --per-page 2`.
  Claude captured only `head -80` of its stdout, so its final report was
  UNKNOWN for #338's last JSON fields despite successfully reading both
  pages and the terminal `has_next=false`.
- Issue #335, session read: 3 pages with 2,2,2 events; 6 total,
  `events_complete=true`; historical `labeled jules` at
  2026-10-08T17:53:06Z.
- Issue #338, session read: 2 pages with 2,2 events, each HTTP 200,
  page 2 `has_next=false`. The script's final fields were not visible in
  Claude's truncated output. **Do not misrepresent that transcript as
  an in-session PASS for #338.**
- GitHub writes 0 and Jules starts 0 reported by the session.
  These are session-reported values, not an independent audit of every call.
- Local Windows Claude Code diagnostic was a DIFFERENT session and failed
  due to cp932 UnicodeDecodeError; it does not prove the cloud result.

## Independent direct GitHub readback (ChatGPT GitHub connector, same day)

Read-only REST:
`GET /repos/kamiyusense/multi-ai-council-phase0/issues/{335,338}/events?per_page=2&page=N`

| Issue | page 1 | page 2 | page 3 | page 4 | Total events | jules labeled event |
|---|---|---|---|---|---|---|
| #335 | 2 | 2 | 2 | 0 | 6 | yes, event 32812577102 |
| #338 | 2 | 2 | 0 | not needed | 4 | none |

Issue #338 events, independently observed:
- 32814810366 referenced
- 32838071056 referenced
- 32839285361 referenced
- 32863022962 referenced

All four had no label changes. Current #338 is OPEN with no labels.
Current #335 is CLOSED with a `jules` label.

## Conclusion and limits

**PASS: authenticated private-repo GET from the ACTUAL existing Reviewer
cloud session, with successful per_page=2 reads to #338 terminal page and
a confirmed full six-event history for #335.** Unlike newly created
Probes 01/03 (403), this existing Routine had working GitHub access.

**Independent readback PASS:** #338 has exactly four events, no historical
`jules` label. Combining the terminal-page observation from the cloud
session and independent direct readback is sufficient for practical Route A
read feasibility. Strict proof of #338's untruncated printed JSON in that
specific cloud session remains UNKNOWN (stdout was truncated). No fresh run
is needed merely to repeat a working GET.

**NOT PROVEN:** unattended future wakes, write privilege, startup or
end-to-end autonomy, exact production Routine config after the temporary
edit, or next Jules start. No LIVE authorization, Merge or Routine v1.6
activation is implied.

## Immediate recovery

The existing Reviewer Routine currently contains a temporary diagnostic
prefix. Restore by replacing its WHOLE prompt with the exact original
v1.5.1 file from main:
`docs/evidence/claude-jules-stop-resistant-20261007/routine-prompt-v1.5.1.md`
at blob `83068a713f0a4c4a8681d4e1c7f71f34714562f1`.
Do not alter existing two PR triggers, repository, enabled status, or
schedule. Read back via Routine UI. Do not Run now again.

Prepared-safe follow-up after recovery: develop Route A Layer4 read
integration on Draft PR #340, using this confirmed authenticated-GET route,
without starting Jules or activating v1.6. Route B remains a nondeployed
fallback only.
