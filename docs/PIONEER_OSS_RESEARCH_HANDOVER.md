# Pioneer / OSS Multi-Agent Development Research Handover

Updated: 2026-09-21  
Status: research handover / adoption candidates only

> この文書は、現Chatで行った「先駆者はどうやって複数AIで開発しているか」「既存OSSを流用できないか」の調査内容を、新しいChatへ引き継ぐためのもの。  
> ここに挙げる仕組みは **まだPhase 0正式採用ではない**。実装へ取り込む前に、license / safety / Windows / auth / retry / permission / GitHub副作用をコードレベルで監査する。

---

## 0. 2026-10-01 acceleration shortlist — 日常実装は先にこちら

この詳細研究を全部読み直してから毎回実装を始める必要はない。
日常の実行方針は
[DEVELOPMENT_ACCELERATION_PLAYBOOK.md](DEVELOPMENT_ACCELERATION_PLAYBOOK.md)
を正として先に読む。

今回の追加調査で、特に「今すぐ自作量を減らせる」ものを次へ絞った。

### GitHub Webhooks — direct official reuse

Official:
- https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks
- https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries

使う答え:
- raw body + `X-Hub-Signature-256` + HMAC-SHA256
- constant-time comparison
- `X-GitHub-Event` + payload `action` で早期filter
- `X-GitHub-Delivery` を外部eventの一次dedupe identityとして使う
- requested redeliveryでも同じ delivery ID
- receiverは10秒以内に2xxを返し、長いworker処理をHTTP request内で行わない

Phase 0では、まずこの公式patternで十分。独自webhook frameworkを先に
作らない。

### Trigger.dev — tiny idempotency primitive only

Repository:
https://github.com/triggerdotdev/trigger.dev

Observed license: Apache-2.0.

使う答え:
- deterministic key material
- scope identity
- SHA-256 digest

Phase 0では retry=0 が固定なので、Trigger.dev本体のrun/attempt machineryを
持ち込まない。既存 stable ID で足りない場合だけ小さいhash helperを使う。

### Standard Webhooks / Svix — semantics only unless multiple providers need it

Spec:
https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md

Svix:
https://github.com/svix/svix-webhooks

Observed Svix license: MIT.

使う答え:
- original/raw payload bytesを検証
- message IDをidempotency keyとして扱う
- signature comparisonをconstant-timeで行う

GitHub-onlyの間はGitHub公式HMAC + Python標準libを優先し、Svix server /
Redis / Postgres / retry scheduler / DLQは入れない。

### CloudEvents — event identity concept only

Spec:
https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md

使う答え:
- `source + id` がdistinct event identity
- 同じ `source + id` の再送をduplicateとして扱える

Phase 0の origin identity と carrier identity を分離してbindingする設計の
答え合わせとして使う。SDK dependencyは現時点では不要。

### Temporal / Inngest — future painkiller, not current dependency

Temporal Python SDK / samples:
- https://github.com/temporalio/sdk-python
- https://github.com/temporalio/samples-python
- observed license: MIT

Inngest:
- https://github.com/inngest/inngest
- server repository observed license: SSPL + future-license terms

どちらもdurable workflow / idempotencyの答え合わせには使うが、今はPhase 0を
別platformへ移植しない。既存GitHub durable control planeで実害が出てから
再検討する。

### Short rule

```text
repo内reuse
-> 公式実装例
-> 小さいpermissive OSS部品
-> design-only reference
-> 最後に自作
```

「安全そうだから追加」ではなく、「次の実装境界に必要だから追加」を採用条件とする。

## 1. 結論

今の「GitHubを共通セーブポイントにする」方針はかなり筋が良い。

先駆者の実装・研究で共通して見える形は、おおむね次。

```text
Central Manager / Orchestrator
  -> dependency-aware task split
  -> isolated git worktree / branch per writer
  -> structured task contract
  -> independent agent work
  -> tests / validation
  -> commit SHA checkpoint
  -> review
  -> PR
  -> human-approved integration / Merge
```

重要なのは、AI同士を延々と自由会話させることではない。

長期的な連携では、次の方が安定しやすい。

- Git branch / worktree
- commit SHA
- structured task/state
- tests
- receipt / correlation
- PR
- central ledger/controller

Phase 0へ当てはめると:

```text
GitHub        = durable checkpoint / source history
SQLite ledger = active task / receipt / correlation state
Relay          = live transport
Orchestrator   = dependency / execution controller
Tests / CI     = executable verification
Human          = final decision
```

---

## 2. GitHub checkpointは苦肉の策ではなく王道寄り

想定している運用:

```text
Agent A
  -> commit SHA

Chat / Agent B
  -> same SHA readback / review

next worker
  -> continue from that SHA
```

は、複数Agent開発でよく使われるGit中心の協調方式と整合する。

commit SHAは、Gitで追跡されたその時点の状態を正確に指せる。

注意:
- uncommitted fileはcommit SHAに含まれない
- Gitへ入れるべきでないartifact / RAW evidenceは別保管が必要

---

## 3. CAID

Research:
- CAID = Centralized Asynchronous Isolated Delegation
- paper: Effective Strategies for Asynchronous Software Engineering Agents
- public repository: `JiayiGeng/CAID`

主要アイデア:
1. central manager
2. dependency-aware task planning
3. asynchronous engineer agents
4. isolated git worktree
5. branch/merge coordination
6. executable tests for integration

Phase 0への示唆:
- Managerが依存関係を作る
- 独立タスクだけ並列化
- Writerはworktree/branch分離
- 統合は明示的
- testsを完了判定に使う

既知の不一致:
- current CAID implementationはAPI-key / base-URL系設定を前提にしており、現Phase 0のsubscription-login / no-metered-API方針とそのままでは一致しない
- code reuse licenseは、現調査時点では明示確認できていないため **UNKNOWN**

結論:
- design/referenceとして有力
- code copyはlicense確認まで保留

---

## 4. Writer swarmよりsingle-writer default

実運用知見では、複数Agentを全部Writerにするより、

```text
1 Writer
+ read-only / low-write Reviewers
```

の方が安定しやすい。

推奨原則:

> 思考は積極的に並列化し、書き込みは保守的に並列化する。

例:

```text
Codex  -> Writer
Claude -> Reviewer
Gemini -> Reviewer
```

本当に独立したmoduleのみparallel writer候補:

```text
Agent A -> Relay
Agent B -> Safety
Agent C -> Report generator
```

条件:
- separate branch/worktree
- clear file ownership
- dependency確認済み
- integration/testは別工程

---

## 5. Dependency DAG

仕事を3社へ均等分割するのではなく、依存関係を先に作る。

例:

```text
A
├-> B --┐
└-> C --┴-> D
```

- A完了後にB/C
- B/Cは独立なら並列
- Dは両方完了後

強く結合したファイルや循環依存は同じWriterへ寄せる。

将来ledgerで持ちたい候補:
- task_id
- dependency
- owner/agent
- base SHA
- branch/worktree
- state
- receipt/correlation
- result commit SHA
- validation state

---

## 6. AGENTS.md

repo-nativeなAgent指示ファイルを使う方向が有力。

Codex / Julesでは `AGENTS.md` 系のproject guidanceが利用可能。

Phase 0候補:

```text
AGENTS.md
  = provider共通のAgent契約

CLAUDE.md / provider-specific file
  = 必要なら薄いbridgeのみ
```

AGENTS.mdに入れる候補:
- architecture boundary
- build/test commands
- allowed paths
- prohibited operations
- branch/PR policy
- evidence requirements
- live-model prohibition
- completion/report contract

ただし、実際のselected runtimeごとのinstruction precedenceを先に確認してから採用する。

---

## 7. ACP

ACP = Agent Client Protocol

Coding Agentを共通のclient/server形式で扱うためのprotocol候補。

調査で確認した候補:
- `agentclientprotocol/codex-acp`
- `agentclientprotocol/claude-agent-acp`
- Gemini CLI ACP mode
- OpenHands external ACP agents

狙える形:

```text
Phase 0 Orchestrator
        |
        v
Phase 0 Safety / Live Gate
        |
        v
ACP-compatible Relay boundary
   |       |       |
 Codex   Claude   Gemini CLI
```

利点:
- providerごとのRelay plumbing自作量を減らせる可能性
- process / message envelopeを共通化しやすい

調査時点で見つかったlicense情報:
- codex-acp: Apache-2.0
- claude-agent-acp: Apache-2.0
- OpenHands: MIT

重要なUNKNOWN:
- 現プロジェクトはGoogle側でagy / Antigravityを使ってきた
- `agy / Antigravity ACP compatibility = UNKNOWN`
- Gemini CLIへ勝手に置換しない
- exact subscription/auth route compatibilityは実環境監査が必要

---

## 8. OpenHands

OpenHandsは、複数Coding Agentを扱う既存基盤として有力な参考/流用候補。

注目点:
- external agent server pattern
- ACP subprocess supervision
- provider abstraction
- structured communication
- Codex / Claude / Gemini CLI系連携

ただしPhase 0には大きすぎる可能性がある。

問いは:
> OpenHands全体を採用するか

ではなく:
> Relay / process / adapterのどの小さい部品だけ流用すると自作量を減らせるか

とする。

---

## 9. Open Orchestrator

Candidate:
- `gitpcl/openorchestrator`

調査で注目した機能:
- agentごとのgit worktree
- multiple AI tool support
- agent messaging
- conflict-aware workflow
- validation
- push / PR workflow

調査時点のlicense表示:
- MIT

監査必須:
- permission model
- retry semantics
- Windows behavior
- subprocess handling
- GitHub write behavior
- provider auth assumptions

---

## 10. conduct

Candidate:
- `ldlac/conduct`

注目点:
- isolated git worktree + branch per agent
- process output
- diff review
- optional push / PR
- mock agent
- Windows release

調査時点のlicense表示:
- MIT

Phase 0へ入れる場合:
- built-in merge/push等はそのまま使わず承認境界でwrap/disable
- auto side effectsを監査

---

## 11. multi-agent-orchestrator-skill

Candidate:
- `hyw007726/multi-agent-orchestrator-skill`

非常に近い要素:
- Claude / Codex / Gemini worker
- isolated worktrees
- scoped prompts
- reviewer agents
- coordination files
- structured state/events
- fake CLI tests
- live tests分離

coordination file ideas:
- `DECISIONS.md`
- `context.json`
- `CALLER_CONTEXT.md`
- review summary

Phase 0の
- `HANDOVER_CURRENT.md`
- architecture docs
- checkpoint/evidence
と発想が近い。

Critical incompatibility:
permission bypass / high-autonomy flagsの例を含む。

Phase 0では以下をコピーしない:
- `--dangerously-skip-permissions`
- `--dangerously-bypass-approvals-and-sandbox`
- `--yolo`
- 同等のapproval bypass
- automatic restart/retry defaults

結論:
- schemas / coordination / fake-CLI tests / handoff ideasは有力
- unsafe launch defaultsはreject

---

## 12. Stacked PR

依存した変更を、小さなPRのstackとして扱う方法。

```text
main
 <- PR A
      <- PR B
           <- PR C
```

使い分け候補:
- independent tasks -> parallel branches/worktrees
- dependent tasks -> stacked PR
- tightly coupled shared foundation -> single writer first

Phase 0では必須ではない。
private repo規模とGitHub UI/CLI運用を見て採否判断。

---

## 13. A2A

A2A = Agent-to-Agent protocol

大きな位置付け:
- ACP: controller/client <-> coding agent
- A2A: agent <-> agent / task / artifact exchange

Phase 0 dependencyにはしない。

ただし将来互換を意識して、ledger/message構造で以下を明示しておくのは有益:
- task_id
- state
- artifact
- message
- receipt
- correlation
- capability

---

## 14. 現時点で良さそうな全体構成

```text
                     Human
                       |
                       v
            Phase 0 Orchestrator
              /       |       \
             /        |        \
       Task DAG   SQLite Ledger  Safety Gate
             \        |        /
              \       |       /
                 Relay Layer
                     |
          ACP/custom adapter boundary
             /       |       \
          Codex    Claude    Google
             \       |       /
              isolated worktrees
                     |
              tests / evidence
                     |
              commit SHA
                     |
               reviewer(s)
                     |
                    PR
                     |
             Human-approved Merge
```

役割:
- GitHub = durable checkpoint/source history
- SQLite = active coordination ledger
- Relay = transport
- Orchestrator = dependency/controller
- worktree = writer isolation
- tests = verification
- commit SHA = handoff checkpoint
- PR = review boundary
- human = final integration authority

---

## 15. 自作を減らす方針

### 既存OSSを先に監査する部分
- git worktree management
- branch creation
- subprocess lifecycle
- ACP transport
- structured task envelope
- event/receipt ledger pattern
- agent status
- diff collection
- mock worker harness
- test fixtures
- AGENTS.md conventions

### Phase 0独自として保持する部分
- fail-closed fan-out gate
- secret / PII / private-code handling
- retry = 0
- no paid/API fallback
- billing/auth/permission UNKNOWN -> stop
- executed-model verification
- RAW-first evidence
- Provider Response Contract
- deterministic Council comparison
- safety-warning override
- human final decision
- first-5-case checkpoint

---

## 16. 「丸パクリ」方針の正確な意味

ユーザー方針:
> 1から全部作るより、公開されている安全な実装を土台にして改善したい。

採用する運用:
> OSS-first / reuse-first

ただし無監査copyではなく、候補ごとに:

1. license
2. exact reusable modules
3. dependencies
4. Windows support
5. subscription-login compatibility
6. API-key / paid-route assumptions
7. permission bypass
8. automatic retry/restart
9. Git write / merge behavior
10. destructive cleanup
11. secret handling
12. provider assumptions
13. test coverage
14. upstream maintenance

を確認する。

結果分類:
- direct dependency
- fork
- vendored small module + license notice
- design-only reimplementation
- reject

**Unlicensed / license UNKNOWN codeはコピーしない。**

---

## 17. 次Chatの監査優先順位

generic Relay / orchestratorを自作する前に:

1. ACP
2. codex-acp
3. claude-agent-acp
4. Gemini CLI ACP
5. OpenHands ACP agent/server pieces
6. Open Orchestrator
7. conduct
8. multi-agent-orchestrator-skill
9. CAID
10. AGENTS.md
11. stacked PR
12. A2A

Goal:

> Phase 0固定安全境界を壊さず、自作量を最小化する。

---

## 18. 借用コードに対する非交渉条件

reuse/forkしても以下は維持:

- no permission bypass
- no `--dangerously-*`
- no blind automatic retry
- no automatic model fallback
- no paid/API-key fallback
- no Billing/Credits/Overages mutation
- no settings/permission mutation
- no runtime GitHub write
- development GitHubは承認範囲のみ
- no automatic Merge
- no force push
- no branch deletion
- no live provider execution without explicit approval
- UNKNOWN safety boundary -> fail closed
- human final decision

候補OSSがこれと根本的に両立しない場合は、Phase 0安全を弱めず候補をrejectする。

---

## 19. CONFIRMED / UNKNOWN

### Research handover上のCONFIRMED
- central manager + isolated worktree/branch方式は複数先駆例に存在
- CAID public code exists
- OpenHands public code exists
- codex-acp / claude-agent-acp public code exists
- Gemini CLI has ACP mode
- Open Orchestrator public code exists
- conduct public code exists
- multi-agent-orchestrator-skill public code exists
- Codex / Julesでrepo-native instruction方式を利用できる
- GitHub stacked PR workflow exists
- A2A is an active future-facing agent protocol

### UNKNOWN / next audit
- agy / Antigravity ACP support
- exact reusable OpenHands modules
- exact Windows reliability in this user's environment
- exact subscription/auth behavior without API fallback
- CAID code reuse license
- best OSS combination
- ACPがPhase 0 lifecycle/receipt/model-verification要件を全部満たすか
- stacked PRがこの小規模private repoで本当に必要か
- current Relay prototypeの何割をupstreamで置換できるか

---

## 20. Final recommendation

新Chatは、generic multi-agent / Relay infrastructureをすぐ1から書き始めない。

先に:

```text
existing OSS inspection
-> license audit
-> safety diff
-> Windows/auth compatibility
-> reusable module identification
-> choose smallest safe base
-> implement only missing Phase 0-specific pieces
```

長期的に狙う形は:

> **central controller + isolated workers + structured state + Git checkpoints + executable verification + human final integration**
