# Signal Step 7 proof 5（Loop 136）の結果と DURABLE 採用候補

状態: **LIVE は 1 回だけ実行済み。認証の流れは最後まで通りました。production registry と Issue #33 は変更していません。**
採用（PLACEHOLDER → DURABLE）の Merge は人間の判断です。この文書と PR はそれを実行しません。

## 結果（GitHub の読み戻しで確認）

| 項目 | 値 |
| --- | --- |
| proof task / Loop | `signal-active-proof-5` / 136（carrier レーンは J-YELLOW） |
| durable レーン | `chatgpt-semi-auto` |
| main（issuer 実行時・publish 実行時） | `aebae14695cfaaf1dc8bcc2ec35faca9c898fd48` |
| issuer run | `37150285702`（人が 1 回だけ実行、成功、attempt 1） |
| carrier run | `37150477481`（commit `67071fb`、成功） |
| Jules session | `7218641455365522473`（作成 20:08:57Z） |
| 自動 publish run | `37150495337`（`workflow_run` で自動起動、人の操作なし） |
| Jules の生の状態 / 正規化 | `IN_PROGRESS` / `RUNNING`（観測 20:09:35Z） |
| 使用回数 | POST 1 / GET 2（carrier 1 + publish 1）/ issuer 1 / retry 0 / fallback なし |
| 最終 receipt | `COMPLETE`、`rerun_allowed=false`、追加の GET・POST は不可 |
| レーン登録（`chatgpt-semi-auto` のみ） | READY |
| 採用前チェック | `READY_FOR_HUMAN_APPROVAL`（`registry_write_allowed=false`） |

proof 4 の失敗原因（人手の publish が遅れて Jules が完了済みになる）は、carrier 成功の約 6 秒後に publish が自動起動したことで解消しました。publish の fresh GET は carrier の作成から約 38 秒後で、Jules はまだ作業中でした。

## Jules の出力 PR #286（GitHub だけで検査。追加の Jules GET なし）

- 変更ファイルは `docs/evidence/signal-active-proof-5/PROOF.md` の 1 つだけ。base は隔離した work branch の `5ebad97…`、branch 名は今回の session のもの、未 Merge。
- **逸脱が 1 点あります:** ファイル末尾に改行がありません（21 バイト。契約は 22 バイトの `signal active proof 5\n`）。文字そのものは正しく、他のファイルは変わっていません。`assess_output_readback` は「proof content is not the exact allowed content」と判定します。
- この逸脱は Jules の成果物の体裁の問題で、認証の流れ（権限・provider 認証・publisher・collector・レーン登録）の結果には影響しません。ただし契約に厳密に従えば「出力は完全一致」ではないため、判断は人に残します。PR #286 は Merge しません。

## 採用候補（この PR）

- `docs/evidence/signal-step7-proof5/adoption-candidate.json`: 現在の registry の digest（`6af0268e…`）、候補 registry、採用 record、proof 5 の各 run / digest / receipt、`registry_write_allowed=false`、`human_approval_required=true`。
- 候補と現在の registry の差は `chatgpt-semi-auto` の `identity_state` だけです（`validate_lane_adoption_diff` で確認）。他の 3 レーンは PLACEHOLDER のままなので、全体の登録は `NOT_WIRED` のままです（Issue #33 の移行は行いません）。
- 新しいテスト `test_signal_step7_proof5_candidate.py`（17 件）が、記録された証拠・出力の逸脱・採用差分・失敗時の閉じ方を確認します。

## この PR がまだやっていないこと

- production registry の書き換え。これは別の採用変更（`identity_state` の 1 行 + 「全部 PLACEHOLDER」を前提にしている既存の安全テストの調整）で、人の承認の後に行います。試験的に書き換えたところ、既存テスト 12 件が失敗しました（すべて「production は全部 PLACEHOLDER」という前提のテストです）。
- Issue #33 の更新、Jules 出力 PR の Merge、proof 6。

## 人が決めること

1. proof 5 の結果（出力の末尾改行の逸脱を含む）を受け入れてよいか。
2. 受け入れる場合、採用変更（registry の 1 行 + 安全テストの調整）を作る許可。
