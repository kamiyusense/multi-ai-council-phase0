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
  approval_policy:
    granular:
      sandbox_approval: false
      rules: false
      mcp_elicitations: false
      request_permissions: false
      skill_approval: false
  thread_sandbox: workspace-write
---

Official Symphony の GitHub Issue `{{ issue.identifier }}` を扱います。
タイトル: {{ issue.title }}
本文:
{{ issue.description }}

この実験では Issue 本文に明記された一つの小さな成果物だけを、提供された隔離 workspace と non-default proof branch で作成してください。`main` と PR #320 の branch は変更しません。push、Merge、force push、reset、clean、ファイル削除、Billing/Secret/API-key 操作はしません。

最初に branch、HEAD、作業ツリーを読み、対象 Issue と許可パスを確認してください。作業後は `git status --short`、`git diff --check`、対象ファイルの内容を確認し、観測できた turn/continuation/retry/workspace の事実だけを報告してください。複数 turn、通常の continuation、retry、backoff、stall recovery は Official Symphony に任せます。Issue を自動で閉じたり、成果を別 branch に採用したりしません。詰まった場合は事実を報告し、危険な副作用を再送しません。
