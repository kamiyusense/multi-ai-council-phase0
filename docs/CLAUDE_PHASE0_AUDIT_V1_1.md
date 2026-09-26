# CLAUDE_PHASE0_AUDIT_V1 — Multi-AI Council Phase 0 / Relay:Anthropic・Claude経路の監査と安全設計

- 作成：Claude(Anthropic専門監査・安全設計担当)
- 作成日：2026-09-23(JST)
- 対象リポジトリ(概念上)：`kamiyusense/multi-ai-council-phase0`(**このリポジトリは読んでいません**。GitHubの読み書きはしていません)
- 作業方法：read-onlyのみ。live model turn、`claude -p`の実行、SDK/ACP経由の呼び出し、API keyの操作、設定変更、package install、GitHub書き込みはいずれも**一切行っていません**
- 想定読者：Sol(統括)、Jules(実装)、Work/Luna(検証・receipt)、Gemini(相互監査)

---

## 0. 要約

### 0.1 総合判定

**BLOCKED**(Phase 0 RelayからClaudeをlive起動する条件は満たされていません)

主なblocker(詳細は§31):

1. **retry=0を保証できない。** `CLAUDE_CODE_MAX_RETRIES`(上限15)の外側に、原因ごとの予算を持つ再送経路が複数あります。ストリーム無応答時の1回retry、ストリーム途中切断時の自動継続、非ストリーミングでの再送、idle watchdog、structured-output retry、advisor 400時の再送などです。現行sourceで「全経路が0になる」ことは確認できません(§7・§8)。
2. **「1 dispatch = 1 logical model turn」をClaude側が破る経路が確認されています。** 非対話モードで途中切断された応答の自動継続(v2.1.246)、background task完了時のmodel call(v2.1.274)、中断ターンの自動再実行(`CLAUDE_CODE_RESUME_INTERRUPTED_TURN`、`resume_reason`)があります(§15)。
3. **実際に実行されたモデルを独立して検証できません。** 手に入る証拠はすべてclient側の自己申告です(`system/init`、`modelUsage`、OTel `api_request`)。サブスク経路には、request単位のbackend証拠を利用者が取得する手段が見つかりませんでした(§10)。
4. **認証経路が実行中に変わりうることが確認されています。** 設定ファイルはhot reloadされ、`apiKeyHelper`も対象です。ACP側のコードコメントには「ターン間で資格情報が入れ替わる」前提が明記されています。また、`-p`/SDKでFableを使うと、usage creditsへの課金が**同意プロンプトなしで**行われます(§11・§12・§21)。

### 0.2 ユーザーが今やること

なし。人間が確認するのは「claude.ai > 設定 > 使用状況 > 使用クレジット = OFF」の目視だけで、これは2026-09-23 17:47 JSTのスクリーンショットで確認済みです(証拠E25)。

### 0.3 やってはいけないこと

- live起動
- `--resume` / `--continue` の使用
- `ANTHROPIC_API_KEY` の設定
- usage creditsをONにすること
- Fableモデル、`[1m]` 付きモデル、fast mode、advisorの有効化

### 0.4 モデル選択

**🔴 最終Go/No-Go判断は上位モデルで行ってください。** 本書を実装に落とす作業は、§27のテスト実装を中心に**🟢 軽量モデルで可**です。

### 0.5 この文書の読み方

各項目には、次の6つのうちどれか1つの判定語を付けています。

| 判定語 | 意味 |
|---|---|
| CONFIRMED | 一次資料または現行sourceで十分に確認できた |
| PARTIAL | 一部は確認できたが、完全な保証はできない |
| UNKNOWN | 証拠が足りない |
| BLOCKED | 現在のPhase 0のlive要件を満たせないことが確認された |
| FAIL | 要求と明確に矛盾する挙動が確認された |
| NOT_APPLICABLE | 今回の経路には該当しない |

**READYは使っていません。**

情報源どうしが食い違う箇所は、`DOCS:` / `SOURCE:` / `CHANGELOG:` / `CURRENT EFFECT:` に分けて書き、統合していません。

### 0.6 注意事項

- **依頼文の途中切れ：** 依頼文は「【30. Config Identity】… MCP confi」で切れていました。§30は切れていた部分を補って書いています。§31以降に予定されていた指示があったとしても、受け取っていません。
- **WebFetch要約の誤り：** 公式ドキュメントの取得に使ったWebFetchは、長いページでは要約・切り詰めを挟みます。実際に、存在しない表の行(`--restricted` と `--setting-sources` の説明)を作り出していたことを確認しました(E13を参照)。そのため、docsを根拠にする箇所のうち要約経由のものには **[docs/要約経由]** と付けています。原文の逐語照合が必要な場合は、実装担当が原文を読んで確認してください。

---

## 1. 証拠カタログ(Evidence IDs)

| ID | 証拠 | 版 / 取得日 | 優先度 |
|---|---|---|---|
| E01 | `anthropics/claude-code` の `CHANGELOG.md`。commit `56f3653`、tag `v2.1.280` | commit 2026-09-22T16:37Z | 2 |
| E02 | `anthropics/claude-agent-sdk-typescript` の `CHANGELOG.md`。tag `v0.3.280`、commit `58d2e4b` | 2026-09-22T16:38Z | 2 |
| E03 | `anthropics/claude-agent-sdk-python`。tag `v0.2.158`(commit `93332a3`)。`src/claude_agent_sdk/_cli_version.py` の値は `2.1.280`、`_internal/transport/subprocess_cli.py`、`types.py` | 2026-09-23T01:40Z | 2・3 |
| E04 | `agentclientprotocol/claude-agent-acp`。release `v0.81.0`(commit `d571358`、2026-09-22)と、未releaseのHEAD `281e47e`(tag `v0.81.1-preview.5`、2026-09-23)。対象は `src/acp-agent.ts`、`src/permissions/modes.ts`、`src/hide-claude-auth.ts`、`src/elicitation.ts`、`src/settings.ts`、`docs/model-configuration.md`、`package.json` | 同左 | 5 |
| E05 | `agentclientprotocol/agent-client-protocol` の `v1.9.1`(2026-09-18)。対象は `docs/protocol/v1/prompt-turn.mdx` | 同左 | 4 |
| E06 | docs「Environment variables」 https://code.claude.com/docs/en/env-vars (ページが長く途中で切れている) | 2026-09-23取得 | 1 |
| E07 | docs「Settings」「Settings reference」 | 2026-09-23 | 1 |
| E08 | docs「Model configuration」 | 2026-09-23 | 1 |
| E09 | docs「Authentication」 | 2026-09-23 | 1 |
| E10 | docs「Permission modes」(全文を保存) | 2026-09-23 | 1 |
| E11 | docs「Headless / -p」(全文) | 2026-09-23 | 1 |
| E12 | docs「Sessions」(全文) | 2026-09-23 | 1 |
| E13 | docs「CLI reference」。一部のみ取得。**1回目の要約で `--restricted` と `--setting-sources` の行を作り出し、2回目の逐語要求では「NOT FOUND」と返した** | 2026-09-23 | 1(要注意) |
| E14 | docs「Costs」(全文) | 2026-09-23 | 1 |
| E15 | docs「Advisor」(全文) | 2026-09-23 | 1 |
| E16 | docs「Fast mode」(全文) | 2026-09-23 | 1 |
| E17 | docs「Interactive mode」の「Wait for a usage limit to reset」節 | 2026-09-23 | 1 |
| E18 | docs「Legal and compliance」(全文) | 2026-09-23 | 1 |
| E19 | docs「Agent SDK overview」(全文) | 2026-09-23 | 1 |
| E20 | Help Center 11145838「Use Claude Code with your Pro or Max plan」 | 最終更新 2026-08-19 | 1 |
| E21 | Help Center 15036540「Use the Claude Agent SDK with your Claude plan」 | 最終更新 2026-06-16 | 1 |
| E22 | この作業環境にあった `@anthropic-ai/claude-code@2.1.42` の `cli.js`(公式npm配布物)を静的に読んだもの。**旧版で、リリース日はUNKNOWN**。`system/init` の項目として `apiKeySource`・`claude_code_version`・`model`・`permissionMode`・`tools`・`mcp_servers`・`session_id` を確認 | 2.1.42 | 3 |
| E23 | GitHub issue anthropics/claude-code #87930。題名「Regression in 2.1.228 … client silently falls back to non-streaming」。**題名のみで、本文とstaffの回答は未確認** | — | 6(弱) |
| E24 | docs「Agent SDK TypeScript reference」(途中で切れている) | 2026-09-23 | 1 |
| E25 | ユーザー提供のスクリーンショット「使用状況」。使用クレジットのトグルはOFF、残高1.58クレジット、9/13購入分の69%使用済み | 2026-09-23 17:47 JST | 人間確認 |
| E26 | docs「Monitoring usage(OpenTelemetry)」[docs/要約経由] | 2026-09-23 | 1 |

**アクセスできなかったもの(UNKNOWNの主な原因)：**

- npm registry(`npm view`、npmjs.com)がセキュリティポリシーで403になり、現行 `@anthropic-ai/claude-code@2.1.280` の実コードと、TS SDK `0.3.280` の実コードを取得できませんでした。
- Help Center 12429409(usage credits)は429エラーでした。
- Consumer Termsはfetchの承認待ちでタイムアウトしました。
- Phase 0の設計リポジトリは読んでいません。

**→ 現行Claude Code(2.1.280)の「source」を直接読んだ証拠はありません。** 現行版について言えるのは、DOCSとCHANGELOGの記述までです。実装を直接確認できたのはE22(2.1.42)、E03(Python SDK)、E04(ACP)だけです。

---

## 5. Version監査(2026-09-23時点で改めて確認)

| 対象 | 現行 | 日付 | 根拠 | 判定 |
|---|---|---|---|---|
| Claude Code(`anthropics/claude-code` のCHANGELOG先頭とtag) | **v2.1.280** | tag commit 2026-09-22T16:37Z | E01 | CONFIRMED(changelog/tag上の最新) |
| Claude Codeの「stable」チャネル版 | UNKNOWN | — | npmのdist-tagを取得できなかった | UNKNOWN |
| Claude Code v2.1.279 | Claude CodeのCHANGELOGに**記載なし**。TS SDKのCHANGELOGには「parity with v2.1.279」とある | — | E01・E02 | 情報源間で不一致(DOCS/CHANGELOG間) |
| Claude Agent SDK(TypeScript) | **v0.3.280** | 2026-09-22T16:38Z | E02 | CONFIRMED(changelog/tag) |
| Claude Agent SDK(Python) | **v0.2.158**(同梱CLIは2.1.280) | 2026-09-23T01:40Z | E03 | CONFIRMED |
| claude-agent-acp(release) | **v0.81.0** | 2026-09-22 | E04 CHANGELOG | CONFIRMED |
| claude-agent-acp(main HEAD) | v0.81.1-preview.5(`281e47e`) | 2026-09-23 | E04 | CONFIRMED(未release) |
| ACPが依存するAgent SDK | `@anthropic-ai/claude-agent-sdk` **0.3.280**(完全固定) | — | E04 package.json | CONFIRMED |
| ACPのTypeScriptライブラリ | `@agentclientprotocol/sdk` **1.5.0** | — | E04 package.json | CONFIRMED |
| ACPのprotocol / schema repo | agent-client-protocol **v1.9.1** | 2026-09-18 | E05 | CONFIRMED |
| 公式docs | 各ページに更新日の表示はない。本文中の最新版記載は v2.1.280 | 取得 2026-09-23 | E06〜E19 | PARTIAL(ページ単位の更新日はUNKNOWN) |

**前回報告の数字の見直し：**

- 「最新 v2.1.278」は、E01で**v2.1.280**に更新されました。
- 「ACP 0.79.0 / SDK 0.3.274」は、**ACP 0.81.0 / SDK 0.3.280**に更新されました。
- **ACPのmain HEADには、v0.81.0で `permissions.disableBypassPermissionsMode` が無視されていたことを修正するcommitが入っています(#1165、未release)。** 詳細は§17・§19。

**Phase 0への意味：** 1週間で約10版が進んでいます。**version pinとdrift検知を、preflightの必須項目にします。**

---

## 6. Version Drift監査(v2.1.42 → v2.1.280)

**方法：** E01のCHANGELOGから、v2.1.43〜v2.1.280の5,006項目を機械的に取り出し、キーワードで絞り込みました。**下の表は網羅ではなく、Phase 0の安全性に関係する主な変更です。** 同じ手順で再抽出する方法は§27のTEST L-03に書いています。

「OLD」の列は、E22(2.1.42の静的読解)で確認できた範囲です。

| # | 分野 | OLD(v2.1.42 / E22) | CHANGE(版・E01) | PHASE0への影響 | 再検証 |
|---|---|---|---|---|---|
| D01 | 最大retry回数 | `CLAUDE_CODE_MAX_RETRIES` の既定は10、上限なし。0を指定するとloopは1回 | 2.1.186で上限15に。2.1.199で `CLAUDE_CODE_RETRY_WATCHDOG` 下では上限なしになり、既定300回に。2.1.211で整数envに `1e6` 形式も受理 | 0の意味と、他経路への効き方がUNKNOWN | YES |
| D02 | 非ストリーミング再送 | streamが失敗するとnon-streamingで**再送**。server flag `tengu_disable_streaming_to_non_streaming_fallback` で制御 | 2.1.83で `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK` 追加。2.1.105で停滞したstreamも再送に。2.1.110/111で上限を付けて撤回。2.1.144で応答前の停滞は「streamingを1回やり直す」に変更。2.1.239でBedrockの「全ターン二重課金」を修正。issue #87930(2.1.228での退行) | 1 dispatchで2回以上のrequestが出る。envで止められる可能性はあるが、現行の効きはUNKNOWN | YES |
| D03 | stream idle watchdog | 不明(E22の範囲外) | 2.1.196で**全providerで既定ON**。5分無イベントならabortして**retry**。`CLAUDE_ENABLE_STREAM_WATCHDOG=0` で無効。2.1.210+で `CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS` | 暗黙の再送。無効化は可能 | YES |
| D04 | 無応答時のretry | — | 2.1.243で「約3分でtimeoutし、**1回retry**」。2.1.261で待ち時間が `API_TIMEOUT_MS` に | 原因ごとの予算。`MAX_RETRIES=0` が効くかはUNKNOWN | YES |
| D05 | 接続断のretry | — | 2.1.181で思考中の接続断をretry。2.1.198でECONNRESET等をbackoffつきでretry。2.1.214で新しいsocketでretry | 暗黙の再送 | YES |
| D06 | 途中切断応答の自動継続 | — | **2.1.246で「非対話セッション(`-p`・SDK・cloud)は、server error・接続断・停滞で途中切断された応答を自動で継続する」** | **one-dispatch-one-turnに直接抵触(追加のmodel request)** | YES |
| D07 | 429 | 429は `!O7()` の条件で(サブスクでない場合に)retry | 2.1.199で「使用量上限と無関係な一時的429を**サブスク加入者でも**自動retry」 | 暗黙の再送 | YES |
| D08 | 認証回復 | 401を受けるとOAuthを更新して**同じloop内で再送** | 2.1.225で一時的401が長期 `CLAUDE_CODE_OAUTH_TOKEN` を保存ログインで置き換える不具合を修正(=**認証経路が入れ替わる事象が実在した**)。2.1.246でapiKeyHelperの401/403を**無言でretry**。2.1.248でtoken refresh lock中はretryable error | 認証回復が再送を起こす | YES |
| D09 | fallback chain | 529を3回受けると、`fallbackModel` が設定されていれば切替 | 2.1.166で予期しない非retryable errorのとき「**fallback modelで1回retry**」。2.1.247でsubagentにもchainを適用。SDKの `system/model_fallback` は trigger `overloaded` / `server_error` / `last_resort` / `model_not_found` / `permission_denied` | chainを設定しない前提でも `last_resort` の意味はUNKNOWN | YES |
| D10 | 内容に基づくfallback | — | 2.1.219+でカテゴリ別に。`switchModelsOnFlag`(既定true)。-p/SDKでの扱いはDOCSとACPのコメントで記述が分かれる(§9) | 別モデルでの再実行 | YES |
| D11 | 中断ターンの再開 | — | 2.1.216(cloud)で中断ターンをresume時に再実行。2.1.221で `CLAUDE_CODE_RESUME_INTERRUPTED_TURN=0` を有効な値として扱うよう修正。2.1.269で `…_MAX_AGE_MS` と「6時間以上前のturnを再実行する」不具合を修正。SDKに `resume_reason` 追加 | 暗黙の再実行 | YES |
| D12 | SIGTERM | — | 2.1.212でBashのprocess treeをkillして143で終了。2.1.236で-p/SDKではSIGTERM時に中断ターンを**記録しない**ように。docs(E11)は「resumeするとSIGTERMで残ったturnを続ける」 | 記述の不一致(§16) | YES |
| D13 | background task | — | 2.1.274で「headless/SDKで、background task完了のたびにmodel call」を1回に集約 | 追加のmodel call | YES |
| D14 | cancel / interrupt | — | SDKに `interrupt_receipt_v1`(`still_queued`)、`cancel_queued`、`aborted: true`、`perTaskStopAffordance` 追加 | cancel後も処理が走り得ることを示す | YES |
| D15 | permission | — | 2.1.248で `--restricted` 追加(CHANGELOGでの説明とdocsの記述が不一致、§13)。2.1.259で `--permission-prompts none`。2.1.228(macOS/Linux)と2.1.233(Windows)でPro/Maxの対話端末の既定がauto mode | 起動モードの固定が必要 | YES |
| D16 | 設定の再読み込み | — | docs(E07)：settingsの変更は**実行中のsessionに適用**。`permissions`・`hooks`・`apiKeyHelper` も対象。2.1.271でmacOSのpolling fallback | 認証・権限が実行中に変わり得る | YES |
| D17 | 背景のHaiku | — | 2.1.277で「SDK/IDEの外から起動した `claude -p` ではHaikuの自動タイトルを廃止」。**SDKやIDEから起動した場合はUNKNOWN** | 別モデルの呼び出し | YES |
| D18 | advisor | — | 2.1.260で-p/SDKにも `/advisor`。2.1.275/276で400退行。2.1.280で「advisor tagが拒否されたら**advisorなしで再送**」 | 同一turn内で別モデル(server tool)を使う。再送もある | YES |
| D19 | 既定モデル | — | 2.1.280で**Proの既定がOpus 5.5**、`opus` aliasもOpus 5.5に。2.1.183で廃止予定モデルの自動差し替えを警告 | aliasの解決がversionで変わる | YES |
| D20 | fast mode | — | usage credits専用(E16)。拒否されたら**標準速度で再送** | 課金経路と再送 | YES |
| D21 | usage上限での自動継続 | — | 2.1.234で自動継続(**対話セッションのみ**。-pは対象外、E17) | -pではNOT_APPLICABLE | NO(-pでは対象外) |
| D22 | ACPのbypass | ALLOW_BYPASSは「rootでない」なら真 | #1129(0.77.0)でhostの `allowDangerouslySkipPermissions=false` を尊重。#1165(**未release**)で `disableBypassPermissionsMode` を尊重 | 0.81.0は設定を無視する | YES |
| D23 | ACPの対象SDK | 0.3.274(0.79.0) | 0.3.280(0.81.0) | pin対象 | YES |

---

## 7. retry経路の分解(A〜Z)

**列の意味：**

- 層：C=CLI、S=Agent SDK、A=ACP、V=Anthropic server
- 既定：既定の挙動
- 無効化：無効化の方法
- 回数：retry回数
- 追加req：provider requestが増えるか
- 観測：Phase 0から観測できるか
- 0保証：retry=0を保証できるか

| 経路 | 層 | 契機 | 既定 | 無効化 | 文書化 | 現行src | 回数 | 追加req | 観測 | 0保証 | 判定 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A. HTTP/API request retry | C | 一時的なAPI error | ON(2.1.42では10、現行上限15) | `CLAUDE_CODE_MAX_RETRIES`(現行docsでの記載は確認できず) | CHANGELOG D01 | 2.1.42のみ | ≤15 | YES | `system/api_retry`(E11) | NO | PARTIAL |
| B. stream接続のretry(応答前の停滞) | C | 応答前にstreamが止まる | ON(2.1.144: streamingを1回やり直す) | UNKNOWN | CHANGELOG | 無 | 1 | YES | api_retry(UNKNOWN) | NO | UNKNOWN |
| C. stream失敗後のnon-streaming再送 | C | stream error・停滞 | ON(D02) | `CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK`(CHANGELOG 2.1.83) | CHANGELOG・E23 | 2.1.42ではserver flagで制御 | ≥1 | YES | 専用eventはUNKNOWN。OTel `api_request` の件数で検出可 | NO | PARTIAL |
| D. 529 / 5xx | C | overloaded、server error | ON(Aの予算) | A | E11 `error: overloaded` | 2.1.42 | ≤15 | YES | api_retry | NO | PARTIAL |
| E. rate limit(429) | C | 使用量と無関係な429 | ON(2.1.199) | A(UNKNOWN) | CHANGELOG | 無 | UNKNOWN | YES | api_retry `rate_limit` | NO | PARTIAL |
| F. network timeout | C | `API_TIMEOUT_MS`、idle watchdog | ON(D03・D04) | `CLAUDE_ENABLE_STREAM_WATCHDOG=0`。無応答retryの無効化はUNKNOWN | E06・CHANGELOG | 無 | 1〜 | YES | api_retry `no_response`(E11、v2.1.261+) | NO | PARTIAL |
| G. 接続リセット | C | ECONNRESET等 | ON(D05) | UNKNOWN | CHANGELOG | 無 | UNKNOWN | YES | api_retry(`error_status: null`) | NO | UNKNOWN |
| H. OAuth更新後の再送 | C | 401 | ON | UNKNOWN | CHANGELOG D08 | 2.1.42(loop内で再送) | loop内 | YES | api_retry `authentication_failed` | NO | PARTIAL |
| I. 401 / 403からの回復 | C | apiKeyHelperの401/403 | 最初の2回は**event無し**で再送(E11) | apiKeyHelperを禁止(clean profile) | E11 | 無 | 2+ | YES | 3回目以降のみevent | NO(ただしapiKeyHelper禁止でN/A) | PARTIAL |
| J. auth helperの再取得 | C | TTL 5分、失敗時 | ON | apiKeyHelperを禁止 | E09 | 無 | ≤3 | 無(認証のみ) | — | — | NOT_APPLICABLE(clean profileでは) |
| K. 下層SDK(@anthropic-ai/sdk)のretry | C内部 | — | 2.1.42では主経路が `maxRetries:0` | — | 無 | 2.1.42のみ | 0(旧) | — | — | 現行はUNKNOWN | UNKNOWN |
| L. CLI本体のretry | C | =A〜H | — | — | — | — | — | — | — | NO | PARTIAL |
| M. Agent SDK側のretry | S | — | Python SDKにmodel request retryは無し(E03をgrep。retryはtranscript mirrorとrmtreeだけ) | — | — | Python: CONFIRMED。TS: UNKNOWN | 0 | 無 | — | Python: YES | CONFIRMED(Python)/UNKNOWN(TS) |
| N. claude-agent-acp側のretry | A | 認証回復時のquery再作成 | promptの自動再送は見つからず。**sign-out後の再作成で「保存済み会話をresume」**(E04 hide-claude-auth.tsのコメント) | clean profileでACPを使わない | E04 | CONFIRMED(static) | 0〜1 | 条件付きで有 | — | NO | PARTIAL |
| O. serverが指示するretry | V・C | `x-should-retry` header(2.1.42)、server feature flag | ON | 不可(D02の旧flagはserver側) | 無 | 2.1.42 | — | YES | 無 | NO | UNKNOWN |
| P. tool失敗後のmodel再呼出 | C | tool結果の返却 | agentic loopで**毎回新しいrequest** | tool無効化 + `--max-turns 1` | E11 | — | tool数に依存 | YES | stream上の `tool_use` | 条件付き | PARTIAL |
| Q. 分類器による再実行 | C・V | safety classifierのflag | `switchModelsOnFlag=true`(既定) | `switchModelsOnFlag:false`(`--settings` で当該sessionだけ) | E08 | 無 | 1 | YES(別モデル) | UNKNOWN(`system/model_fallback` かどうか) | NO | PARTIAL |
| R. model fallback chain | C | overload / unavailable | **既定OFF**(E08) | `--fallback-model` と `fallbackModel` を設定しない | E08 | 2.1.42 | ≤3 model | YES | `system/model_fallback`(E02) | 条件付き | PARTIAL(`last_resort` がUNKNOWN) |
| S. session resume | C | `--resume` / `--continue` | 明示したときだけ | 使わない + `--no-session-persistence` | E12 | — | — | YES | — | YES(運用で) | CONFIRMED(制御可) |
| T. 中断ターンの再開 | C | host再起動、resume | 既定値はUNKNOWN | `CLAUDE_CODE_RESUME_INTERRUPTED_TURN=0`(2.1.221+) + 永続化なし | CHANGELOG・E02 | 無 | 1 | YES | `resume_reason`(E02) | 条件付き | PARTIAL |
| U. background agentのretry | C | background taskの完了 | 完了時にmodel call(D13) | tool禁止(Agent・Bash・Monitor) | CHANGELOG | 無 | — | YES | `task_notification` | 条件付き | PARTIAL |
| V. subagentのretry | C | subagentの404等 | chainを適用(2.1.247) | Agent toolを禁止 | CHANGELOG | 無 | — | YES | `tool_progress.subagent_retry` | 条件付き | PARTIAL |
| W. MCP / toolのretry | C | MCP接続 | 再接続retry(2.1.121/191/243) | MCPを禁止 | CHANGELOG | 無 | ≤3 | 無(model以外) | `mcp_servers` | — | NOT_APPLICABLE(clean profileでは) |
| X. permission後の再request | C | 拒否結果の返却 | 拒否結果を渡して継続 | `--permission-prompts none`(再試行するなと指示) + tool禁止 | E11 | 無 | — | YES | `permission_denied` | 条件付き | PARTIAL |
| Y. compaction後の再request | C | contextが上限に近い | auto-compactと、失敗時の上限3回(2.1.76) | 短いpromptなら発生しにくい(保証なし) | CHANGELOG | 無 | ≤3 | YES | UNKNOWN | NO | UNKNOWN |
| Z1. 途中切断応答の自動継続 | C | 非対話で応答が途中で切れた | **ON(2.1.246)** | **不明** | CHANGELOG | 無 | UNKNOWN | YES | UNKNOWN | NO | **FAIL**(要求と矛盾する挙動を確認) |
| Z2. advisor拒否後の再送 | C | 400 advisor tag | ON(2.1.280) | `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1`(E15) | E15・CHANGELOG | 無 | 1 | YES | UNKNOWN | 無効化すれば成立 | PARTIAL |
| Z3. fast modeの標準速度再送 | C | fast modeの拒否 | ON(E16) | `CLAUDE_CODE_DISABLE_FAST_MODE=1` | E16 | 無 | 1 | YES | `system/notification` | 無効化すれば成立 | PARTIAL |
| Z4. structured outputのretry | C | `--json-schema` 違反 | ON(`error_max_structured_output_retries` が存在、E02) | `--json-schema` を使わない | E02 | 無 | UNKNOWN | YES | `terminal_reason` | 不使用なら成立 | PARTIAL |
| Z5. 永続retry(watchdog) | C | `CLAUDE_CODE_RETRY_WATCHDOG` | OFF(明示時のみ) | 環境変数として禁止 | CHANGELOG・E02 | 無 | 既定300 | YES | api_retry heartbeat、`rate_limit_event` | 禁止で成立 | CONFIRMED(禁止対象) |
| Z6. 大きすぎる画像を除去して再送 | C | 画像が過大 | ON(2.1.126) | 画像を入れない | CHANGELOG | 無 | 1 | YES | UNKNOWN | 不使用で成立 | PARTIAL |
| Z7. malformed tool call後のretry | C | tool呼出が壊れている | ON(2.1.251) | tool禁止 | CHANGELOG | 無 | UNKNOWN | YES | `terminal_reason` | 条件付き | PARTIAL |
| Z8. usage上限での自動継続 | C | usage limit | 対話のみON(E17) | -pを使う | E17 | — | ≤2 | YES | — | — | NOT_APPLICABLE(-pでは) |

**結論(§7)：** Claude Codeには「retry=0」を一括で強制する公開スイッチがありません。無効化の手段が確認できない経路も残っています(B、G、Y、Z1)。**→ BLOCKED。**

Phase 0側で取れる現実的な対策：

- 「retryが起きないこと」を前提にしません。「**2回目以降のrequestを検出したら、そのdispatchの結果を不採用にし、再dispatchしない**」という**検出してfail-closedにする方式**に切り替えます。
- 検出には `system/api_retry`、OTel `api_request` の件数、`modelUsage` のモデル数、`system/model_fallback`、`resume_reason` を使います。

---

## 8. `CLAUDE_CODE_MAX_RETRIES` の徹底監査

| 質問 | 結果 | 根拠 | 判定 |
|---|---|---|---|
| 現行sourceに存在するか | 現行sourceは読めていない。CHANGELOGには2.1.186(上限15)、2.1.199(watchdog下で上限解除)とある | E01 | PARTIAL(CHANGELOGでは存在、sourceは未確認) |
| public docsに存在するか | env-varsページは途中で切れているため確認できない。取得できた範囲には無い | E06 | UNKNOWN |
| 正式にサポートされているか | CHANGELOGで挙動が変更されている以上、存在はしている。docsでの位置づけはUNKNOWN | E01 | PARTIAL |
| 0を受け付けるか | 2.1.42では、文字列"0"がtruthyなので `parseInt` で0になり、loopは1回だけ回る | E22 | CONFIRMED(2.1.42)/UNKNOWN(現行) |
| 0の意味 | 2.1.42では「追加試行0回で、初回requestは1回行う」 | E22 | CONFIRMED(2.1.42) |
| 0にしても初回requestは1回出るか | 出る(2.1.42) | E22 | CONFIRMED(2.1.42) |
| 0にしても別のretry経路が残るか | **残る**。2.1.42でもnon-streaming再送は同じ関数を別に呼んでいた。現行ではD02〜D08・D18・D20・Z1 | E22・E01 | **CONFIRMED(残る)** |
| stream fallbackに効くか | 2.1.42ではnon-streaming側も同じ関数(同じ予算の別インスタンス)を使っていた。現行はUNKNOWN | E22 | UNKNOWN |
| auth recoveryの再送に効くか | 2.1.42ではloopの範囲内。現行はUNKNOWN | E22 | UNKNOWN |
| classifier rerunに効くか | 別の仕組みなので効かない可能性が高いが、根拠は無い | — | UNKNOWN |
| model fallbackに効くか | 2.1.42では529の数え方は独立(3回) | E22 | UNKNOWN(現行) |
| timeout retryに効くか | E11に「`no_response` では `max_retries` はこの原因の1回を表し、全体の予算ではない」とある | E11 | **効かない可能性が文書化されている → FAIL方向のPARTIAL** |
| Agent SDK経由でも効くか | SDKはCLIを子processとして起動し、環境変数を渡す(Python: `process_env = {**os.environ, …, **options.env}`) | E03 | PARTIAL(渡ることは確認。効き方はA次第) |
| ACP経由でも効くか | ACPは `env = {...process.env, ...}` を渡す | E04 | PARTIAL |
| server側が制御するretryに効くか | 効かない(client設定なので) | 構造上 | UNKNOWN |

**結論：** `CLAUDE_CODE_MAX_RETRIES=0` は「A経路の予算を0にする**かもしれない**」だけで、Phase 0のretry=0と同じ意味にはなりません。**判定：PARTIAL(単独では要件を満たさない)**

---

## 9. モデルが変わる経路の分解

| 経路 | 既定 | 無効化 | 検出(output/event) | modelUsage | backendの独立証拠 | Phase 0で拒否できるか | blocker | 判定 |
|---|---|---|---|---|---|---|---|---|
| 明示した `--fallback-model` | OFF | 指定しない。preflightで指定を拒否 | `system/model_fallback` | 見える | 無 | YES | 無 | CONFIRMED(E08・E02) |
| 既定のfallback chain(`fallbackModel` 設定) | 未設定ならOFF | 設定のどの層にも無いことを確認。`--settings` で空にできるかはUNKNOWN | 同上 | 見える | 無 | YES(設定の監査で) | 無 | PARTIAL |
| 容量・overloadによるfallback | chainが無ければ切替えずにretry(E08) | 同上 | api_retry `overloaded` | — | 無 | YES | 無 | PARTIAL(`last_resort` がUNKNOWN) |
| region fallback | 情報なし | — | — | — | 無 | — | — | UNKNOWN |
| safety classifierによる再実行 | `switchModelsOnFlag=true`(既定) | `false` にする | UNKNOWN | 見える(別モデルが加わる) | 無 | modelUsageで事後に検出 | **有** | PARTIAL。DOCS:「非対話でpromptを出せない統合ではrefusalで終了」(false時の記述)。ACPのsource:「未宣言のdialog種別ではCLIはfail-closedでrefusal errorになる」。**true時に-pでどうなるかはUNKNOWN** |
| policy classifierによる再実行 | auto modeでのみ | auto modeを使わない | — | 分類器のモデル(Sonnet 5)が加わる | 無 | YES | 無 | CONFIRMED(E10) |
| auto mode | -p/SDKの既定はManual(E10) | `--permission-mode default` / `dontAsk` | `system/init` の `permissionMode` | 分類器のモデル | 無 | YES | 無 | CONFIRMED |
| 背景のHaiku | 2.1.277で「SDK/IDE外から起動した-p」では自動タイトル廃止。E14:resume用の要約jobがある | 永続化なし。SDK経由はUNKNOWN | modelUsage | 見える | 無 | 事後検出 | 有(SDK経由) | PARTIAL |
| subagentのモデル | 親のモデルを継承、または定義で指定 | Agent toolを禁止 | `parent_tool_use_id` | 見える | 無 | YES | 無 | CONFIRMED(tool禁止時) |
| tool固有のモデル(WebSearch・WebFetch要約など) | WebFetchは内部で要約モデルを使う可能性がある | WebFetch・WebSearchを禁止 | — | 見える可能性 | 無 | YES | 無 | UNKNOWN(モデル名) |
| 要約・compactionのモデル | 本体と同じ。条件によって縮小なし(E08) | 短いprompt | — | — | 無 | 事後 | 低 | PARTIAL |
| fast mode | OFF(usage creditsが必要) | `CLAUDE_CODE_DISABLE_FAST_MODE=1` | `system/notification` | speedの区別はUNKNOWN | 無 | YES | 無 | CONFIRMED(E16) |
| model aliasの解決 | `opus` → Opus 5.5(2.1.280)。versionで変わる | **フルIDで固定**(`claude-opus-5-5` 等) | `system/init.model` | `canonicalModel`(E02) | 無 | YES | 無 | CONFIRMED(E08) |
| server側のmodel routing | 情報なし | — | — | — | 無 | 不可 | 有 | UNKNOWN |
| モデル廃止・差し替え | 「自動で新モデルに更新」の警告(2.1.183)、Fable IDのalias自動変換(2.1.257) | pinとdrift検知 | stderrの警告、`(auto-updated)` | 見える | 無 | YES(警告で停止) | 無 | PARTIAL |
| advisor(server tool) | OFF(明示が必要) | `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1` | UNKNOWN | UNKNOWN | 無 | YES | 無 | CONFIRMED(E15) |
| `opusplan` | 明示時のみ | 使わない | — | 見える | 無 | YES | 無 | CONFIRMED |
| 実行中の `set_model`(SDKの制御request) | host次第 | SDKのhostで送らない | — | 見える | 無 | YES | 無 | CONFIRMED(2.1.212) |
| 組織の既定モデルへの無言の切替(不具合) | 2.1.268で修正 | pin | — | 見える | 無 | 事後 | 低 | PARTIAL |
| ACP側のモデル対応付け | `CLAUDE_MODEL_CONFIG` の `modelOverrides` / `availableModels` | ACPを使わないか、設定を固定 | — | 見える | 無 | YES | 無 | CONFIRMED(E04 docs) |
| Fableの同意prompt | **-p/SDKではpromptを出さずに課金**(E08) | Fableを禁止し、usage creditsをOFFに | — | 見える | 無 | YES | **有(課金)** | CONFIRMED |

**結論：** どの経路も、backendの独立証拠がありません。**Phase 0が「実際に実行されたモデル」を要件にする限りBLOCKED**です。自己申告を使った「不一致なら不採用」の検出方式までなら、PARTIALで設計できます。

---

## 10. モデル同一性の検証

| 層 | 取得元 | 性質 | 最大到達 |
|---|---|---|---|
| REQUESTED_MODEL | Relay自身が渡す `--model` のフルID | Phase 0の自己記録 | CONFIRMED |
| RESOLVED_MODEL | `system/init.model`(E11) | CLIの自己申告 | SELF_REPORTED |
| REPORTED_MODEL | 以下の3つ。①streamの `assistant.message.model`(APIのresponseをCLIが転送したもの。構造はAPI準拠と推定されるが、Claude Code docsで逐語確認はしていない)。②OTel `api_request.model` と `request_id`(E26[要約経由])。③`OTEL_LOG_RAW_API_BODIES=file:<dir>` によるresponse JSON全体(E26) | CLIが中継したAPI response | SELF_REPORTED(client経由) |
| EXECUTED_MODEL | 利用者が取得できるbackend側の記録は見つからない | — | **UNKNOWN / 取得不能** |
| BILLED_MODEL | サブスク：claude.aiの使用状況は割合のみでモデル別request明細は無い(E25)。`/usage` はローカル履歴からの近似(E14)。API課金なら、Console Usageのモデル別集計が別経路の証拠になりうる(E14)が、**Phase 0はAPI課金を禁止**しているので使えない | — | **UNKNOWN** |

**一致の判定ルール(提案)：**

```
MODEL_IDENTITY_STATE =
  SELF_CONSISTENT   if REQUESTED == init.model
                       == every assistant.message.model
                       == keys(modelUsage) == {REQUESTED}
                       and 0 model_fallback events
                       and count(OTel api_request) == 1
  MISMATCH          if 上記のどれかが不一致(→ 結果を不採用。再dispatchしない)
  INCOMPLETE        if どれかの証拠が欠けている(→ 不採用)
```

`INDEPENDENTLY_VERIFIED` は**付与できない**ことを仕様として明記します。判定はUNKNOWNです。

---

## 11. 認証・課金経路の監査

**優先順位の出典：** E09の「Authentication precedence」を逐語で取得しています。

| # | route | 優先 | 誰が選ぶか | 起動前に検出 | 実行中の変更 | hot reload | fallbackしうるか | subscription-only preflight | API課金 | 追加credits | 自己申告の証拠 | 独立証拠 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R0 | Claude apps gateway session | 最上位(一覧の外) | managed settings / `/login` | settings + `/status` | — | managed | — | **拒否** | 有 | 有 | `/status` | 無 |
| R1 | Bedrock / Vertex / Foundry(`CLAUDE_CODE_USE_*`) | 1 | env | env | env注入で可 | settingsの `env` ブロック | — | **拒否** | 有(cloud) | — | `apiProvider`(E04) | cloud請求 |
| R2 | `ANTHROPIC_AUTH_TOKEN` | 2 | env | env | settings env | 可 | — | **拒否** | 有 | — | `tokenSource` | 無 |
| R3 | `ANTHROPIC_API_KEY` | 3 | env | env | settings env | 可 | **-pでは常に使用**(E09) | **拒否** | **有** | — | `apiKeySource=ANTHROPIC_API_KEY` | Console |
| R4 | `apiKeyHelper` | 4 | settings(全層) | settings | **可**(hot reload対象、E07) | 可 | 401で再実行 | **拒否** | 有 | — | `apiKeySource=apiKeyHelper` | — |
| R5 | `CLAUDE_CODE_OAUTH_TOKEN`(setup-token) | 5 | env | env | settings env | 可 | 過去に一時的401でstoredに置換される不具合(2.1.225) | **原則拒否**(サブスクだが長期tokenの漏洩リスク。Phase 0の方針次第) | 無 | 有(credits ONなら) | `tokenSource` | — |
| R6 | Anthropic profile / WIF(`ANTHROPIC_PROFILE`、federation) | 6(`user_oauth` はR7の下) | env・file | env + `~/.config/anthropic` / `%APPDATA%\Anthropic` | file置換で可 | — | — | **拒否** | 有(Console) | — | `/status` の `Profile` 行 | — |
| R7 | claude.ai OAuth(`/login`、`.credentials.json`) | 7 | 利用者 | `/status`、`system/init` | refresh | — | 自動refresh | **唯一許可** | 無 | **有(credits ON時、Fable・1M・fast)** | `subscriptionType`、`apiKeySource=none` | claude.aiの使用状況(集計のみ) |
| R8 | `/login managed key`(Consoleログインで作ったkey) | R3/4相当 | `/login` | `apiKeySource` | — | — | — | **拒否** | 有 | — | `apiKeySource=/login managed key` | Console |
| R9 | Agent SDKの認証 | CLIに従う | env・options.env | 同上 | TS SDKでは `options.env` がprocess.envを**置換**、Python SDKは継承 | — | — | 上記に準ずる | — | — | init | — |
| R10 | ACPの認証 | CLIに従う + `authenticate` / `providers/set` | ACP client | `_meta` | **ターン間で入れ替わり得る**(E04) | settings watch | gateway | **拒否**(gateway/provider設定) | 有 | — | account(initializeで固定) | — |
| R11 | managed settings(`C:\Program Files\ClaudeCode\managed-settings.json` 等) | 設定の最上位 | 管理者(本人PCでは本人) | ファイル | reload | 可 | — | 検査対象 | — | — | `/status` の Skipped sources | — |
| R12 | keychain / cached OAuth | R7の保存先 | — | — | refresh | — | — | R7として扱う | — | — | — | — |
| R13 | `--bare` の認証 | **OAuthもkeychainも読まない**(E11) | — | — | — | — | — | **サブスクと両立しない** | — | — | — | — |

**「usage creditsがOFFならAPI課金経路は無い」は誤りです。** R1〜R4・R6・R8は、usage creditsの設定と**無関係に**課金されます。usage creditsのトグルが止めるのは、R7(サブスク)の上限を超えた分と、Fable・1M・fast modeの課金だけです。後者は -p では同意promptなしで課金されます(E08・E16)。

**判定：** route R7だけを使うように制御することはPARTIALです(起動時の検出は可能だが、実行中は§12の理由で保証できない)。

---

## 12. 認証driftとhot reloadの監査

「起動前は安全 → 実行中に変化 → 別の認証route」という流れが起こりうるかを確認しました。

| 変化の入口 | 可能性 | 根拠 | 判定 |
|---|---|---|---|
| `settings.json` のhot reload(user・project・local) | **有**。「実行中のsessionに、`permissions`・`hooks`・`apiKeyHelper` を含めて適用」 | E07 | CONFIRMED |
| managed settingsのreload | **有**。管理元から届いた設定は実行中のsessionにも効く(例：auto mode解除) | E10・E07 | CONFIRMED |
| 設定の `env` ブロック経由のenv注入 | 有。settingsの `env` はsubprocessのenvの**後に**適用される | E04のコメント、E02 | CONFIRMED |
| `apiKeyHelper` | TTL 5分で再実行。出力が変われば資格情報も変わる | E09 | CONFIRMED |
| token / OAuthのrefresh | 自動。一時的401で資格情報が置換された不具合がある(2.1.225で修正) | E01 | PARTIAL |
| ファイル上の資格情報の入れ替え(ターン間) | **有**。ACPのコメント:「A file-based credential replaced by a subscription between two turns」。SDKはinitialize時のaccountを**memoize** | E04 | CONFIRMED(ターン境界での入れ替わり) |
| plugin・MCPの設定 | hooksがコマンドを実行できる(同じ権限で) | E11 | PARTIAL |
| shell wrapper / PATH | `claude` がwrapperになっている可能性 | 一般論 | UNKNOWN |
| 親processのenv | SDKもACPも継承する(Python: `os.environ` を継承。ACP: `...process.env`) | E03・E04 | CONFIRMED |

**結論：起動時だけの検証では不十分です(BLOCKED要因)。** 必要な対策：

1. **freeze：** 専用の `CLAUDE_CONFIG_DIR`(使い捨て)を使い、user・project・local設定が存在しない状態で起動します。環境変数はallowlistだけを渡し、`env -i` 相当にします。
2. **monitor：** 実行中に、settingsの全パス、`.credentials.json`、`~/.config/anthropic`、managed settingsのmtimeとhashを監視します。変化したら **INVALIDATE**(不採用)にします。
3. **post-verify：** 終了後に、`system/init` の `apiKeySource=none`・`subscriptionType` あり・`tokenSource` なし・`apiProvider=firstParty` を確認し、さらに事後のhashが事前と一致することを確認します。
4. 1 dispatch = 1 process(使い捨て)とし、同じprocessで2回目のpromptを送りません。

---

## 13. `-p`(通常)/`--bare`/`--restricted` の比較

| 項目 | `-p`(通常) | `--bare -p` | `--restricted`(2.1.248+) |
|---|---|---|---|
| サブスクのOAuth | 使える | **使えない**(OAuthもkeychainも読まない。E11) | UNKNOWN(CHANGELOGは「settings filesを無視」とだけ書いていて、資格情報への言及は無い) |
| API key | 使う(存在すれば**常に**使う) | 必須(`ANTHROPIC_API_KEY` かapiKeyHelper) | UNKNOWN |
| user / project / local settings | 読む(`-p` ではtrust dialog無しでproject hooksも実行、E11) | 自動探索しない(`--settings` は可) | CHANGELOG:**無視**。DOCS:逐語は取得できず(E13) |
| managed settings | 読む | 読む(UNKNOWN) | UNKNOWN |
| hooks | project含めて実行 | skip | settings由来は無視(CHANGELOG) |
| MCP(`.mcp.json`) | 接続する | skip | UNKNOWN |
| plugins / skills / commands | 読む | skip(`--add-dir` のskillsは例外) | UNKNOWN |
| CLAUDE.md / auto memory | 読む | skip | UNKNOWN |
| AGENTS.md | UNKNOWN | UNKNOWN | UNKNOWN |
| cwdの内容 | tool次第 | tool次第 | fileツールはcwd内のみ |
| trust prompt | **出ない**(-pは未trustでもhooksと `.mcp.json` を実行、E11) | — | — |
| permissions | `default`(Manual) | 同左 | bypass拒否 |
| tools | 全部 | Bash・Read・Edit | コマンド実行系とWebFetchを除去(CHANGELOG)。DOCS:UNKNOWN |
| session永続化 | ON(`--no-session-persistence` でOFF) | 同左 | 同左 |
| background agents | 可 | 可 | UNKNOWN |
| ブラウザ連携 | 可 | UNKNOWN | UNKNOWN |

**DOCSとCHANGELOGの不一致(`--restricted`)：**

- CHANGELOG(2.1.248)：「コマンドやコードを実行する組込toolとWebFetchを除去し、fileツールはcwd内に限定、bypassPermissionsを拒否し、user・project・local settingsを無視する」
- DOCS(E10)：「`--restricted` で始めたsessionはbypassPermissionsを拒否」は逐語で確認。tool構成の記述は、逐語要求ではNOT FOUND(E13)
- CURRENT EFFECT：UNKNOWN

**Phase 0向け最小構成案(実行はしない)：**

```
CLAUDE_CONFIG_DIR=<使い捨てdir、中身は.credentials.jsonのコピーのみ(※)>
cwd=<空の使い捨てdir(gitなし)>
claude -p
  --model <フルID>
  --tools ""            (UNKNOWN:空指定の可否。§14参照)
  --disallowedTools "*"
  --permission-mode dontAsk
  --permission-prompts none
  --no-session-persistence
  --max-turns 1
  --output-format stream-json --verbose
  --settings '<CLAUDE_CLEAN_ENV_V1のJSON>'
```

(※) 資格情報ファイルをコピーする方式は、**Anthropic docsで想定されている運用かどうかがUNKNOWN**です。§22とも関係します。代わりに `claude setup-token` で得た `CLAUDE_CODE_OAUTH_TOKEN` を使う方式もありますが、**長期tokenの扱いは秘密情報の管理にあたり、人間の承認が必要**です。

`--restricted` の併用は、DOCSでtool構成を逐語確認できるまで**保留**します(UNKNOWN)。

---

## 14. CLAUDE_CLEAN_ENV_V1(仮想profile)

```yaml
profile: CLAUDE_CLEAN_ENV_V1
env:
  allow_only:            # これ以外の環境変数は子processに渡さない
    - PATH               # 固定の最小値にする(§23 T17)
    - HOME / USERPROFILE # 使い捨てdirに向ける
    - CLAUDE_CONFIG_DIR  # 使い捨てdir
    - SystemRoot, TEMP, TMP (Windows必須分)
    - CLAUDE_CODE_MAX_RETRIES=0
    - CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK=1   # CHANGELOG 2.1.83。docsでの確認はUNKNOWN
    - CLAUDE_ENABLE_STREAM_WATCHDOG=0               # CHANGELOG 2.1.196
    - CLAUDE_CODE_RESUME_INTERRUPTED_TURN=0         # CHANGELOG 2.1.221
    - CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1            # E15
    - CLAUDE_CODE_DISABLE_FAST_MODE=1               # E16
    - CLAUDE_CODE_SKIP_PROMPT_HISTORY=1             # E13(no-session-persistence相当)
    - CLAUDE_CODE_ENABLE_TELEMETRY=1                # 証拠用(OTelをローカルにconsole/file出力)
    - OTEL_LOGS_EXPORTER=console                    # 外部送信しない
  deny_if_present (1つでもあればFAIL_CLOSED):
    - ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL
    - ANTHROPIC_PROFILE, ANTHROPIC_FEDERATION_RULE_ID, ANTHROPIC_ORGANIZATION_ID
    - CLAUDE_CODE_USE_BEDROCK, CLAUDE_CODE_USE_VERTEX, CLAUDE_CODE_USE_FOUNDRY
    - ANTHROPIC_AWS_API_KEY, AWS_BEARER_TOKEN_BEDROCK, ANTHROPIC_FOUNDRY_*
    - CLAUDE_CODE_RETRY_WATCHDOG
    - ANTHROPIC_MODEL, ANTHROPIC_DEFAULT_*_MODEL, ANTHROPIC_SMALL_FAST_MODEL, CLAUDE_CODE_SUBAGENT_MODEL
    - FALLBACK_FOR_ALL_PRIMARY_MODELS          # 存在するだけで有効になる(E06)
    - CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST, CLAUDE_CODE_USE_GATEWAY
    - IS_SANDBOX, CLAUDE_CODE_EXECUTABLE (ACP)
    - CLAUDE_CODE_OAUTH_TOKEN                   # Phase 0の方針で許可しない限り
    - NODE_OPTIONS, NODE_EXTRA_CA_CERTS (UNKNOWN扱い。予期しない注入を避ける)
settings (--settings で当該sessionだけに渡す。user設定は書き換えない):
  switchModelsOnFlag: false
  fallbackModel: []            # 空配列で無効になるかはUNKNOWN → 「設定のどこにもfallbackModelが無い」ことをpreflightで確認
  autoContinueAtUsageLimit: false
  fastMode: false
  permissions: { defaultMode: "dontAsk", disableBypassPermissionsMode: "disable", deny: ["*"] (構文はUNKNOWN) }
  disableAutoMode: "disable"
  enableAllProjectMcpServers: false (UNKNOWN key)
deny_config_sources:
  - <cwd>/.claude/**, <cwd>/.mcp.json, <cwd>/CLAUDE.md, <cwd>/AGENTS.md → cwdを空にするので存在しない
  - user設定 → CLAUDE_CONFIG_DIRを使い捨てにして存在しない状態にする
  - managed settings → 存在したら内容をhashしてblock判定(本人PCにある場合は内容を監査)
forbid:
  hooks: all
  mcp: all ( --strict-mcp-config + 空の --mcp-config の組合せが有効かはUNKNOWN )
  plugins / skills / slash commands: --disable-slash-commands
  resume / continue / fork / session-id reuse: 禁止
  fallback: 禁止
  api routes: R0-R6, R8(§11)
fix:
  model: フルID(例:claude-opus-5-5 または claude-sonnet-5)。aliasは禁止。[1m]は禁止。Fableは禁止
  permissions: dontAsk + permission-prompts none
  cwd: 空の使い捨てdir
  tools: 無し(Phase 0でClaudeは「読む・答える」だけ。入力はprompt本文で渡す)
  retry: CLAUDE_CODE_MAX_RETRIES=0 + 検出したらfail-closed
  timeout: API_TIMEOUT_MS=固定値(例:600000)。Relay側のwall-clock上限 > API_TIMEOUT_MS
unknown:
  - --tools "" の受理可否
  - fallbackModel: [] の意味
  - --restricted の現行のtool構成
  - 新しいenv名の現行docsでの記載
```

---

## 15. session永続化とresumeの監査

| 項目 | 既定 / 挙動 | 根拠 | 「1 dispatch = 1 fresh turn」との衝突 | 判定 |
|---|---|---|---|---|
| 永続化の既定 | ON。`~/.claude/projects/<proj>/<id>.jsonl` に書く | E12 | 衝突(resume可能な状態が残る) | CONFIRMED |
| `--no-session-persistence` | -pのみ。保存せず、resumeもできない | E13(逐語) | 解消 | CONFIRMED |
| `--resume` / `--continue` | 明示したときだけ。-pのsessionはpickerに出ないが、IDを指定すれば再開できる | E12 | 衝突 | CONFIRMED(禁止で回避可) |
| 中断ターンの自動再開 | `CLAUDE_CODE_RESUME_INTERRUPTED_TURN`、`resume_reason`(「host再起動で中断されたturnの自動再実行」) | E01・E02 | **衝突** | PARTIAL(既定値はUNKNOWN) |
| SIGTERM後のresume | DOCS:「resumeすると、SIGTERMで未完了になったturnを続ける」(E11)。CHANGELOG 2.1.236:「print/SDKではSIGTERM時に中断ターンを記録しない」 | E11・E01 | 衝突 | 記述が不一致 → CURRENT EFFECT:UNKNOWN |
| session/load(ACP) | `loadSession: true` を広告。`resumeSession`、`unstable_forkSession` がある | E04 | 衝突 | CONFIRMED |
| ACPの自動再作成 | sign-out後に「保存済み会話をresume」してqueryを作り直す | E04 hide-claude-auth.ts | **衝突** | CONFIRMED(static) |
| background taskの回復 | 2.1.208「orphanになったbackground taskを1件の要約にまとめる」、2.1.274の完了通知 | E01 | 衝突(tool使用時) | PARTIAL |
| scheduled taskの回復 | resume時に有効期限内のtaskを復元(E12) | E12 | 衝突 | CONFIRMED(永続化なしで回避) |
| tool呼出の回復 | 「resume時に実行中だったtoolは再実行しない」(E12) | E12 | 低 | CONFIRMED |
| 文脈の復元 | 全履歴を復元 | E12 | 衝突 | CONFIRMED |
| subagentの復元 | 「CLIがbackground subagentを自分で再開」(E02) | E02 | 衝突 | CONFIRMED |
| MCP状態の復元 | 再接続(2.1.243) | E01 | 低(MCP禁止) | NOT_APPLICABLE |
| OAuthの回復 | ACPはsign-out後に再作成+resume。CLIは401でrefresh | E04・E22 | 衝突 | PARTIAL |
| 資源消費を伴う追加turn | cross-session message、goalのcheck-in、scheduled taskが「新しいturn」を開始する(E14) | E14 | 衝突 | CONFIRMED(機能を使わなければ回避) |

**衝突の一覧(ONE DISPATCH = ONE FRESH LOGICAL MODEL TURNに反するもの)：**

1. 中断ターンの自動再開
2. SIGTERM後のresume継続
3. ACPのsession/load・resume・自動再作成
4. background完了時のmodel call
5. 途中切断応答の自動継続(§7 Z1)
6. cross-session・goal・scheduledによる新turn
7. 永続化されたsessionを使った再開

---

## 16. signalとcancellationの挙動、Phase 0の状態遷移

| 事象 | model requestは止まるか | backendは止まるか | 子processは残るか | 後から結果が届くか | orphanになるか | resume可能か | retry | 認証回復 | fallback |
|---|---|---|---|---|---|---|---|---|---|
| SIGINT / SDKの `interrupt()` | 止まる。turnを `aborted: true` で終了(E02) | UNKNOWN(clientがstreamを切っても、server側の生成停止は保証されない) | Bashのtreeはkill | `still_queued` のmessageは**実行される**(E02・E04) | 有(queued) | 可(永続化時) | 無(想定) | 無 | 無 |
| SIGTERM | 「終了中は新しいmodel requestを送らない」(E11) | UNKNOWN | treeをkillして143で終了(2.1.212) | 無 | turnは未完了 | DOCSとCHANGELOGが不一致(§15) | 無 | 無 | 無 |
| ACPの `session/cancel` | 仕様上はSHOULD(MUSTではない)(E05) | UNKNOWN | — | 30秒の猶予の後に強制的にcancelled扱い。「underlying query may still be wedged」(E04) | **有** | ACPのloadで可 | 無 | 無 | 無 |
| timeout(`API_TIMEOUT_MS`・watchdog) | abortする | UNKNOWN | — | — | — | — | **retryする**(§7 F) | — | — |
| processのkill(SIGKILL) | 突然停止 | UNKNOWN | 子(Bash等)が残りうる | — | — | transcriptは途中まで | — | — | — |
| 接続切断 | — | UNKNOWN | — | — | — | — | **retryまたは自動継続**(§7 G・Z1) | — | — |
| stdinのclose | SDKがinputを閉じると、permission promptはcancel(E11) | — | — | — | — | — | — | — | — |
| 親processの死亡 | UNKNOWN(子のCLIが生き残るかどうか) | UNKNOWN | **残る可能性** | 出力先が無い | 有 | 永続化時は可 | 継続しうる | 継続しうる | — |
| networkの切断 | — | UNKNOWN | — | — | — | — | retry(G) | refresh失敗 | — |

**判定：** どの事象でも「backendが止まったこと」を証明できません。**PARTIAL / UNKNOWN**です。

### 16.1 Phase 0状態遷移案(`CLAUDE_DISPATCH_FSM_V1`)

```
PREPARED ──preflight PASS──▶ ARMED ──spawn──▶ SPAWNED ──system/init検証OK──▶ SENT
   │                           │                 │                              │
   └─preflight FAIL──▶ REJECTED_PREFLIGHT         └─init不一致──▶ ABORTED_PRE_SEND (process kill, 再dispatch可)
                                                                              │
SENT ──result(success) & 証拠一致──▶ COMPLETED_VERIFIED (receipt書込み)
SENT ──result(success) & 証拠不一致/欠落──▶ COMPLETED_UNTRUSTED (結果不採用・再dispatch禁止)
SENT ──api_retry / model_fallback / resume_reason / request_count>1 観測──▶ TAINTED (以後の結果は不採用・再dispatch禁止)
SENT ──wall-clock超過 or 外部cancel──▶ CANCEL_REQUESTED ──SIGINT──▶ INTERRUPTING
INTERRUPTING ──process exit(≤grace)──▶ PROCESS_EXITED ──▶ BACKEND_UNKNOWN
INTERRUPTING ──grace超過──▶ KILLED ──▶ BACKEND_UNKNOWN
BACKEND_UNKNOWN ──(exit後に遅延出力やorphan result到着)──▶ ORPHAN_RESULT (記録のみ・不採用)
BACKEND_UNKNOWN ──quarantine期間満了──▶ TERMINAL_UNKNOWN (人間判断待ち。自動の再dispatch禁止)
任意状態 ──Relay crash──▶ (再起動時) durable stateがSENT以降なら TERMINAL_UNKNOWN (再送禁止)
```

**不変条件：**

1. SENTに入る**前**に、`dispatch_id` と状態SENTをdurable(GitHub・Work/Luna側)に記録します(write-ahead)。
2. SENT以降の状態から、同じ `dispatch_id` で再びSPAWNEDに戻る遷移はありません。
3. 再実行は必ず新しい `dispatch_id` で行い、人間またはSolの明示承認を必要とします。
4. 1 `dispatch_id` = 1 OS process = 1 `CLAUDE_CONFIG_DIR` = 1 `session_id` とし、すべて使い捨てにします。

---

## 17. permission安全性の監査

| 項目 | 現行の挙動 | 根拠 | 判定 |
|---|---|---|---|
| bypassPermissions / `--dangerously-skip-permissions` | 起動時に有効化が必要(flag、またはuser・managed・`--settings` の `defaultMode`)。project・localの `defaultMode:"bypassPermissions"` は効かない(v2.1.257+) | E10・E07 | CONFIRMED |
| rootでの拒否 | Linux・macOSでroot/sudoなら拒否。認識されたsandbox内ではskip | E10 | CONFIRMED(**Windowsには言及なし → UNKNOWN**) |
| `disableBypassPermissionsMode:"disable"` | CLIはどの層の指定でも尊重(E04の#1165の説明と、settings-reference「Any file」) | E04・E07 | CONFIRMED(CLI) |
| `allowDangerouslySkipPermissions`(SDK) | 既定はfalse。bypassに必要 | E24 | CONFIRMED |
| `permissionMode` の既定 | `-p` とSDKはManual。対話端末はPro/Maxでauto(v2.1.228+、Windowsは2.1.233+) | E10 | CONFIRMED |
| dontAsk | promptになるものはすべて拒否。読み取り専用のコマンドは許可 | E11 | CONFIRMED |
| acceptEdits | fileの書込みと一部コマンドを自動承認 | E11 | CONFIRMED(Phase 0では禁止) |
| restricted | §13(DOCSとCHANGELOGが不一致) | E01・E13 | PARTIAL |
| auto mode | 分類器のモデルが追加で動く。サブスクでは分類器分も計上されうる | E10 | CONFIRMED(禁止) |
| ACPのpermission | `allowBypass = ALLOW_BYPASS && disableBypassPermissionsMode !== "disable" && host opt-out !== false`。**`disableBypassPermissionsMode` の条件はmain HEAD(#1165、未release)のみ。v0.81.0には無い** | E04 | **FAIL(v0.81.0)** |
| ACPのroot / 非root | `IS_ROOT = (geteuid?.() ?? getuid?.()) === 0` | E04 | CONFIRMED |
| **Windows** | `process.geteuid` と `getuid` は未定義なので `undefined === 0` はfalse。**IS_ROOTはfalse、ALLOW_BYPASSはtrue** | E04(static読解) | CONFIRMED |
| Windows + ACPで危険modeが**既定**になるか | 既定のmodeは `resolvePermissionMode(creationOpts.permissionMode ?? settings.permissions.defaultMode)`。何も無ければ `"default"`。ただし**user settingsに `defaultMode:"bypassPermissions"` があれば、それが初期modeになる**(`filterEscalatingDefaultMode` がproject由来のみ除外) | E04 | **PARTIAL:既定ではないが、user settingsやhostの指定で有効になり得る。v0.81.0ではdisable設定でも止まらない** |
| ACPの `CLAUDE_CODE_EXECUTABLE` | この環境変数で実行するbinaryを差し替えられる | E04 | 脅威(T18) |

---

## 18. Agent SDKの監査

| 観点 | Python 0.2.158(source確認) | TypeScript 0.3.280(sourceは読めていない) | 判定 |
|---|---|---|---|
| CLI wrapperか | **YES**。`subprocess_cli.py` がCLIを `--output-format stream-json --verbose --input-format stream-json` で起動する | DOCS:「Claude Code binaryを動かすlibrary」(E19) | CONFIRMED(Py)/PARTIAL(TS) |
| SDK自身がAPIを呼ぶか | 呼ばない(retryもmodel呼出も無い) | UNKNOWN | CONFIRMED(Py) |
| retryの所有 | CLI | CLI(DOCS) | PARTIAL |
| timeoutの所有 | CLI(`API_TIMEOUT_MS`)とhostのwall-clock | 同左 | PARTIAL |
| 認証の所有 | CLI。env:**`os.environ` を継承**し、`CLAUDE_CODE_ENTRYPOINT=sdk-py` を付け、`options.env` を上書き | `options.env` が**process.envを置換**(0.3.x系で「once again replaces」、E02) | CONFIRMED(Py)/CONFIRMED(TS changelog) |
| fallbackの所有 | CLI(`--fallback-model`、`fallback_model` を渡す) | CLI | CONFIRMED(Py) |
| permissionの所有 | CLI + hostの `canUseTool` | 同左 | CONFIRMED |
| sessionの所有 | CLI(`--resume`、`--continue`、`--fork-session`、`--resume-session-at`、`--resume-drops-turn`) | 同左(`persistSession` optionあり、E24) | CONFIRMED |
| toolの所有 | CLI | CLI | CONFIRMED |
| モデル選択の所有 | CLI(`--model`)。hostの `set_model` は実行中にも適用(2.1.212) | 同左 | CONFIRMED |
| logging / 証拠 | `ResultMessage.model_usage` は**CLIの `modelUsage` をそのまま中継**(types.py 1318行付近) | `modelUsage` の `canonicalModel`、`provider`、`costBasis`(E02)。`usage` は主loopのみ、`modelUsage` は累積(E02) | CONFIRMED |
| processのライフサイクル | SDKが子processを管理 | 同左 | PARTIAL |
| 追加の保護 | `verbatim_prompts`(`@path` 展開やslash commandを無効化、CLI 2.1.248+) | `verbatimPrompts` | CONFIRMED(E03・E02) |

---

## 19. claude-agent-acpの監査(community製、Anthropic公式ではない)

- **公式との境界：** 組織は `agentclientprotocol`。Anthropic公式のSDK `@anthropic-ai/claude-agent-sdk` 0.3.280 に完全固定で依存しています。ACPで追加される振る舞いはAnthropicの保証外です。

| 観点 | 事実 | 根拠 | 判定 |
|---|---|---|---|
| 最新版 | v0.81.0(2026-09-22)。HEADは0.81.1-preview.5 | E04 | CONFIRMED |
| SDK依存 | 0.3.280 | E04 | CONFIRMED |
| 認証 | claude login・console login・gateway・Bedrock認証を提供。`--hide-claude-auth` flagで**サブスク課金を拒否**できる(opt-in) | E04 | CONFIRMED |
| 環境変数の転送 | **`env = {...process.env, ...userOptions.env, ...providerEnv}`**。親のenvをすべて渡す | E04 8137行付近 | CONFIRMED(脅威) |
| settingSources | 既定は `["user","project","local"]`。host側で上書き可能 | E04 | CONFIRMED |
| permission | §17(v0.81.0はdisable設定を無視) | E04 | FAIL(v0.81.0) |
| cancel | `interrupt()` の後、30秒の強制cancelled。`still_queued` のmessageは**実行を継続** | E04 | CONFIRMED |
| timeout | 独自のmodel timeoutは無い(CLIに依存)。構造化usage取得は5秒 | E04 | PARTIAL |
| モデル選択 | `ANTHROPIC_MODEL`、`CLAUDE_MODEL_CONFIG`(overrides・allowlist)、host settings | E04 | CONFIRMED |
| sessionのlifecycle | loadSession・resumeSession・forkを提供。認証後に自動再作成+resume | E04 | CONFIRMED(衝突) |
| retry | promptの自動再送は見つからない。`api_retry` はclientに転送 | E04 | PARTIAL |
| fallback | refusal fallback dialogは、form elicitationに対応したclientでだけ表示(同意すれば別モデルで再実行) | E04 elicitation.ts | CONFIRMED |
| cwd | `params.cwd` をそのまま使う | E04 | CONFIRMED |
| MCP | clientが指定したMCPとuser指定をmerge | E04 | CONFIRMED(禁止が必要) |
| 実行binary | `CLAUDE_CODE_EXECUTABLE` か、同梱のCLI | E04 | CONFIRMED(脅威) |
| 結果・証拠 | usage・modelUsageをACP更新として中継 | E04 | PARTIAL |
| Windows | bypassが許可される(§17) | E04 | CONFIRMED |
| processの終了処理 | 猶予30秒の後、query wedgeの可能性をlogに出す | E04 | PARTIAL |
| 設定の監視 | user・project・local・managedのsettingsをwatchして再解決 | E04 settings.ts | CONFIRMED(drift) |

**推奨：** Phase 0では**ACP経路を使いません(NOT_APPLICABLE扱い)**。どうしても使う場合は、(a) #1165を含む版にpinし、(b) `--hide-claude-auth` は**サブスク専用のPhase 0とは両立しない**ので使わず、(c) env allowlistをhost側で強制します。

---

## 20. serverが制御する挙動(client optionで止められない可能性があるもの)

| 挙動 | 根拠 | clientで止められるか | 判定 |
|---|---|---|---|
| feature flagの配布(advisor、auto mode、fast mode、streaming fallback等) | E15「featureはflagで有効化」、E22 `tengu_*` | 一部は可(`DISABLE_TELEMETRY` 等でflag取得を止めると、advisorなどがOFFになる。E15) | PARTIAL |
| `x-should-retry` headerによるretry指示 | E22(2.1.42) | UNKNOWN | UNKNOWN |
| safety classifierのflag | E08 | 再実行は `switchModelsOnFlag` で抑止できるが、flag自体は止められない | PARTIAL |
| auto modeの分類器モデル(server設定が優先) | E10 | auto modeを使わなければ無関係 | NOT_APPLICABLE |
| server-side classifier(API・Enterprise) | CHANGELOG 2.1.278 | 同上 | NOT_APPLICABLE |
| advisor(server tool) | E15 | env var | CONFIRMED(止められる) |
| model routing・置換 | 資料なし | 不明 | UNKNOWN |
| token refresh | E09 | 不可 | PARTIAL |
| overloadからの回復 | — | 不可 | UNKNOWN |
| request replay(server側の重複実行) | 資料なし | 不明 | UNKNOWN |
| session継続(cloudの再実行) | 2.1.216(cloud) | local -pでは該当しない | NOT_APPLICABLE |
| model access entryの更新による既定モデル切替 | 2.1.268(不具合修正) | pinで回避 | PARTIAL |
| 利用上限・usage creditsの判定 | E16・E08 | 不可(サーバ判定) | PARTIAL |

---

## 21. usage creditsと課金経路

| 課金 | 何で発生するか | usage credits OFFで止まるか | Phase 0 |
|---|---|---|---|
| Claude subscriptionの利用枠 | R7の通常利用 | 無関係(枠内) | **唯一許可** |
| usage credits(旧称extra usage) | サブスクの上限超過、Fable(プランによる)、1M context(Opusと Sonnet 4.6の1Mなど)、fast mode(常にcredits) | **止まる**(fast modeは「usage creditsが必要」。Fableは-pで無言課金なので、OFFが唯一の防壁) | OFFを必須にし、**毎回人間が確認** |
| API Console credits・API key課金 | R3・R4・R8 | **止まらない** | envとsettingsで禁止 |
| Bedrock | R1 | 止まらない | 禁止 |
| Vertex | R1 | 止まらない | 禁止 |
| Foundry | R1 | 止まらない | 禁止 |
| Enterprise課金 | 組織設定 | 該当しない | NOT_APPLICABLE |
| Agent SDK月次credit(計画) | E21:2026-06-15に**一時停止**。「SDK、`claude -p`、third-party appは引き続きサブスクの利用枠を消費」 | 計画が再開されると、credit枯渇後は「usage creditsがONならcreditsへ、OFFなら停止」 | 監視が必要(制度変更リスク) |

**E25の観測：** トグルはOFFですが、**残高1.58クレジット**があります(9/13に購入した分の69%を使用済み)。後日トグルがONになると、この残高が即座に使われます。

**課金routeのpreflight案(`BILLING_ROUTE_PREFLIGHT_V1`)：**

1. `usage_credits_toggle`:人間がスクリーンショットで確認します。証拠のhashとtimestampを記録し、24時間を超えたら再確認します。自動では取得しません。
2. env deny list(§14)を適用します。
3. settingsの全層に `apiKeyHelper`・`env.ANTHROPIC_*`・`fastMode:true`・`advisorModel`・`model` にFableや[1m]が**無い**ことを確認します。
4. 起動後の `system/init` で、`apiKeySource ∈ {none}`、`subscriptionType` あり、`tokenSource` なし、`apiProvider` が無いか `firstParty` であることを確認します。ACPのallowlist論理(E04)に準拠します。
5. 結果の `modelUsage[*].costBasis` と `provider` を記録します。値の意味は[E02]。
6. 終了後に、人間がclaude.aiの「使用状況」の残高が変わっていないことを確認します(任意・推奨)。

---

## 22. 利用規約・ポリシー・サポートされる使い方

| 質問 | 根拠 | 判定 |
|---|---|---|
| 1. 本人が自分のPCで、改変していないClaude Code CLIを本人のPro/Maxログインで使う | E18:「end userが**unmodified Claude Code binary**に自分のサブスクでsign-inすることを妨げない」。E20の運用記事 | **CONFIRMED(supported)** |
| 2. 自作controllerが、改変していないClaude Codeを子processとして起動する | E21:「`claude -p` は引き続きサブスクの利用枠を消費」(課金上の扱いとして明記)。E18:開発者が製品として他者に提供する場合はAPI key。**本人専用の自動化を明示的に許可した文言は見つからない** | PARTIAL(課金上の扱いは明記。本人専用自動化の是非は明文なし) |
| 3. Agent SDKを自作Relayに組み込み、サブスク認証を使う | E21:月次credit(一時停止中)の対象として「Claude Agent SDK usage **in your own projects**」を明記し、現状はサブスク枠を消費と記載。E19・E18:「第三者の開発者が**自分の製品に**claude.aiログインを提供すること」を禁止 | PARTIAL(本人のprojectでの利用は課金上想定されている。Relayを他者に提供するとNG) |
| 4. claude-agent-acp経由 | E21:「Agent SDK経由でサブスク認証するthird-party apps」も利用枠の消費対象に列挙。一方、ACP自身が `--hide-claude-auth` を用意(配布者向けの配慮) | PARTIAL |
| 5. 第三者向けではない本人専用の自動化 | 「本人専用の自動化」を直接扱う条文は、取得できた資料には無い。Consumer Termsは取得失敗 | **UNKNOWN** |

**運用上の注意(一次資料に基づく)：**

- E18:「Advertised usage limits for Pro and Max plans assume ordinary, individual usage of Claude Code and the Agent SDK」。
- E18:「Anthropic reserves the right to take measures to enforce these restrictions … without prior notice」。
- **Relayを他人に使わせる形にはしないでください。**

---

## 23. Claude経路専用のthreat model(40件)

列の意味：前提=前提条件、検出=検出方法、防止=防止策、証拠=残す証拠、残存=残存リスク、状態=現在の状態

| ID | 攻撃・失敗モード | 前提 | 影響 | 検出 | 防止 | 証拠 | 残存 | 状態 |
|---|---|---|---|---|---|---|---|---|
| T01 | 隠れた `ANTHROPIC_API_KEY` | 親env、profile、settingsの `env` ブロック | API課金 | env scan、init `apiKeySource` | env allowlistと使い捨てCONFIG_DIR | env hash、init | 低 | 設計済み |
| T02 | 古い、または他人のOAuth | 長期token、共有の資格情報 | 別accountでの課金 | init `email` / `organization`(`/status` 相当) | 期待するaccount IDと照合 | init account | 中 | UNKNOWN(initのaccount項目名は要確認) |
| T03 | 実行中のsettings hot reload | 監視されているfile | 認証・権限の変化 | mtimeとhashの監視 | 使い捨てCONFIG_DIR、空のcwd | pre/post hash | 中(managed) | 設計済み |
| T04 | `MAX_RETRIES` の外側でのretry | §7 B・C・F・G・Z1 | 複数turn・二重課金 | OTel `api_request` の件数、api_retry | 検出したら不採用 | OTel log | **高** | BLOCKED |
| T05 | model fallback | chain、`last_resort` | 別モデル | `model_fallback`、modelUsage | chainを禁止 | stream | 中 | PARTIAL |
| T06 | safetyによる再実行 | 既定true | 別モデルで再実行 | modelUsageのkey数 | `switchModelsOnFlag:false` | stream | 中 | PARTIAL |
| T07 | 認証回復による再送 | 401 | 二重request | api_retry `authentication_failed` | 検出したら不採用 | stream | 中 | PARTIAL |
| T08 | session resume | 永続化 | 再実行 | `resume_reason` | 永続化なし、resume禁止 | stream | 低 | 設計済み |
| T09 | SIGTERM後のresume | DOCS記述 | 再実行 | 同上 | 永続化なし | — | 低 | 設計済み |
| T10 | orphan result | cancel、`still_queued` | 遅れた結果の誤採用 | FSMのORPHAN_RESULT | 状態がSENT以降なら不採用 | FSM log | 低 | 設計済み |
| T11 | background model turn | tool・background task | 追加turn | `task_notification` | tool禁止 | stream | 低 | 設計済み |
| T12 | 隠れたhook | project `.claude/settings.json` | 任意コマンドの実行 | cwd scan | 空のcwd、CONFIG_DIRの隔離 | tree hash | 低 | 設計済み |
| T13 | 隠れたMCP | `.mcp.json`、user MCP | 外部通信・tool | init `mcp_servers` が空であること | 同上 | init | 低 | 設計済み |
| T14 | 無視される設定file | `.gitignore` 下の `.claude/settings.local.json` | 隠れた設定 | ignoredも含めてscan | 空のcwd | scan log | 低 | 設計済み |
| T15 | symlinkによる設定 | `.claude` → 外部 | 設定の差し替え | `lstat` scan | symlinkを拒否 | scan | 低 | 設計済み |
| T16 | 親envの注入 | Relay親processのenv | 経路の変化 | env diff | `env -i` + allowlist | env hash | 低 | 設計済み |
| T17 | PATH hijack | PATH上に偽の `claude` | 偽の実行 | 絶対pathとhash | 絶対pathで起動 | exe hash | 低 | 設計済み |
| T18 | 偽のclaude binary(`CLAUDE_CODE_EXECUTABLE`) | ACP・SDK | 偽の実行 | exe hash | envを禁止、hashをpin | exe hash | 低 | 設計済み |
| T19 | version drift | auto-update | 挙動の変化 | `--version`、init `claude_code_version` | auto-update停止(`DISABLE_AUTOUPDATER` 等。名称はUNKNOWN)、pin | version | 中 | PARTIAL |
| T20 | package drift | npmやwheelの更新 | 同上 | lockfileのhash | pin | lock hash | 中 | PARTIAL |
| T21 | ACP version drift | 同上 | permissionの退行 | version確認 | ACP不使用 | — | 低 | 設計済み |
| T22 | 実行中のsettings変更 | T03 | — | — | — | — | — | T03に統合 |
| T23 | cwdの汚染 | 残ったfile | 文脈の汚染 | tree hash | 使い捨てcwd | hash | 低 | 設計済み |
| T24 | 古いworkspace | repoを使う場合 | 誤ったbase | TREE_IDENTITY_V1 | Gate | receipt | 中 | 既存Gateに依存 |
| T25 | 古いsession | session ID再利用 | 文脈の混入 | 新規UUID | `--session-id` を毎回新規・永続化なし | init `session_id` | 低 | 設計済み |
| T26 | 古いreceipt | receipt書込み失敗 | 二重実行 | write-ahead | FSM不変条件1 | GitHub | 中 | 設計済み |
| T27 | 重複dispatch | Relayの再起動 | 二重turn | dispatch_idの一意性 | durableなlock | GitHub | 中 | 設計済み |
| T28 | transportの結果が曖昧 | exit≠0、結果なし | 成否不明 | FSM | TERMINAL_UNKNOWN | FSM | 中 | 設計済み |
| T29 | process終了後もbackendが動く | cancel、kill | 課金・生成 | 検出不能 | 受容してTERMINAL_UNKNOWN | — | **高** | UNKNOWN |
| T30 | cancel後に結果が届く | ACPの猶予30秒 | 誤採用 | ORPHAN_RESULT | 不採用 | FSM | 低 | 設計済み |
| T31 | usage metadataの嘘・欠落 | client自己申告 | 誤判定 | 複数の証拠源を突き合わせ | 欠落なら不採用 | 全証拠 | **高** | UNKNOWN(独立証拠なし) |
| T32 | 実際に別モデルが実行された | server routing | 品質・監査の破綻 | 検出不能 | 無し | — | **高** | UNKNOWN |
| T33 | Fableの無言課金 | Fable指定、credits ON | usage credits消費 | modelUsage | Fableを禁止、credits OFF | — | 低 | 設計済み |
| T34 | fast modeの課金 | `fastMode:true` | usage credits消費 | 設定scan | `DISABLE_FAST_MODE` | — | 低 | 設計済み |
| T35 | advisorによる追加モデル | `advisorModel` | 別モデル | 設定scan | `DISABLE_ADVISOR_TOOL` | — | 低 | 設計済み |
| T36 | 途中切断応答の自動継続 | 非対話 | 追加request | OTelの件数 | 検出したら不採用 | OTel | **高** | FAIL(無効化手段が不明) |
| T37 | non-streaming再送 | stream error | 二重request・二重課金 | OTelの件数 | `DISABLE_NONSTREAMING_FALLBACK` | OTel | 中 | PARTIAL |
| T38 | prompt injection経由のtool実行 | toolを許可した場合 | 任意の操作 | — | tool無し、`verbatim_prompts` | — | 低 | 設計済み |
| T39 | `@path` 展開やslash commandの誤発動 | promptに `@` や `/` を含む | fileの読込み・コマンド実行 | — | `--disable-slash-commands`、SDKの `verbatimPrompts` | — | 低 | 設計済み |
| T40 | Agent SDK月次creditの制度再開 | E21の計画が再開 | 課金方式の変化 | Help Centerの監視 | credits OFF | — | 中 | 監視 |

---

## 24. `CLAUDE_PHASE0_PREFLIGHT_V1` 仕様

すべて**fail-closed**です。1つでもFAILかUNKNOWNがあれば `overall_state=BLOCKED` にします。

**IDENTITY**

- `claude` を絶対pathで解決し、realpathとsymlinkの有無を記録します。
- 実行fileのSHA-256をpin値と照合します。pin値は、人間がreviewしたversionのhashにします。
- `claude --version` の結果がpinと一致すること。**これは実行時のmodel呼び出しを伴わないはずですが、起動時にnetworkへ出るかはUNKNOWNです。preflightの最初のliveではない呼び出しとして、人間の承認後に扱います。**
- 期待するpackage:@anthropic-ai/claude-code(npm)またはnative installer。どちらかを明示します。
- ACP:不使用(`acp_version=null`)。
- SDK:使う場合は、Python SDKの版と同梱CLIの版(`_cli_version.py`)の両方をpinします。

**AUTH**

- env deny list(§14)の全項目がunset。
- 使い捨て `CLAUDE_CONFIG_DIR` 内のfile一覧がallowlistどおり(`.credentials.json` 等)であること。
- settingsのどの層にも `apiKeyHelper`・`env`・`forceLoginMethod ≠ claudeai` が無いこと。
- managed settingsのfile(OS別のpath)の有無と内容hash。存在すれば、内容を監査してから許可リストと照合します。
- cloud provider経路が無いこと。
- `usage_credits_evidence`:人間確認のhash(24時間以内)。

**MODEL**

- `requested_model` はフルIDで、allowlistに含まれること。aliasは禁止。`[1m]` は禁止。`fable*` は禁止。
- `fallbackModel` と `--fallback-model` が無いこと。
- `switchModelsOnFlag=false`(`--settings`)、advisorとfast modeは無効。
- auto modeは禁止(`disableAutoMode`)。

**RETRY**

- `CLAUDE_CODE_MAX_RETRIES=0`、`DISABLE_NONSTREAMING_FALLBACK=1`、`CLAUDE_ENABLE_STREAM_WATCHDOG=0`、`RETRY_WATCHDOG` はunset。
- 実行時の規則:`api_retry` が1件でもあれば **TAINTED**、auth retryが1件でもあれば TAINTED、OTel `api_request` が2件以上なら TAINTED。
- timeout:Relayのwall-clockの上限は `API_TIMEOUT_MS` + margin とし、超えたら **CANCEL_REQUESTED** にします(再試行しない)。

**SESSION**

- `--session-id` は毎回新しいUUID。`--no-session-persistence` と `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1` を付けます。
- `--resume`、`--continue`、`--fork-session`、`--resume-session-at` は存在すれば拒否。
- `CLAUDE_CODE_RESUME_INTERRUPTED_TURN=0`。

**WORKSPACE**

- cwdは空の使い捨てdir(`.git` なし)。repoを使う場合はTREE_IDENTITY_V1とCLAUDE_RUNTIME_IDENTITY_V1(§29)を必須にします。
- `.claude/`・`.mcp.json`・`CLAUDE.md`・`AGENTS.md`・symlinkがcwdと親dirに無いこと。**CLAUDE.mdは親dirも探索されるため、使い捨てdirは、上位にCLAUDE.mdが無い場所に作ります。**

**PERMISSIONS**

- `--permission-mode dontAsk`、`--permission-prompts none`。
- `disableBypassPermissionsMode:"disable"`(`--settings`)。
- toolは「無し」を目標にします。受理できる指定方法はUNKNOWNなので、`--disallowedTools "*"` を候補にします(E13の逐語表では「`"*"` removes every tool」。これは1回目の要約経由で、UNKNOWN扱い)。

**OUTPUT**

- `--output-format stream-json --verbose`、OTelはconsoleまたはfileでローカル出力。
- 行ごとに保存し、SHA-256のchainを取ります。
- 次のどれかがあればfail-closed:`api_retry`、`model_fallback`、`resume_reason`、`permission_denied`、`notification`(fast mode)、モデル不一致、`terminal_reason ≠ completed`、`is_error`。

**TEARDOWN**

- process exit codeを記録。子processが残っていないこと(Windows:Job Objectで管理)。
- CONFIG_DIRとcwdを証拠のarchiveに移してから削除します。**再起動しません。**
- orphanの監視:exit後の出力は記録だけにします。
- 2回目の起動は禁止(同じ `dispatch_id`)。

---

## 25. preflight結果のJSON schema(案)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "claude_phase0_preflight_result_v1",
  "type": "object",
  "required": ["schema_version","profile","dispatch_id","checked_at","claude_code_version","claude_code_version_state",
    "executable","auth_route","auth_route_state","forbidden_env_state","forbidden_settings_state","retry_zero_state",
    "stream_retry_state","auth_recovery_state","fallback_state","model_identity_state","permission_state",
    "session_persistence_state","resume_state","workspace_state","hooks_state","mcp_state","tool_policy_state",
    "billing_route_state","usage_credits_state","overall_state","blockers","unknowns","evidence_refs"],
  "properties": {
    "schema_version": {"const": "1"},
    "profile": {"const": "CLAUDE_PHASE0_PREFLIGHT_V1"},
    "dispatch_id": {"type": "string", "pattern": "^[0-9a-f-]{36}$"},
    "checked_at": {"type": "string", "format": "date-time"},
    "claude_code_version": {"type": "string"},
    "claude_code_version_state": {"$ref": "#/$defs/state"},
    "executable": {"type": "object", "required": ["path","realpath","sha256","is_symlink"],
      "properties": {"path":{"type":"string"},"realpath":{"type":"string"},"sha256":{"type":"string"},"is_symlink":{"type":"boolean"}}},
    "sdk_version": {"type": ["string","null"]},
    "sdk_bundled_cli_version": {"type": ["string","null"]},
    "acp_version": {"type": ["string","null"]},
    "auth_route": {"enum": ["claude_ai_oauth","oauth_token_env","api_key_env","auth_token_env","api_key_helper","profile","cloud_provider","gateway","managed_key","none","unknown"]},
    "auth_route_state": {"$ref": "#/$defs/state"},
    "forbidden_env_state": {"$ref": "#/$defs/state"},
    "forbidden_env_found": {"type": "array", "items": {"type": "string"}},
    "forbidden_settings_state": {"$ref": "#/$defs/state"},
    "settings_layers": {"type": "array", "items": {"type": "object",
      "properties": {"layer":{"enum":["managed","cli","local","project","user"]},"path":{"type":"string"},"exists":{"type":"boolean"},"sha256":{"type":["string","null"]}}}},
    "retry_zero_state": {"$ref": "#/$defs/state"},
    "stream_retry_state": {"$ref": "#/$defs/state"},
    "auth_recovery_state": {"$ref": "#/$defs/state"},
    "fallback_state": {"$ref": "#/$defs/state"},
    "classifier_rerun_state": {"$ref": "#/$defs/state"},
    "requested_model": {"type": "string"},
    "model_identity_state": {"enum": ["SELF_CONSISTENT_EXPECTED","UNKNOWN","BLOCKED"]},
    "permission_state": {"$ref": "#/$defs/state"},
    "session_persistence_state": {"$ref": "#/$defs/state"},
    "resume_state": {"$ref": "#/$defs/state"},
    "workspace_state": {"$ref": "#/$defs/state"},
    "tree_identity_v1": {"type": ["object","null"]},
    "runtime_identity_v1": {"type": ["string","null"], "description": "CLAUDE_RUNTIME_IDENTITY_V1 digest"},
    "hooks_state": {"$ref": "#/$defs/state"},
    "mcp_state": {"$ref": "#/$defs/state"},
    "tool_policy_state": {"$ref": "#/$defs/state"},
    "billing_route_state": {"$ref": "#/$defs/state"},
    "usage_credits_state": {"enum": ["HUMAN_CONFIRMED_OFF","HUMAN_CONFIRMED_ON","STALE","UNKNOWN"]},
    "usage_credits_evidence": {"type": ["object","null"], "properties": {"sha256":{"type":"string"},"observed_at":{"type":"string","format":"date-time"},"observer":{"const":"human"}}},
    "overall_state": {"enum": ["PASS","BLOCKED"]},
    "blockers": {"type": "array", "items": {"$ref": "#/$defs/finding"}},
    "unknowns": {"type": "array", "items": {"$ref": "#/$defs/finding"}},
    "evidence_refs": {"type": "array", "items": {"type": "string"}}
  },
  "$defs": {
    "state": {"enum": ["PASS","FAIL","UNKNOWN","NOT_APPLICABLE"]},
    "finding": {"type": "object", "required": ["id","state","detail"],
      "properties": {"id":{"type":"string"},"state":{"enum":["FAIL","UNKNOWN","BLOCKED"]},"detail":{"type":"string"},"evidence":{"type":"string"}}}
  },
  "allOf": [{"if": {"anyOf": [
      {"properties": {"forbidden_env_state": {"not": {"const": "PASS"}}}},
      {"properties": {"auth_route": {"not": {"const": "claude_ai_oauth"}}}},
      {"properties": {"usage_credits_state": {"not": {"const": "HUMAN_CONFIRMED_OFF"}}}}
    ]}, "then": {"properties": {"overall_state": {"const": "BLOCKED"}}}}]
}
```

**規則：** `overall_state=PASS` になるのは、すべての `*_state` が PASS か NOT_APPLICABLE のときだけです。**UNKNOWNが1つでもあればBLOCKED**です。

---

## 26. runtime evidenceのschema(案)

```json
{
  "$id": "claude_phase0_runtime_evidence_v1",
  "type": "object",
  "required": ["dispatch_id","correlation_id","fsm_state","requested_model","init","model_usage_models","retry_events",
    "fallback_events","classifier_events","auth_refresh_events","resume_events","request_count_observed","process_exit",
    "orphan_result","result_state","evidence_refs"],
  "properties": {
    "dispatch_id": {"type": "string"},
    "correlation_id": {"type": "string", "description": "GitHub receipt/Work-Luna側と共有"},
    "fsm_state": {"enum": ["COMPLETED_VERIFIED","COMPLETED_UNTRUSTED","TAINTED","ABORTED_PRE_SEND","BACKEND_UNKNOWN","ORPHAN_RESULT","TERMINAL_UNKNOWN"]},
    "requested_model": {"type": "string"},
    "init": {"type": "object", "properties": {
      "claude_code_version": {"type":"string"}, "model": {"type":"string"}, "apiKeySource": {"type":"string"},
      "permissionMode": {"type":"string"}, "session_id": {"type":"string"}, "tools": {"type":"array"},
      "mcp_servers": {"type":"array"}, "plugins": {"type":"array"}, "capabilities": {"type":"array"},
      "account": {"type":"object", "description":"subscriptionType/tokenSource/apiProvider 等(取得可否はUNKNOWN→取得できなければfield欠落を記録)"}}},
    "reported_models": {"type": "array", "items": {"type":"string"}, "description": "各assistant messageのmodel"},
    "model_usage_models": {"type": "array", "items": {"type":"string"}},
    "model_usage_raw": {"type": "object"},
    "api_key_source": {"type": "string"},
    "permission_mode": {"type": "string"},
    "retry_events": {"type": "array", "items": {"type":"object"}},
    "fallback_events": {"type": "array", "items": {"type":"object"}},
    "classifier_events": {"type": "array", "items": {"type":"object"}},
    "auth_refresh_events": {"type": "array", "items": {"type":"object"}},
    "resume_events": {"type": "array", "items": {"type":"object"}, "description": "resume_reason付きmessage"},
    "notification_events": {"type": "array", "items": {"type":"object"}},
    "permission_denials": {"type": "array"},
    "session_id": {"type": "string"},
    "session_persistence": {"const": false},
    "cancel_events": {"type": "array", "items": {"type":"object","properties":{"at":{"type":"string"},"kind":{"enum":["SIGINT","SIGTERM","KILL","WALLCLOCK","EXTERNAL"]},"receipt_still_queued":{"type":"array"}}}},
    "otel_api_requests": {"type": "array", "items": {"type":"object","properties":{"request_id":{"type":"string"},"client_request_id":{"type":"string"},"model":{"type":"string"},"attempt":{"type":["integer","null"]}}}},
    "request_count_observed": {"type": "integer", "description": "otel_api_requestsの件数。0=観測失敗(→UNTRUSTED)"},
    "process_exit": {"type": "object", "properties": {"code":{"type":["integer","null"]},"signal":{"type":["string","null"]},"at":{"type":"string"},"children_remaining":{"type":"integer"}}},
    "orphan_result": {"type": "boolean"},
    "terminal_reason": {"type": ["string","null"]},
    "is_error": {"type": "boolean"},
    "result_state": {"enum": ["ACCEPTED","REJECTED","UNKNOWN"]},
    "config_hash_pre": {"type": "string"},
    "config_hash_post": {"type": "string"},
    "stream_log_sha256_chain_head": {"type": "string"},
    "evidence_refs": {"type": "array", "items": {"type":"string"}}
  }
}
```

**ACCEPTEDにする条件：**

- fsm_stateが `COMPLETED_VERIFIED` で、かつ以下がすべて成り立つこと。
  - `request_count_observed == 1`
  - `retry_events`・`fallback_events`・`classifier_events`・`auth_refresh_events`・`resume_events` がすべて空
  - `model_usage_models == [requested_model]` で、`reported_models` もすべて `requested_model`
  - `api_key_source == "none"`
  - `config_hash_pre == config_hash_post`
  - `terminal_reason == "completed"`
- それ以外はREJECTEDにします。**REJECTEDのとき自動で再dispatchしません。**

注：「1 dispatch = request 1回」は、tool無し・`--max-turns 1` を前提にしています。thinkingを伴う単発の応答が1 requestで収まることは、docsで逐語確認していません(UNKNOWN)。Phase 0では「requestが2回以上ならREJECTED」を安全側の既定にします。

---

## 27. regression testの一覧(59件)

**凡例：**

- 「mock」：M = mockかfixtureだけで実施できる。S = 静的検査。H = 人間の確認
- 「live」：live実行が必要か
- 「blk」：Phase 0のblockerか

§28の `FAKE_ANTHROPIC_V1` を前提にしています。**実際のproviderには接続しません。** network sandboxで外部への通信は全面拒否します。

### A. retry

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 期待する証拠 |
|---|---|---|---|---|---|---|---|---|---|
| A-01 | 529を1回受けたら直ちにTAINTED | fakeが1回目に529 | dispatch | api_retry→TAINTED、再dispatchしない | ACCEPTED、または2回目のdispatch | M | NO | YES | api_retry、FSM log |
| A-02 | `MAX_RETRIES=0` の実効 | fakeが常に529 | dispatch | fakeが受けたrequestが1回 | 2回以上 | M | NO | YES | fakeのrequest log |
| A-03 | stream途中切断 | 50%送った後にTCP reset | dispatch | 再request(自動継続・再送)を検出してTAINTED | 2回目のrequestを見逃してACCEPTED | M | NO | YES | fake log、OTel件数 |
| A-04 | non-streaming再送 | stream endpointが500を返し、non-stream endpointは200 | `DISABLE_NONSTREAMING_FALLBACK=1` あり/なしで比較 | ありなら1回、なしなら2回を検出してTAINTED | ありで2回、または検出漏れ | M | NO | YES | fake log |
| A-05 | idle watchdog | headersの後、無送信で6分 | watchdog=0あり/なし | 再送を検出 | 検出漏れ | M | NO | YES | fake log |
| A-06 | 無応答(headersなし) | headersを送らない | dispatch | 1回retry(D04)を検出してTAINTED、wall-clockでcancel | 無限待ち | M | NO | YES | api_retry `no_response` |
| A-07 | 429(使用量と無関係) | 429 + `Retry-After:1` | dispatch | TAINTED | ACCEPTED | M | NO | YES | api_retry `rate_limit` |
| A-08 | `RETRY_WATCHDOG` の注入 | 環境変数にセット | preflight | forbidden_env FAIL | 起動する | S | NO | YES | preflight JSON |
| A-09 | Relay側に再試行が無いこと | fakeが常時500 | dispatchを3回呼ぶ | 起動は3回とも別dispatch_idで、それぞれ人間承認を要求 | 自動の再起動 | M | NO | YES | FSM |

### B. 認証

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| B-01 | 隠れたAPI key | 親envに `ANTHROPIC_API_KEY=dummy` | preflight | FAIL、起動しない | 起動する | S | NO | YES | preflight |
| B-02 | settingsの `env` ブロックにAPI key | user settingsの `env` にkey | preflight | FAIL | 見逃す | S | NO | YES | settings scan |
| B-03 | apiKeyHelperの存在 | project settingsにhelper | preflight | FAIL | 見逃す | S | NO | YES | scan |
| B-04 | 実行中のhelper注入 | 起動後にsettingsへ書込み | 実行中 | mtime監視で検知してTAINTED | ACCEPTED | M | NO | YES | watch log |
| B-05 | 401→refresh→再送 | fakeが1回目に401 | dispatch | api_retry `authentication_failed` を検出してTAINTED | ACCEPTED | M | NO | YES | stream |
| B-06 | init `apiKeySource≠none` | fakeを使わず、stream fixtureで代替 | 解析 | REJECTED | ACCEPTED | M(fixture) | NO | YES | parser test |
| B-07 | `tokenSource` あり | fixture | 解析 | REJECTED | ACCEPTED | M | NO | YES | parser |
| B-08 | profile(`~/.config/anthropic`)の存在 | fixture dirを作成 | preflight | FAIL | 見逃す | S | NO | YES | scan |
| B-09 | managed settingsの変更 | 起動後にmanaged fileを更新 | 実行中 | TAINTED | 見逃す | M | NO | YES | watch |
| B-10 | `--bare` の混入 | 引数に `--bare` | preflight | FAIL(サブスク経路と両立しない) | 起動する | S | NO | YES | argv check |

### C. fallback

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| C-01 | `--fallback-model` の拒否 | argvに含める | preflight | FAIL | 起動する | S | NO | YES | argv |
| C-02 | settingsの `fallbackModel` | user settingsに記述 | preflight | FAIL | 見逃す | S | NO | YES | scan |
| C-03 | `FALLBACK_FOR_ALL_PRIMARY_MODELS=0` | 値が0でも存在すれば有効(E06) | preflight | FAIL | 「0だからOK」と判断する | S | NO | YES | env |
| C-04 | `system/model_fallback` の検出 | fixtureにeventを入れる | 解析 | TAINTED | 見逃す | M | NO | YES | parser |
| C-05 | 分類器による再実行 | fakeが1回目のresponseをrefusal(stop_reason等)にする。**形式はUNKNOWN→fixtureのcase差し替えで対応** | dispatch | 2回目のrequest、または別モデルを検出してTAINTED | ACCEPTED | M | NO | YES | fake log |

### D. モデル同一性

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| D-01 | response.modelの不一致 | fakeが `model` に別IDを返す | dispatch | MISMATCHでREJECTED | ACCEPTED | M | NO | YES | stream |
| D-02 | modelUsageに2モデル | fixture | 解析 | REJECTED | ACCEPTED | M | NO | YES | parser |
| D-03 | alias指定の拒否 | `--model opus` | preflight | FAIL | 起動する | S | NO | YES | argv |
| D-04 | `[1m]` とFableの拒否 | `--model claude-fable-5` 等 | preflight | FAIL | 起動する | S | NO | YES | argv |
| D-05 | OTelの欠落 | OTel出力を空にする | 解析 | UNTRUSTED(`request_count_observed=0`) | ACCEPTED | M | NO | YES | evidence |

### E. session

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| E-01 | resume系flagの拒否 | argvに `--resume`、`--continue`、`--fork-session` | preflight | FAIL | 起動する | S | NO | YES | argv |
| E-02 | 永続化されていないこと | fake実行後 | CONFIG_DIRをscan | transcript(.jsonl)が0件 | 存在する | M | NO | YES | scan |
| E-03 | `resume_reason` の検出 | fixture | 解析 | TAINTED | 見逃す | M | NO | YES | parser |
| E-04 | `RESUME_INTERRUPTED_TURN` がunsetまたは1 | env | preflight | FAIL(0以外) | 見逃す | S | NO | YES | env |

### F. cancel

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| F-01 | wall-clock超過 | fakeが無限に遅延 | 超過 | SIGINT→猶予→KILL→BACKEND_UNKNOWN | 自動の再dispatch | M | NO | YES | FSM |
| F-02 | exit後の出力 | fakeが遅れてresponse | kill後 | ORPHAN_RESULT(記録のみ) | 採用する | M | NO | YES | FSM |
| F-03 | Relay crash後 | SENT状態でRelayをkill | 再起動 | TERMINAL_UNKNOWN、再送しない | 再送 | M | NO | YES | durable state |
| F-04 | 子processの残存(Windows) | Job Object | kill | 子が0 | 残存 | M | NO | YES | process list |
| F-05 | SIGTERMとSIGINTの違い | fake | それぞれ送信 | どちらもBACKEND_UNKNOWN、resumeしない | resumeする | M | NO | YES | FSM |

### G. workspace

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| G-01 | cwdに `.claude/settings.json` | fixture | preflight | FAIL | 見逃す | S | NO | YES | scan |
| G-02 | cwdに `.mcp.json` | fixture | preflight | FAIL | 見逃す | S | NO | YES | scan |
| G-03 | 親dirに `CLAUDE.md` | 上位dirに配置 | preflight | FAIL | 見逃す | S | NO | YES | scan |
| G-04 | ignoredのsettings.local.json | `.gitignore` 下に配置 | preflight | FAIL | 見逃す | S | NO | YES | scan(ignoredも含める) |
| G-05 | symlinkの `.claude` | link | preflight | FAIL | 見逃す | S | NO | YES | lstat |

### H. permission

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| H-01 | bypass系flagの拒否 | argv | preflight | FAIL | 起動する | S | NO | YES | argv |
| H-02 | user settingsの `defaultMode:bypassPermissions` | fixture | preflight | FAIL | 見逃す | S | NO | YES | scan |
| H-03 | init `permissionMode≠dontAsk` | fixture | 解析 | REJECTED | ACCEPTED | M | NO | YES | parser |
| H-04 | toolsが空でない | init `tools` に要素 | 解析 | REJECTED | ACCEPTED | M | NO | YES | parser |

### I. settings

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| I-01 | pre/postのconfig hash | 実行中にfileを変更 | 終了後 | hashが不一致でREJECTED | ACCEPTED | M | NO | YES | hash |
| I-02 | `fastMode` / `advisorModel` の存在 | fixture | preflight | FAIL | 見逃す | S | NO | YES | scan |

### J. receipt / replay

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| J-01 | write-ahead | GitHubのmock書込みを失敗させる | dispatch | SENTの前で停止し、起動しない | 起動する | M | NO | YES | FSM |
| J-02 | 完了receiptの書込み失敗 | 結果の後で書込み失敗 | 再起動 | TERMINAL_UNKNOWN、再実行しない | 再実行 | M | NO | YES | FSM |
| J-03 | dispatch_idの重複 | 同じIDで2回 | dispatch | 2回目を拒否 | 起動する | M | NO | YES | durable lock |

### K. ACP(不使用の確認と、将来のためのtest)

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| K-01 | ACP経路の拒否 | 設定でACP経路を指定 | preflight | FAIL(`NOT_APPLICABLE` 以外は不可) | 起動する | S | NO | YES | preflight |
| K-02 | [将来] ACP #1165の有無 | ACPのsourceをpin | 静的grep:`disableBypassPermissionsMode` が `allowBypass` 式に含まれること | 含まれる | 含まれない | S | NO | 将来 | grep |
| K-03 | [将来] Windowsで `ALLOW_BYPASS` がtrueになること | modes.tsのunit(geteuidが未定義) | 評価 | trueを確認し、Relay側で `allowDangerouslySkipPermissions=false` を強制 | 強制されない | S | NO | 将来 | unit |

### L. version drift

| ID | 目的 | 準備 | 操作 | 期待 | 失敗条件 | mock | live | blk | 証拠 |
|---|---|---|---|---|---|---|---|---|---|
| L-01 | exe hashのpin | pin値 | preflight | 一致 | 不一致でFAIL | S | NO | YES | hash |
| L-02 | versionのpin | pin値 | `--version`(※§24参照) | 一致 | FAIL | S | NO(※) | YES | version |
| L-03 | CHANGELOG差分の監視 | pinした版から最新まで | キーワード抽出(§6の手順:`^## ` で分割し、retry・fallback・resume・auth・permission・settings・classifier・watchdog・non-streamingで正規表現) | 新しい項目は人間reviewへ | 無審査で版を上げる | S | NO | YES | diff report |
| L-04 | SDKの同梱CLI版 | Python SDKの `_cli_version.py` | 照合 | pinと一致 | 不一致 | S | NO | YES | file |

---

## 28. Mock provider設計(`FAKE_ANTHROPIC_V1`、実装はしない)

**目的：** 実際のAnthropic providerに接続せず、Claude Code CLIのretry・fallback・cancelの挙動を観測します。

**構成：**

- ローカルのHTTPS serverです(自己署名cert。CLIが信頼するよう `NODE_EXTRA_CA_CERTS` を**テスト環境に限って**設定します)。
- CLIに `ANTHROPIC_BASE_URL=https://127.0.0.1:<port>` を渡し、`ANTHROPIC_API_KEY=fake-not-a-real-key`(**本物のkeyは絶対に使わない**)を渡します。
- **注意：この構成は認証route R3を使うので、サブスク経路の検証にはなりません。** retry・fallback・cancelの「CLIの挙動」だけを検証する目的に限ります。
- network sandbox:127.0.0.1以外への外向き通信をすべてblockします。fast modeの可用性確認は `api.anthropic.com` に直接出ていくことがある(E16)ためです。`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` も併用します。
- 記録:受信したrequestごとに `seq`、`path`、`stream`(true/false)、`model`、header(`x-client-request-id` 等。keyはredact)、body hashをJSONLに書きます。

**実装するendpoint：**

- `POST /v1/messages`(stream / non-stream)
- (必要に応じて)`GET /v1/models`
- 未知のpathには404を返し、logに残します。

**scenario DSL(例)：**

```yaml
scenario: A-03_partial_stream_reset
responses:
  - match: {seq: 1, stream: true}
    action: stream
    events: [message_start(model=$REQ_MODEL), content_block_start, text_delta*20]
    then: tcp_reset_after_ms: 200
  - match: {seq: ">=2"}
    action: stream_ok(model=$REQ_MODEL)   # 2回目が来た事実自体を記録する
assert:
  relay_result: TAINTED
  fake_request_count: ">=2"   # CLIの挙動を記録(事実の固定)
```

**用意するcase：**

| case | 模擬内容 |
|---|---|
| 529 | `{"type":"error","error":{"type":"overloaded_error"}}`、status 529 |
| timeout | 接続を受け付けてheadersを送らない / headers後に無送信 |
| partial stream | 途中まで送ってreset / 途中で `event: error` |
| connection reset | 受信直後にRST |
| 401 | `authentication_error` |
| token refresh | 401の後、2回目は200(再送の観測用) |
| 403 | `permission_error` |
| classifier rerun | refusal相当のresponse。**実際のwire形式はUNKNOWN**なので、case定義を差し替えられるようにする |
| fallback | 1回目が404 `not_found_error`(model)。chain設定ありとなしで比較 |
| model mismatch | `message_start.message.model` を別IDにする |
| orphan result | cancel後にresponseを完了させる |
| delayed result | 応答の完了を大きく遅らせる |

**出力：** 各testの「CLIが実際に何回requestしたか」を**事実として固定**します。版を上げるときは、この事実表の差分を人間がreviewします(L-03と連動)。

---

## 29. Workspace Integrityとの統合、`CLAUDE_RUNTIME_IDENTITY_V1`

**基本方針：** Claudeには**repoを渡さない**のが第一案です。reviewの対象は、Work/LunaがGitHub canonicalから作ったdiffやfile内容のsnapshotとし、prompt本文として渡します。

- この場合、TREE_IDENTITY_V1はWork/Luna側で成立させ、Claude側のcwdは空にします(→ Claude側のGitのtree同一性は `NOT_APPLICABLE`)。
- promptに `snapshot_digest`(対象treeのhashとpromptのsha256)を含め、receiptに記録します。

どうしてもrepoを使う場合、TREE_IDENTITY_V1に以下を追加します。

- **Git側：**
  - `git ls-files -v` で小文字や `S` / `h` の行が0件
  - `git config core.sparseCheckout` がfalse
  - `git submodule status` が空、または期待どおり
  - `git status --porcelain=v2 --untracked-files=all --ignored` が期待と一致
  - `core.fsmonitor`・`core.hooksPath`・`filter.*` が無い
  - `.gitattributes` のfilter指定が無い
- **Claude runtime側(Gitで管理されていない、またはignoredの設定)：** 下記を対象にします。

```
CLAUDE_RUNTIME_IDENTITY_V1 = sha256( canonical_json({
  "v": 1,
  "exe": {"realpath":..., "sha256":..., "version":...},
  "argv": [...固定順...],
  "env_allowlist": {k: v for allowlisted},          # 値は秘密を含まないもののみ。秘密はhashのみ
  "env_denylist_absent": true,
  "config_dir_manifest": [{"path","sha256","mode"} ... ],   # 使い捨てCLAUDE_CONFIG_DIR全file
  "settings_layers": [{"layer","path","exists","sha256"}], # managed/user/project/local(存在しないことも記録)
  "cwd_manifest": [{"path","sha256","type"} ...],          # ignored・隠しfile・symlinkを含む全走査
  "ancestor_claude_md": [{"path","sha256"}],               # cwdから上位への探索
  "credentials_fingerprint": sha256(credential_file_bytes), # 中身は記録しない
  "managed_settings": {"path","exists","sha256"},
  "anthropic_profile_dir": {"path","exists","manifest_sha256"},
  "otel": {"exporter":"console|file","path":...}
}))
```

**接続方法：**

- preflightで計算し、終了後に再計算します。一致しなければREJECTEDにします。
- GitHub receiptには `tree_identity_v1`、`runtime_identity_v1`、`prompt_sha256`、`stream_log_chain_head`、`fsm_state` をまとめて書きます(durable)。
- 判定語：この仕組みで**runtime設定の同一性**は確立できます(PARTIAL:managed settingsやserver flagはhashの範囲外)。

---

## 30. Config Identity(依頼文が途中で切れていた部分を補った)

結果を左右する要素ごとに、canonical hashにできるかを整理しました。

| 要素 | hash可能か | 方法 | 残り |
|---|---|---|---|
| 実行fileのversion・hash | 可 | §29の `exe` | auto-updateの停止を確認(T19) |
| model | 可(requestedのみ) | argv | executedはUNKNOWN |
| 認証route | 部分的 | env・settings・init | server側はUNKNOWN |
| permission mode | 可 | argvとinit | — |
| retry設定 | 可(env) | env allowlist | 無効化できない経路がある(§7) |
| fallback設定 | 可 | settingsとargv | `last_resort` はUNKNOWN |
| session flag | 可 | argv | — |
| cwd | 可 | manifest | — |
| env allowlist | 可 | canonical | — |
| user・project・local・managed settings | 可 | hash(存在しないことも含める) | managedはOSで場所が異なる |
| MCP設定 | 可 | 空であることを証明 | — |
| hooks・plugins・skills・CLAUDE.md・AGENTS.md | 可 | manifest | 上位dirの探索範囲はdocsで要確認 |
| server feature flag | **不可** | — | UNKNOWN(clientが取得したflagのcacheは `CLAUDE_CONFIG_DIR` 内にある可能性。形式はUNKNOWN) |
| Anthropic側のモデル実装・routing | **不可** | — | UNKNOWN |
| usage creditsのtoggle | 不可(自動では) | 人間確認のhash | 時点情報 |

**結論：** client側の設定はhashで同一性を示せます(PARTIAL)。server側(flag・routing・classifier)は範囲外で、**完全なconfig identityは不可能**です(UNKNOWNが残る)。

---

## 31. Claude固有に追加すべき安全gate(依頼項目I)

| Gate | 内容 | 位置 |
|---|---|---|
| G-C1 `CLAUDE_VERSION_PIN_GATE` | exe hash、version、CHANGELOG差分reviewの済み印 | preflight |
| G-C2 `CLAUDE_ENV_FREEZE_GATE` | `env -i` + allowlist + denylist | spawn |
| G-C3 `CLAUDE_CONFIG_ISOLATION_GATE` | 使い捨て `CLAUDE_CONFIG_DIR` と空のcwd、上位のCLAUDE.md検査 | preflight |
| G-C4 `CLAUDE_SUBSCRIPTION_ROUTE_GATE` | init `apiKeySource=none`・`subscriptionType` あり・`tokenSource` なし・`apiProvider` がfirstParty | SENT直前(init受信時) |
| G-C5 `CLAUDE_BILLING_HUMAN_GATE` | usage credits OFFの人間確認(24時間以内) | preflight |
| G-C6 `CLAUDE_SINGLE_REQUEST_GATE` | OTel `api_request` がちょうど1件で、retry・fallback・resume・classifierのeventが0件 | 結果判定 |
| G-C7 `CLAUDE_MODEL_SELF_CONSISTENCY_GATE` | §10の規則 | 結果判定 |
| G-C8 `CLAUDE_RUNTIME_IDENTITY_GATE` | pre/postの一致 | 結果判定 |
| G-C9 `CLAUDE_NO_RESUME_GATE` | argv・env・永続化fileが0件 | preflightと事後 |
| G-C10 `CLAUDE_FSM_WRITE_AHEAD_GATE` | SENTを書き込んでから起動 | spawn |

---

## 32. 最終判定

### 32.1 Phase 0 RelayからClaudeをlive起動してよい根拠は揃ったか

**BLOCKED**

| # | Blocker | 分類 | 解消の見込み |
|---|---|---|---|
| B1 | retry=0を保証できない(§7 B・G・Y・Z1、§8) | BLOCKED | Anthropic側の公開スイッチが無ければ解消しない。Phase 0の要件を「**検出して不採用(detect-and-reject)**」に**人間とSolが正式に変更**すれば、PARTIALで前進可能 |
| B2 | 途中切断応答の自動継続(v2.1.246) | FAIL | 同上。G-C6で検出する前提 |
| B3 | 実行されたモデルを独立に検証できない | UNKNOWN | 要件を「自己申告の整合性(SELF_CONSISTENT)」に緩めるかどうかを人間が判断 |
| B4 | 実行中の認証drift | PARTIAL → G-C2・G-C3・G-C8で軽減 | 実装とmock test後に再評価 |
| B5 | 現行2.1.280のsourceを読めていない(npmが403) | UNKNOWN | npm取得が許可された環境で `cli.js` またはbinaryを静的に監査する |
| B6 | docs逐語確認が未完了(env-varsのretry系、`--restricted`、`--setting-sources`、`--tools ""`) | UNKNOWN | 人間またはGeminiが原文ページで逐語確認する |
| B7 | 本人専用自動化の規約上の明文 | UNKNOWN(E21で課金上の扱いは明記) | Consumer Termsの確認(fetchに承認が必要) |

### 32.2 READYにするための最短経路(提案、要承認)

1. **要件の再定義(人間・Sol):**
   - 「retry=0」を「**provider requestが2回以上観測されたら、結果を不採用にし、再dispatchしない**」に言い換えます。
   - 「executed model」を「self-consistent」に言い換えます。
   - この言い換えはsafety要件を弱める変更なので、**人間の明示承認が必要**です。
2. **静的な作業(live不要):**
   - §27のS・M testと、§28のfake providerを実装します。
   - CLI 2.1.280の実際のretry回数を**fakeで事実として固定**します(fakeにはAPI key形式の偽文字列を使い、サブスクには触れない)。
3. **docsの逐語確認:** B6。
4. **最小のlive smoke(人間の承認後、1回だけ):**
   - 条件:§24をすべてPASSし、usage credits OFFを当日に確認済み。
   - 使うモデルはSonnet 5のフルID(Opus 5.5は既定が1M context。Proでusage creditsが必要かどうかはUNKNOWN、E08)。
   - promptは無害な固定文。tool無し、`--max-turns 1`。
   - 結果はG-C4・G-C6・G-C7で判定します。

### 32.3 モデル選択

- この監査文書の作成(複数資料の統合と矛盾検出):🔴 上位モデルで実施しました。
- 本書に基づくtestとfakeの実装:🟢 軽量モデルで可。
- 32.2の手順1(要件の再定義)と手順4(live Go/No-Go):🔴 上位モデルと人間。

---

## 付録:出典URL

- CHANGELOG: https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md (tag v2.1.280)
- TS SDK CHANGELOG: https://github.com/anthropics/claude-agent-sdk-typescript/blob/main/CHANGELOG.md (v0.3.280)
- Python SDK: https://github.com/anthropics/claude-agent-sdk-python (v0.2.158)
- claude-agent-acp: https://github.com/agentclientprotocol/claude-agent-acp (v0.81.0 / HEAD 281e47e、PR #1165・#1129)
- ACP protocol: https://github.com/agentclientprotocol/agent-client-protocol (v1.9.1) の `docs/protocol/v1/prompt-turn.mdx`
- docs: https://code.claude.com/docs/en/env-vars 、/settings 、/settings-reference 、/model-config 、/authentication 、/permission-modes 、/headless 、/sessions 、/cli-reference 、/costs 、/advisor 、/fast-mode 、/interactive-mode 、/legal-and-compliance 、/agent-sdk/overview 、/agent-sdk/typescript 、/monitoring-usage
- Help Center: https://support.claude.com/en/articles/11145838 、https://support.claude.com/en/articles/15036540
- Issue: https://github.com/anthropics/claude-code/issues/87930 (題名のみ)


---
---

# PART 2 — Section 31〜47(続編・2026-09-23 JST 追記)

- 前提:PART 1(§0〜§32)をそのまま使います。再調査はしていません。
- 前回版には §31「Claude固有gate」と §32「最終判定」を置いていましたが、今回の依頼の番号と重なります。**前回版の §31 と §32 は「§P1-31」「§P1-32」と読み替えてください。** 内容は §40 と §44 で置き換えます。
- 今回も次のことはしていません。live実行、Chrome操作、GitHub書込み、設定変更、package install。
- 今回新たに使ったsource(E27〜E33)

| ID | source | 版 / 日付 |
|---|---|---|
| E27 | claude-agent-acp main HEAD `df38ccc`(2026-09-23T12:01+02:00、**未release**)。PR #1097「resumeしたsessionで maxTurns / maxBudgetUsd の変更が無視されていた」を修正 | 未release |
| E28 | docs「Use Claude Code with Chrome」 https://code.claude.com/docs/en/chrome (全文) | 2026-09-23取得 |
| E29 | Help Center 12902446「Claude in Chrome permissions guide」[要約経由] | 最終更新 2026-08-12 |
| E30 | Help Center 12902428「Use Claude in Chrome safely」[要約経由] | 最終更新 2026-08-12 |
| E31 | docs「CLI reference」の逐語照合(2回目)。`--disable-slash-commands`、`--disallowedTools`、`--max-turns`、`--fallback-model`、`--permission-prompts`、`--max-budget-usd`、`--bare` の行を**逐語で確認**。`--session-id`、`--tools`、`--settings` は**ページが途中で切れて NOT FOUND** | 2026-09-23 |
| E32 | Python SDK `subprocess_cli.py` の 588〜597行目。`tools=[]` のとき `--tools ""` を渡す。651行目で `--session-id=` を渡す | v0.2.158 |
| E33 | `git ls-remote https://github.com/kamiyusense/multi-ai-council-phase0` が認証要求で失敗(private repoか、存在しない) | 2026-09-23T10:03Z |

---

## 31. Receipt と Replay Prevention の統合(`CLAUDE_DISPATCH_FSM_V2`)

### 31.1 設計原則

1. **「receiptが無い」を「実行されていない」と推定しない。** receiptが無いのは「記録が無い」という事実だけです。
2. 外部作用(provider request)が起きたかどうかは、**起動した事実**を境目にして非対称に扱います。一度でもprocessを起動したら、以後はずっと「起きた可能性あり」とします。
3. 状態は必ず**先にdurableに書いてから**進めます(write-ahead)。書けなければ、その先へは進みません。
4. 同じ `dispatch_id` を再び起動することは**仕様上存在しない遷移**にします。

### 31.2 状態の一覧

| 状態 | 意味 | provider requestの可能性 | durableに記録する時点 |
|---|---|---|---|
| `RESERVED` | dispatch_idを確保した。何も起動していない | 無 | 確保と同時 |
| `SPAWN_INTENT` | 起動の直前の宣言。**この記録が成功したときだけ起動できる** | 無(記録時点) | 起動前 |
| `PROCESS_STARTED` | OS processが存在する(pidと開始時刻を記録) | **有り得る**(起動直後から) | 起動直後(失敗しても状態はSPAWN_INTENT+αとみなす) |
| `INIT_OBSERVED` | `system/init` を受信し、G-C4の検証が済んだ | 有り得る | 受信時 |
| `REQUEST_MAY_BE_SENT` | promptをstdinに書き込んだ | **高** | 書込み前 |
| `MODEL_MAY_BE_RUNNING` | stream_eventを受信中 | 確実 | 最初のeventで |
| `PARTIAL_RECEIVED` | 一部を受信した(最後に受け取ったeventのseqとhash) | 確実 | 定期的に |
| `RESEND_SUSPECTED` | api_retry、auth_refresh、model_fallback、resume_reason のいずれかを観測した。またはOTelの `api_request` が2件以上 | 2回以上 | 観測時 |
| `RESULT_RECEIVED` | resultメッセージを受信した | — | 受信時 |
| `CANCEL_REQUESTED` | Relayがcancelを決めた | 有り得る | 送信前 |
| `PROCESS_GONE` | processが消えた(exit、kill、crash、観測不能)。exit codeとsignalを記録 | 有り得る | 観測時 |
| `BACKEND_UNKNOWN` | process側は終了したが、backendの状態は確認できない | 有り得る | 同上 |
| `LATE_RESULT` | PROCESS_GONEの後、またはCANCEL_REQUESTEDの後に出力が届いた | — | 観測時(隔離して保存) |
| `RECEIPT_WRITE_FAILED` | 終端receiptの書込みが失敗した | — | ローカルのjournalに記録 |
| `TERMINAL_ACCEPTED` | 結果を採用した(§26のACCEPTED条件をすべて満たす) | — | 終端 |
| `TERMINAL_REJECTED` | 結果を不採用にした(外部作用はあったものとして扱う) | — | 終端 |
| `TERMINAL_UNKNOWN` | 成否を判定できない | — | 終端 |

### 31.3 遷移(抜粋、これ以外は禁止)

```
RESERVED → SPAWN_INTENT → PROCESS_STARTED → INIT_OBSERVED → REQUEST_MAY_BE_SENT → MODEL_MAY_BE_RUNNING
  → PARTIAL_RECEIVED* → RESULT_RECEIVED → (evidence判定) → TERMINAL_ACCEPTED | TERMINAL_REJECTED
任意(PROCESS_STARTED以降) --retry系観測--> RESEND_SUSPECTED --(以後の結果)--> TERMINAL_REJECTED
任意(PROCESS_STARTED以降) --cancel決定--> CANCEL_REQUESTED --exit--> PROCESS_GONE → BACKEND_UNKNOWN
任意(PROCESS_STARTED以降) --process消失--> PROCESS_GONE → BACKEND_UNKNOWN
BACKEND_UNKNOWN --遅延出力--> LATE_RESULT(記録のみ) → TERMINAL_UNKNOWN
BACKEND_UNKNOWN --quarantine満了--> TERMINAL_UNKNOWN
RESULT_RECEIVED --receipt書込み失敗--> RECEIPT_WRITE_FAILED --(復旧時)--> §31.4
INIT_OBSERVED --G-C4失敗(stdin未書込み)--> PROCESS_GONE(kill) → TERMINAL_REJECTED (※送信前だが「起動済み」なので再利用しない)
```

補足:INIT_OBSERVEDで失敗した場合も、`system/init` の前に何か通信した可能性は否定できません。**起動済みはすべて「外部作用あり得る」に分類します。**

### 31.4 新しいcontrollerが復旧するときの判定(機械判定表)

入力は、durable storeに残っている**最後の状態**と、ローカルjournalの有無です。

| 最後のdurable状態 | ローカルjournal | 判定 | 同じdispatch_idの再起動 | 次の行動 |
|---|---|---|---|---|
| なし(dispatch_id自体が無い) | — | `SAFE_TO_CONTINUE` | 対象外 | 新しいdispatchを作れる |
| `RESERVED` | — | `SAFE_TO_CONTINUE` | **可**(未起動が確定しているため。SPAWN_INTENTの書込みが唯一の起動許可なので) | そのまま進めてよい |
| `SPAWN_INTENT` | processの痕跡なし | `UNKNOWN` | **不可** | 起動した可能性を否定できない → TERMINAL_UNKNOWN。人間かSolの判断 |
| `PROCESS_STARTED` 〜 `PARTIAL_RECEIVED` | 任意 | `MUST_NOT_REDISPATCH` | 不可 | 生き残りprocessを探してkill → BACKEND_UNKNOWN → TERMINAL_UNKNOWN |
| `RESEND_SUSPECTED` | 任意 | `TERMINAL` | 不可 | TERMINAL_REJECTED |
| `RESULT_RECEIVED` | 結果とevidenceが揃っている | `SAFE_TO_CONTINUE`(receiptの完成だけ) | 不可 | 保存済みの結果でevidence判定をやり直し、receiptだけ書く。**modelは呼ばない** |
| `RESULT_RECEIVED` | 結果が無い | `UNKNOWN` | 不可 | TERMINAL_UNKNOWN |
| `RECEIPT_WRITE_FAILED` | journalあり | `SAFE_TO_CONTINUE`(receiptの再書込みだけ) | 不可 | receiptだけ冪等に再書込み(dispatch_idと内容hashをkeyにする) |
| `CANCEL_REQUESTED` / `PROCESS_GONE` / `BACKEND_UNKNOWN` / `LATE_RESULT` | 任意 | `MUST_NOT_REDISPATCH` | 不可 | TERMINAL_UNKNOWN |
| `TERMINAL_*` | — | `TERMINAL` | 不可 | 何もしない |

**不変条件(実装のassertにする):**

- `redispatch_allowed(dispatch_id)` が真になるのは、最後の状態が `RESERVED` のときだけです。
- 状態が `SPAWN_INTENT` 以降なら、「新しいdispatch_id」「人間またはSolの承認」「前回のdispatch_idへの参照(`supersedes`)」の3つが揃わない限り、同じ作業を再び実行してはいけません。
- 「receiptが無い」は、判定表では常に `UNKNOWN` 以下に倒します(SAFEにはしません)。

**判定:** CONFIRMED(設計として閉じています)。ただしdurable store側の原子性(GitHubへの書込みの冪等性)は既存Phase 0の実装に依存するため、**NOT VERIFIED AGAINST CURRENT REPOSITORY** です。

---

## 32. Browser Reviewer Relay への Claude 追加

### 32.1 変えない原則

- 正本はGitHubの `review_response` だけです。
- browserやChat UIはtransportであって、成功の証拠になりません。
- tab ID、session ID、会話URLは**正しさの判定に使うfieldにしません**(記録用のメタデータとしてだけ使います)。

### 32.2 role設計(SolとClaudeの競合を避ける)

| role | 誰が | 権限 | 同じrequestへの回答 |
|---|---|---|---|
| `PRIMARY_REVIEWER` | Sol | review_responseの提出 | 1件 |
| `SECONDARY_REVIEWER` | Claude | `secondary_review_response`(**別種のrecord**)の提出。primaryを上書きできない | 1件 |
| `BACKUP_REVIEWER` | Claude | primaryが `TERMINAL_UNKNOWN` になった後、**新しい `round`** でだけ起動できる(同じroundの代替はしない) | 1件 |

- **同時に回答した場合の競合:** record種別とroleが違うので、衝突は構造上起きません。最終判断(`semantic_decision`)はSolだけが出します。Claudeの結果はSolの判断の入力です。
- **Claude in Chromeをtransportとして使う場合:** Browser Reviewer Relayのtransportを置き換えるだけです。正本の書き手はWork/Lunaのままです(ClaudeがGitHubへ直接書き込むことはしません)。

### 32.3 request / response の結び付け

```
review_request {
  request_id, round, correlation_id, reviewer_role,
  target: { repo, pr_number, head_sha, tree_sha, base_sha },
  wake_reservation_id,          # 1 request = 1 wake予約(再wake禁止)
  issued_at, expires_at, generation
}
review_response(ClaudeはSECONDARY用のrecord種別) {
  request_id, round, correlation_id, reviewer_role,
  reviewed_head_sha, reviewed_tree_sha,     # Claudeが実際に読んだsnapshotのhash
  snapshot_digest,                           # Work/Lunaが渡したpromptの材料のsha256
  dispatch_id, fsm_terminal_state,           # §31
  findings[], submitted_at, generation
}
```

### 32.4 Work/Lunaが受理する条件(1つでも外れたら拒否)

1. `request_id`、`round`、`correlation_id`、`generation` が一致する。
2. `reviewed_head_sha` と `reviewed_tree_sha` が、request発行時の `target` と一致する。さらに**受理時点のPR headとも一致する**。一致しなければ `STALE` として拒否します。
3. 同じ (`request_id`, `round`, `reviewer_role`) の受理済みrecordが**無い**。あれば `DUPLICATE` として拒否します。
4. `fsm_terminal_state == TERMINAL_ACCEPTED` であり、§26のevidenceがそろっている。
5. `expires_at` を過ぎていない。
6. retryもfallbackも無い:`dispatch_id` がこのrequestで1つだけ。

**判定:** 設計はCONFIRMEDです。既存のrelayとの整合は **NOT VERIFIED AGAINST CURRENT REPOSITORY** です。

---

## 33. Claude in Chrome の監査

| 項目 | 事実 | 根拠 | 判定 |
|---|---|---|---|
| 必要なもの | extension 1.0.36以上、Anthropicのプラン(Pro、Max、Team、Enterprise)、`/login` | E28 | CONFIRMED |
| 利用枠 | Anthropicのプランを直接使う。**API keyや `setup-token` だとChrome連携はOFF** | E28 | CONFIRMED(サブスク経路でのみ動く) |
| 権限モデル | 3モード:Manual、Auto(安全チェック付き)、Skip(**確認なし**)。サイト単位で「今回だけ」「このサイトは常に」「拒否」 | E29 | CONFIRMED[要約経由] |
| 常に確認が要る操作 | download、機微情報の入力、権限の付与 | E29 | CONFIRMED[要約経由] |
| 禁止操作 | 購入、アカウント作成、完全削除、カード情報 | E29 | CONFIRMED[要約経由] |
| browser profile | **ユーザーの実際のChromeのlogin状態を共有**(「既にsign-inしている全サイトにアクセス可」) | E28 | CONFIRMED |
| cookie、localStorage | login状態を共有するので**実質的にアクセスできる**。個別APIの有無はUNKNOWN | E28 | PARTIAL |
| 読めるもの | console、DOM、network(tool一覧)、screenshot、GIF | E28 | CONFIRMED |
| browser側のretry | 「tabが無い」ときは新しいtabを作ってretryするよう、docsが案内している | E28 | PARTIAL(自動retryの有無はUNKNOWN) |
| taskの回復 | service workerがidleになると切断し、`/chrome` で再接続 | E28 | CONFIRMED |
| Claude Codeとの統合 | `--chrome`、native messaging host、`bridge.claudeusercontent.com` 経由 | E28 | CONFIRMED |
| 証拠の取得 | screenshotのdisk保存(v2.1.211+)、GIF、console log | E28 | CONFIRMED |
| UIの成功とbackendの成功の分離 | 分離する仕組みは無い(UI観測だけ) | — | 設計で分離が必要 |
| 古いtabやsessionのリスク | tab groupはsessionに紐づく。`/resume` や終了時の扱いは状態によって変わる(E28) | E28 | PARTIAL |
| prompt injection | 公式が警告し、**別のbrowser profile**を推奨 | E30 | CONFIRMED |

**Phase 0で推奨するrole:**

| role | 適否 | 条件 |
|---|---|---|
| Web UIのregression test(AIBOのローカルWeb UIなど) | ◎ | 専用のChrome profile(何にもloginしていない)、localhostだけ許可、Manualモード |
| consoleとDOMの調査 | ◎ | 同上 |
| network調査 | ○ | 同上 |
| Web専用providerの検証(Sol ChatのUIなど) | △ | 実際のアカウントにloginが要る → injectionのリスク。**Skipモードは禁止** |
| Browser Reviewer transport | △ | §32.2の原則を守る。UIが成功しても証拠にはしない |

- **判定:** 現時点でPhase 0のlive用途にはBLOCKEDです(§P1-32のblockerと同じ認証経路と課金のUNKNOWNがあるため)。静的な設計はCONFIRMEDです。
- 🟡 ユーザーが普段使っているChrome profileでは使わないでください(E30)。

---

## 34. `CLAUDE_EXECUTOR_CONTRACT_V1`(Claude Codeを第二のexecutorにする場合)

```yaml
contract: CLAUDE_EXECUTOR_CONTRACT_V1
identity:
  dispatch_id: uuid(fresh)            # §31
  execution_generation: int           # mutation leaseの世代(fencing token)
  runtime_identity: CLAUDE_RUNTIME_IDENTITY_V1   # §29
repo:
  expected_repo: owner/name
  expected_branch: refs/heads/<task-branch>      # task専用。default branchは禁止
  expected_head: <sha>
  expected_tree: <tree sha>
  tree_identity: TREE_IDENTITY_V1 (+§29のgit追加検査)
scope:
  allowed_paths: [glob...]            # これ以外への書込みは後段で検出してREJECT
  allowed_operations: [read, edit_within_allowed_paths]   # commitとpushはRelay側が行う(Claudeにgitの書込み権限を与えない)
lease:
  mutation_lease: {holder: dispatch_id, generation, expires_at}   # GitHubまたはWork/Lunaが発行
policy:
  retry: 0 (検出→REJECT、§7)
  fallback: disabled (§9)
  resume: forbidden; session_reuse: forbidden; persistence: off
  auth: claude_ai_oauth only; api_key: forbidden
  model: fixed full ID; usage_credit_only_models: forbidden (Fable, [1m], fast mode)
  tools_allowlist: [Read, Edit]  # Bash、WebFetch、MCP、Agentは禁止
  permission_mode: dontAsk + permission-prompts none
post_run (Relay側で実行。Claudeは関与しない):
  precommit_revalidation:
    - lease.generationが最新であること
    - 現在の作業branchのHEADとtreeがexpected_*と一致すること(Claudeの編集前の基準)
    - 変更されたpathがallowed_pathsの範囲内
    - CLAUDE_RUNTIME_IDENTITY_V1がpreとpostで一致
  commit:
    parent == expected_head を検証
    commit tree == ステージした内容のtreeを検証
  push: expected_branchへ、lease(`--force-with-lease=<branch>:<expected_head>` 相当)で
  remote_readback: pushの後にremote branchのHEAD == 作ったcommit、treeが一致
  terminal_receipt: {dispatch_id, generation, commit_sha, tree_sha, readback_ok, fsm_state}
ambiguous_write:
  pushの成否が不明(timeoutなど) → readbackで確認する
    remote == 自分のcommit → ACCEPTED
    remote == expected_head → 未反映。同じdispatchでは再pushしない → TERMINAL_UNKNOWN。人間とSolに判断を委ねる
    それ以外 → CONFLICT → REJECTED
```

**Claude Codeがこの契約を満たせるか:**

| 項目 | 状態 | 理由 |
|---|---|---|
| fresh identity、no resume、no session reuse | PARTIAL | flagとenvで制御できる(§15)。中断ターンの既定値はUNKNOWN |
| retry=0 | **BLOCKED** | §7 |
| fallbackの無効化 | PARTIAL | §9 |
| API keyなし | PARTIAL | §11・§12(実行中のdrift) |
| usage-credit専用modelの禁止 | CONFIRMED | 起動時の引数とsettingsで拒否できる |
| model固定 | PARTIAL | 実行されたモデルはUNKNOWN |
| tool allowlist | CONFIRMED | `--tools` と `--disallowedTools`(E31・E32) |
| allowed_paths | PARTIAL | Claude側のpermission rulesは補助。**真の強制はRelay側の事後diff検査** |
| precommit、commit、readback | CONFIRMED(Relay側で実装すれば) | Claudeにgitの書込みをさせない設計 |
| mutation lease | CONFIRMED(設計) | Claudeの外側の仕組み |
| 総合 | **BLOCKED** | retry=0の要件とlive blocker |

---

## 35. Julesとの相互監査(ClaudeはRead-only reviewer)

```
Jules PR (head H, tree T)
 → Work/Luna: review_request(reviewer_role=CLAUDE_SECONDARY, target={H,T})
 → Work/Luna: canonical snapshotを作る(GitHub APIからdiffと関連fileを取得し、内容をhash)
 → Claude(tool無し、prompt本文にsnapshotを入れる。§14・§24)
 → structured findings(JSON)
 → Work/Luna: 検証(§32.4) → GitHubのdurable review record(PR commentまたはcheck run。書くのはWork/Lunaの権限だけ)
 → Sol: 最終的なsemantic判断(Claudeのfindingsは入力の1つ)
 → 次のJules task
```

**Claudeのreview結果schema(`CLAUDE_REVIEW_RESULT_V1`):**

```json
{
  "review_id": "uuid",
  "request_id": "uuid",
  "round": 1,
  "correlation_id": "string",
  "reviewer_role": "CLAUDE_SECONDARY",
  "dispatch_id": "uuid",
  "expected_head": "sha",
  "expected_tree": "sha",
  "reviewed_snapshot_digest": "sha256",
  "decision_scope": "ADVISORY_ONLY",
  "findings": [
    {
      "finding_id": "CLR-001",
      "severity": "BLOCKER|MAJOR|MINOR|INFO",
      "classification": "CONFIRMED|PARTIAL|UNKNOWN|FAIL",
      "location": {"path": "string", "line_start": 1, "line_end": 1},
      "claim": "string",
      "evidence_refs": ["snapshot:path#Lx-Ly", "doc:URL"],
      "counterexample": "string|null",
      "recommended_tests": ["string"]
    }
  ],
  "unknowns": ["string"],
  "submitted_at": "date-time",
  "generation": 1
}
```

**設計の意図:**

- Claudeは書き込まないので、writerどうしの衝突は起きません。
- Claudeが見るのは、Julesのworkspaceではなく**GitHub canonicalから作ったsnapshot**です。これで「Julesが見ているものと同じ誤り」を共有しにくくなります。
- `decision_scope=ADVISORY_ONLY` と固定し、merge判断の権限は持たせません。

**判定:** 設計はCONFIRMEDです。live実行はBLOCKEDです(§44)。

---

## 36. `ADVERSARIAL_REVIEW_V1`(独立reviewerとしてのClaude)

### 36.1 Solの結論を最初から見せるか

**見せません(2段階方式)。** 理由は次の3つです。

1. 先に結論を見せると、anchoring(最初に見た結論に引きずられること)で相関した見落としが増えます。これは一般的な認知バイアスの知見で、**本件で測定したものではありません(UNKNOWN扱い)**。
2. Phase 0が狙っているのは「異なるfailure mode」です。
3. 比較は後段で機械的にできます。

- Stage A(blind):同じsnapshotと仕様だけを渡し、Solの結論は渡しません。
- Stage B(compare):Stage Aの結果を**commit(hashをdurableに記録)した後で**、Solの結論を渡して差分を分析させます。Stage Aを後から書き換えることは禁止です。

### 36.2 必須の8ステップ(各ステップの出力は必須で、空なら理由を書く)

| # | step | 出力 |
|---|---|---|
| 1 | independent source audit | 主張ごとの一次資料と、その版・日付。無ければUNKNOWN |
| 2 | counterexample search | 仕様を満たしているのに危険な入力や状態の例を最低3件 |
| 3 | failure-mode enumeration | 部品(transport、auth、model、workspace、receipt)ごとの失敗モード |
| 4 | invariant break attempt | 各不変条件を破る手順を試しに組み立てる(実行はしない) |
| 5 | evidence-strength audit | 証拠を CONFIRMED / 自己申告 / 要約経由 / 推論 に分類する |
| 6 | UNKNOWN inflation check | 証拠があるのにUNKNOWNにしている箇所(過度な保守)を指摘する |
| 7 | false-PASS search | PASSとされている項目のうち、根拠が自己申告や推論だけのものを列挙する |
| 8 | implementation-vs-spec mismatch | コードと仕様書の食い違い(読めた範囲で) |

- **出力の制約:** 判定語はCONFIRMED、PARTIAL、UNKNOWN、BLOCKED、FAILだけ。曖昧な形容は禁止です(§37)。
- **Stage Bの出力:** `agree[]`、`disagree[]`(それぞれの根拠)、`sol_only[]`、`claude_only[]`。不一致はSolの判断より上の人間レビューに回します。

---

## 37. 安全性の分類規則

- 使ってよい判定語:**CONFIRMED、PARTIAL、UNKNOWN、BLOCKED、FAIL**(該当しない場合だけNOT_APPLICABLE)。
- 禁止表現:「安全そう」「おそらく問題ない」「十分安全」「問題なさそう」「基本的に大丈夫」など。これらが出力に含まれた場合、parserがそのreviewを**不採用**にします(検査用の正規表現をTEST A36-01として§42に登録)。
- 判定にはevidence_refが必須です。refが無いCONFIRMEDは自動でUNKNOWNに格下げします。
- 「要約経由」の証拠だけでCONFIRMEDになっている項目は、**PARTIAL以上にしない**ことを推奨します(本書のPART 1にある[要約経由]の項目も、これに従って読んでください)。

---

## 38. 反証(15件):壊れ方と防御

| # | 反証シナリオ | どう壊れるか(根拠) | 防御 | 残る状態 |
|---|---|---|---|---|
| 1 | retry=0なのにrequestが2回 | ストリーム途中切断の自動継続(2.1.246)、non-streaming再送、無応答1回retry(§7) | OTelの `api_request` 件数と、fake providerでの事実固定。2回以上なら不採用。再dispatchしない | **FAIL**(防止は不可、検出だけ) |
| 2 | subscriptionのつもりがAPI経路 | `-p` ではenvのAPI keyが常に優先(E09)。settingsの `env` ブロック | env freeze、使い捨てCONFIG_DIR、init検査(G-C4)、事後hash | PARTIAL |
| 3 | 要求したmodelと実行されたmodelの不一致 | 分類器による再実行、alias、server routing | フルIDで固定、`switchModelsOnFlag:false`、自己整合の検査 | **UNKNOWN**(独立証拠が無い) |
| 4 | cancel後もbackendが動いている | ACPの仕様上cancelはSHOULD(E05)。`still_queued`(E02) | FSMのBACKEND_UNKNOWN、再dispatch禁止 | UNKNOWN(検出できない) |
| 5 | processの死後に結果が届く | ACPの30秒猶予、親processの死亡 | LATE_RESULTとして隔離し、採用しない | CONFIRMED(設計) |
| 6 | freshのつもりがresumeになる | ACPの自動再作成とresume(E04)。中断ターンの再実行(`resume_reason`)。**ACPのresumeで変更したlimitが無視される(E27、未release修正)** | `--no-session-persistence`、ACP不使用、`resume_reason` 検出 | PARTIAL |
| 7 | cwdはcleanだがglobal設定が入り込む | user settings、managed settings、上位dirのCLAUDE.md(※探索範囲はdocsで要確認)、profile dir | 使い捨てCONFIG_DIR、managed settingsのhash、上位dirの走査 | PARTIAL(managedは除去できない) |
| 8 | permissionは安全なはずがACPでbypassできる | v0.81.0は `disableBypassPermissionsMode` を無視。Windowsでは常にALLOW_BYPASS | ACP不使用。使う場合はpinとhost opt-out | FAIL(v0.81.0) / NOT_APPLICABLE(不使用時) |
| 9 | receipt失敗後に二重実行 | receiptが無いのを未実行と誤認 | §31.4の判定表 | CONFIRMED(設計) |
| 10 | version driftで安全条件が消える | 1週間で約10版。既定値の変更(Proの既定がOpus 5.5、2.1.280) | exe hashのpin、auto-updateの停止(方法の名称はUNKNOWN)、CHANGELOG差分のreview | PARTIAL |
| 11 | 実行中に認証経路が変わる | settingsのhot reload(E07)、ターン間の資格情報入れ替え(E04) | 1 dispatch = 1 process = 1 turn、監視、事後hash | PARTIAL |
| 12 | fallback eventがevent streamに出ない | 分類器による再実行を示すevent名がUNKNOWN | modelUsageのkey数と、OTelの `api_request` 側の `model` でも検査(3系統で突き合わせ) | UNKNOWN |
| 13 | output parserがretry eventを見落とす | 未知のsubtype、行の分割、stderr側のみに出る情報 | **未知のsystem subtypeは不採用扱い**(allowlist parser)、JSONLの完全性チェック、stderrも保存 | CONFIRMED(設計) |
| 14 | 古いClaude processが新しいgenerationの結果を書く | lease切れのprocessが遅れて完了する | 書き手はWork/Lunaだけ。generation(fencing token)の照合。Claudeには書込み権限を与えない | CONFIRMED(設計) |
| 15 | Claude reviewerが古いPR headをreviewする | snapshot作成後にforce-pushされる | `reviewed_head_sha` と受理時のPR headを照合(§32.4-2)。不一致ならSTALEとして拒否 | CONFIRMED(設計) |

---

## 39. UNKNOWNを解消する計画(Unknown Closure Plan)

列の見方:
- 静的 = 静的testで解消できるか
- mock = mock testで解消できるか
- live = live実行が必要か
- 人間 = 人間の関与が必要か
- 未解消時のリスク = このUNKNOWNが残った場合の影響
- live阻止 = 解消しないとliveを止めるか

| ID | 何が不明か | なぜ不明か | 解消に必要な証拠 | 静的 | mock | live | 人間 | 未解消時のリスク | live阻止 |
|---|---|---|---|---|---|---|---|---|---|
| U01 | 現行2.1.280の実装 | npm取得が403 | cli.jsまたはbinaryの静的監査 | ◎ | — | — | 取得を許可 | 全体 | YES |
| U02 | `MAX_RETRIES=0` が各経路に効くか | 実装が読めない | U01 + fake(A-02〜A-07) | ○ | ◎ | — | — | 二重request | YES |
| U03 | 途中切断応答の自動継続を止める手段 | 資料に無い | docsやstaffの回答、U01 | ○ | ◎(挙動の固定) | — | issueで確認 | 二重request | YES |
| U04 | 分類器による再実行の-pでの挙動(true時) | DOCSとACPで記述が違う | fake(C-05)。wire形式はUNKNOWN | — | △ | △ | — | 別モデル実行 | YES |
| U05 | `system/model_fallback` の `last_resort` の意味 | 未記載 | U01、docs | ○ | ○ | — | — | 予期しない切替 | YES |
| U06 | EXECUTED_MODELとBILLED_MODEL | backend証拠が無い | Anthropicが提供する証拠(存在しない) | — | — | — | **要件を変えるか判断** | 監査が成立しない | YES(要件次第) |
| U07 | 中断ターン再開の既定値 | 未記載 | U01、docs | ○ | ○ | — | — | 再実行 | YES |
| U08 | SIGTERM後のresume(DOCSとCHANGELOGで相違) | 資料間で矛盾 | U01 | ○ | ○ | — | — | 再実行 | NO(永続化OFFで回避) |
| U09 | `--restricted` の現行のtool構成 | docsのページが途中で切れる | docs原文 | ◎ | — | — | 人間がページを確認 | 構成の誤り | NO(不使用) |
| U10 | `--setting-sources` の値 | docsページが404、要約が捏造 | docs原文、SDK source | ○ | — | — | — | 設定の侵入 | NO(CONFIG_DIRで代替) |
| U11 | `fallbackModel: []` の意味 | 未記載 | U01 | ○ | ○ | — | — | — | NO(存在しないことを確認すれば足りる) |
| U12 | 新しいenv(`DISABLE_NONSTREAMING_FALLBACK`、`ENABLE_STREAM_WATCHDOG` など)がdocsで正式か | env-varsページが途中で切れる | docs原文 | ◎ | ○(効果の確認) | — | 人間がページを確認 | 効かないenv | YES |
| U13 | Opus 5.5(1M)がProでusage creditsを要するか | 未記載 | docs、Help Center | ○ | — | — | 人間 | 課金 | NO(Sonnet 5で回避) |
| U14 | cancelやkill後のbackend停止 | 観測手段が無い | 無し | — | — | — | 受容を判断 | 課金、生成 | YES(要件次第) |
| U15 | 本人専用の自動化の規約上の扱い | Consumer Termsを取得できない | 規約の原文 | ○ | — | — | **人間** | アカウントの措置 | YES |
| U16 | usage creditsがOFFのとき、Fableや1Mは確実に止まるか | 未記載(E16はfastのみ) | Help Center 12429409(429エラーで未取得) | ○ | — | △ | 人間 | 課金 | NO(Fableと1Mを禁止) |
| U17 | 背景のHaikuがSDK経由で動くか | 2.1.277の記述が「SDK外」のみ | U01、fake | ○ | ◎ | — | — | 別モデル | NO(CLIを直接起動) |
| U18 | auto-updateの停止方法の正式名 | 未確認 | docs | ◎ | — | — | — | drift | YES |
| U19 | init/controlでaccount情報(`subscriptionType` 等)を取得する方法(-p単独の場合) | SDKではinitializeで取得(E04)、-pのstreamでは未確認 | U01、fake | ○ | ◎ | — | — | 認証経路の未検証 | YES |
| U20 | CLAUDE.mdの上位dir探索の範囲 | 未確認 | docs原文 | ◎ | ○ | — | — | 文脈の汚染 | NO(使い捨てdirの配置で回避) |
| U21 | Phase 0 repoとの整合 | repoにアクセスできない(E33) | read権限 | ◎ | — | — | 人間(共有方法) | 重複実装 | NO |
| U22 | thinking付きの単発応答が1 requestで収まるか | 未記載 | fake + U01 | ○ | ◎ | △ | — | 誤ったTAINTED判定 | NO(安全側に倒れるだけ) |

**今回解消したUNKNOWN:**
- `--tools ""` の受理(旧§14のUNKNOWN):公式Python SDKが「tools=[]」のときに `--tools ""` を渡す実装を確認(E32)→ **CONFIRMED(公式SDKが使うインターフェース)**。
- `--disallowedTools "*"` で全toolを除去できること:docsの逐語で確認(E31)→ **CONFIRMED**。
- `--disable-slash-commands`:逐語で確認(E31)→ **CONFIRMED**。
- `--session-id`:公式SDKが使用(E32)→ **CONFIRMED(存在)**。docsの行は途中で切れていて未確認。

---

## 40. `CLAUDE_LIVE_POC_READY` gate(機械判定)

```yaml
gate: CLAUDE_LIVE_POC_READY
rule: READY は「必須条件がすべて PASS」かつ「必須UNKNOWNが0件」かつ「人間の明示承認がある」ときだけ。それ以外は NOT_READY(理由を列挙)
conditions:
  C01 claude_code_version_pinned: PASS if 実行fileのsha256とversionがpin値と一致
  C02 executable_identity_verified: PASS if 絶対path、realpath、symlink無し、hash一致
  C03 sdk_version_pinned: PASS or NOT_APPLICABLE(CLIを直接使う場合)
  C04 acp_version_pinned: NOT_APPLICABLE required(Phase 0ではACP不使用。使う場合は#1165と#1097を含むrelease版にpin)
  C05 runtime_config_hash_pinned: PASS if CLAUDE_RUNTIME_IDENTITY_V1がpre=post
  C06 subscription_route_verified: PASS if init/accountでclaude_ai_oauthと判定(U19に依存)
  C07 forbidden_auth_absent: PASS if env、settings、profile、managedに禁止の認証源が無い
  C08 usage_credit_safety: PASS if 人間確認のOFFが24時間以内 かつ Fable、[1m]、fast、advisorが無効
  C09 retry_acceptable_under_invariant: PASS only if 人間とSolが「検出→不採用」方式を正式採用済み かつ U02、U03、U12がmockで事実固定済み
  C10 fallback_disabled_or_detectable: PASS if chainが無く、switchModelsOnFlag=false、U04、U05の扱いが決まっている
  C11 model_identity_evidence_acceptable: PASS only if 人間が「SELF_CONSISTENTで可」と正式に決定済み(U06)
  C12 no_session_resume: PASS if 永続化OFF、resume系flagが無い、RESUME_INTERRUPTED_TURN=0
  C13 permission_safe: PASS if dontAsk、prompts none、tools空、bypass無効
  C14 workspace_clean: PASS if 空のcwd、上位にCLAUDE.md等が無い
  C15 config_identity_clean: PASS if C05と同じ
  C16 dispatch_reservation_durable: PASS if §31のwrite-aheadがmock test(J-01〜03)に合格
  C17 orphan_handling_ready: PASS if F-01〜F-05に合格
  C18 no_api_key: C07に含む
  C19 terms_position_decided: PASS only if 人間がU15についての判断を記録済み
  C20 human_explicit_live_approval: PASS only if 人間の承認record(日時、対象dispatch_id、1回限り)がある
mandatory_unknowns_must_be_zero: [U01, U02, U03, U04, U05, U06(判断で解消可), U07, U12, U14(判断で解消可), U15(判断で解消可), U18, U19]
current_evaluation(2026-09-23): NOT_READY
  failing: C09, C10, C11, C16, C17, C19, C20
  unknown: U01, U02, U03, U04, U05, U06, U07, U12, U14, U15, U18, U19
```

**現在の判定:BLOCKED**(gateの出力はNOT_READY)

---

## 41. 実装の優先順位

| 優先度 | 項目 |
|---|---|
| **P0**(live前に必須) | §31のFSMとwrite-ahead、§31.4の復旧判定、env freeze、使い捨てCONFIG_DIRとcwd、preflight(§24・§25)、allowlist parser(未知のsubtypeは不採用)、runtime evidence判定(§26)、fake provider(§28)とretry・fallbackの事実固定、禁止表現のlint(§37)、要件の再定義についての人間とSolの決定 |
| **P1** | CLAUDE_RUNTIME_IDENTITY_V1、version pinとCHANGELOG差分の監視、Claudeのread-only review経路(§35)、ADVERSARIAL_REVIEW_V1のprompt(§36)、Browser Reviewer用のsecondary record(§32) |
| **P2** | OTelをfile出力にして回収する仕組み、Windows Job Objectでのprocess管理、Claude in ChromeでのUI regression(専用profile) |
| **P3** | CLAUDE_EXECUTOR_CONTRACT_V1(Claudeをwriterにする)、ACP経路の再評価 |

---

## 42. Sol/Jules実装Backlog

liveが不要で、静的testかmockだけで進められるものから並べています。

| ID | TITLE | WHY | FILES/AREA(提案。現行repoとの照合はNOT VERIFIED) | TESTS | 依存 | RISK | 優先 | 静的のみで可 | live要否 |
|---|---|---|---|---|---|---|---|---|---|
| CB-01 | Claude dispatch FSM(`CLAUDE_DISPATCH_FSM_V2`) | 二重実行の防止 | `automation/relay/claude/fsm.py` | J-01〜03、§31.4の表を全件table-driven test | 既存のreceipt/state実装 | 中 | P0 | YES | NO |
| CB-02 | 復旧判定 `recovery_verdict()` | receiptが無い状態を未実行と誤認しない | 同上 | 状態ごとに全件、`redispatch_allowed` のassert | CB-01 | 中 | P0 | YES | NO |
| CB-03 | env freezeとallowlist・denylist | 認証経路の混入を防ぐ | `automation/relay/claude/env_policy.py` | B-01、B-02、A-08、C-03、E-04 | — | 低 | P0 | YES | NO |
| CB-04 | 使い捨てCONFIG_DIRとcwdの生成、上位dirの走査 | global設定の侵入を防ぐ | `.../claude/sandbox_dirs.py` | G-01〜05、B-08 | — | 低 | P0 | YES | NO |
| CB-05 | argv builderと禁止flag検査 | resume、fallback、bypass、bareの混入を防ぐ | `.../claude/argv.py` | E-01、C-01、H-01、B-10、D-03、D-04 | — | 低 | P0 | YES | NO |
| CB-06 | settings全層の走査(managed含む、OS別path) | apiKeyHelper、fast mode、advisorを検出 | `.../claude/settings_scan.py` | B-03、C-02、H-02、I-02 | — | 低 | P0 | YES | NO |
| CB-07 | stream-jsonのallowlist parser | retry eventの見落とし防止(反証13) | `.../claude/stream_parser.py` | B-06、B-07、C-04、D-02、E-03、H-03、H-04、未知のsubtype→REJECT | fixtureの収集 | 中 | P0 | YES | NO |
| CB-08 | evidenceの判定(§26) | ACCEPTEDの条件を機械化 | `.../claude/evidence.py` | D-01、D-05、I-01 | CB-07 | 中 | P0 | YES | NO |
| CB-09 | preflight JSONの出力(§25) | 機械判定 | `.../claude/preflight.py` | schema検証、UNKNOWN→BLOCKED | CB-03〜06 | 低 | P0 | YES | NO |
| CB-10 | `FAKE_ANTHROPIC_V1` | liveを使わずCLIの挙動を固定する | `tests/fakes/anthropic_fake/` | A-01〜07、B-05、C-05、F-01〜02 | network sandbox | 中(偽keyのみ。本物のkeyは禁止) | P0 | YES(CLI実行は偽endpoint相手) | NO |
| CB-11 | 禁止表現のlint(§37) | 曖昧な判定を排除 | `.../review/lint_verdict_language.py` | A36-01:「安全そう」などの語を検出したら不採用 | — | 低 | P0 | YES | NO |
| CB-12 | CLAUDE_RUNTIME_IDENTITY_V1 | 設定の同一性 | `.../claude/runtime_identity.py` | I-01、canonical JSONの安定性test | CB-04・06 | 低 | P1 | YES | NO |
| CB-13 | version pinとCHANGELOG差分のreport | drift対策 | `.../claude/drift_report.py` | L-01〜04 | — | 低 | P1 | YES | NO |
| CB-14 | read-only review経路(§35) | Julesとの相互監査 | `.../review/claude_secondary.py` | STALE/DUPLICATEの拒否、`decision_scope` の固定 | CB-01、08 | 中 | P1 | YES(mock) | live POCは要 |
| CB-15 | ADVERSARIAL_REVIEW_V1のpromptとschema | 相関した見落としを減らす | `docs/…/ADVERSARIAL_REVIEW_V1.md` | Stage AのhashをStage Bより先にcommitすること | CB-14 | 低 | P1 | YES | live POCは要 |
| CB-16 | Browser Reviewerのsecondary record | Solとの競合回避 | reviewer transport | §32.4の6条件 | CB-14 | 中 | P1 | YES | NO |
| CB-17 | OTelのfile出力の回収 | request件数の証拠 | `.../claude/otel_collect.py` | D-05 | CB-10 | 中 | P2 | YES | NO |
| CB-18 | Windows Job Objectでのprocess管理 | orphan対策 | `.../claude/proc_win.py` | F-04 | — | 中 | P2 | YES(Windows CI) | NO |
| CB-19 | Chrome UI regression(専用profile) | AIBOのWeb UI | 別track | 手順書 | 人間の環境 | 中 | P2 | NO | 要(人間) |
| CB-20 | CLAUDE_EXECUTOR_CONTRACT_V1 | writerとしてのClaude | 後回し | §34 | 全P0 | 高 | P3 | 一部 | 要 |

---

## 43. 現行repositoryとの重複チェック

**NOT VERIFIED AGAINST CURRENT REPOSITORY**

- `kamiyusense/multi-ai-council-phase0` は、`git ls-remote` が認証を要求して失敗しました(E33。private repoか、名前が違う可能性)。
- 候補に挙がった `docs/RELAY_LIVE_BLOCKERS.md`、`docs/RELAY_ACP_SDK_CONTRACT.md`、`docs/RELAY_STATIC_CHECKPOINT.md`、`docs/EXECUTOR_WORKSPACE_INTEGRITY_P0_CHECKPOINT.md`、`docs/HYBRID_WORK_CHAT_REVIEWER_RELAY_PROPOSAL.md`、`docs/WORK_COMMAND_BUS_RUNTIME_CONTRACT.md`、`RELAY_JULES_HANDOFF.md`、`automation/command_bus/workspace_integrity.py`、reviewer transport、receipt/stateのlogicは、どれも**読めていません**。
- §42の「FILES/AREA」は**提案用の仮の置き場所**です。実装担当は既存の構成に合わせて読み替えてください。重複しそうなのは、CB-01・02(receipt/state)、CB-04(workspace_integrity.py)、CB-16(reviewer transport)です。

---

## 44. 最終判定(更新)

### 総合:**BLOCKED**(前回から変わらず)

| 観点 | 判定 |
|---|---|
| Claudeをlive providerとして起動すること | BLOCKED |
| retry=0(文字どおりの意味) | FAIL(2回目のrequestを防ぐ手段が無い経路を確認) |
| retry=0(「検出→不採用」に再定義した場合) | PARTIAL(fakeでの事実固定がまだ) |
| 実行されたモデルの独立検証 | UNKNOWN |
| サブスク専用の経路 | PARTIAL |
| session / resume | PARTIAL |
| ACP経路 | FAIL(v0.81.0。bypass設定の無視、resume時のlimit無視。修正は未release) → Phase 0では使わない |
| 設計(FSM、gate、schema、test、backlog) | CONFIRMED(文書として完成) |
| 既存repoとの整合 | NOT VERIFIED |

---

## 45. Sources と PART 1 の結論の変更点

### 45.1 PART 1からの変更(必ず反映すること)

| 箇所 | 変更前 | 変更後 | 根拠 | 種別 |
|---|---|---|---|---|
| §5・§19 ACP HEAD | `281e47e`(0.81.1-preview.5) | **`df38ccc`**(未release) | E27 | main branchの未release挙動 |
| §19・§17 ACPのFAIL項目 | disableBypass無視のみ | **加えて、warmな `session/resume` と `session/load` で `maxTurns` と `maxBudgetUsd` の変更が無視される**(client側は成功を受け取る。修正は未release) | E27 | release 0.81.0の挙動 |
| §14・§13 `--tools ""` | UNKNOWN | **CONFIRMED**(公式Python SDKが使用) | E32 | 現行SDKのsource |
| §24 `--disallowedTools "*"` | UNKNOWN(要約経由) | **CONFIRMED**(docsの逐語) | E31 | docs |
| §24 `--disable-slash-commands` | 要約経由 | **CONFIRMED**(逐語) | E31 | docs |
| §24・§13「CLAUDE.mdは上位dirも探索される」 | 断定して書いていた | **UNKNOWN(U20)**。今回のsession内に根拠が無かった。本書の自己訂正 | — | 訂正 |
| §5「release日」 | tagのcommit日時を記載 | tagのcommit日時は**releaseの目安**であって、npmの公開日時ではない(npmには接続できなかった) | E01 | 注記 |
| 総合判定 | BLOCKED | BLOCKED(変わらず) | — | — |

### 45.2 時点を混ぜないための区別

- **current release:** Claude Code 2.1.280、TS SDK 0.3.280、Python SDK 0.2.158、ACP 0.81.0、ACP protocol 1.9.1
- **main branchの未release挙動:** ACPの#1165、#1097(release版の挙動とは別物として扱う)
- **docsが将来の挙動として書いているもの:** Agent SDKの月次credit(2026-06-15に一時停止中。E21)、「`--bare` は将来 `-p` の既定になる」(E11)
- **旧実装の挙動:** 2.1.42(E22)。現行の根拠には使っていません

### 45.3 今回追加したURL

- https://code.claude.com/docs/en/chrome
- https://support.claude.com/en/articles/12902446-claude-in-chrome-permissions-guide
- https://support.claude.com/en/articles/12902428-use-claude-in-chrome-safely
- https://code.claude.com/docs/en/cli-reference (逐語照合)
- https://github.com/agentclientprotocol/claude-agent-acp/pull/1097 (commit `df38ccc`)
- https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/_internal/transport/subprocess_cli.py
