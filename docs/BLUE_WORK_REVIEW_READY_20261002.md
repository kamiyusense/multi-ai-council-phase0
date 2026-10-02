# PR #217 — 2026-10-02 最終検品用チェックポイント

続行の最新記録は [Session診断と検品](BLUE_WORK_CONTINUATION_20261002.md)。以下は前夜のチェックポイント。

この文書は実験枝だけの記録。最新HEADはPR #217とgit/refから必ず読み直す。
Mergeは最後まで保留。main/#203のコード、4色carrierのcode/state、Work設定は変更していない。
既存正式Jules carrierにはユーザー承認に基づくLoop125 claim/命令だけを追加した。
開発の通常commit/非破壊fast-forwardは許可範囲内。runtimeの無人GitHub write権限ではない。

## 完成した範囲

receiptと命令ID/対象PR/branch/HEAD/世代/元review/verificationの照合、
PRファイル全ページ取得の前後HEAD競合検査、正式command/claim/dispatch/job/timing/Session/
result PR/tree/allowlist/review要求の照合を補強した。既存BWJ-1〜3、DURABLE_REVIEW_V2、
正式schema-v3/V2 validatorを再利用した。新server/DB/queue/schedulerはない。

既存Workの同一carrier COMMENT形式をChat命令とJules結果検品に使う。
色別prefix/label/Jules lane/世代と、予約済みresult namespace/purposeは混ぜない。
BlueのWork検品→次task提案→正式global claim→一件Jules受理→結果Work検品を、
監督下で一度進めた。自動Actions→Work中継や無人連続運転の成功とは区別する。

Jules Loop125のraw PR227は意味的FAIL。PRは変更せず、217にGET readerの修正を保存した。
ASCII ID/safe branch/typed outputs/aware同一瞬間/validated updateTime/必要項目だけのprojection/
固定safe exception/no redirect/30秒1MiB/無retryを直接mock検証。
失敗時はsafeな段階名だけをUNKNOWN artifactに保存し、既存outputを上書きしない。
readback workflowはrequest追加commitとrun_attempt1だけ。一件既存Session GETの後継は作らない。
STATIC workflowに将来のjules-work/** base result PR入口を追加し、既存prepare-only CLIを再利用。
現在のsource認証接続はNOT_WIRED/UNKNOWNのままで、候補や実投稿権限は生成しない。

## LIVE台帳（max10、最終9使用）

| 回 | 操作 | terminal / 観測 |
| --- | --- | --- |
| 01 | Blue read-only起動 | PASS、receipt5938151988 |
| 02 | Blue独立検品 | FAIL、receipt5938273083。2件を修正 |
| 03 | Blue修正delta独立検品/次task提案 | PASS、receipt5938512018 |
| 04 | 正式J-BLUE Loop125一件投入 | 受理、Session12436642121757218108、結果PR227。原結果は意味的FAIL |
| 05 | Blueが既存Jules原結果を独立検品 | FAIL、receipt5944478821。完成Session sourceは別項目UNKNOWN |
| 06 | Yellow read-only接続/混線防止 | UNKNOWN、receipt5944505227。起動は確認、tree確認能力不足 |
| 07 | Green read-only接続/混線防止 | PASS、receipt5944510318 |
| 08 | Red read-only接続/混線防止 | PASS、receipt5944504857 |
| 09 | Blue最終修正delta独立検品 | PASS、receipt5944599531。source UNKNOWNとは別 |

外部Work命令1件/新Jules Session1件を1回。読取り・STATIC Actions・既存Session GETは観測。
新Sessionは1件、Work命令は8件。Work outcomeはPASS5/FAIL2/UNKNOWN1。
試験04の新Julesは受理済みだが、原コードFAIL・完成sourceUNKNOWNで正式採用しない。新Scheduled Task/設定変更は0件。曖昧送信の再送0件。
すべてのWork receiptは元reviewとcommand/PR/branch/HEAD/世代/terminalを照合済み。
Green/Yellowのnode ID表記も実reviewのnode_idと照合し、数値IDを捏造しない。
Yellow UNKNOWNはcontrollerがtreeを読めても独立検品PASSへ書き換えない。

## 検証

3370044のfull949（948成功/skip1）はexactHEAD Actions36910508737/job110531683234で確認。
568a30dのfull984（983成功/skip1）はActions36955285231/job110676786533の実logで確認。
診断修正後local full987（986成功/Windows-only skip1、failure/error0、47.665秒）、
compileall/diff check/mock正式閉ループが成功。保存後exactHEAD `931697eac8ea561a41589799187545eba5c0d62b` の
Actions36956416439/job110680237549も987件/skip1、failure/error0（55.260秒）で成功。
compileall/diff check/MOCK/preflight/artifact保存を実step/logで確認。
最終独立Work receipt5944599531は同じコードHEAD/treeでPASS。
保存12blobは内容一致、対象外626blobを維持。後続commitは証拠文書だけでコード同一。
[evidence Actions](evidence/blue-work-night-20261002/actions-final-readback.json)を参照。
修正前raw227の8 regression methodは9 assertion failures/5 errors（subcase込み）で再現。
過去のreceipt test harness errorは製品不具合と区別して保存してある。
コードの自己検品、Work独立検品、CIとLIVE source照合は別の証拠軸。

## UNKNOWN / BLOCKED

- 既存Session GET run36955281748/job110676775395は一回だけfailure。固定safe ValueErrorで停止し、
  rawレスポンスもartifactも得られず原因はUNKNOWN。完成sourceContext/createTime/unique PR outputを
  actor/title/URL/緑dispatchから補完しない。再実行はしていない。
- timestampのsubsecondと正式helperの秒精度には注意が必要。ただし今回失敗の実原因と推測しない。
  診断artifactの新実装はSTATICだけ検証し、新GETで原因を確認したとは報告しない。
- 原Jules結果の正式採用/次Session/連続運転はUNKNOWN source境界で停止。
  コピーした修正内容はControllerコードであり、raw PR227の正式PASS採用ではない。
- Actions生成COMMENT reviewが既存Workを起こせるかUNKNOWN。現workflowはread権限のみ。
  投稿権限やdefault/base workflow採用が必要な工程はBLOCKEDとして分離。Mergeも未承認。
- Yellowの完全tree証明はUNKNOWN。Windows専用テストはこの環境では未実行。
- ローカルexec transportが切れたため、その後はconnector保存と既存STATIC Actionsだけで検証。
  新しい権限・接続・課金設定を作って解決しない。

## 公式資料と先行方式

2026-10-02に[OpenAI Scheduled tasks](https://learn.chatgpt.com/docs/automations)を再取得。
一件で複数event trigger、event/time-based同時不可、GitHub review等で起動、
近接イベントは一実行にまとめる場合がある点を確認。既存4色の設定は変更せず兼用。
同ページには件数/時日rateの数値がなく、account固有の5件制限・当日の利用枠はUNKNOWN。
前日の別資料の数値を今回のaccount保証に昇格しない。ユーザー指定の5件制約を維持する。

[Jules Sessions](https://jules.google/docs/api/reference/sessions)の既存GET/sourceContext/createTime/
outputs照合と、[GitHub trigger制約](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
を再利用。GITHUB_TOKENのActions連鎖制約は外部Work到達保証とは別。
OpenCaraのevent振分け/PR直列化、HiveMind reviewerのPR入口、PR115のwake hint/正本分離は
前checkpointの先行方式を継続。丸ごとの導入や未承認サービスへの送信はない。

## 再開地点 / 最終検品

1. 最新217 HEAD/Actions、原227と実験側修正diff、下記証拠を読み直す。
2. completed Session GETのsafe診断を正規範囲で一回観測できる計画を固定する。
   秘密/設定/権限変更が必要ならその段階だけ保留。失敗requestやterminal命令は再送しない。
3. sourceが証明されてからBWJ-4の実result event→Actions→一件COMMENT→Workを検証する。
4. fresh正式claimの次task/一件cycle/小規模soakは残りLIVE budgetと承認範囲を固定して進める。
   今回のmax10は無期限・無限実行の許可ではない。
5. Mergeはユーザーの検品と個別判断。217のbaseは203開発枝であり、217 Mergeだけで
   mainへの自動workflow採用やreview投稿権限が得られるとは扱わない。

自律工程は現在28種類の調査・再現・修正・検証・保存・readbackとして整理し、Jules中規模Loop
18〜30回と同等の工数を証明したとはしない。実Jules投入はLoop125一回。
細かな工程確認は求めず、承認された安全範囲で継続した。
最終独立delta reviewと保存後Actionsの結果をPR217/checkpointに保存した。
9/10で停止。source認証/実Actions reviewの境界を推測で越えず、残枠消費のための任務は作らない。
ここまでコード・模擬回帰・独立検品・保存/readbackを終え、残りはLIVE source診断と自動bridge境界。

28工程の実施区分: navigation/正式仕様/4色探索/差分/公式資料、Blue read-only/独立検品、
再現/receipt修正/pagination修正/lineage修正/回帰/保存readback/delta独立PASS、
global全ledger/claim予約/work branch+命令/Session受理readback、結果差分/異常再現/reader修正/
STATIC Actions/既存GET一回failure/原結果Work検品/3色接続/診断修正/最終回帰/最終保存と独立検品。
工程数はこのまとまりの数で、実APIリクエスト数やJules工数換算ではない。

証拠: [night batch](BLUE_WORK_NIGHT_BATCH_20261002.md) /
[JSON・修正前log](evidence/blue-work-night-20261002/) /
[PR217](https://github.com/kamiyusense/multi-ai-council-phase0/pull/217) /
[raw PR227](https://github.com/kamiyusense/multi-ai-council-phase0/pull/227)。
