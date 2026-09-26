# Visible Work Routing Discovery

Purpose: remove the requirement that a human manually search for the hidden
event-triggered Work run.

Priority is strict:

1. Reuse this Scheduled Task's own associated persistent chat if this exact
   task proves it is stable and user-visible.
2. Otherwise inspect the current event-triggered Work runtime for native
   existing-thread delegation capability. Inspection only; do not send.
3. Only when native delegation is unavailable or UNKNOWN may a separate
   read-only Cloud Browser preflight inspect chatgpt.com and existing Work UI.
4. Create at most one fixed visible Work only if no existing route works.
5. Human Google auth and Jules remain blocked until a user-visible route is
   proven.

Correctness remains GitHub-ledger based. Chat/thread/session identifiers are
operator convenience only and must not be persisted as correctness inputs.

The first discovery action must never open a browser, send a cross-thread
message, create a Work, start human auth, start Jules, or start another model.
It records only non-secret capability metadata and exact PR #4 head/tree
readback.
