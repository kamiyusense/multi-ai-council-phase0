# PR217 — 長尺STATIC完成バッチ / 日本語引き継ぎ

最新HEAD/CIは [PR217](https://github.com/kamiyusense/multi-ai-council-phase0/pull/217) と最終Conversation checkpointをfresh readbackする。
この文書は実験branch `experiment/blue-work-autonomous-development` に限る。Merge保留。
**追加LIVE0 / Session GET0 / claim予約0 / 設定・権限変更0**。以前の10trialを再利用しない。

## 再開時の正本と履歴

開始HEAD9d2a23024e23faca78c720fb2962b483c4607b4e、tree77b9caf994a59c396a545a3d046473af307fb868。
OPEN/Draft/unmerged、PR203 HEAD66d366523ebe28726fcb36b0e5a45cb3368aa52d。
raw PR227 HEADb4c5608f983ef42b5bd206bfc9c4f0f465ae7869、base337004由来、formal work branchへ向いた2ファイルの未Merge結果。
PR227は前の独立検品FAILの履歴として無変更。PR217のController修正を原結果のPASS採用へ書き換えない。
Blue167/Yellow165/Green166/Red171はOPEN/Draft/unmerged、active_generation1をcurrent protocol/stateで照合した。
main README→handover→router→playbook→roadmap→4色index、正式Jules carrier上のColor/Semi-Auto/Controller/validatorを読む。
現在のworker routingをこのバッチから変更しない。明示されたSTATIC Work作業を自分で実施し、別AIへの委託なし。

Trial10 `blue-20261002T055200Z-pr217-session-diagnostic-review-10`:
review5388681925、submit05:50:51Z、target9d2a230、expiry07:52Z。
Controller [5947745815](https://github.com/kamiyusense/multi-ai-council-phase0/pull/217#issuecomment-5947745815) と今回のfresh7reviews/6commentsにterminalなし。
**UNKNOWN・再送禁止**。後からreceiptが見つかってもcommand/PR/branch/HEAD/tree/generation/review/timeを照合し、期限後のPASSを自動採用しない。

## 実装から再現した欠陥と修正

最初の修正前4regressionのうち3FAIL、その後の追加自己検品で1件のFAIL（直接の循環参照）を実際に記録した。

1. `source_mode=CAPTURED` に自己申告VERIFIEDを添えるだけでnext-task候補を生成できた。現在は認証adapter未接続としてBLOCKED。MOCKのみの候補を実際の権限へ変換しない。
2. `verify_result_lineage` の秒精度helper経由でacceptance/readbackの1ns差がVERIFIED_SNAPSHOTになった。既存 `_exact_time` で9桁まで比較し、updateTime逆転も停止。
3. 正しいPR output1件のほかに空outputがあってもunique扱いだった。全outputs長1、唯一のPR URLを要求。

4. 検品回答が自分のresponseを成功証拠に引用しても次候補を出せた。自分のrequest/response/consumptionへの直接参照をBLOCKEDにした。任意URLの多段循環や証拠originを一般的に証明したとはしない。

追加で、create-only CLI出力が既存/symlinkの場合はGitHub readerを作る前に停止する。再保存を理由に余分なGETをしない。
UTC範囲外provider時刻の診断も固定の安全な分類に止める。大規模rewrite、依存framework、DB/queue/serverを追加していない。

## Session source認証の準備

`jules_session_evidence.py` は正規routeが今後受け取るCREATE/GETレスポンスをその場で最小投影する純粋関数。
保存するのはSession ID、providerのexact createTime/updateTime、repo/starting branch、command/Loop/lane、target branch/HEAD/tree、dispatch commit/run/job、capture時刻/source種別/state/output PR番号、retry0/fallback disabled。
prompt/description/title/header/key/raw bodyは保存しない。秘密を含む例も投影で消えることをテストした。
CREATE captureはcommand期限内、完成captureはfuture不可、両者のSession/完全時刻/正式context/一意PR outputを照合する。
hashは内容の指紋であり、認証証明ではない。保存形式の `UNAUTHENTICATED_CAPTURE` を任意JSONからVERIFIEDに変えられない。

既存Loop125は秒精度しか残っていない。診断run36970590374/job110723542520の既存logを今回読み戻した。
exact createTime=false、same-second=true、unique PR output=false、source認証UNKNOWN。
PR227作成19:19:05Zはdispatch受理19:08:33Zの後だが、順序だけではSession output227を証明できない。
URL差・0件/2件・別PRのどれが原因かはraw bodyを保存していないためUNKNOWN。新GETで調べたとは報告しない。
古い証拠へ正確な時刻を逆算して埋めない。前の失敗run36955281748の原因もUNKNOWN。

## 自動bridgeと4色の到達地点

既存1色1carrierをChat命令とJules結果検品で共用する設計を維持する。追加Scheduled Task0。
共通lane metadata、BWJ-1/2のcommand body、世代管理、terminal parser、reviewer ledger、schema-v3 claim validatorを再利用。

- GitHub-only preflight: opened/synchronize→current formal source/claimから色判定→carrier/state/full reviews/comments→result HEAD/tree/全files/ancestry→dispatch jobs→最終fresh fence。
- fork/無関係PR/危険path/delete/rename/symlink/古いtargetは停止。途中変更/不完全取得/権限不明はUNKNOWN。既存command/terminalならNO_OP、再投稿しない。
- production source認証未接続はBLOCKED。実際の投稿candidateとposting authorityを作らない。
- MOCK bridge: exact source capture→review candidate→fake submit→fake Work terminal→trigger/HEAD/tree/generation/time照合→独立review record→次タスク/schema-v3 claim候補→予約・dispatchの直前でSTOP。
- 完了記録欠落はUNKNOWN。送信の成否が不明なら再送しない。遅いreceiptや重複terminalは次Julesへ進めない。
- carrier HEADはcurrent stateで読む。前Loopのcarrier HEADを固定して正当な更新を拒否しない。target HEAD/treeは厳密に固定。

本番Actionsの権限はcontents/pull-requests/actionsのreadのまま。新workflow、外部サービス、App/PAT/secretは作成していない。
既存 `blue-work-reconcile-static.yml` にMOCK pipeline/soak/artifactを追加し、eventは`--lane auto`で正式claimから選ぶ。
review本文の候補は既存prefix＋厳密JSON、COMMENTを将来のreview APIへ渡す。carrier HEADを固定した権限やcommit_idから採用許可を作らない。
将来の最小追加権限候補は対象bridge jobの `pull-requests: write`。今回は有効化せず、source認証・workflow配備・明示承認・送信直前fresh dedupeも別に必要。
単一writerのconcurrency＋ durable deterministic command ID＋成功不明時readbackが必要。POST失敗でfallback/PAT/newIDを作らない。

## 模擬閉ループ・再起動・競合

E2E fixtureは `tests/fixtures/work_bridge/pre-submit.json` と `terminal.json`。
MOCK source modeを明記し、fake recordをLIVE証拠と誤認しない。
32仮想Loop（4色各8）、1280障害観測。event逆順/重複/receipt先着/欠落/古い世代/HEAD更新/期限切れ/source欠落競合/出力0・2件/fork/path異常/self-review/partial pagination/retry/再起動等。
全ての不安全ケースでnext claimが出ないことをassertする。件数だけを安全証明とはしない。
global番号衝突、他色command消費/receipt採用、二重dispatch、terminal再実行、古い世代/source未認証/target不一致の採用、Merge/forceの観測違反0。
これらはfixture内の不変条件。全ての現実の障害を証明したという主張ではない。

fresh WorkはGitHubだけからcommand/review/receipt/source/reviewer consumptionを復元する。
レビュー投稿前crash:同一固定candidateのみ。投稿直後crash:レビュー存在＋receiptなしUNKNOWN、再投稿しない。
receipt後crash:exact terminal/tree/trigger照合。review消費後restart:durable consumption receiptでNO_OP、次candidate再発行なし。
次claim候補後crash:NOT_RESERVEDの候補は権限ではない。全global ledger/branches/targetをfresh recheck。
4色が同時に同番号candidateを作れる点は残るが、予約済み番号をfresh readした4件ともBLOCKED、番号を自動で変えたり再試行しない。
新DB/queue/session常駐を復旧の正本にしない。

## テストと検品入口

[結果JSON](evidence/blue-work-static-20261002/tests.json) / [修正前FAIL](evidence/blue-work-static-20261002/regression-before.txt) /
[full log](evidence/blue-work-static-20261002/full-tests.txt) / [4色soak](evidence/blue-work-static-20261002/four-lane-soak.json) /
[変更ファイル・blob](evidence/blue-work-static-20261002/changed-files.json)。
full command_bus1045、成功1044/Windows-only skip1/失敗0/error0。新規38test methodとそのparameterケース。
compileall、diff check、既存正式MOCK、pre-submit/terminal CLI、soakの保存artifactを照合する。
GitHub exact-HEAD Actions/run/job/artifactと保存後readbackは最終checkpointに追記する。Actions greenをsource認証や意味的PASSにしない。
今回のコードの再検品はこの担当によるSTATIC自己検品。別AI独立検品/新LIVE検証は未実施。前夜のPASSをこのdeltaへ転用しない。

## BWJ roadmapと残り

BWJ-1–3再利用済み。BWJ-5独立review契約、BWJ-6正式claimのSTATIC準備とMOCK統合は拡張済み。
BWJ-4の本物のresult event→Actions→carrier→WorkはNOT_WIRED。BWJ-7–9の本物の連続運転は未達。
source認証adapter・信頼できるcapture originの検証・Actions投稿・workflow採用/権限はBLOCKED。
既存Loop125 source/unique output、Trial10、YellowのLIVE tree確認能力はUNKNOWN。
Merge217→203/203→mainはユーザーの別判断。217をMergeしただけで本番default workflowや投稿権限が得られるとはしない。

## 次回LIVE承認候補 — 今回は一切実行しない

詳細は [固定計画](BLUE_WORK_NEXT_LIVE_PLAN_20261002.md)。新予算は別承認が必要、旧10/10から残枠を作らない。
通常成功ならBlueで2段階（新bounded Session＋自動wake、次bounded Session＋復帰wake）、連続性を3段階目で確認する案。
SessionごとCREATE1/完成GET1/自動COMMENT1を上限固定。新Session3・Work3なら最大6trial、観測GET3は別の明示枠。
これは成功経路の最小見積りで、source adapter/配備/権限の準備未完なら0回でBLOCKED停止。1回で全完成を約束しない。
他3色のLIVE接続とWindow専用検証はこのBlue計画に含めない。必要になれば別に最大1wake/色の承認候補。

## 自律工程と停止

今回の工程区分はfresh state/正式資料/既存CI・差分/Trial10 readback/STATIC再検品/修正前再現/3修正/
capture設計実装/negative matrix/event全件preflight/4色共通bridge/strict terminal/reviewer接続/next claim候補/
E2E/soak/global collision/restart/CLI I/O fence/full回帰/自己検品再修正/日本語引き継ぎ/次LIVE計画/
証拠保存/通常commit・FF/readback/Actions検証の26区分。Jules工数や投入Loop数へ換算しない。
有益なSTATIC実装・模擬試験・証拠保存を終えた時点で終了する。Merge待ちやevent到着待ちでspinnerを保持しない。
