# PR217 続行 — 2026-10-02 Session診断と検品
最新状態は [STATIC完成バッチ](BLUE_WORK_STATIC_COMPLETION_20261002.md)。下記の診断計画は実施済みの履歴であり再実行指示ではない。
これは実験枝だけの継続記録。入口は [PR217](https://github.com/kamiyusense/multi-ai-council-phase0/pull/217) と最新HEAD。Merge保留。
前夜の記録は [最終検品](BLUE_WORK_REVIEW_READY_20261002.md) / [night batch](BLUE_WORK_NIGHT_BATCH_20261002.md)。

## 正本の再確認
続行開始時のGitHub HEADは a3e3c2e67cb0dfb3c506cbe06fedc65e237c169e、tree41529071d07d0e20d5491e187fbb2a17c31eb422。
PR203は66d366523ebe28726fcb36b0e5a45cb3368aa52d、raw PR227はb4c5608f983ef42b5bd206bfc9c4f0f465ae7869でopen/unmerged。
mainのREADME/handover/router/playbook/roadmap/4色index、正式carrierのColor/Semi-Auto/Task Prompt/Controller/validatorをfresh read。
正式claimとV2 validatorは前回コピーと同じblob。古い会話だけを正本にしない。

## 再現と最小修正
canonical a3e3 readerでmockされた3件を再現した。小数秒9桁の末尾をdatetimeが切り捨てるため、
1nsの異なるcreateTimeと、createTimeより1ns前のupdateTimeを一致/順序正常として許可した。
10桁小数秒の不正なexpected timeでもGETを行った。原HEADの実再現logを保存。
修正は既存aware parserを使い、RFC3339の9桁までを検証し、datetime＋残り3桁で完全比較する。
同じ瞬間のUTC/JSTは許可、不正offset/未知offset(-00:00)/UTC範囲外/10桁はI/O前停止。
正式helperの秒精度表示は変更していない。秒だけ一致することを正式な完全一致へ昇格しない。

診断は同一GETレスポンスから固定名のBoolean比較だけを取り出す。name/branch/createTime/state/repo/output/updateを区別し、
HTTP401/403/404/429等は固定ラベルだけ、raw body/headers/key/prompt/description/任意error文字列は出さない。
UNKNOWN artifactとlogは観測のみ。source認証/採用/次Sessionの権限を生まない。
既存outputのcreate-only、no redirect、30秒1MiB、一件GET、retry0/fallback disabledを維持する。
errorメタデータの改変もCLI出力前に再filterする。

## 固定診断計画（送信前）
- observation_id: blue-20261002-session-diagnostic-01
- 既存Session:12436642121757218108、正式Loop125 / command relay-dev-loop-125-bwj-session-get-reader。
- branch:jules-work/relay-dev-loop-125-bwj-session-get-reader、既存timing evidence:2026-10-01T19:08:33Z、対象PR227。
- 対象result HEAD:b4c5608f983ef42b5bd206bfc9c4f0f465ae7869、tree ec62e889dbdd5683d6c7c415950f9291e2573f76。
- 新create-only request:docs/evidence/blue-work-continuation-20261002/session-diagnostic-request.json。
- 専用request追加commitは変更1ファイルだけ。旧request/失敗Actions/terminal Work命令は再実行しない。
- 既存read-only workflowを最小拡張、contents:readを維持。run_attempt1、固定Session/PR/branch/time/purpose/integer型を検査。
- 診断実行期限:2026-10-02T08:00:00Z。期限後・別identity・複数file・更新・再実行はGET前停止。
- 作業順:code/test/計画保存→exactHEAD STATIC CI成功/readback→新診断request一件追加→一件GET→logs/artifact/readback→STOP。
- 新しいSession/Work設定/secret/権限/課金/外部サービスは追加しない。原PR227を採用しない。
- 不明/FAILでも二回目診断を自動生成しない。成功でも新Julesや自動carrier投稿へ進まない。
前回failure run36955281748は分類情報もrawもartifactもない。上記は原因を隠すblind retryではなく、
原因分析（診断情報不足/静的precision不具合）後の新しいread-only観測。前回実原因は結果確認までUNKNOWN。

## LIVE枠と停止境界
既存台帳の数え方を維持:新Work命令/新Jules Sessionはtrial、GETは観測。続行開始9/10（Work8、Jules1）。
今回計画は既存Session GET観測1回。残り1trialは必要な最終独立read-only検品にのみ利用可能。
10を超えるLIVE、Merge、auth/permission/settings/billing変更は未承認。
Actions→carrierの本投稿workflowは現在read権限のみでNOT_WIRED。権限増加やMergeによる採用が必要な工程を隔離する。
STATIC/模擬検証はその境界と独立に進める。

## テスト（保存前）
原canonical3 regression:3 failures/0errors（意図した再現）。修正後full1007:成功1006/Windows-only skip1/0failure/0error、48.722秒。
新regression20件は時刻精度/秘密を含まない診断/CLI/実workflow preflightの異常系を検証。
compileall/diff whitespace/MOCK正式schema-v3閉ループも成功。単なる自己申告と区別し、GitHubのexactHEAD Actionsを読み戻す。
独立Work検品は前HEAD931へのPASSであり、今回新コードの独立PASSではない。

## UNKNOWNと再開
完成Sessionの厳密なsource系譜、Actions生成review→Work、自動閉ループ/連続運転は未証明。
診断Booleanはprovider source認証や正式採用の代用品ではない。Yellowのtree確認能力はUNKNOWNのまま。
診断結果・最新CI・最終検品をこの文書とPR217へ追記する。途中でもこの固定計画とGitHubだけで再開できる。

公式参考: [Jules Session GET](https://jules.google/docs/api/reference/sessions) /
[Jules Session types](https://jules.google/docs/api/reference/types) /
[Google protobuf Timestamp](https://protobuf.dev/reference/protobuf/google.protobuf/#timestamp)。
公式Timestampの9桁/offset契約を設計参考にした。新dependencyやupstreamコードのコピーはない。

## 実施後の固定結果
診断run36970590374/job110723542520（request commit9d2a23024e23faca78c720fb2962b483c4607b4e）はCLI exit2で安全停止。
name/branch/repository/COMPLETED/same-secondは一致、exact createTimeとunique PR output比較はfalse。
source認証はUNKNOWN。既存の安全なlogのみを今回読み戻し、raw responseは取得・保存せず、新GETも行っていない。
artifact11211033930のzip digestは05354a93401dbbb1f50d8b4a9db8526b32e85a98b8881084fa574ea62ada9373。
Trial10 review5388681925は2026-10-02T05:50:51Zに提出済み、expiry07:52Z。
Controller checkpoint5947745815と今回のfresh comment全件readbackでreceiptなし。UNKNOWN固定、再送禁止。
前の9/10は履歴。承認予算10/10は消費済み。今回STATICバッチの新LIVEは0回。
