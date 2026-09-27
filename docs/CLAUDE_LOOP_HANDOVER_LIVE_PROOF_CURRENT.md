# Claude Loop live-proof handover (CURRENT)

更新日: 2026-09-27 JST

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
