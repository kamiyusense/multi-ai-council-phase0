# PR #217 — 2026-10-02 深夜バッチ

対象は既存 `experiment/blue-work-autonomous-development` のみ。Merge保留。
開始時にGitHubから再取得したHEAD: `044e96b69f4bcf7c2efb43cb325f8b5181e086e1`、
tree: `d152694485762e81efd6c9536e5d9790b3c528d8`。
ユーザーは今回の目的に限り既存Work/JulesのLIVE試験を最大10回まで承認。
以前のSTATIC限定記録は履歴であり、この承認を上回る現在の禁止ではない。
Merge/main直接write/force/破壊/権限・設定・認証・課金変更は今回も禁止。

## 最初のLIVEと独立検品

実行前にPR #217 Conversationへ目的・command ID・HEAD/tree・世代・期限・停止条件を固定。
外部Work命令1件または新Jules session1件を1回と数える。読取りやSTATIC Actionsは観測。
曖昧な送信はreadbackし、再送しない。terminal済み命令は続行しない。
検品中はremote target HEADを固定し、localで独立したSTATIC準備だけ行う。

| 回 | 内容 | 結果 | 証拠 |
| --- | --- | --- | --- |
| 01 | Blue generation 1でPR #217のread-only起動 | PASS。対象HEAD/tree未変更 | [review 5383867576](https://github.com/kamiyusense/multi-ai-council-phase0/pull/167#pullrequestreview-5383867576) / [receipt 5938151988](https://github.com/kamiyusense/multi-ai-council-phase0/pull/167#issuecomment-5938151988) |
| 02 | 同じHEADの独立コード検品 | FAIL。実装不足2件を発見。正常な検品結果として修正へ進む | [review 5383944482](https://github.com/kamiyusense/multi-ai-council-phase0/pull/167#pullrequestreview-5383944482) / [receipt 5938273083](https://github.com/kamiyusense/multi-ai-council-phase0/pull/167#issuecomment-5938273083) |

両receiptのcommand ID・PR・branch・before/after HEAD・generation・terminalを直接照合。
これはconnector生成COMMENT reviewから既存Blue Workを起動できた証拠。
ActionsのGITHUB_TOKEN生成reviewによる自動起動、正式Jules結果の自動中継、
完全な無人閉ループが証明された意味ではない。

## 再現と最小修正

- `_records`: terminal receiptにnonempty verification文字列配列を必須化。
  optional capability_boundaryはnullまたは文字列。元review/対象/HEAD/世代の照合を維持。
  証拠のないreceiptはUNKNOWNで、再実行権限も処理済み権限も生まれない。
- `result_files`: ファイル全ページ取得の前後でPR番号・HEAD・branch/repository・base・
  changed_files・open/merged状態を比較。取得中に変化した場合はValueError、再取得/再試行なし。
- `verify_result_lineage`: 正式commandのbase treeとcompareの実tree、pinned result Git commitの
  HEAD/tree、Sessionの一意PR出力、実行logの一意timing行を照合。
  捕捉データの検証結果へresult PR/HEAD/tree/lane/allowed_pathsを残す。
- `assess_result_review`: 上記のresult identityとreview request/HEAD/tree/命令IDを結び、
  source allowlistの後付け拡張を拒否。単なるVERIFIED_SNAPSHOT文字列を別結果へ流用できない。
  捕捉データの照合は認証・意味的PASS・独立検品の代わりではない。

修正前のsource/review/取得競合8テストは8 FAIL。
receiptはGitHub-pinned original実装を別moduleとして再生し、3テスト/12 subcase FAILを確認。
初回receiptテストにhelper引数数の誤りが1件あったためテストを直し、originalを再生し直した。
このharness errorは製品の不具合と区別し、証拠に記録する。

修正後: full suite949件（成功948、Windows-only skip1、failure/error0）。
重点87件すべて成功。compileall、diff whitespace、更新MOCK閉ループも成功。
結果と修正前失敗は [evidence](evidence/blue-work-night-20261002/) に保存。
保存後のexact-head Actionsと独立delta reviewはPR #217から読み戻す。

## 正式仕様と次段階

current mainのREADME/引き継ぎ/router/playbook/Blue roadmap/4色indexを再取得。
main workflowからJules carrierを発見し、現行Color Lane/Semi-Auto/Task Prompt/Controller Guide、
workflow、runtime contract、validatorsを取得。schema-v3 validatorと正式V2 validatorは
PR #217の再利用copyとblob一致。旧claim番号を新dispatchへ流用しない。

公式Session GETは [Jules sessions](https://jules.google/docs/api/reference/sessions) の
既存session読取りであり、新session作成POSTと別操作。既存secretを作成/表示/変更しない。
現在の認証source readerはNOT_WIREDのまま。既存正規routeで小さく接続する候補を検討し、
未接続JSONを認証済みへ昇格しない。

[GitHub workflow event制約](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
は外部Workのwebhook到達保証ではない。今回のconnector起動PASSと別に検証が必要。
現在のSTATIC workflowはread権限のみで、review投稿権限を勝手に拡大しない。
必要なMerge/権限変更はその工程だけBLOCKEDにし、他のSTATIC開発を継続する。

次は修正HEADの独立delta review。PASS後に用途・HEAD・command/claimを個別固定して
正式global claim/次Jules/結果検品へ進める。新LIVE総数は常に10以下。
未確認送信・terminal receiptの再実行・同じ失敗の無分析再試行は禁止。
