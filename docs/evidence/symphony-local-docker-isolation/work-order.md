# 💙 Official Symphony / New Chinponey — Local Docker固定イメージ取得・隔離実測（ユーザー明示許可済）
<!-- correlation: sym-local-docker-approved-acquisition-20261010-v1 -->

**STATUS: USER AUTHORIZED IMAGE DOWNLOAD; LOCAL EXECUTION NOT YET STARTED.** このPRコメント自体はCodex Local起動でもイメージ取得でもない。Codex Localが本コメントを読んで、通常のシステム承認を遵守し、以下の限定範囲で長尺作業を実行する。

## 0. 範囲と正本

Repo `kamiyusense/multi-ai-council-phase0`; 作業対象は既存のDraft PR **#343**, branch `claude/symphony-g61-production-wiring-static` のみ。参照HEAD `e43636c07f2e51245fdb28a360ed4d7c6847b249`; parent #320参照HEAD `8c53c505a21318c6133da0bef85af18ae3711103`; main参照HEAD `abb5402079d4af341c349ea9e8b6a8a5c3f2d37c`。すべて開始時に**fresh readback**。進行中の他セッションと競合したら隔離する。

最新checkpoint: PR #343 comment **6097448034**（バックアップPASS、remote PASS、CI3本PASS）。過去に未保存だった4ソースは通常commit/FF push済み、履歴証拠維持。以前のCIは `38051363541`, `38051363549`, `38051363536`。Docker daemonは Ubuntu WSL2 → Docker Desktop4.91.0/Engine29.8.0 接続PASS、Local隔離だけ `NOT_RUN_IMAGE_UNAVAILABLE`。

今回ユーザーは、**下記の正確な固定digest 2件だけを既存の正規配布先からローカルDockerへダウンロードし、そのイメージを使ってモデル非起動・ネットワーク隔離・読み取り専用のSTATIC試験を行うこと**を明示許可した。イメージ追加取得に関する人間への確認は不要。ただし実環境・システムに承認UIが出た場合は回避・代理承認しない。

**許可された取得対象は次の2件だけ：**
1. `python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce` （Docker Hubのofficial python repo）
2. `ghcr.io/gitleaks/gitleaks@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f` （GHCRのGitleaks repo）

参照GitHub workflow（PR #343 HEADで独立読取した実ファイル）: `.github/workflows/symphony-g63-synthetic-verifier.yml`。上記2つの`PYTHON_IMAGE`/`SCANNER_IMAGE`と**byte-for-byte一致**を確認してから取得する。作業前に最新workflowでpinが変化していたら、新しいdigestの取得は承認に含まれないため停止して報告。ほかのタグ、`:latest`、似た名前、別registry、既存private imageへの代用、再タグは不可。

## 1. 最初に端末と既存保存物を保護
- **Codex Local / Windows WSL Ubuntu**上の既存許可された通常実行経路を使用（CloudからPCを動かしたと偽らない）。
- `docker version` で Client/Server 両方、daemon 接続、`docker image inspect` の有無、空き容量、CPU archとworkflow pinを読む。
- 前回のWindows永続バックアップ（SHA-256 `57083b6da83e7c83ae7bacaac6ac7423457d6c0c959721e57d984350374fcd92`）とクリーンworktreeを破棄・上書きしない。
- 以前のdefault launcher `Failed to create unified exec process ... os error 2` が再発する場合は通常の正規reviewed command pathだけを使う。失敗経路の迂回・不明な許可の代理承認禁止。

## 2. 2 image取得（ユーザー承認はここに限る）
- 既に指定digestの実物がある場合はpullしない。
- ない場合に限り、各exact digestに対して**通常の `docker pull <exact-ref>` を1回ずつ**実施。外部registryの結果が不明・タイムアウトの場合はローカル `docker image inspect` / image inventoryでreadbackし、blind retryしない。
- pullの成否、取得digest/arch/id、イメージの配布先、実行版、サイズ、実測コンテナ起動有無を安全なログに記録。digest不一致、registry接続/認証不明、サイズ不足、unknown image、platform mismatchは `FAIL/UNKNOWN` として当該subtaskだけ停止。他imageのpull、Docker設定/daemon変更、credential入力、新プラン加入や課金操作はしない。
- 必要ならimageの実configやinspectをread-onlyで確認。秘密情報の値・認証情報・home/configファイルは成果物に保存しない。

## 3. 安全なLocal隔離STATIC試験（LIVE 0）
- 固定2imageを利用する際は、信頼できるoperator側で**専用の合成fixtureと全候補ファイルのみ**新規の一時作業ディレクトリに準備し、SHA/参照を保存。workspace/home/.git/credential、ユーザーの実ファイル、Docker socket、秘匿環境変数をコンテナへ渡さない。
- 既存CIと同等の `--network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 --pids-limit 64 --memory 256m --cpus 2`、限定`--tmpfs /tmp:rw,noexec,nosuid`、fixtureの`--mount ... readonly`で、Python synthetic syntax/fixture isolated test、Gitleaks clean+synthetic-negative scanを実行する。GitHub CI jobのコマンドを照合し、ローカルに不適切な `GITHUB_WORKSPACE` 全体や個人Windowsディレクトリをマウントしない。
- root書込不可、uid、mount読み取り専用、network無効、capなし、host socketなし、secret selectorなし、CPU/memory/PIDsなど実際の `docker inspect`/結果/ログで確認。試験はモデルなし・実workerなし・実GitHub成果採用なし・実HTTP writeなし。
- 結果は `PASS`/`FAIL`/`NOT_RUN` を独立証拠で区別。イメージ取得PASSだけで隔離PASSを推測しない。試験の問題で既存開発・GitHub証拠を破壊しない。

## 4. 他の独立した安全仕事（可能なら続行）
- 本番候補のoperator所有のcheckout/テスト/scan/CI出所証明と、reviewed real sender capabilityの **read-only/prepare-only** の不足を現在の実コードと照合。限定された真に有益なSTATIC修正があれば最小実装＋tests＋証拠。単なるMOCK件数水増しや新scheduler/worker launcherの実装は禁止。
- 現行の `REAL_CANDIDATE_NOT_QUALIFIED`、`REAL_SENDER_NOT_WIRED`、one-run authorization NONE はそのまま。PIN2件のLocal隔離PASSによって**LIVE GOになったと宣言しない**。
- Official Symphony scheduling/polling/continuation/retry/backoff/stall/concurrency/cleanupは変更しない。

## 5. 証拠とGitHub継続
- Docker terminal logs、`docker inspect`のセーフフィールド、ローカル固定image ID/RepoDigests、実試験結果、fixture SHA、実ソースのテスト、残るgateと判定をWindows側の既存永続成果物配下の新しい一意のパスに保存。原本上書きなし。テストと差分から機密情報を除外。
- repoへの変更が意味のあるものなら、許可済み既存非default PR #343の範囲内で最新HEAD/clean worktree/FF条件を検証後、通常commit/fast-forward push。結果が曖昧ならGitHub readbackを最優先し再送禁止。remote commit/tree/blob＋exact-head CI（Symphony/Blue/synthetic independent）まで。意味のないno-op commitは不要。新差分なしならappend-only PR commentの証拠・判定のみでもよい。
- **今回の明示許可はDocker image2件の取得とOFF STATIC試験だけ**。PR Merge、main/default書込、force push、実Git Database POST、GraphQL updateRefs real mutation、実成果採用、新LIVE model/provider/worker、proof Issue/ref生成、秘密情報・設定・権限・Billing変更は禁止。

## 6. 最終報告（日本語、一括）
取得2件のexact digestとpull/inspect、Local隔離 PASS/FAIL/NOT_RUN、各実証log/証拠SHA、実作業HEAD/CI（変更した場合）、残るreal candidate/verifier/sender/LIVE gates、必要な実人間判断だけを一度に報告。

**Codex推奨モデル：Luna High（今回の定型Local Docker試験・証拠整理）。安全な実装レビューや本番送信権限設計の難所に入る時のみSol 6.1 Highに切り替える。** 追加質問で途中停止せず、安全なバッチを使い切る。
