# Blue Jules × Work 自律開発・隔離実験

2026-10-01 / STATIC only / independent review pending / LIVE not run

## 現在地と引き継ぎ入口

この実験は PR #203 の `66d366523ebe28726fcb36b0e5a45cb3368aa52d`
（tree `08e5d1d8af9ede9677f34ab0dbe5c1f6f6d2a54d`）から分離した。
対象は `experiment/blue-work-autonomous-development`、統合先は
`feature/blue-work-jules-webhook-loop`。main・PR203・carrier・Work設定は変更しない。
次の担当はこの文書、隣の正式ロードマップ、実験Draft PRの差分と
`docs/evidence/blue-work-autonomous-20261001/` を読み、すべて最新状態で照合する。
固定SHAは開始地点の証拠であって、将来の実行対象ではない。

ユーザーからの追加指示・他AIへの委託なしで、最新状態確認→公式/先行実装調査→
隔離ブランチ作成→実装計画→実装→異常系検証→自己修正→全体検証→保存/読戻しを進める。
保存・GitHub Actionsの結果はDraft PR本文に追記して最終確認する。

## 調査結果（確認済みとUNKNOWNを分離）

| 項目 | 確認結果 | 一次資料・確認箇所 |
| --- | --- | --- |
| 1タスクの複数イベント | 公式に対応。時刻起動との併用は不可 | [Scheduled tasks](https://learn.chatgpt.com/docs/automations) の Trigger tasks from app events |
| GitHubイベント | PR activityをレビュー等で絞り込める | 同上 Supported event triggers |
| 同一タスクで2種類の仕事 | 同じ既存レビュー形式でtaskを分ける設計は可能と判断。実際の保存済みWork promptの解釈・同時実行は未検証 | 公式はtriggerとsaved promptの役割を説明。個別の兼用動作保証はUNKNOWN |
| 最大5件 | ユーザーの環境条件として維持。今回の公式ページに数値の裏付けを発見できずUNKNOWN | 設定変更・追加作成はしない |
| イベント回数/課金/同時実行上限 | 本方式の具体的な数値はUNKNOWN。無制限・追加消費なしとはしない | 公式Scheduled tasks・[Pricing](https://learn.chatgpt.com/docs/pricing)。後者はWork/Codexの共有利用量を説明 |
| reviewの作成 | COMMENTを指定するREST操作があり、Pull requests write権限が必要 | [Reviews API](https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request) のpermissions/body parameters |
| Actionsのイベント連鎖 | GITHUB_TOKEN由来のイベントが次のActionsを起動することには制約がある。現在の例外も確認。レビュー投稿で外部Workが起動するかとは別問題 | [Triggering a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow) の Triggering a workflow from a workflow |
| Actions review → Work | 本アカウントでの実起動、bot author/filter、利用可能権限はUNKNOWN | 禁止されたLIVE試験を実施していない |
| 遅延・欠落・重複 | GitHubの記録を読み直す設計を採用。Workがイベントを必ず1対1で届ける保証は確認できない | [PR115](https://github.com/kamiyusense/multi-ai-council-phase0/pull/115) はSTATIC研究のみ。公式資料からcoalescingの現在の保証も確認不能 |

先行実装も直接読んだ。

- [OpenCara README](https://github.com/OpenCara/OpenCara): event/actionごとの事前絞り込み、初回と追従レビューの分離、PR単位の直列化が参考になる。
- [HiveMind Actions reviewer](https://github.com/BUZASLAN128/HiveMind-Actions/blob/825dba92b39e4004b0fc4f74e674334f8460ea96/.github/workflows/agent-reviewer.yml): opened/synchronizeで検品を起動し、信頼判定と検品処理を分ける構造を確認。MITを確認した。
- PR115: 起動通知よりdurable command/receiptの読戻しを優先する考え方を再利用。

上流コードの丸ごと導入・外部サービスの新設は行わない。今回の実装はリポジトリ内の
BWJ-1/2とdurable reviewer契約を組み合わせたもの。上流からコードを転記していない。
上流のretry/fallback/自動Merge・無制限反復は導入しない。

## 既存4色Workの兼用方式

窓口、ラベル、command prefix、generation、terminal receiptを維持する。
新しいScheduled Taskは0件。初期実装はBlueのみ。ほかの色への実装展開は未実施。

| 入り口 | 同じ窓口へ渡す仕事 | 判別と権限 |
| --- | --- | --- |
| Chat → 既存carrierのCOMMENT review | 既存のbounded task | 元のtask/allowed_pathsを保存。実験のpreflightは実行しない |
| Jules result PR → 小さなActions中継 → 同carrierのCOMMENT review | 結果の読み取り・検品提案 | `blue-jules-result-pr<PR>-<full SHA>`。BWJ-2の読み取り専用task/verificationに固定 |
| Work → carrier Conversation comment | 結果・terminal receipt | command reviewに変換しない。次の起動には使わない |

今回のActionsは上記中継の**オフライン準備工程のみ**。commit済みの人工データを
読み、候補をローカルファイルへ出す。実際のresultイベントを取得/認証する部分、
GitHub reviewの投稿機能、Jules起動機能は存在しない。
本物のtaskはtask内容に沿って動けるかを承認済みの試験で後から確かめる必要がある。

## 実装と証明の範囲

- `blue_work_reconcile_prepare.py`: 現在のcarrier/state/protocol照合、完全なページ読取の要求、BWJ-1/2の合成、current result PR照合、worker preflight、既存durable review requestの準備。
- `blue_work_wake_prepare.py`: 読取専用taskとverificationを定数として再利用。既存の出力内容は維持。
- `blue_work_reconcile_cli.py`: オフライン入力からPREPARE_ONLYの候補を生成。明示時刻を要求し、出力は新規作成のみ。送信モードはない。
- `blue-work-reconcile-static.yml`: 実験branchのpush/実験PRで既存+新規テスト、compile、人工データの再生を行う。contents readのみ。秘密情報やWork/Jules実行機能を参照しない。
- テスト2ファイルと人工fixture: 混線、重複、古いHEAD、期限、世代、欠損、二重JSONキー、terminal、旧形式記録との共存を検証する。

重要な発見: 現在のBlue carrierには世代番号追加前の古いsmoke review/receiptが残る。
その**読み取れるIDだけ**は再送防止のため確認するが、世代や実行許可を補完しない。
対象コマンドそのものが古い/不完全ならUNKNOWN。無関係な旧Chat記録は新しいJules結果の
処理を妨げない。新しいreserved result記録の欠損・矛盾はUNKNOWNで止める。

`PREPARED`/`VALIDATED`は人工/外部提供snapshotの整合性確認結果であり、
署名・正規のJules claim/session/result系譜の証明、排他的な実行予約、独立検品PASS、
LIVE起動許可ではない。`records_complete=true`も入力契約であり、この関数自身が
ページ取得を証明するわけではない。carrierの一意な全件探索と正規のlineage確認は
将来の読み取りアダプターの責務で、現在はNOT_WIRED。

同時に2回prepareを呼ぶと同じ候補が返る。関数は副作用を持たず予約をしない。
将来の投稿ではcarrier単位の直列化、投稿直前の全記録再読取、成功不明writeの
読戻しが必要。レビューAPIにexactly-onceの保証を推測してはいけない。
古いcarrier SHAを実際のtarget HEADと比較しない。

## 更新した実行ロードマップ

| 段階 | 今回の結果 | 次の境界 |
| --- | --- | --- |
| BWJ-1〜3 | PR203の既存実装を再利用。既存の全体テスト再実行 | 人工データ成功はLIVE成功ではない |
| BWJ-4 STATIC準備 | snapshot照合、candidate作成、offline Actions replay、worker preflightを実装 | 認証済みlineage/読み取りアダプター、直列化された投稿、read-only実起動試験は未実装/未実施 |
| BWJ-5 STATIC準備の一部 | 既存DURABLE_REVIEW_V2 requestを生成しvalidatorで検証 | 実際の意味・差分・テストの独立検品と結果保存は未実施 |
| BWJ-6 | 未実装/BLOCKED | PR203のrequest helperはcurrent carrierと同じ契約ではない。schema-v3 global claimとwork_branchを使う現在のvalidatorに接続する必要がある |
| BWJ-7以降 | 未実施 | 先に1回の読取専用Work実起動を証明する |

BWJ-6のために第二のLoop番号管理や独自claim engineは作らない。
現在のcarrierの`loop_id_claim.py`/`jules_api_request.py`を正本として、
既存claim/command routeへの最小接続を後工程で独立検品する。
この実験ではclaimファイルや実行用commandを一切投稿しない。

## 検証と再開

既存全体テスト、35件の新規テスト、compile、diff、fixture CLIの結果は
`docs/evidence/blue-work-autonomous-20261001/checkpoint.json` と `unittest.txt` を参照。
最初の不完全な検証環境では既存テストに8件の問題が出たが、必要なcompose fixtureが
不足していたのが原因。取得・正確なblob照合後、既存817件は816成功/1skipとなった。
新規テスト初回の1エラーは欠損ケースを作るテスト補助の参照ミスで、修正後成功。
失敗を隠したり既存コードを無関係に変更したりしていない。

再現コマンド（開発担当向け）:

```sh
python -m unittest discover -s automation/command_bus/tests -t . -v
python -m compileall -q automation/command_bus
python -m automation.command_bus.blue_work_reconcile_cli automation/command_bus/tests/fixtures/blue_work_reconcile/input.json --now 2026-10-01T12:00:00Z
git diff --check
```

未完了: 独立検品、production lineage/authenticated readback、投稿時の競合保護、
本物のActions review→Work起動、Work promptの兼用確認、BWJ6接続、失敗/no-changeで
PR eventが出ない場合の復旧。新DB/常駐pollerは実測で必要になるまで追加しない。

停止理由: 今回有用なSTATIC candidate/replayと既存review契約の接続を完了した。
次は独立検品と実際のtransport境界。UNKNOWNを埋めるためにLIVEを起動したり、
未検証の投稿処理まで作り込んだりしない。

LIVE試験に必要な承認（今回は要求/実行しない）:

1. 独立検品後、必要なら実装PRの統合を別途承認する。
2. disposable resultで1件のcarrier COMMENT reviewと1回のBlue Work起動を承認する。
   読取専用・Jules起動0・target変更0・terminal receiptを読み戻してSTOPする。
3. 投稿権限・資格情報の変更が必要なら、その具体的な変更を別途承認する。
4. 次のJules実起動や閉ループ1周は、上記とは別の承認を必要とする。

retry=0 / fallback=disabled / Merge禁止 / default直接write禁止 /
force push・履歴変更・branch削除・追加課金・未承認LIVE禁止。
