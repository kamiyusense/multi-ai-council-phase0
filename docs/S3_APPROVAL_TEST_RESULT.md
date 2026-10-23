# S3 approval-comment test result (2026-10-23)

Test Issue: #459 (test only; no approval was consumed). Read back with the GitHub REST API
`GET /repos/kamiyusense/multi-ai-council-phase0/issues/459/comments` on 2026-10-23 (~11:47Z).

| Comment id | Written by | `user.id` | `performed_via_github_app` | `created_at` | `updated_at` | Body | `judge_approval` |
|---|---|---|---|---|---|---|---|
| 6364045450 | owner, GitHub Mobile, then a 👍 reaction | 20355232 | null | 2026-10-23T11:40:49Z | 2026-10-23T11:40:49Z | bare approval word | APPROVED |
| 6364058115 | Grok Bot via the Cursor GitHub integration | 20355232 | `cursor` (Cursor) | 2026-10-23T11:41:35Z | 2026-10-23T11:41:35Z | test text + `AI-Agent: grok` | NOT_BARE_APPROVAL |

Earlier read-back (#346): comments Claude wrote from the project thread carry `performed_via_github_app: claude`.

## Findings

1. **A reaction does not change `updated_at`.** The owner's comment kept `updated_at == created_at` after the 👍,
   so the "never edited" condition does not misfire on reactions.
2. **App-mediated AI writes are visible.** Both AI routes that write under the owner's account (Claude, Grok Bot via
   Cursor) set `performed_via_github_app`; the owner's GitHub Mobile comment does not. `judge_approval` now also
   requires the field to be present and null (`VIA_APP` / `APP_UNKNOWN`), on top of the signature rule. This blocks
   an unsigned bare approval word from Claude or Grok Bot even if a signature is forgotten.
3. **Residual gap:** an AI that writes with the owner's own credentials outside an App (for example a CLI using the
   owner's git/gh login on the PC, such as Codex/Symphony or Antigravity) would also show null. For those writers
   the signature rule and their prompts remain the only guard. UNKNOWN until observed: what Codex/Symphony and
   Antigravity writes show.
4. **No GitHub settings change was needed** (see `docs/S3_SETUP_AND_APPROVAL_TEST_JA.md`).
