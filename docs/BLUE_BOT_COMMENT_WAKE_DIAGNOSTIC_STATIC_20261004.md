# Blue bot comment wake diagnostic — STATIC (not activated)

Question: does a **bot-authored, non-review PR event** wake the Blue Work task?
(bot-authored review on #167 did not in generation 3; human review did.)
Official OpenAI help only says GitHub tasks can respond to "supported pull
request activity"; per-action names and bot filtering are undocumented (UNKNOWN).

Design: one `workflow_dispatch` (owner `kamiyusense`, `main` only, attempt 1,
`approved_main` == HEAD) posts ONE PR conversation comment on carrier #167 as
`github-actions[bot]`. Body starts with `[BLUE_BOT_COMMENT_WAKE_DIAGNOSTIC_V1]`,
never a command/receipt prefix, so a woken Work run must NO-OP.

- Gates: #167 open + `cloud-blue`; no earlier diagnostic comment (1 per lifetime);
  `diag_id` unused. Result file written before the POST.
- POST budget consumed before the network call; no retry, no fallback; failed or
  ambiguous POST -> `STOPPED_UNKNOWN`, never resend.
- No Jules, provider, model, target write, label/settings change, token creation.
- Evidence of a wake = Blue PR Review Lane `last_run_time` advancing after the
  comment `created_at` (owner reads the task screen). The comment alone proves nothing.
- Interpretation: advance => bot non-review events can wake Work (design the
  Jules-result bridge on that event class); no advance => bot-authored events are
  likely filtered; only human-authored or polling routes remain.

Activation needs: human Merge of this PR, then owner dispatch with a fresh `diag_id`.
Does not touch lane IDs or registry files.
