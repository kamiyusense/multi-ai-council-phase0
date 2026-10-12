# Official Symphony 最小 LIVE proof — Local 操作手順

この文書は **Local での LIVE 実行が明示承認された後** に使います。Cloud では Issue 作成、Official Symphony 起動、Codex worker/model 起動をしません。準備済みの [Issue 文面](SYMPHONY_MINIMAL_LIVE_PROOF_ISSUE.md) と [WORKFLOW.md](SYMPHONY_MINIMAL_LIVE_PROOF_WORKFLOW.md) を使います。検証対象の Official Symphony は `openai/symphony@be10a1b79df723d6d7612b5651c8522704dafb2e` です。起動するのは素の upstream Elixir 実装で、New Chinponey の STATIC controller はこの実験の scheduler になりません。

## 2026-10-09 generation 4 — 最小実機 proof の達成範囲

[generation 4 の結果](SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_ISSUE_336_G4.md)は、今回定義した worker lifecycle / 隔離1ファイル proof の **PASS**。固定版 Official Symphony が Issue #336 を選択し、実 Codex App Server、モデル turn 1件の完了、同じ thread の自然な continuation、指定ファイル1件の生成まで観測した。2 turn目は観測後の Ctrl+C で中断し、完了として数えない。generation 4 内の retry/backoff、stall recovery は NOT_OBSERVED。過去3 generation の FAIL はそのまま保存する。

子プロセスの API selector と tracker token の変数名は未検出。既存ファイル変更・削除・worker commit/push は0、LIVE停止直後の main / PR / proof refs は開始時と一致した。成果は proof workspace に残し、他branchへ採用していない。`git diff --check` は untracked の内容を対象にしないため、新規成果の直接readbackと `git diff --no-index --check /dev/null <artifact>` も確認する（差分がある場合のexit 1と空白エラーを区別する）。

既存 Issue #336 と proof branch は再作成・更新しない。proof branch は初回の開始commitを保持し、PR #320はoperator証拠のcommitで進む。この2つのHEAD不一致だけを小さいproof taskの停止理由にしない。採用時のcurrent canonical HEAD / task validity / diff確認は引き続き別境界。workflowへこの区別をSTATIC追記したが、その追記自体は再LIVE未検証。

以後のcorrective LIVEは、現在の明示承認がそのgenerationを含む場合だけ行う。各generationでfresh readback、auth/schema/config/rendered prompt検証、過去process停止、新しい空workspace rootを確認する。既存upstreamはclean / detached / exact pinを検査して再利用し、初回用のIssue作成・branch作成・clone手順を繰り返さない。WSLの実機launcherでは、PATH上のWindows shimとの衝突を避けるため、検証済み `/home/yuuki/.local/bin/mise` を使った。LIVE successだけではNew Chinponeyのproduction transportやdurable restart/recoveryの完成証拠にはならない。

## 2026-10-09 generation 3 の観測と次の検証

[generation 3 の結果](SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_ISSUE_336_G3.md)は独立した **FAIL**。実 Issue #336 の選択、隔離 workspace、Codex App Server child とその禁止環境変数名の不在まで観測したが、App Server 起動中の応答待ちが既定の5秒で2回失敗した。session ID、モデル turn、成果ファイルは未確認。正確に `initialize` と `thread/start` のどちらの応答が遅れたかは UNKNOWN。LIVE中に `reject` と UTF-8 encoding のエラーは再発しなかったが、`turn/start` へは到達していないため ASCII 修正の実機成功とは呼ばない。

停止後、upstream の LIVE E2E 設定と同じ `codex.read_timeout_ms: 60000` を proof workflow に追加し、STATIC 検証した。これは「60秒で必ず成功する」という証拠ではない。次の corrective LIVE は独立した Generation 4 として、新しい workspace root、fresh GitHub/auth/readback、current schema/config/prompt validation、前回 process 停止確認を終えてから行う。過去 workspace と証拠を削除・上書きしない。この runbook 自体は LIVE 承認ではない。

## 2026-10-09 実機観測後の停止境界

[Issue #336 の Local 結果](SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_ISSUE_336.md)を先に読む。最初の LIVE campaign は一度起動・停止済みである。Codex CLI `0.162.0-alpha.2` は upstream の既定 `approval_policy` に含まれる `reject` を受理せず、モデル turn は始まらなかった。今回の workflow は現行 App Server schema に合わせて `granular` の全承認カテゴリを `false` に明示した。これは STATIC 修正であり、再 LIVE の成功証拠ではない。**この runbook や STATIC 修正を、2回目の LIVE 起動の承認と解釈しない。**

次の LIVE を別途承認された場合は、起動前にその時点の Codex App Server schema と workflow の `approval_policy` を照合する。`never` は使わない。固定版 Symphony では `never` が内部承認要求の自動承認も有効にするため、元の fail-closed 意図を保てない。

## 2026-10-09 generation 2 の観測と次の停止境界

別途承認された generation 2 (`symphony-minimal-live-issue-336-g2`) は新しい workspace root で一度起動し、停止済み。[generation 2 の結果](SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_ISSUE_336_G2.md)を参照。`granular` policy は初回の `reject` protocol error を越え、実 Codex App Server の `thread/start` まで進んだ。子プロセスの禁止 API selector と GitHub tracker secret の変数名は `/proc` で未検出だった。一方、`turn/start` の JSON encoding 前に `Jason.EncodeError` が発生し、モデル turn と成果ファイルは未作成。generation 2 の結果は **FAIL** として別記録する。3回目の LIVE はこの runbook によって承認されない。

固定版 upstream `Workflow.split_front_matter/1` は Unicode mode なしの `~r/\R/` で原文を行分割する。日本語の UTF-8 継続バイト `0x85` を改行と誤認し、prompt template が invalid UTF-8 になることを STATIC 再現した。上流ソースを変更せず、この proof workflow の template 本文だけを ASCII にした。Issue 本文の日本語はテンプレートへ後から挿入される。次に別途 LIVE 承認がある場合は、policy schema に加えて、固定版 upstream で **Issue を含む実 rendered prompt の UTF-8 妥当性**を起動前に確認する。今回の ASCII 修正は STATIC であり、3回目の LIVE 成功証拠ではない。

## 0. 先に知っておくこと

- 使う場所は Windows の **WSL Linux ターミナル** です。GitHub 画面で PR #320 は Draft のままにします。
- `gh`、`git`、`codex`、`mise`、`rg`、`curl`、`python3`、`sha256sum` が WSL にあることを確認します。なければそこで停止します。Codex には ChatGPT subscription のログインが必要です。API key 経路で進めません。
- GitHub tracker には既存の認証を使用します。新しい token、API key、Secret、権限、Billing 設定は作成・変更しません。秘密値を画面や記録へ貼りません。
- `symphony-minimal-live-proof` ラベルを付けた **open Issue はこの proof Issue 一件だけ** にします。PR は GitHub tracker の dispatch 対象ではありません。
- `main`、PR #320 branch、既存データへ worker が write しないことが条件です。証拠ファイルは専用 proof branch の隔離 workspace にだけ置き、commit/push はしません。
- 実験中、Issue が open のままだと Official Symphony は正常 turn の後に継続したり再試行したりします。それを観測するのが目的です。準備なく放置せず、観測後に Ctrl+C で止めます。

## 1. WSL と repository を確認する（読み取りのみ）

Windows Terminal で Ubuntu/WSL を開き、以下を順番に実行します。repository が別の場所にある場合は最初のパスだけ実際の場所へ直します。

```bash
pwd
for tool in git gh codex mise rg curl python3 sha256sum; do command -v "$tool" || { echo "$tool が見つからないため停止"; return 1 2>/dev/null || exit 1; }; done
SYMPHONY_REPO="$HOME/multi-ai-council-phase0"
cd "$SYMPHONY_REPO"
git remote -v
git branch --show-current
git status --short
```

remote が `kamiyusense/multi-ai-council-phase0` で、branch が `codex/symphony-inspired-minimal-controller` であることを確認します。`git status --short` に何か出たら同期せず停止し、何があるか確認します。古い Local task の未確認変更は取り込みません。

## 2. fresh fetch と fast-forward-only 同期

```bash
git fetch origin main codex/symphony-inspired-minimal-controller
git merge --ff-only origin/codex/symphony-inspired-minimal-controller
git status --short
git rev-parse HEAD
git rev-parse origin/main
gh pr view 320 --repo kamiyusense/multi-ai-council-phase0 --json state,isDraft,headRefName,headRefOid --jq '{state,isDraft,headRefName,headRefOid}'
```

`git rev-parse HEAD` と PR の `headRefOid` が同じで、PR が OPEN/Draft であることを確認します。違う場合は次へ進まず fresh readback します。`main` は読むだけです。PR branch に `main` を merge/rebase しません。

## 3. 認証と paid route を安全に確認する

```bash
gh auth status
codex login status
```

Codex の表示が ChatGPT login と判断できない場合、または API key 認証を示す場合は **ここで停止** します。`codex login` を勝手にやり直さず、Billing/credits を変更しません。quota 数字が表示されないだけなら停止理由ではありません。

次は **変数名の有無だけ** を確認します。値を表示しません。`OPENAI_API_KEY` などが親環境に存在しても、以下の起動コマンドと workflow の `codex.command` で子プロセスから取り除きます。worker の実環境は LIVE 開始後の証拠で再確認します。

```bash
env | cut -d= -f1 | rg '^(OPENAI_API_KEY|CODEX_API_KEY|AZURE_OPENAI_API_KEY|OPENAI_BASE_URL|OPENAI_API_BASE)$' || true
rg -n '^  command: env -u OPENAI_API_KEY' docs/SYMPHONY_MINIMAL_LIVE_PROOF_WORKFLOW.md
if test -f "$HOME/.codex/config.toml" && rg -q 'base_url|model_provider|api_key|openai_base_url' "$HOME/.codex/config.toml"; then echo 'Codex custom provider/config を確認するまで停止'; fi
```

最後の行が停止メッセージを出した場合、設定の値を共有せず、ChatGPT subscription 以外に流れないことを確認できるまで開始しません。Official Symphony は GitHub tracker token を Codex child から除去します。workflow の `env -u` は OpenAI API-key/custom endpoint selector を child から除去します。これらは構造的な経路対策であり、LIVE のアカウント readback はまだ未実施です。

## 4. proof Issue を作る（ここから承認後の Local 操作）

GitHub のこの repository の Issues 画面で、[準備済み Issue 文面](SYMPHONY_MINIMAL_LIVE_PROOF_ISSUE.md) の Title と Body を貼り付けます。**`symphony-minimal-live-proof` ラベル**を一緒に付けます。ラベルがまだなければ Issues → Labels → New label で同名のラベルを一度だけ作ります。**ラベル作成の直前と Issue 作成の直前にそれぞれ**次の PR HEAD readback を実行します。Issue を閉じず、番号を控えます。作成応答が曖昧な場合は Issue 一覧を読み直し、同じ Issue を盲目的に再作成しません。

```bash
gh pr view 320 --repo kamiyusense/multi-ai-council-phase0 --json headRefOid,isDraft,state --jq '{headRefOid,isDraft,state}'
```

```bash
read -rp '作成した proof Issue 番号: ' SYMPHONY_PROOF_ISSUE
[[ "$SYMPHONY_PROOF_ISSUE" =~ ^[1-9][0-9]*$ ]] || { echo 'Issue 番号が不正'; return 1 2>/dev/null || exit 1; }
gh issue view "$SYMPHONY_PROOF_ISSUE" --repo kamiyusense/multi-ai-council-phase0 --json number,state,title,labels,url --jq '{number,state,title,labels:[.labels[].name],url}'
gh issue list --repo kamiyusense/multi-ai-council-phase0 --state open --label symphony-minimal-live-proof --json number --jq '.[].number'
```

最後の一覧が **この Issue 番号一つだけ** でなければ起動しません。Issue 番号を workflow に手で書く必要はありません。Official Symphony は GitHub tracker の `required_labels` で候補を絞ります。

## 5. 専用 proof branch を Local operator が作る

GitHub write の直前に PR #320 の current HEAD を再読します。作成済み branch が見つかった場合は push せず、HEAD と用途を調べます。

```bash
cd "$SYMPHONY_REPO"
git fetch origin codex/symphony-inspired-minimal-controller
git merge --ff-only origin/codex/symphony-inspired-minimal-controller
SYMPHONY_PR_HEAD="$(gh pr view 320 --repo kamiyusense/multi-ai-council-phase0 --json headRefOid --jq .headRefOid)"
test "$(git rev-parse HEAD)" = "$SYMPHONY_PR_HEAD" || { echo 'PR HEAD 不一致。停止'; return 1 2>/dev/null || exit 1; }
SYMPHONY_PROOF_BRANCH="codex/symphony-minimal-live-proof-$SYMPHONY_PROOF_ISSUE"
git ls-remote --heads origin "$SYMPHONY_PROOF_BRANCH"
```

`git ls-remote` が何も表示しないことを確認した場合だけ、次を一度実行します。応答不明なら `git ls-remote` で readback し、盲目的に push を繰り返しません。

```bash
git push origin "HEAD:refs/heads/$SYMPHONY_PROOF_BRANCH"
git ls-remote --heads origin "$SYMPHONY_PROOF_BRANCH"
```

## 6. Official Symphony を別 directory に固定版で用意する

この手順は別の新規 directory を使います。既存 directory がある場合は上書き・削除せず停止します。

```bash
SYMPHONY_UPSTREAM="$HOME/symphony-official-proof"
test ! -e "$SYMPHONY_UPSTREAM" || { echo '既存の Symphony directory があるため停止'; return 1 2>/dev/null || exit 1; }
git clone https://github.com/openai/symphony.git "$SYMPHONY_UPSTREAM"
git -C "$SYMPHONY_UPSTREAM" checkout --detach be10a1b79df723d6d7612b5651c8522704dafb2e
git -C "$SYMPHONY_UPSTREAM" rev-parse HEAD
cd "$SYMPHONY_UPSTREAM/elixir"
mise trust
mise install
mise exec -- mix setup
mise exec -- mix build
```

digest と upstream commit を記録します。秘密値は記録しません。

```bash
sha256sum "$SYMPHONY_REPO/docs/SYMPHONY_MINIMAL_LIVE_PROOF_WORKFLOW.md"
```

## 7. 起動準備の最終 readback

```bash
export SYMPHONY_PROOF_BRANCH
export SYMPHONY_PROOF_WORKSPACES="$HOME/symphony-proof-workspaces"
mkdir -p "$SYMPHONY_PROOF_WORKSPACES"
export GITHUB_TOKEN="$(gh auth token)"
test -n "$GITHUB_TOKEN" || { echo 'GitHub tracker 認証がないため停止'; return 1 2>/dev/null || exit 1; }
gh issue view "$SYMPHONY_PROOF_ISSUE" --repo kamiyusense/multi-ai-council-phase0 --json state,labels --jq '{state,labels:[.labels[].name]}'
gh pr view 320 --repo kamiyusense/multi-ai-council-phase0 --json headRefOid --jq .headRefOid
git ls-remote --heads "https://github.com/kamiyusense/multi-ai-council-phase0.git" "$SYMPHONY_PROOF_BRANCH"
```

Issue は open、専用ラベル付き、proof branch は先ほどの PR HEAD から作成済みであることを確認します。`GITHUB_TOKEN` は tracker 用で、値を表示しません。Official Symphony の GitHub adapter はこの token を Codex child に渡さない実装です。workspace root に他の重要データがある場合は使いません。

## 8. ここから先は Local LIVE — Official Symphony を起動

このコマンド以降、実際の Codex worker/model が開始する可能性があります。**今回の Cloud バッチでは実行していません。** 起動は別途明示承認された Local 操作だけです。
固定版 Official Symphony の CLI は、engineering preview のため長い acknowledgement flag を必須にしています。これは上流 CLI の構文要件であり、Cloud から LIVE を承認するものではありません。

```bash
cd "$SYMPHONY_UPSTREAM/elixir"
env -u OPENAI_API_KEY -u CODEX_API_KEY -u AZURE_OPENAI_API_KEY -u OPENAI_BASE_URL -u OPENAI_API_BASE mise exec -- ./bin/symphony --i-understand-that-this-will-be-running-without-the-usual-guardrails --port 4000 "$SYMPHONY_REPO/docs/SYMPHONY_MINIMAL_LIVE_PROOF_WORKFLOW.md"
```

ターミナルの `Dispatching issue to agent`、`Starting worker attempt`、`Completed agent run` を確認します。別の WSL ターミナルで `http://localhost:4000/` または `http://localhost:4000/api/v1/state` を開くと状態を読めます。公開・転送ポートとして外部に出しません。

## 9. turn / retry / workspace / 成果を観測

ログの `Continuing agent run ... turn=` は同じ agent 内の継続です。`Retrying issue_id=... in ...ms` は upstream の retry/backoff、`Stalled` 関連ログは stall の観測材料です。**発生しなかった項目は「未観測」**です。New Chinponey が毎 turn を gate する必要はありません。

**別の WSL ターミナル**を開き、ダッシュボードまたは状態 API で `codex_app_server_pid` を読みます。次は **環境変数名だけ** を調べ、値を表示しません。PID が取れない、process が既に終了した、`/proc` を読めない場合は「実 child 環境 UNKNOWN」と記録します。禁止名が一つでもあれば起動したターミナルで Ctrl+C を押します。

```bash
curl -fsS http://127.0.0.1:4000/api/v1/state | python3 -m json.tool | rg 'codex_app_server_pid|workspace_path'
read -rp '画面に表示された Codex app-server PID: ' SYMPHONY_CODEX_PID
[[ "$SYMPHONY_CODEX_PID" =~ ^[1-9][0-9]*$ ]] || { echo 'PID が不明。UNKNOWN として停止'; return 1 2>/dev/null || exit 1; }
test -r "/proc/$SYMPHONY_CODEX_PID/environ" || { echo 'child 環境を読めない。UNKNOWN として停止'; return 1 2>/dev/null || exit 1; }
python3 - "$SYMPHONY_CODEX_PID" <<'PY'
from pathlib import Path
import sys
names = {part.split(b"=", 1)[0] for part in Path(f"/proc/{sys.argv[1]}/environ").read_bytes().split(b"\0") if part}
forbidden = {b"OPENAI_API_KEY", b"CODEX_API_KEY", b"AZURE_OPENAI_API_KEY", b"OPENAI_BASE_URL", b"OPENAI_API_BASE"}
if names & forbidden:
    raise SystemExit("禁止環境変数を検出。Ctrl+C で停止")
print("Codex child の禁止環境変数名なし")
PY
```

同じ WSL ターミナルで、専用 workspace だけを確認します。

```bash
SYMPHONY_PROOF_WORKSPACES="$HOME/symphony-proof-workspaces"
mapfile -t SYMPHONY_GIT_DIRS < <(find "$SYMPHONY_PROOF_WORKSPACES" -maxdepth 2 -type d -name .git -print)
printf '%s\n' "${SYMPHONY_GIT_DIRS[@]}"
test "${#SYMPHONY_GIT_DIRS[@]}" -eq 1 || { echo 'workspace が一つと確認できないため停止'; return 1 2>/dev/null || exit 1; }
SYMPHONY_WORKSPACE_DIR="$(dirname "${SYMPHONY_GIT_DIRS[0]}")"
```

表示された workspace で次を読みます。`find` が何も返さない場合は Symphony ログの `workspace=` を確認します。workspace を削除しません。

```bash
cd "$SYMPHONY_WORKSPACE_DIR"
git branch --show-current
git rev-parse HEAD
git status --short
git diff --check
git diff -- docs/evidence/symphony-minimal-live-proof
```

`git diff` は untracked 新規ファイルを表示しないため、`git status --short` に出た `docs/evidence/symphony-minimal-live-proof/issue-<番号>.md` を個別に開いて内容を確認します。許可外ファイル・削除・secret 混入があれば成果を採用せず停止します。

## 10. 止め方と失敗時の readback

起動したターミナルで **Ctrl+C** を押します。すぐに再起動せず、プロセス終了を確認します。停止後、次を読みます。

```bash
read -rp '確認する proof Issue 番号: ' SYMPHONY_PROOF_ISSUE
SYMPHONY_PROOF_BRANCH="codex/symphony-minimal-live-proof-$SYMPHONY_PROOF_ISSUE"
gh issue view "$SYMPHONY_PROOF_ISSUE" --repo kamiyusense/multi-ai-council-phase0 --json state,labels,comments --jq '{state,labels:[.labels[].name],commentCount:(.comments|length)}'
gh pr view 320 --repo kamiyusense/multi-ai-council-phase0 --json headRefOid,isDraft,state --jq '{headRefOid,isDraft,state}'
git ls-remote --heads "https://github.com/kamiyusense/multi-ai-council-phase0.git" "$SYMPHONY_PROOF_BRANCH"
```

起動エラー・network read failure はログを保存して readback し、非破壊の読み取りは bounded retry して構いません。Issue 作成、branch push、GitHub write、モデル dispatch、成果採用の成功が曖昧な場合は **同じ操作を盲目的に再送しません**。まず remote と workspace を読み直し、成功/未実行/不明を分けます。古い worker の後着結果は current HEAD と task validity を再確認するまで採用しません。retry/backoff が発生しても勝手に paid fallback へ切り替えません。

最後に Issue URL、開始/終了 HEAD、upstream commit、workflow SHA-256、ログ時刻、worker 開始、turn/continuation/retry/stall の観測有無、workspace path、`git status --short`、`git diff --check`、成果ファイル、UNKNOWN を記録します。proof branch の成果を他 branch へ自動採用・Merge しません。

## この手順で確認できる範囲

Cloud STATIC は fake tracker candidate → 新 worker admission → durable INTENT → STARTED → TERMINAL → fresh HEAD → STALE discard → fresh controller continuation を模擬します。上記 Local LIVE は素の Official Symphony が実際に tracker polling、workspace、Codex App Server、turn、retry を行うかを観測する最小試験です。現状、**Official Symphony の実 process と New Chinponey durable ledger を結ぶ production transport は未接続**です。Local proof の成功だけで「durable production autonomous campaign 完成」や自動 Git ref adoption PASS としません。
