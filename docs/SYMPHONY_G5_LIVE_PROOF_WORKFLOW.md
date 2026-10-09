---
tracker:
  kind: github
  provider:
    repo: kamiyusense/multi-ai-council-phase0
    token: $GITHUB_TOKEN
  required_labels:
    - symphony-g5-observation-proof
  active_states:
    - open
  terminal_states:
    - closed
polling:
  interval_ms: 30000
workspace:
  root: $SYMPHONY_G5_PROOF_WORKSPACES
hooks:
  after_create: |
    test -n "$SYMPHONY_G5_PROOF_BRANCH"
    gh repo clone kamiyusense/multi-ai-council-phase0 . -- --branch "$SYMPHONY_G5_PROOF_BRANCH"
agent:
  max_concurrent_agents: 4
  max_turns: 20
codex:
  command: env -u OPENAI_API_KEY -u CODEX_API_KEY -u AZURE_OPENAI_API_KEY -u OPENAI_BASE_URL -u OPENAI_API_BASE -u GITHUB_TOKEN -u GH_TOKEN -u SYMPHONY_G5_OBSERVER_KEY_HEX -u SYMPHONY_G5_OBSERVER_EVENTS codex app-server
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

Work only in the isolated workspace and non-default proof branch named by the
Issue. Create or edit only its single approved evidence file. Inspect the
starting branch, HEAD, allowed path, and working tree before editing. Verify
the file content and `git diff --check` afterward. Report observed turns,
continuation, retries, status and workspace facts accurately. Keep normal
multi-turn continuation, retry/backoff and stall recovery under Official
Symphony. Do not commit, push, merge, close the Issue, adopt into PR #320 or
main, or change Billing, Secrets, API keys or permissions. If an external write
outcome is unclear, report it for readback; do not blindly resend it.
