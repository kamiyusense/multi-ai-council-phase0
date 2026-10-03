# Signal Step 7 追加 LIVE 証明: LIVE 経路（STATIC 完成）と開始手順

> **更新（proof 4 の事後分析後）:** 下の「実行順」のうち、publish の人手 dispatch（手順 5）は廃止しました。carrier 成功を受けて publish が自動起動します。最新の手順と理由は [SIGNAL_STEP7_AUTO_PUBLISH_20261003.md](SIGNAL_STEP7_AUTO_PUBLISH_20261003.md) を参照してください。人の操作は issuer の 1 回だけです。

状態: **STATIC で検証済み。LIVE は 1 回も実行していません。**
カウンタ: Jules POST 0 / Jules GET 0 / issuer dispatch 0 / OIDC LIVE 0 / retry 0。旧 Session 132 には一切アクセスしていません。

## 追加したもの
| 部品 | 役割 |
| --- | --- |
| `automation/command_bus/signal_step7_live_proof.py` | 公開側の本体。計画の検証、重複防止、予算管理、認証、公開、読み戻し、レーン登録確認、採用前ゲート再評価、証拠保存 |
| `automation/command_bus/signal_step7_live_proof_cli.py` | GitHub / Jules に実際につなぐ部分。`--check`（通信なし）と `--bind-out`（ファイル生成のみ）あり |
| `.github/workflows/signal-step7-live-publish.yml` | LIVE 用 workflow 候補。手動実行（workflow_dispatch）のみ。main 限定・run_attempt 1・許可アクターは 20355232 のみ |
| `docs/evidence/signal-sf8/step7-live-plan-template.json` | 計画テンプレート。対象の HEAD / tree は未バインド（全ゼロ）なので、このままでは実行できない |
| テスト 2 本 | 失敗注入を含む 65 件（実 GitHub / Jules への通信なし） |

## 予算の内訳（全体: POST 1 / GET 2 / issuer dispatch 1 / retry 0）
- carrier（既存 workflow）: Jules セッション作成 POST 1 回 + 作成時刻の読み戻し GET 1 回。
- 新 workflow: 認証用の新しい GET 1 回。**ここで GET の予備は 0 になります。**
- issuer dispatch: 人間が 1 回。完了済みの run id を新 workflow に渡す。

## 実行順（LIVE 開始時）
1. 🟠 人間: この PR（または同内容）を main に取り込む。workflow_dispatch と issuer の条件が main 限定のため必須。
2. Claude（LIVE ではない準備）: target ブランチと Draft target PR、work ブランチ、data ブランチを作り、`--bind-out` で計画を固定し、固定済み計画を data ブランチに置く。
3. 🟠 人間: issuer workflow を 1 回 dispatch。**必ず Jules セッション作成より前**（認証の発行時刻がセッション作成時刻より後だと拒否されるため）。
4. carrier command と claim を `feature/chat-work-command-bus` に push（POST 1 + GET 1）。人間の「開始」の指示を受けて Claude が行うか、人間が行う。
5. 🟠 人間: 新 workflow を 1 回 dispatch（入力 3 つ: session id、issuer の run id、計画の sha256）。**セッションが完了する前**に行う必要がある。
6. Claude: 結果を読み戻し、Jules の出力 PR を `assess_output_readback` で検査し、採用候補を再生成して PR に反映。Merge はしない。

## フェイルクローズする条件
別 repo / 別 branch / 別 target HEAD・tree / 別 session / 別レーン id（fixture 含む）/ 別 authority run / 再実行 / 古い authority / 古い観測 / 別 sourceContext / 別 startingBranch / 別 owner generation・fencing / command・receipt・evidence の重複 / 出力 PR の変化 / 想定外のパス / 想定外の内容 / provider が UNKNOWN または終了状態 / 書き込み結果不明 / GET 超過 / POST 2 回目。
失敗しても最終 receipt が残り、同じ run を再実行できません（`rerun_allowed=false`）。

## まだ残っている BLOCKED
- 本物の Jules / GitHub でこの経路を動かしたことはありません（STATIC のみ）。
- 公開側の GET の時点で、Jules セッションがまだ作業中（QUEUED / PLANNING / IN_PROGRESS）である必要があります。完了していれば UNKNOWN で停止し、この GET は戻りません。
- target ブランチ / Draft PR の作成と計画の固定は、まだ行っていません（LIVE 開始の直前に行う設計です）。
- production registry は PLACEHOLDER のまま。Issue #33 は STOPPED のまま。`READY_FOR_HUMAN_APPROVAL` になっても `registry_write_allowed=false` です。
