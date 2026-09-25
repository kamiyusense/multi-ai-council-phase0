# Jules API Route Decision — 2026-09-25

Status: **ADOPTED / PREPARED FOR ONE BOUNDED LIVE SMOKE**

Repository: `kamiyusense/multi-ai-council-phase0`

## 1. Decision

The user explicitly authorized the **Jules API route** for Phase 0.

This is a scoped exception to the older "no API-key route" rule. It applies only to
Jules orchestration for this project. It does **not** authorize OpenAI, Anthropic,
Gemini Developer API, Vertex AI, other metered provider APIs, Billing/Credits/
Overages changes, or unrelated external services.

The custom BrowserHook / Work Cloud Browser route remains frozen. Do not resume it
unless the user explicitly reverses this decision.

## 2. Selected predecessor

Primary implementation:

- repository: `google-labs-code/jules-action`
- license: MIT
- pinned commit for first smoke:
  `bff7875eaa123cac6742b7cfc51005b95ba4d566`
- observed tag associated with this code: `v1.0.0`

Why selected:

- GitHub-native execution
- calls Jules REST API directly
- supports explicit `starting_branch`
- builds `sourceContext.githubRepoContext.startingBranch`
- `automationMode = AUTO_CREATE_PR`
- `requirePlanApproval = false`
- no internal automatic retry in the action
- API key can be supplied through GitHub Actions Secrets
- no browser/Jules UI dependency
- no custom controller is required for the first smoke

## 3. Confirmed source behavior

The pinned action builds a Jules payload equivalent to:

```json
{
  "prompt": "...",
  "sourceContext": {
    "source": "sources/github/<owner>/<repo>",
    "githubRepoContext": {
      "startingBranch": "<explicit branch>"
    }
  },
  "requirePlanApproval": false,
  "automationMode": "AUTO_CREATE_PR"
}
```

and submits it once to:

`POST https://jules.googleapis.com/v1alpha/sessions`

using `X-Goog-Api-Key`.

## 4. Known defects / limitations

Do not treat the upstream README as exact executable truth.

Known findings:

1. README shows `google-labs-code/jules-invoke@v1`.
   The current repository is `google-labs-code/jules-action`, and the bare
   `v1` ref was not found in the audit. Use the pinned commit above for the
   first smoke.
2. The action's `curl` does not use an HTTP fail mode. A GitHub Actions green
   result is therefore **not** sufficient proof that Jules accepted the session.
3. The action does not expose session ID / PR URL as formal Action outputs.
   Read back Jules/GitHub after execution.
4. Inputs are interpolated into shell usage. The first smoke avoids arbitrary
   untrusted issue text and uses a fixed branch and fixed task prompt.
5. Whether a Jules-created PR always uses the requested starting branch as its
   PR base remains **UNKNOWN** until the live smoke proves it.
6. Jules REST API billing remains:
   `PROBABLY_SAFE_BUT_NOT_EXPLICITLY_GUARANTEED`.
   Official setup does not require a Cloud Project/Billing flow in the examined
   docs, but no first-party statement was found guaranteeing zero usage-based
   charges for every API session.

## 5. First bounded smoke

Target:

- PR #4
- branch: `feature/relay-transport-7070955470193506982`
- current head at this decision checkpoint:
  `2fc399ac7b415746763114c3951aa2e3b45adee7`

The SHA above is historical evidence, not a permanent target. Fresh-read PR #4
immediately before launch.

Task:

- modify exactly `tests/relay/test_dispatcher.py`
- add one regression test proving
  `abort_signal={"aborted": True}` blocks before slot reservation and provider
  dispatch
- no implementation file change
- run:
  - `PYTHONPATH=src python -m unittest discover -s tests -t . -v`
  - `python -m compileall -q src tests`
  - `git diff --check`

## 6. Smoke acceptance

Before launch:

- fresh PR #4 head/tree is recorded
- target branch name is exact
- API key exists only in an approved secret store
- one logical dispatch only
- retry = 0
- fallback = disabled

After publication, require direct readback:

- Jules session/task exists
- resulting Jules commit ancestry is based on the fresh PR #4 head
- resulting PR base/source relationship corresponds to the exact PR #4 branch
- target-relative changed path set is exactly:
  `tests/relay/test_dispatcher.py`
- operation is MODIFY
- no unrelated change
- test evidence is available or explicitly UNKNOWN
- no automatic Merge

GitHub Actions "green" alone is not PASS.

If submission success is ambiguous, do not re-dispatch. Read back first. If
still unverifiable, terminalize as UNKNOWN.

## 7. API key handling

Allowed route after user action:

`Jules Settings -> API key -> GitHub repository Secret JULES_API_KEY`

Rules:

- never commit the key
- never paste the key into Chat
- never persist it in command/evidence files
- never echo it into logs intentionally
- do not create/change Billing, Credits, Overages, Cloud Project, Vertex AI,
  Gemini Developer API, or unrelated settings
- API-key creation and GitHub Secret mutation are user/system approval boundaries

## 8. Secondary candidate

`hahwul/cjules` is retained as a debugging/readback reference, not the primary
runtime.

Strengths:

- explicit `--repo` / `--branch`
- watch/logs/patch/PR/JSON output
- Git-aware branch detection

Reason it is not the first runtime:

- community binary dependency
- its session creation path includes retry/reconciliation behavior that does not
  match the current default `retry=0` policy as cleanly as jules-action

Do not add cjules unless the first route produces a concrete need.

## 9. Architecture after adoption

Preferred Phase 0 direction:

```text
Chat / durable GitHub command
  -> GitHub
  -> GitHub Actions
  -> pinned google-labs-code/jules-action
  -> Jules REST API
  -> exact non-default target branch
  -> Jules
  -> GitHub PR/result
  -> fresh GitHub readback
  -> Sol semantic review
  -> human-approved Merge only
```

Do not rebuild a custom browser relay before this predecessor route is tested.
