# BWJ-4 follow-up: STATIC candidate, no new LIVE approval

## 現在地点

BWJ-0–3 / M1 はSTATIC完成。BWJ-5/6は既存のSTATIC契約を再利用。
BWJ-4 / M2 の本物のwake証明は未達。旧proofは **FAIL / activation consumed**。
修正PR #282はMerge済み。今回、新しいLIVE・carrier review・Work起動・receipt投稿は0。

## 旧FAILを保持する

- proof `blue-bwj4-20261002T212217Z-transport-proof-01`
- [run 37147398998](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/37147398998)
  / job 111274071729 / attempt 1 / main HEAD `5faf37def13dc6678e0f8cba7396f06183d2c048`
- GitHub側の結論はfailure。「Fresh gates and secret-free ATTEMPTING record」で
  `ValueError: GitHub read scope violation`。ATTEMPTING upload / POST工程はskipped。
- fresh artifact集合は0、carrier内の旧proof review/terminal receiptは0。
  それでもactivationは1回消費済み。再実行・再送・別token補完は不可。
- [旧checkpoint](https://github.com/kamiyusense/multi-ai-council-phase0/pull/282#issuecomment-5972682210)
  は訂正・削除せず保持する。Work実wakeは証明されていない。

## #282の統合検品

- starting main `915fb588279722bcf6d71b93805b1dd788b3bed0`, tree `9ae9c21c483a7569b7a7a7b3878e5d3645ff37ba`
- inspected #282 HEAD `aae789411bf2c10288f2d45e3e011c47a9a5b988`, 変更2ファイル
- Merge `aebae14695cfaaf1dc8bcc2ec35faca9c898fd48`, tree `e331efa33dcc2903c2a21cb5f5a260aa6248d297`
- reader blob `df947140bc526d01405d34b8df510424660cc39f`, test blob `5adfcba5e84d8694c3bdd73f17894c0c269aea41`
- main進行はSignal/Relayの独立変更。#282対象/Blue workflow/authに競合なし。
- exact-head CI 37147611078 / job 111274681870: 全体1450 / skip1、重点42成功。
- artifact 11282786738 SHA-256 `95d71318fb2c884045bdece2c2a064b3960a90d7aee291280595eec17daf690a`
- fresh mainと#282を組み合わせたローカル回帰1493 / skip1 / failure,error0、重点64成功。
  Windows専用ACL初期化試験のみskip。compileall / diff --check成功。

正規numeric paginationはrepository ID **1378815294だけ**許可。
owner/name形式とrepo-relative endpointを比較し、endpoint/filter/host/scheme/encoded path/
credentials/redirectの既存拒否を維持。実際のLink header生bytesは旧runに残っていないためUNKNOWN。
fixtureは診断された形を再現する合成例であり、実headerの原本とは呼ばない。
既存SnapshotReaderで、旧guardは同じscope violation、新guardは完全なlane snapshotと最終再読まで進む。

## 新候補の最小構造

候補ファイル: `BLUE_BWJ4_FOLLOWUP_AUTHORIZATION_CANDIDATE.json`。
proof候補 `blue-bwj4-20261003T194515Z-transport-proof-01`, **proof_generation=2**。
worker_generationは既存 **1** のまま。proof世代とworker世代は別物。

- approved=false / expiry=null。これは承認でもclaim予約でもない。
- 現行workflowは引き続き旧authorizationファイルだけを読む。候補を読み込む経路は追加しない。
- generation 1の「全履歴がcurrent run 1件だけ」gateは維持。旧proofの再dispatchは拒否される。
- generation 2は別の明示承認後だけ利用可能。全履歴は厳密に旧FAIL1件+新current run1件。
- old run/head/attempt/repo/actor/workflow blob、旧authorizationのproof ID、job/step結果、artifact集合を
  fresh GETで確認する。unknown/cancelled/rerun/余計なrun/旧POST実行/旧artifact追加ならSTOP。
- old proofのreview/receiptが予期せず存在した場合もSTOP。
- 新runでPOSTを試みる前にcomplete historyを再確認する。artifact保持期限切れを再試行理由にしない。
- target #172 / carrier #167 / worker generation 1、14-field commandとreceiptの既存bindingを再利用。
- 新しい送信method、provider route、workflow、権限は追加しない。

## 次の承認後に必要なactivation package

現段階はNOT_APPROVED。以下のslotは承認後・実行直前にfresh確定する。過去mainを入力に使わない。

| Slot / gate | 必須条件 |
|---|---|
| authorization | 通常PRで候補を現行authorizationへ反映、approved=true、明示承認時刻から6時間以内のexpiry |
| reviewed main / tree | その時点のcurrent main。今回のDraftを含む必要変更のMergeを人間が承認 |
| workflow blob | current main上の `.github/workflows/blue-work-wake-proof.yml` のblob |
| carrier | unique OPEN cloud-blueをfresh発見、protocol/head/tree/genを確認 |
| target | #172 branch/head/treeが候補の封印値と一致、OPEN/unmerged |
| history | 旧FAILは消費済みとして保持、新proofのrun/review/receiptは0。既存runをrerunしない |
| workflow dispatch | main、承認actor、new proof ID、fresh approved_main/workflow_blob、attempt=1 |
| before POST | secret-free ATTEMPTINGをdurable upload、そのartifact ID/digest/run/head/jobをfresh GET |
| POST | COMMENT 1件以下、exact carrier commit/body、final reread fence、結果不明でも再送なし |
| Work | logical wake1以下、wake通知をauthorityにせずfresh GitHub reconciliation |
| receipt | Work自身が1件以下。trigger review / command / worker generation / carrier / target HEAD/tree binding |
| PASS | review・意図したWork origin・on-time terminal receipt・target不変を独立に直接確認 |
| UNKNOWN / FAIL | receipt欠落/起動不明/曖昧writeはUNKNOWN、契約違反はFAIL、いずれもSTOP |

予算候補: activation1 / workflow run1 / COMMENT review1 / logical Blue wake1 / terminal receipt1。
provider CREATE/GET/model、Jules CREATE/GET/submit、claim、次command、target変更、adoption、retryは全て0。
fallback=disabled。既存job-local pull-requests:writeだけを再利用し、権限差分0。
target/result PRのコードは実行しない。新Session source認証、BWJ-5 LIVE、BWJ-7は対象外。

## STATIC検証と止まる地点

ローカル: focused 76件 / full command_bus 1505件、skip1、failure/error0。
compileall / diff --check成功。新規12件はfull回帰にも含む。
GitHub exact-head CI / artifact / 最終HEADは候補PR checkpointで追記する。

fixture/mockだけで canonical Link → fresh lane snapshot → history fence → fake durable attempt → fake review
readback → simulated receipt bindingを検証。missing receipt、duplicate terminal、late receipt、stale target/
generation、ambiguous POST/no resendは既存focused suiteを再利用。provider/実POST/実Work/claimは0。
receipt bindingのSTATIC成功は本物のWork originを証明しない。

今回の候補PRを勝手にMergeしない。新LIVEをdispatchしない。
次の人間判断は「この候補の検品後Mergeと、明示した新proofのtransport-only一回予算を承認するか」。
承認後は期限を通常PRでfresh設定し、改めて検品・Merge・preflightが必要。
rollbackは起動しないこと。必要なら通常PRでapprovalを閉じる。履歴/branch/証拠は削除しない。
