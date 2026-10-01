# Claude Loop live-proof handover (CURRENT)

> **Development route:** For new implementation work, read
> [DEVELOPMENT_EXECUTION_ROUTER.md](DEVELOPMENT_EXECUTION_ROUTER.md) from
> current main before choosing Jules, Green Cloud Work or a Local Work prompt.
> The live proof and recorded one-shot approvals below are historical,
> consumed evidence; they do not authorize another live execution.
>

## 2026-09-28 最新LIVE結果（先に読む）

- 人間がIssue #23 comment `5864265631` で追加許可した1回のREAL再試験は**成功して終端済み**。新dispatch `e80d615b-9e87-4b20-9bad-2812a76adee6`、対象PR head `1373bf5512f7208ca88452b0bda12632bd5dbd05`、tree `a28c42d33f23c391b634bafddf36b6c436604de9`。このSHAは履歴であり、次回の正本にはしない。
- 前確認時点のmainは `88020699a00056d3635899c2d9d4c7739f87a25b`。PRはmainより古かったが、main側とPR側の変更ファイル重複は0件で、PRはOPEN / MERGEABLE / CLEAN、対象headのActionsは2件ともSUCCESS。merge/rebase/force pushはしていない。
- 保存済み`claude.ai` OAuth / Pro subscriptionで `claude auth status` がログイン済み。API key/Console/setup-token経路を使わず、`--safe-mode` 修正版の隔離容器でClaude Code生成processを**1回だけ**起動し、exit 0、restart 0。返答は固定文字列 `PHASE0_CLAUDE_LIVE_OK` の1行と完全一致。
- Gate DBの今回のevidenceは1件のみ: ordinal 1、`ADMITTED`、request body SHA-256 `4781909b9ddf633cc22816202463a9c864195491c5189e71f5d52d6bccf8b7fb`、upstream HTTP 200。Gateが観測した実Anthropic `POST /v1/messages` は**1回**。retry 0、fallback disabled、max turns 1。モデル名や請求状態は検証しておらず推測しない。
- Terminal receiptは `phase0-runs/real-claude-proof-20260928-r3/terminal-receipt.json` と元のGate DBに保存済み。Gateの契約上の `state=SUCCEEDED`、完了判定 `completion_status=COMPLETE`。Gate停止後にread-onlyでDBと外部receiptを照合し、累計dispatch 3件、evidence 1件、terminal receipt 3件、DB store identity一致を確認。Claude runtimeとGateは停止し、auth volume・Gate volume・外部bootstrap receipt・証拠を保持した。
- **CLAUDE AUTH=PASS、REAL CLAUDE=PASS、REAL ANTHROPIC=PASS**。この追加許可は消費済み。追加dispatch、Claude実行、Loop開始、夜間自動運転、Jules連携、Mergeは実施しない。

## 2026-09-28 前回LIVE失敗と修正（履歴）

この節以降の `--bare` / 実行回数0 / STATIC直前の記述は過去時点の履歴であり、現在の実行状態ではない。

- PR #25 の2026-09-28再試行は、`phase0-runs/real-claude-proof-20260928-r2/terminal-receipt.json` に `FAILED` として終端保存済み。dispatch `d384c645-cf10-433f-a44e-d2d41130efa7`、Claude起動1回、再起動0、Gateが観測した `/v1/messages` 送信0回。Gate DBには累計dispatch 2件、evidence 0件、terminal receipt 2件。GateとClaude runtimeは停止済み。
- `claude auth status` は既存auth volumeで `claude.ai` のログイン済みとPro subscriptionを示した。一方、実runtimeは `Not logged in` でGate到達前に終了した。再認証・再dispatch・再送は行っていない。
- Anthropic公式CLI資料と同社リポジトリの報告では、`--bare` は保存済みOAuthを読まない。旧launcherの `--bare` が今回の失敗の有力原因。公式資料でOAuthを維持し追加機能を止める `--safe-mode` が確認できたため、launcherとCompose contractを `--safe-mode` へ変更した。既存のtool無効化、MCP遮断、1 turn、retry 0、Gate経由の条件は維持した。
- この修正に対する本物Claudeの再実行は**未実施**。今回の1回許可は消費済み。次のgenerationには新たな明示許可とfresh preflightが必要。
- 参照: https://code.claude.com/docs/en/cli-reference 、https://github.com/anthropics/claude-code/issues/73926

初版: 2026-09-27 JST / LIVE追記: 2026-09-28 JST

## 最優先ルール

- この文書や過去ChatのSHAを正本にしない。
- 続行時は必ず GitHub current state を fresh readback する。
- Repository: `kamiyusense/multi-ai-council-phase0`
- Target: PR #25 / branch `feature/claude-night-loop-prepare`
- 推測禁止。確認不能は `UNKNOWN`。
- `retry=0`、`fallback=disabled`。
- 成功不明のwriteを同じ内容で再送しない。まずreadback。
- terminal receipt / completed action の重複実行禁止。
- Merge、main直接write、force push、branch削除は人間の明示承認なしに行わない。

## このhandoverの位置

Claude night-loop / Admission Gate の STATIC 実装は live proof 直前まで完了した。

この文書作成直前に独立確認した PR #25 head:
`452a47ebfaaeaf82b67d20ffd18314bd84d1454d`

ただし、このhandover保存commitにより branch head は進むため、
新しいChatではこのSHAを固定せず必ずfresh readbackすること。

PR #25 は OPEN / 未Merge / mergeable。
直前headを対象とするActions runは0件だった。

## STATICで完成済みのもの

### Admission Gate

安全条件:

> 1 Phase 0 dispatch につき Anthropic upstream へ送信可能な
> `POST /v1/messages` は最大1回。

Claude Code内部のretry / continuation / model fallbackそのものを
安全条件にしない。

2件目以降のgeneration attemptは Gate が upstream transmission 前に拒否する。

Gate:
- upstream exact: `https://api.anthropic.com`
- production startup: `OPEN_EXISTING_ONLY`
- expected store ID必須
- normal startupからbootstrap fallback禁止
- internal + egress network
- `gate-state` volumeのみ
- `claude-auth` volume mount禁止

### Claude runtime

存在する成果物:

- `automation/command_bus/docker/claude-runtime/Dockerfile`
- `automation/command_bus/docker/claude-runtime/claude_runtime_launcher.mjs`
- `automation/command_bus/docker/admission-gate/Dockerfile`
- `automation/command_bus/docker/admission-gate/gate_entrypoint.py`
- `automation/command_bus/claude_gate_compose.yaml`

Claude Code:
- exact version pin: `2.1.283`
- non-root runtime
- auth path: `/home/node/.claude`
- `CLAUDE_CONFIG_DIR=/home/node/.claude`

runtime Claude:
- internal network only
- direct egressなし
- exact Gate URL: `http://gate:8080`
- `claude-auth` volumeのみ
- Gate state mount禁止
- default fail-closed
- `PHASE0_LIVE_EXECUTION=1` がない限りClaude processを起動しない
- dispatch ID required

実launcherで確認済みの主要制限:
- `--bare`
- `--no-session-persistence`
- `--max-turns 1`
- `--tools ""`
- strict empty MCP
- `--permission-prompts none`
- `--verbose`

### Auth bootstrap

`auth-bootstrap`:
- egress only
- runtime internal networkへ参加しない
- `claude-auth` volumeのみ
- workspaceなし
- Gate stateなし
- API key/token envなし
- explicit human auth profile
- Claude subscription login用

credentialをhostから抽出・表示・コピーする設計ではない。

### Compose

STATIC packagingは runnable-but-not-run 状態。

以前の:
- `UNBUILT`
- Gateの `/bin/false`

placeholderは解消済み。

ただしDocker image build/start自体はまだ0回。

## 最新STATIC検証

最終修正commit:
`452a47ebfaaeaf82b67d20ffd18314bd84d1454d`

parent:
`a7f296a96642fb567912e2dc8a9ec53b9ef2245e`

tree:
`dec53b8a721b9fd027da9b853be0396279a1a49e`

最終修正で:
- actual launcherへ `--bare` 追加
- Compose contractとの一致をregression test化

報告済み検証:
- focused tests: 55 PASS / 1 skip
- command_bus: 373 PASS / 1 skip
- compileall PASS
- Compose JSON PASS
- static topology PASS
- Docker artifact validation PASS
- launcher default fail-closed PASS
- git diff --check PASS

独立GitHub readbackでもremote launcherに `--bare` が存在し、
対象headのActions run 0件を確認した。

Issue #23の関連checkpoint:
- `5856033739`: static pre-live state reached
- `5854193846`: --bare mismatch correction
- `5854185153`: runnable packaging present

## 実行回数 0 を維持しているもの

このhandover時点:

- Docker build = 0
- Docker pull = 0
- Docker start/run = 0
- Claude login = 0
- real Claude execution = 0
- Anthropic request = 0
- Jules execution = 0
- real credential read/extraction/display = 0
- production Gate bootstrap = 0
- Merge = 0

## 残っているUNKNOWN

STATICでは解消できない:

1. Docker imageの実build成功
2. actual Docker daemon上のnetwork isolation
3. runtime Claudeのdirect egress遮断実証
4. GateだけがAnthropicへ出られることの実証
5. named volume ownership / UID/GID
6. Gate production DB + external receiptの実bootstrap/open
7. Claude subscription loginの実container動作
8. actual Claude Code 2.1.283 + saved subscription + custom Gate compatibility
9. automatic model fallbackの実挙動
10. 1回のbounded real dispatchで Gate-transmitted `/v1/messages` が最大1か

automatic model fallbackが完全停止することを安全条件にしない。
Admission Gateのupstream budgetを安全境界とする。

## 次の段階 = LIVE PROOF

ここから先は STATIC ではない。

次に必要になり得る操作:

1. Docker daemon / environment fresh readback
2. image build/pull
3. Gate用volume / DB / external receiptの安全なbootstrap
4. network / volume ownership readback
5. auth-bootstrap起動
6. 人間によるClaude subscription login
7. auth-bootstrap停止
8. runtime Claude direct Internet egressがないことを確認
9. Gate egress / upstream path確認
10. real ClaudeをGate越しに1回だけbounded execution
11. Gate evidenceでupstream `POST /v1/messages` count確認
12. evidence / receipt保存
13. 全container停止

これらはDocker image/volume作成、real credential persistence、
最終的にAnthropicへのreal requestを伴うため、
新しいChatはユーザーの明示承認なしに開始してはいけない。

## 新Chatで最初にやること

1. PR #25 / Issue #23 / main / PR #4 / PR #6 をfresh readback。
2. このhandoverファイルをremoteから読む。
3. PR #25 current head / tree / changed paths / Actions stateを確認。
4. STATIC成果物が消えていないことを確認。
5. live proof前のUNKNOWNを再確認。
6. まだlive承認が無ければ停止し、ユーザーへlive proofの承認境界を簡潔に示す。
7. 承認された場合のみ、安全な小段階に分け、各write/外部actionはretry=0でreadbackしながら進める。

## 後段の大方針

Standalone A/Bを先にlive-greenにする:

A. `JULES_BACKEND`
Claude reviewer/planner -> existing Jules durable route.

B. `CLAUDE_BACKEND`
Claude-only bounded coding loop for Jules quota exhaustion.

A/Bがそれぞれlive-greenになる前に takeover/orchestration の実装へ進まない。

A/B完了後:
- Claude/Gemini向けprior-art research promptを先に作る
- GPT側も独立調査
- 3者比較
- その後takeover/orchestration設計

現在は takeover/orchestration は deferred。
