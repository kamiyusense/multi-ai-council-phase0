# ChatGPT Web Existing Work Preflight

Purpose: test priority-3 routing only after associated-chat usability is not
proved and native existing-thread delegation remains unavailable or UNKNOWN.

The live probe is navigation-only:

1. Fresh-read PR #4 head/tree and require exact command binding.
2. Open `https://chatgpt.com` using Work Cloud Browser.
3. Observe whether ChatGPT Web is reachable and whether the browser is already
   authenticated to the same account context. Do not start a sign-in flow.
4. If authenticated, inspect the ChatGPT/Work UI and the existing Work list.
5. Look only for the exact command-provided preferred existing Work title. The first probe may use the already-known visible Work `WORK【クラウド】`. Do not enumerate/persist unrelated chat titles.
6. If found, open it read-only and verify the Work surface is openable. Do not
   type or send anything.
7. Never send a message, create a Work, start a target model turn, start human
   auth, start Jules, or persist chat/thread/session/browser identifiers.
8. Fresh-read PR #4 head/tree again before writing durable evidence.

A PASS proves only that an existing fixed Work can be reached through UI from
the event-triggered Work's Cloud Browser. It does not authorize a future send.
Any cross-thread/UI relay message remains a separately authorized live POC.

If the existing Work list is visible but the exact preferred existing Work does not exist, classify `NO_SUITABLE_EXISTING_WORK` and stop at prepare-only for the single-fixed-Work route (for example, preparing one future `Phase 0 Jules Operator`).
