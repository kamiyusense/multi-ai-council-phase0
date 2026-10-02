# PR #217 自律開発バッチ — STATIC引き継ぎ

対象: `experiment/blue-work-autonomous-development` のみ。PR #203への直接変更はしない。
開始時の正本: PR #217 HEAD `66a726d6e9782ad358aa1ecd161e4fb60704be4e`、
PR #203 HEAD `66d366523ebe28726fcb36b0e5a45cb3368aa52d`。
2026-10-01の追加指示による独立実装。Jules投入・別AIへの委託は0件。

## 到達地点と限界

| 工程 | このバッチの到達地点 | 実運用の状態 |
| --- | --- | --- |
| BWJ-1/2 | 既存classifier/prepareを小さく4色共通化。Blue互換テストを維持 | 実送信なし |
| BWJ-3 | 正式な系譜・検品契約・次タスク候補まで模擬統合 | MOCKのみ |
| BWJ-4 | GitHub GET-onlyイベントpreflightを既存STATIC Actionsへ追加 | 本物のWork wake未実施 |
| BWJ-5 | 既存DURABLE_REVIEW_V2の捕捉された検品結果を照合・消費・復旧 | 独立AI検品は未実施 |
| BWJ-6 | 正式schema-v3 claim + 正式JULES_CHAT_SEMIAUTO_V2候補を検証 | NOT_RESERVED。branch/command未作成 |
| BWJ-7以降 | 未着手 | LIVE禁止境界を維持 |

これはM2/M3/LIVE完了の証拠ではない。`VERIFIED_SNAPSHOT` は捕捉データの照合成功で、
JSONの真正性を認証したという意味ではない。出力には常に `source_authentication=NOT_WIRED`、
送信・モデル実行・採用・claim予約のfalseフラグを残す。MOCKのPASSを独立検品済みに昇格しない。

## 再現して直した問題

独立検品の指摘は今回のユーザー指示で受領した。開始時点のPR #217 reviews、Conversation、
inline commentsは空だったため、外部検品記録を取得したとは主張しない。

既存コードはreceiptの形とcommand_idを確認するだけで、同じIDの別PR・別branch・別HEAD・
別世代でもNO_OPになった。元reviewがないreceiptも処理済み扱いだった。
8件の回帰テストで修正前FAILを保存した。

修正後はcommandとreceiptのrepository/PR/branch/expected HEAD/generationを照合する。
結果検品命令はread-onlyなのでbefore/after HEADも一致が必要。同じ命令のterminal receiptが
複数あればUNKNOWN。worker側は元のCOMMENT reviewを一意に読み戻してからreceiptを評価する。
UNKNOWN時は再実行・再送を許可しない。過去の世代欠落smoke記録は無関係なIDの再送防止にだけ使い、
世代や実行権限を補完しない。

保存前のfresh-readで別の修正commit `574f7da4b2c9c5619a2229f82ffca970f125c5f6` を検出した。
2ファイルの変更と新しい回帰テストを読み、その修正を保持して子commitへ統合する。
adapterでもreceiptには実際のsubmitted reviewが必要で、候補から元reviewを補完しない。
初期HEADを親にした上書きは行わない。

全320 branch（4ページ）と現行ledgerの実データを検査した結果、旧命令`015b`/`043b`、
Julesが長いsuffixを付けたLoop 080子branchを確認した。これらの数値番号も使用済みとして保護する。
新規claim/命令の正式schemaを緩めず、旧命令や子branchを新規dispatch権限には使わない。

実API応答の自己検品でcompare APIに `head_commit` がないことも確認した。
現在は `base_commit` / `merge_base_commit` / 全 `commits` / `total_commits` / 最後のSHAを使う。
URLの`...`は2個の厳密な40桁SHAのcompareだけに許可し、path traversalは引き続き拒否する。

## 4色Workの兼用

| Cloud Work | carrier snapshot | 命令prefix | Jules lane |
| --- | --- | --- | --- |
| 💙 Blue | #167 | `[CW_BLUE_V1]` | J-BLUE |
| 💛 Yellow | #165 | `[CW_YELLOW_V1]` | J-YELLOW |
| 💚 Green | #166 | `[CW_GREEN_V1]` | J-GREEN |
| ❤️ Red | #171 | `[CW_RED_V1]` | J-RED |

番号は復旧スナップショットで選択キーではない。全OPEN PRを取得し、該当labelがちょうど1件で、
PR body・branch・protocol・worker-state・prefixが一致することを確認する。
今回の読取りで4色ともactive_generation=1。今後は必ずGitHubから読み直す。

Chat用とJules用は同じcarrierのCOMMENT review形式を使う。
`<color>-jules-result-pr<PR>-<HEAD>` はread-only検品だけの予約済み命令namespace。
他色の予約IDをChat命令として扱わない。Chat命令のtaskを結果検品taskへ書き換えない。
Work世代とJules global Loop番号は別の制御面であり、相互流用しない。
既存4タスクの設定変更・タスク追加・carrier投稿は一切行っていない。

## 実装ファイル

- `cloud_work_lanes.py`: 色・prefix・Jules laneの小さな共通定義。
- `blue_jules_result_event.py` / `blue_work_wake_prepare.py`: BWJ-1/2の共通関数とBlue互換入口。
- `blue_work_reconcile_prepare.py`: receiptの厳密照合、4色worker preflight、既存review要求。
- `github_readonly.py`: GETだけのtransport、Link全ページ、件数・重複・上限・blob SHA・tree mode検査。
- `cloud_work_snapshot.py`: 全carrier探索とprotocol/state照合、前後readbackによる取得中の競合検知。
- `github_jules_source.py`: current main workflowから正式Jules carrierを発見、全claim/command/branch取得。
- `loop_id_claim.py`: carrier側の正式validatorをそのまま再利用。
- `jules_semiauto_request_v2.py`: carrier側の正式V2 validatorを別名でそのまま再利用。
  実験枝の古いorigin付きV2利用を壊す置換はしていない。取得blob SHAはsource-readbackに保存。
- `jules_result_lineage.py`: schema-v3 claim→命令追加commit→1回のdispatch→job/log→Session→PR→祖先照合。
- `work_result_review.py`: paths/regular-file mode/HEAD/tree/tests/negative evidence、review owner/世代/相関の照合。
  意味的判断は独立reviewerの仕事。greenだけからPASSを生成しない。
- `next_jules_prepare.py`: 全色共通のglobal番号候補、Task Prompt骨格、正式validator、期限・衝突再照合。
  claim内のCLAIMEDは予約後の正式形式を示す候補データ。外側のNOT_RESERVEDが現在の事実。
- `work_closed_loop_prepare.py` / `work_event_prepare_cli.py`: 1回だけのprepare-only統合とcreate-only成果物。
- `.github/workflows/blue-work-reconcile-static.yml`: 既存の実験専用STATIC Actionsに模擬統合、GET-only
  PRイベントpreflight、7日保持のGitHub artifactを追加。read permissionsのみ。send modeなし。
- `tests/test_blue_receipt_binding.py`、`test_github_readonly.py`、`test_cloud_work_snapshot.py`、
  `test_github_jules_source.py`、`test_work_closed_loop_prepare.py`、`test_work_event_prepare_cli.py`、
  `closed_loop_fixtures.py`、`fixtures/work_closed_loop/input.json`: 回帰・統合・競合・復旧テスト。
- この文書、HANDOVER_CURRENT、Blueロードマップと `docs/evidence/blue-work-batch-20261001/`。

## 公式仕様と先行実装を読み直した結果

2026-10-01時点の公式資料:

- [OpenAI Scheduled tasks](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt):
  Free/Go 3、Plus 5、Business/Edu 10、Pro/Enterprise 15のactive上限。
  event-triggeredは全イベントタスク合計30回/時、720回/日。複数イベントがまとめられる場合がある。
  使用量はplan/workspaceに依存する。利用中accountのplan/configは今回調査していない。
- [OpenAI Automations](https://learn.chatgpt.com/docs/automations): 1タスクで複数event triggerを使用可能。
  eventとtime-based scheduleは同一タスクに併用できない。既存4色の1命令形式に2つのpurposeを載せる
  今回の準備は、追加Scheduled Taskを必要としない。
- [GitHub workflow triggering](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow):
  GITHUB_TOKEN発生イベントは通常新Actionsを起動しない。dispatchと一部PR approval-required例外はある。
  これは外部Cloud Work webhook受信の保証ではない。Actions生成COMMENT reviewが既存Workを起こせるかはUNKNOWN。
- [GitHub pagination](https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api):
  Linkのnextを最後まで辿る。多くの一覧はper_page最大100。
- [GitHub compare](https://docs.github.com/en/rest/commits/commits#compare-two-commits):
  paginationなしは250 commits上限。compareのfilesは完全なPR diff代替にしない。
- [PR files](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files): 最大3000 files。
  count・tree modeと照合し、上限に到達した取得はUNKNOWNとする。
- [Jules Session](https://jules.google/docs/api/reference/sessions): sourceContext、createTime、完成時の
  outputs.pullRequest.urlでSessionと結果PRを照合する。API keyの新規取得・表示・変更はしていない。

[OpenCara](https://github.com/OpenCara/OpenCara)のevent/actionの事前振分けとPR単位直列化、
[HiveMind Actions reviewer](https://github.com/BUZASLAN128/HiveMind-Actions/blob/main/.github/workflows/agent-reviewer.yml)
のPRイベント入口、[PR #115](https://github.com/kamiyusense/multi-ai-council-phase0/pull/115)の
「通知はwake hint、GitHubのdurable状態が正本」を参照した。外部実装のコード・fallback・auto-merge・
actorだけの信頼判定・AI実行は導入しない。新Webhook server、DB、queue、schedulerも追加しない。

## 検証と証拠

最終件数と実際のcommit/Actionsは [checkpoint](evidence/blue-work-batch-20261001/checkpoint.json) と
PR #217 bodyの保存後readbackを正本とする。

実装commit: [`fb67ce259e20d1c9047ecd77a93958d3ce018084`](https://github.com/kamiyusense/multi-ai-council-phase0/commit/fb67ce259e20d1c9047ecd77a93958d3ce018084)。
full suiteは938件（成功937、Windows-only skip 1、failure/error 0）、重点84件すべて成功。
同じHEADの [PR Actions](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/36870292540) と
[push Actions](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/36870285179) のjob/logとartifactを
読み戻し、両方938件・成功937・skip 1を確認した。
[Actions readback](evidence/blue-work-batch-20261001/actions-readback.json)にjob ID・step・artifact URLを保存。
公開対象34 blob一致、対象外583 blob維持。保存後の文書更新commitはこの実装commitの子で、
最新HEADはPR #217から取得する。実装コードとfixtureは文書更新で変更しない。

- 修正前: `receipt-before.txt` の8件すべてFAIL（問題の再現）。
- 最終: `unittest.txt` のfull command-bus suite、`focused.txt` の重点検証。
- `source-readback.json`: 仕様blob SHA、開始HEAD、carrier HEAD/世代。
- `formal-static-cycle.json`: 全てMOCK、正式次タスク候補NOT_RESERVED。
- GitHub artifact: 同じexact experiment HEADのmock/preflight成果物。
- compileall、git diff --check、公開対象path whitelistとremote blob SHA照合。

再実行:

```bash
python -m unittest discover -s automation/command_bus/tests -t . -v
python -m compileall -q automation/command_bus
git diff --check
python -m automation.command_bus.work_event_prepare_cli \
  --snapshot automation/command_bus/tests/fixtures/work_closed_loop/input.json \
  --now 2026-10-01T12:00:00Z --output /tmp/formal-static-cycle-new.json
```

出力先は未存在のファイルを指定する。既存成果物を上書きしない。
実験HEADにはroot `src/` / `tests/` が存在しないため、そこを対象とするsuiteは実行していない。
既存のcontrol-plane exact-head validationと同じcommand-bus suiteを実行する。

## 自律工程の数え方

26工程を次のまとまりとして記録する。これは実際のJules Loop投入件数でも、中規模Loop工数の
客観的換算でもない。1人の実装担当による安全な開発・検証・保存工程であり、追加の人間指示は0回。

1. mainナビゲーション6文書のfresh-read
2. Jules正式carrier・命令・claim仕様のfresh-read
3. 4色protocol/state・carrierのfresh-read
4. PR #203/#217差分・Actions・検品記録の確認
5. receipt問題8件のFAIL再現
6. receipt/command/対象/HEAD/世代修正
7. Blue互換維持と最小4色共通化
8. GET-only URL/redirect/credential境界
9. Link全ページとtotal/duplicate/cap検査
10. carrier一意探索・protocol/state照合
11. 取得中のcarrier/record/result競合検査
12. current workflowからJules carrier発見
13. global claim/command/work branch全件取得
14. 正式V2/schema-v3 validator再利用
15. dispatch/job/log/Session/result系譜照合
16. 実compare API自己検品と修正
17. BWJ-5 captured独立review契約照合
18. reviewer競合・消費receipt復旧
19. BWJ-6次task候補・期限・番号衝突再照合
20. 4色Chat/result混線テスト
21. 1ターン模擬閉ループ・異常系・回帰
22. STATIC Actionsへのprepare-only統合
23. roadmap/handover/証拠・通常commit保存
24. 非破壊fast-forward更新・GitHub/Actions readback
25. 保存前に検出した同一枝の別修正を保持して統合・再検証
26. 全branch/ledger実データの旧命令・子branchを再現して番号保護を修正

## 次の安全作業と停止境界

まずPR #217の最新HEADで別担当による独立検品を行う。特にreceipt照合、正式validatorとのdrift、
source認証とsnapshot照合の区別、取得の一貫性、global予約競合を確認する。
このバッチ内の自己検品を独立検品済みとはしない。

その後、既存Jules sessionの認証GETとGitHub dispatch job-log読取りを、許可された既存正規ツールに
接続する設計/STATICテストが次の安全作業。現状はそれを代替する架空のattestationを作らずUNKNOWN。
sourceが認証できるまで実GitHub eventからwake候補を出さない。

LIVE承認が必要な事項:

- BWJ-4: 1回だけ、使い捨て結果を既存Blue carrierのCOMMENT reviewで通知し、read-only Workを起動して
  元命令と完全に一致するterminal receiptを確認する。投稿内容・対象・世代・停止条件を事前固定する。
- 既存Sessionの認証GET能力が不足する場合は正規の接続/権限判断。ただし新secret作成を自動で行わない。
- BWJ-5の実Work検品、BWJ-6のglobal claim予約/branch/命令保存、BWJ-7の新LIVE Jules投入・採用は
  各境界の明示承認が必要。今回その操作は実施しない。
- Merge、main直接write、force、課金・権限・設定変更はこの成果で許可されない。

静的な有益作業を終え、残りがsource認証接続・独立検品・LIVE transport証明の境界となった時点で停止する。
実装量/使用量を増やすための追加機構は作らない。
