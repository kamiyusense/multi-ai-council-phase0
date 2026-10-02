# 次回LIVEの最小計画 — DRAFT / NOT_EXECUTABLE

これは承認候補の設計。今回の実行命令ではない。旧budget10/10、Trial10、Loop125の再送を認めない。
source/投稿adapterのSTATIC独立検品、正規routeへの採用、権限・Merge判断が未完ならLIVE0回でBLOCKED。
新しいtoken/secret/App/外部serviceは使わない。既存正規routeで対応不能ならUNKNOWN停止。

## 実行前に一度だけ封印する共通条件

- repository `kamiyusense/multi-ai-council-phase0`、target PR217 / `experiment/blue-work-autonomous-development`。
- expected HEAD/treeは**最終PR217 Conversation checkpointに記録された実SHA**をfresh ref/commitから再取得して一致を確認する。
  開始snapshot9d2a230/tree77b9cafをfuture実行値にしない。値が変わったらSTOP、既存封印を勝手に書換えない。
- Blue carrierはlabelからcurrent OPEN PRを発見し、protocol/state/genを照合。現在snapshot167/gen1は実行時の代用ではない。
- command ID候補のprefixは `relay-dev-loop-<fresh_global_id>-bwj-source-pilot`。global候補は予約されていない。
  正式schema-v3 claimをcreate-only予約しexact readbackした同番号でだけ命令を封印する。
- Work命令は既存 deterministic `blue-jules-result-pr<new_result_pr>-<exact_result_head>`。
  resultが未生成のためPR番号/HEADは現時点UNKNOWN。仮値で実投稿しない。
- stageごとtarget HEAD/tree、result PR/branch/HEAD/tree、command/claim、dispatch run/job、exact Session capture、
  generation/expiry、allowed files、最大回数、stop条件をcreate-only approval artifactへ固定する。
- 全stage retry=0/fallback=disabled。送信成功不明ならGET-only durable readback、再送/別IDの実質retryをしない。
- carrier上の他missionと競合、世代変更、claim衝突、二重terminal、source不一致/期限切れ/権限不明で即STOP。
  result採用、Merge、次dispatchは別の権限。候補artifactから権限を作らない。

## L1 — 新規の厳密なSession証拠＋自動Blue wake

目的:旧Loop125の不完全な証拠を修復したことにせず、新しい正式missionでoriginを確定する。
Jules taskは1個の既存fixture regressionを対象とした小さなSTATIC実装。allowed pathは封印前に1–2ファイルへ限定。
command ID案:上記fresh global ID＋`bwj-source-pilot`。Work IDは新resultの決定的ID。
target:PR217の封印済みHEAD/tree、work branchは正式commandIDから派生。
必要権限:既存Jules route/既存認証、採用済みcapture module、read GitHub、別承認されたbridge jobのpull-requests:write。
回数:新Session CREATE1、completion GET1、Actions COMMENT1、既存Blue Work1。task作成以外のprovider/model0。
成功:CREATE直後exact captureと完成GET captureのSession/time/repo/branch/context/run/jobが一致、unique outputが新result1件、
GitHub全files/ancestry/tree/fresh fence一致、ActionsのCOMMENT review1件をreadback、Blueのstrict terminal1件と独立検品recordが一致。
FAIL:厳密なidentity/tree/世代/検品の明白な不一致、原結果scope違反、receiptのFAIL。
UNKNOWN:出力0/2、receipt欠落、origin未認証、期限後terminal、投稿成否不明、読取能力不足。いずれも再送しない。
stop:成功後もL2の封印・新予算を確認するまで次Session0。FAIL/UNKNOWNはその時点で終了。
証拠:PR217 `docs/evidence/blue-work-next-live/<sealed_stage_id>/` とcarrier review/receipt、Actions run/job/artifact。
raw body/prompt/keyは保存せず、allowlist capture・fingerprint・source origin検証記録を保存。

## L2 — terminal検品から次claim候補・正式投入・再wake

目的:Workの独立PASSが1つの正式schema-v3 successorへつながり、次resultで同じBlueに戻ることを確かめる。
command ID案:`relay-dev-loop-<next_fresh_global_id>-bwj-successor-pilot`。Work IDは新result固定HEADから作る。
targetはL1独立PASSで承認されたcanonical HEAD/treeをfresh readし、同じPR217 branchだけを使用する。
必要権限:L1と同じ＋別承認された正式claim/isolated branch/commandのcreate-only publication。
回数:新Session CREATE1、completion GET1、COMMENT1、Work1。claimは1個のみ、曖昧write再送0。
成功:独立review responseとconsumption receiptの厳密binding、unique claim/command/workbranch、exact capture、
result ancestry/files/tree、自動wakeとterminalが一貫してreadback可能。
FAIL/UNKNOWN/stop:L1と同じ。claim競合はBLOCKED、番号を自動で変えない。結果PASSでもMerge0。
証拠:L1と同じstage分離。L1・L2証拠の相互引用だけでsemantic PASSにしない。

## L3 — 必要な場合のみ、もう一巡で連続性を確認

L2まで成功し、独立検品で意味のある小taskが1つ残る場合だけ。
command ID案:`relay-dev-loop-<next_fresh_global_id>-bwj-continuity-pilot`、Workはresult固定ID。
target/権限/厳密binding/証拠/FAIL/UNKNOWN/停止条件はL2と同じ。
回数:新Session CREATE1、completion GET1、COMMENT1、Work1まで。無意味なtaskを作らない。
L3後は自動でL4を始めず終端。全体上限に達したら原因台帳とGitHub checkpointを保存し停止する。

## 回数の合理的な目安

正常経路のBlue proofは2–3段階、従来の数え方でJules2–3＋Work2–3＝**4–6trial**、完成GET2–3は別の観測枠。
自動wakeだけの最小proofはL1の2trialだが、source→nextclaim→連続運転全体をそれだけで完成とは判定しない。
失敗時の追加試行は含めずretry0。10trialで未解決だった現実から、確実な回数や所要時間は保証できない。
他3色はSTATIC済みだがLIVEは別計画。Blue成功後に各色read-only wake1回、合計最大3trialを別承認候補とする。
Yellowのtree能力UNKNOWNをSTATIC成功からPASSへ変えない。

## Merge/permissionの隔離

現在workflowはreadのみ。COMMENT review APIの最小permission候補はpull-requests:writeだが、設定を今回変えない。
GitHub GITHUB_TOKENで生じたreviewが外部Workを起こすかは公式保証を確認できずUNKNOWN。
GitHub Actionsの再帰抑止規則と、OpenAI側のevent deliveryは別境界。bridge trialは同じ既存tokenで一回だけ測る。
failed wakeをPAT/App permission増加/fallbackへ自動切替しない。
PR217→203、203→mainの採用順とdefault workflow配置は人間のMerge検品・承認事項。
主branchへのcommit、Merge、token/permissions/admin変更、新scheduler、新monitorをこの計画から自動実施しない。
