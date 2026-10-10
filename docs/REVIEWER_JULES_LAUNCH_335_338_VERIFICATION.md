# Reviewer / Jules 実起動の独立検証 — Issues 335 / 338

Date: 2026-10-10 JST. Fresh main `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0` から独立branch
`codex/reviewer-jules-launch-evidence-335-338` へ保存する。PR #320と既存実行レーンは変更しない。
新しいJules起動・Claude/Jules LIVE再試行・ラベル変更は全部0。

## 結論と確認範囲

**Issue 335：Jules実起動 PASS。** 過去の成功宣言やラベル存在だけではなく、
fresh REST GETで公式Julesアプリの開始/完成通知、同じtaskを持つPR、
Jules botのcommit、exact-head CI実log/artifact、Reviewer receiptを別々に確認した。

**Issue 338：GitHub issue-label経由の未起動 PASS。** OPEN、labels空、comments 0。
events 4 / timeline 6を全ページ読んでもlabeled/unlabeled履歴なし。
全repository PR 329件をLink paginationで取得し、Issue 338作成後の3件に
そのIssueを開始したJules task/result PRは見つからない。PR 340は準備用STATIC
開発PRで、Issueへの言及を起動証拠にしない。Jules内部の全session不存在、
現在のprovider terminal stateはUNKNOWN。有限のGitHub記録から世界全体の不在を
推測しない。このbatchではprovider CLI/APIへの問い合わせもしていない。

## Issue 335 の証拠連鎖

| UTC | GitHub独立readback | ID / binding |
|---|---|---|
| 2026-10-08 17:53:06 | jules label / actor kamiyusense | labeled event 32812577102 |
| 17:53:10 | [Jules開始通知](https://github.com/kamiyusense/multi-ai-council-phase0/issues/335#issuecomment-6065845035) | App 842251 / google-labs-jules、task 5755515948434524038 |
| 18:01:00 | [Jules commit](https://github.com/kamiyusense/multi-ai-council-phase0/commit/2ce8caabb63df36c8fb7be1057344dceb7f732ab) | head 2ce8caabb63df36c8fb7be1057344dceb7f732ab |
| 18:01:03 | [PR 337](https://github.com/kamiyusense/multi-ai-council-phase0/pull/337) | jules-5755515948434524038-ead860a1、Fixes 335、同task URL |
| 18:01:06 | [Jules完成通知](https://github.com/kamiyusense/multi-ai-council-phase0/issues/335#issuecomment-6065977783) | App 842251、PR 337への直接link |
| 18:01:07 | [exact-head Blue CI](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/37821036202) | SUCCESS、head 2ce8caa、job 113461812043 |
| 18:04:38 | [Reviewer final receipt](https://github.com/kamiyusense/multi-ai-council-phase0/issues/335#issuecomment-6066036644) | Claude App 1236702、FINAL/PASS/ADOPT_RECORDED、next issue 338 |

ラベル後4秒で公式botが応答し、その後実コード変更を出したので、単なる受付ラベルを
実起動と読み替えていない。PRの表示作者はkamiyusenseであってJules botではない。
作者名1つに依存せず、公式Appによるコメント、task URL/branch、commit identity、
resultの内容とCIで照合した。commitはunsigned。暗号署名済みとは主張しない。

GitHub App label routeはActionsのdispatch routeとは別や。ラベル時刻周辺の
5 ActionsにJules dispatch jobが無いことを起動失敗とは扱わない。Blue CIは
成果テストの証拠で、Jules新規開始そのものの証拠は公式App通知と成果の連鎖や。
古いlegacy combined commit statusはpending/statuses 0だが、実check-runと
exact-head Blue workflowのSUCCESSを使用している。

## 成果とReviewer記録の独立検品

変更は許可されたtest_claude_jules_live_adapter.pyの1件だけ（+6/-2）。
python3 literal 2箇所はsys.executableへ置換され、import sysと回帰テスト1件が追加。
変更前76個の既存assertionはAST比較で全部保持、変更後77個。
同じPR HEADのisolated worktreeで18 tests OKを今回独立再実行した（STATIC、model 0）。

Reviewer v2 strict parserで実comment bodyからreceiptを復元した。head
`2ce8caabb63df36c8fb7be1057344dceb7f732ab`、tree
`01fb0ddf8c237d2978c169fce5abd1d59905f4f4`、expected base/commit parent
`8fbbef941732219e4ad43ce0d32e22922275d040`が一致。
これはReviewerのterminal receiptであり、provider sessionの現在のterminal応答ではない。

当時のCIの全14 step、実job logの1,912 tests OK (skip1)を確認し、artifact
11568963154を実downloadした。SHA-256
`fd161f8bde64664cba0e3676f20854d931361c0647f61a15f5e9cc2518b1039b`
はGitHub digestと一致。以前の「PASSだった」という記述だけに依存していない。
PR 337は現在MERGED、merged_at 2026-10-08T20:36:44Z。Issue 335はCLOSED。
これは過去の状態の読取で、今回のmerge/close操作は0。

## Windows文字コード

前回scratchのgh auth status実行を無断再実行していない。そこにあったcp932 decode
症状と同じ弱点（subprocess text=Trueでplatform localeへ依存）が、既存の
claude_jules_cli_transport.run_readにもあったので、専用branchでSTATIC修正した。

出力をUTF-8/strictで明示decodeする。不正byteは文字の置換でsession identityを
変えずFAILEDにし、decode errorは再試行しない。既存read allowlist、credential
selector除外、ネットワーク失敗時のbounded read retryは維持。dispatch/login/message
経路やprovider状態・設定は変更していない。

新規4回帰はWindows cp932 / Linux UTF-8 defaultを模擬し、日本語・emojiのstdout/
stderr、実fake Python child、不正UTF-8のtyped failureと再送0、非ASCII errorの
失敗保持を検証。Windows-native実機の再テストはNOT_RUNと区別する。

今回の重点95件、full command-bus 2,038件 (skip1)、compileall、diff/secret scan PASS。
offline snapshot再生と、ラベルのみ/別App/別task/別head/338のlabel/不完全ページの
6 negative casesもPASS。再生scriptはnetwork/provider/write口を持たない。

## 保存と残る境界

証拠はREST GETから必要部分を抽出したprojectionや。raw HTTP byte-exactと偽らず、
comment bodyは元のUTF-8内容とSHA-256を保存してる。
公開用の歴史job logは行末空白だけ除いた派生物で、元sanitized logのhashと
公開copyのhashを区別した。元sanitized bytesはlocal evidence bundleへそのまま保管する。最終commit/保存PR/exact-head CIは
publication後のfinal checkpointとlocal reportへ記載し、self-referential hashを捏造しない。

ラベル変更、新規Jules起動、Claude/Jules再LIVE、過去scratch再実行、main/PR320/
実行レーン変更、Merge/force/破壊的cleanup、API key/課金/Secret/permissions変更0。
GitHubで観測できる起動証明にblockerは残っていない。provider内部stateの追加確認は
未実施でUNKNOWN。今回の独立Draft PRをmergeする判断は相棒に残る。
