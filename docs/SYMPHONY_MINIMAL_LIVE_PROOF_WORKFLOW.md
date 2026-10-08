---
tracker:
  kind: github
  provider:
    repo: kamiyusense/multi-ai-council-phase0
    token: $GITHUB_TOKEN
  required_labels:
    - symphony-minimal-live-proof
  active_states:
    - open
  terminal_states:
    - closed
polling:
  interval_ms: 30000
workspace:
  root: $SYMPHONY_PROOF_WORKSPACES
hooks:
  after_create: |
    test -n "$SYMPHONY_PROOF_BRANCH"
    gh repo clone kamiyusense/multi-ai-council-phase0 . -- --branch "$SYMPHONY_PROOF_BRANCH"
agent:
  max_concurrent_agents: 1
  max_turns: 20
codex:
  command: env -u OPENAI_API_KEY -u CODEX_API_KEY -u AZURE_OPENAI_API_KEY -u OPENAI_BASE_URL -u OPENAI_API_BASE codex app-server
  read_timeout_ms: 60000
  approval_policy:
    granular:
      sandbox_approval: false
      rules: false
      mcp_elicitations: false
      request_permissions: false
      skill_approval: false
  thread_sandbox: workspace-write
---

Handle GitHub Issue `{{ issue.identifier }}` with Official Symphony.
Title: {{ issue.title }}
Body:
{{ issue.description }}

Create only the one small artifact specified in the Issue body, inside the provided isolated workspace and non-default proof branch. Do not change `main` or the PR #320 branch. Do not push, merge, force push, reset, clean, delete files, or change Billing, Secrets, or API keys.

First read the branch, HEAD, and working tree, then verify the Issue and allowed path. After working, inspect `git status --short`, `git diff --check`, and the target file content. Report only observed turn, continuation, retry, and workspace facts. Leave multiple turns, normal continuation, retry, backoff, and stall recovery to Official Symphony. Do not close the Issue or adopt the artifact into another branch. If blocked, report facts and do not repeat an ambiguous side effect.
