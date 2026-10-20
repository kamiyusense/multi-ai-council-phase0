# 最終統合R3 — #247/#249検品・順序模擬・Cleanup計画 (2026-10-03 JST, docs only)

現在のmain（`2044412`）を正本とする新規docs-only文書。PR #238 の古い記述は自動的に事実へ昇格していない（§10）。
範囲: STATIC / read-only / mock / 使い捨てworktree。Merge、Ready化、Close、branch削除、force push、rebase、settings/権限/secrets変更、
LIVE（Jules/Claude/Work/provider/model）、Signal issuer再実行は一切していない。#247・Signal PR・Issue #33には書いていない。
読み取り時刻: 2026-10-02T17:58Z〜18:30Z（GitHub fresh readback）。

## 0. 指示文との差分（先に読む）

指示文の参考値は古かった。fresh readbackの結果:

| 項目 | 指示文の参考値 | 実際（GitHub） |
|---|---|---|
| current main | `a3dd5c8` | **`2044412`**（#247 のMerge commit、2026-10-02T17:49:18Z） |
| #247 | Draft / OPEN | **MERGED**（head `e20155c`、人間がMerge済み。指示文送信の約9分前） |
| #249 | ahead 1 / behind 0 | head `d0648c7`、**ahead 1 / behind 13**（mainが進んだため）。mergeable=clean |
| #237 / #4 / #240 | — | いずれも MERGED（#237=`03ee999`、#4=`a765e3f`、#240=`4ddb040`） |

このため「#247 → #249 / #249 → #247」の統合順は、実際には Order A（#247が先）が**既に現実になった**。
両順序は、#249 の元base `a3dd5c8` を起点に仮想再現して比較した（§6）。

## 1. fresh state

| 対象 | HEAD | 状態 |
|---|---|---|
| main | `2044412` | 直近: #247 → #246 → #245 → #248 → #240(`4ddb040`) → #4 → #237 → #235 |
| #248 Claude×Jules Auto Loop | merge `1dc02df`（head `0590d5f`） | **MERGED** |
| #245 / #246 | merge `ac76900` / `a3dd5c8` | **MERGED** |
| #247 Signal runtime binding | `e20155c` | **MERGED** |
| #249 Blue current-main integration | `d0648c7`（branch `blue/current-main-integration-v2`） | Draft・open・clean・95 files(全てA) |
| #238 前回checkpoint | `8dbb8f4` | Draft・open（APIのmergeable_stateはunknown。ユーザー報告はmergeable=false。baseが古い） |
| #203 / #217 / #220 / #236 | `66d3665` / `5d17df1` / `044389e` / `776d877` | 全てDraft・open・不変 |
| #239 | `582032b` | Draft・open（前回 f0f3a0a から更新） |
| #241 / #242 / #243 | `a678746` / `e2c9acb` / `5f04ba7` | open。#243 は Ready（jules-work baseのJules result PR） |
| Issue #33 | updated 2026-10-02T09:35Z | open、表示は「⚫ STOPPED、owner NONE、Loop UNKNOWN」 |
| open PR / branch / main workflow | 119 / 403 / 17 | 前回 115 / 355 / 10 |

## 2. PR #247 — 独立検品（既にMerge済みのためpost-merge検品）

判定: **`ALREADY_MERGED`（post-merge STATIC検品 = PASS）。** 評価は `READY_FOR_HUMAN_MERGE` 相当だったが、人間が先にMergeした。

- 変更: 8 files（code 4 + test 4）、`.github` 変更 **0**、Signal workflow・runtime state・Issue #33 への書込み **0**。
- target/work分離: `prepare_current_jules_semiauto_acquire` が `target_branch`（canonical、read-only）と `provider_starting_branch`（`work_branch`）を分離。Jules Sessionは `work_branch` 起点を要求、target PRは `target_branch` を要求（`...head branch mismatch` / `...branch mismatch` の2本のtest）。
- 契約: carrier `jules_api_request.validate_request` ＋ schema-v3 claim（`verify_command_claim(..., require_dispatchable_current=True)`）を要求。旧origin形は別関数 `prepare_jules_semiauto_acquire` に隔離され、**混ぜるとkeys mismatch**（`test_contracts_are_not_blended`）。
- 証明: provider readback候補に `github-branch:` と `jules-branch:` の2 proof refを追加。authenticatorは新形式で両方が**ちょうど1個**かつ値一致を要求、旧proofだけは旧規則でfail-closed維持。
- Actions: exact head `e20155c` の `Phase 0 loop status signal tests`（run `37040238978`）= **success**。全step success: focused tests / full command-bus / OAuth proxy+launcher / JSON schema parse / compile / diff check。権限は `contents: read` のみ、secret参照なし。
- **UNKNOWN**: Actions logの**テスト件数**とlog内容（LIVE/provider呼出しの有無をlogで確認）は、logの保存先ホストが本環境のegress policyで拒否され取得できなかった。回避していない。workflow定義上は読み取り専用でprovider呼出し能力なし。
- main上（Merge後）のSTATIC再確認: §7（#247を含む tree でfull suite OK）。

### SIGNAL_EXTERNAL_FINDING（記録のみ。修正はSignal担当）

1. 現行carrier経路 `prepare_adopted_current_semiauto_acquire` は、旧経路にあった `_validate_origin_correlation` を通らない（現行carrierのrequestにorigin項目が無く、origin identityはorigin-binding recordに置く設計のため）。同じclaim・同じSessionを2回acquireに通す**重複/再生**を名指しするtestは無い（owner event側の冪等性に依存。未確認）。severity: low / 要確認。
2. #236 は main に無いファイルを 6 件持つ（§12）。#240 とは別実装部分があり、Signal担当が採否を決める必要がある。

## 3. PR #249 — 独立再検品

判定: **`NEEDS_STATIC_FIX`（2点。修正patchを作成・検証済み。#249への書込みは自動安全判定で拒否されたため未適用）。**

確認できたこと（fresh）:
- head `d0648c7`、base = `a3dd5c8`（現mainの祖先）、ahead 1 / behind 13、mergeable clean。95 files は**すべて新規追加**、Signal系path（signal / issuer / oidc / lane_identity / runtime_transition）**0件**。
- Actions: exact head のBlue workflow（run `37040078594`）success、`development lane status` skipped。logの件数はegress拒否でUNKNOWN（PR本文のコメントでは 1276 OK / skip 1）。
- 私のlocal実行（main + #249、順序A）: command_bus **1306 tests OK**（skip 1。内訳は §7）。Blue offline静的ケース（32仮想Loop）は#249内のtestとworkflowで実行される設計。
- 安全項目: retry=0 / fallback disabled / posting_authority=false / claim_reserved=false / external_execution=0 はINTEGRATION.mdとtest群に明記。LIVE budgetを増やす変更なし（台帳ファイルの変更0）。

見つけた問題:

**(1) 非STATICの秘密情報つきworkflowが混入。** `.github/workflows/blue-existing-session-readback.yml` は `JULES_API_KEY` を使い、固定の過去Session（`12436642121757218108`）に対しJules APIのGETを1回行う一回限りの診断で、期限窓（2026-10-02T08:00Z）はすでに切れている。#249本文・INTEGRATION.mdは「STATIC/mockのみ、`.github`はBlue専用STATIC workflow」としているので記述と実体が合わない。トリガーは `experiment/blue-work-autonomous-development` へのpush（path限定）なので**mainに入っても自動起動はしない**が、秘密つきのGET能力を持つdormantなworkflowがmainに登録される。
→ 修正: workflowと専用test `test_blue_session_diagnostic_workflow.py` を削除（7 tests減）、INTEGRATION.mdに訂正記載。

**(2) #203由来の3つのtestがportから漏れている。** 移植を #217-only の差分から作ったため、#203が追加し#217が触れていない `test_blue_jules_result_event.py`、`test_blue_work_wake_prepare.py`、`test_blue_work_jules_webhook_static_e2e.py` が #249 に無い（#217 tree と #249 の全ファイルblob比較で確認。mainにも無い）。一方 #249 の説明は「Blue static E2E は current carrier validator を使う」としている → **その検査が実在しない**。
→ 修正: 3 testを戻し、static E2Eには前回のcarrier契約patch（schema-v3 J-BLUE claim、origin identityはbinding経由）を適用。34 tests、現mainでは `numbered_command_id` 等が #248 で入っているので適用可能。

修正の検証（tree: #249 `d0648c7` + 修正2commit、一時worktree）:
- 旧base上: command_bus **1303 OK**（skip 1、1276 − 7 + 34）。
- 現main上（`2044412` + #249 + 修正）: §7。
- patch: `docs/evidence/final-integration-r3-20261003/patches/pr249-fix-series.patch`（format-patch 2本、`git am` で適用可）。
- **#249ブランチへのpushは、自動安全判定（共有リソース変更）で拒否された。回避していない。** 人間が許可するか、#249担当が `git am` で取り込む。

## 4. Signal SF-8 authority issuer

**`ALREADY_EXECUTED_SUCCESS`**。run `37031275812`、`workflow_dispatch`、head branch `main`、head SHA `4ddb0407001dc18c35f5f45bd37f67664fb9ff32`、attempt 1、conclusion success、job `issue` success（開始 2026-10-02T16:03:22Z）。workflowは `main`・`run_attempt==1`・許可された1人のdispatch者に限定。同名の別runは存在しない（workflow_dispatch一覧で1件）。**再実行しない。**

## 5. LIVE budget（durable evidenceから）

| 台帳 | cap / used / remaining | 根拠 |
|---|---|---|
| Claude Loop A | 10 / **4** / 6 | `claude/claude-jules-autoloop-data`（`1690182`）の `claude-auto-live-budget/slot-01..04.json`。slot=Loop 128,129,130,131。main上にも claim 128〜131 が存在。**台帳の実体ファイルはdata branchにしか無い（mainには無い）** |
| Blue | 10 / **10** / 0 | #249/#217 のBlue docs（「Trial10は10/10投入済み・receiptなし UNKNOWN。9/10は過去の記録」）。Trial10 = **UNKNOWN・再送禁止** |
| 今回の新規LIVE | **0** | |

## 6. #247 × #249 順序（一時統合、remote未変更）

#247はすでにmainに入っているため、**元の比較（base `a3dd5c8`）を仮想再現**した:

| 順序 | 手順 | 結果 |
|---|---|---|
| A | 実際のmain（`2044412`、#247を含む）+ #249 | **CLEAN** |
| B | `a3dd5c8` + #249 → + #247 head `e20155c` | **CLEAN**（両ステップ） |
| tree | A `3b28f9f71c88...` / B `3b28f9f71c88...` | **一致 → `ORDER_EQUIVALENT`** |

衝突files: なし。重複実装・上書き: なし（#249は全て新規path、#247は既存8 fileの修正で交差0）。workflow overlap: #249が追加するのは2本（§3の1本は削除推奨）。test overlap: なし。carrier contractの退行: なし（carrier validator・`jules_api_request_origin.py`・claim検証はmain側のまま、#249は触れない）。

## 7. temp統合treeの横断テスト（実際に走らせた件数）

対象: main(`2044412`) + #249(`d0648c7`)（tree `3b28f9f71c88`）。LIVE/provider/network実行なし。

| 項目 | total | PASS | FAIL | ERROR | SKIP |
|---|---|---|---|---|---|
| command_bus full（owner/generation/lease、carrier契約分割、origin binding、Jules request/claim、session readback、Claude Auto Loop、Blue reconcile、receipt binding、duplicate/replay、stale target を含む） | 1306 | 1305 | 0 | 0 | 1 |
| stack専用 cross-lane + failure-injection（前回のsuiteを使用。上の1306に含む） | 22 | 22 | 0 | 0 | 0 |
| Relay full | 801 | 801 | 0 | 0 | 0 |
| Node `--test` | 16 | 16 | 0 | 0 | 0 |
| compileall | OK | | | | |
| JSON / YAML parse | 下記 | | | | |

main + #249 + 修正2commit（§3）: command_bus **1333 tests OK**（skip 1、FAIL 0、ERROR 0。= 1306 − 7 + 34、cross-lane 22件を含む。tree `014dfa240e33`、merge CLEAN）。
`git diff --check origin/main` はtree A で 10行・4ファイル指摘（取り込んだBlue由来の `test_jules_session_readonly.py` と evidence 2 txt、削除予定の診断workflow testの空白）。#249自身のCIの `git diff --check`（作業tree）は成功しており、基準が違う。報告のみ。
Actions（GitHub側）の結果とは別物。logは `docs/evidence/final-integration-r3-20261003/logs/`。

## 8. #248（Claude Auto Loop）との相互作用

- #248 は #220 の44ファイルをcurrent mainへ移植済み。**前回R2で「GAP」とした adoption-time owner fence は #248 で追加済み**（PR本文: 採用の直前にowner/leaseを再確認し、修正前に失敗するtest付き）。PROFILE import修正も #248 に取り込み済み（`claude_loop.py` は carrier snapshotからprofileを取得）。
- #247 + #249 + #248 のtree（上記1306件）で、carrier request validator / origin binding / loop claim / owner fence / SEMI_AUTO⇄AUTO handover のtestは全て通る。
- **ID名前空間は別物として扱った**: global Loop ID（`loop_id_claims/NNN.json`、全lane共通）、Claude generation（owner chainのfencing、Loop A内）、Blue Work generation（Blue receipt / result event内）、Signalの `loop_id`（durable lane identity。数字IDや Session/PR/branch を昇格させない検査あり）。cross-lane suiteが「他laneが取った番号を尊重する」「generation/世代競合」を別々に検査。

## 9. Issue #33（read-only）

表示: 「⚫ Runtime: STOPPED、Current owner: NONE、Loop: UNKNOWN、Provider: UNKNOWN、Human action: NONE」。updated 2026-10-02T09:35Z、comments 0。本文は「displayは真実の源ではない」と明記。**runtime truthと混同しない**: Signal issuer実行（§4）・#247/#245 Merge後も、表示更新は無い。durable identity（`semiauto_stable_identity`）はregistryがPLACEHOLDERなら失敗する設計のまま。今回Issueへの書込み 0。

## 10. PR #238 の突き合わせ

#238 は古いmainをbaseにしたdocs-only PR（`8dbb8f4`）。**そのままMergeする前提にしない。** 項目別:

| #238の項目 | 現在の状態 |
|---|---|
| 「#237 → #4 …」merge順（§9） | **完了**: #237・#4 はMerge済み。#236/#239/#220/#217の順も**obsolete**（#240・#248・#249に置換） |
| `pr220-claude-loop-profile-import.patch` | **replaced by #248**（PROFILEは#248内で修正済み） |
| `pr217-blue-e2e-carrier-contract.patch` | **still required**（#249に未反映。§3(2)で再構成） |
| `pr217-blue-reconcile-single-trigger.patch` | **replaced by #249**（workflowのpush trigger削除済み） |
| carrier修復（#226/#229内容） | **replaced by #237**（#229はblob一致でmain内、#226は修正版として採用） |
| #230〜#233 / Loop A関連Jules PR | #230・#232・#233 は内容がmainに一致（#248系）。#231 は不一致（Loop 129 FAIL_MAJOR、#232が修正版） |
| 「adoption-time owner fenceはGAP」 | **更新**: #248で解消 |
| Issue #33 評価（`ISSUE33_MIGRATION_READY=NO`） | still required（表示は変わらず、移行未了） |
| Signalの記述（#236/#239、OIDC 0/3 等） | **要更新**: #240・#245・#247・issuer実行成功で状況が変わった |
| open PR/branch/workflow manifest | **cleanup分類だけ再利用可**（件数は115→119、355→403、68→更新が必要） |
| Cloud Work carrier #165〜#171 | still required（`62ab55d`/`c94de42`/`5f9e210`/`cd16ceb`、Draft・不変） |

#238 自体の扱い: **Close候補（`OBSOLETE_CAN_CLOSE_AFTER_MERGE`相当。このR3がMerge/採用された後、または証拠が移行された後）。今回はCloseしない。**

## 11. Cleanup manifest（分類のみ・実行なし）

分類: KEEP_ACTIVE / SOURCE_EVIDENCE_KEEP / REPLACED_CAN_CLOSE_AFTER_MERGE / OBSOLETE_CAN_CLOSE_AFTER_MERGE / KEEP_UNTIL_EVIDENCE_MIGRATED / UNKNOWN

| PR | 分類 | 置換先・根拠（fresh） | evidence | PR Close可能条件 | branch削除可能条件 |
|---|---|---|---|---|---|
| #203 | REPLACED_CAN_CLOSE_AFTER_MERGE | #249（5 files中、2 moduleは#249に更新版、3 testは**漏れていた**＝§3(2)）。#217の前身 | #217側に保存 | **§3(2)の修正を#249に反映** ＋ #249 Merge後 | PR Close後、#217 branchにevidenceがある限り保留不要 |
| #217 | REPLACED_CAN_CLOSE_AFTER_MERGE（部分的に SOURCE_EVIDENCE_KEEP） | #249。94 files は #249 とblob一致、3 files は main が新しい（HANDOVER_CURRENT, ROADMAP）、#217固有のtest 3件は漏れ（§3(2)） | `docs/evidence/blue-work-*` は #249 に同内容が入る。Trial10/Loop125の原証拠は#217 branchが一次 | #249 Merge + §3修正反映 + Blue担当の確認 | **Blueの台帳証拠（live-01〜09、Trial10）がmain上の#249へ入ったと確認できるまで保持** |
| #220 | REPLACED_CAN_CLOSE_AFTER_MERGE | **#248**（32/36 ファイル一致、4 files は #248 で修正版: `claude_jules_autoloop.py`, `claude_loop.py`, `test_claude_jules_autoloop_e2e.py`, `docs/CLAUDE_JULES_AUTOLOOP_INTEGRATION.md`）。必要内容は統合済み | LIVE台帳・Loop 128〜131の証拠は **`claude/claude-jules-autoloop-data` に保存（mainに無い）** | #248 Merge済み＝**条件充足**（人間の判断でClose可） | **削除しない**: `claude/claude-jules-autoloop-data`（台帳の唯一の置き場）、`claude/autoloop-live-target` はLoop A検証の対象で保持。#220 headブランチは人間判断 |
| #236 | KEEP_ACTIVE | main に無い6 files（`signal-sf8-oidc-proof.yml`、`sf8_jules_get_evidence.py` ほか）を持つ。#240 に置換されたのは #239 側のissuer部分 | `docs/evidence/signal-sf8/*` | Signal担当が「#236の残り6件を別PRで採るか捨てるか」を決めた後 | 同左 |
| #238 | OBSOLETE_CAN_CLOSE_AFTER_MERGE | §10。このR3に再編 | R3へ移行（`final-integration-20261002/` の manifest/patch は再利用） | R3のMerge後 | R3のMerge後（evidenceがmain入りしてから） |
| #239 | REPLACED_CAN_CLOSE_AFTER_MERGE | **#240**（「clean successor of #239」）。15/15 filesがmainと**blob一致** | #240経由でmain入り | **条件充足**（#240 Merge済み） | 条件充足後に人間判断 |
| #241 | KEEP_UNTIL_EVIDENCE_MIGRATED | Signal担当のpost-merge checkpoint docs（1 file）。mainに未収録 | docsのみ | Signal担当がMerge/統合 | 同左 |
| #242 | KEEP_UNTIL_EVIDENCE_MIGRATED | Signal LIVE proof evidence（6 files：provider-active、terminal-receipt、`authority-run-readback-37031275812.json` ほか）。mainに未収録 | **一次証拠**（`ALREADY_EXECUTED_SUCCESS` の根拠の保存先） | evidenceがmain入りした後 | 同左 |
| #243 | SOURCE_EVIDENCE_KEEP | Jules result PR（`jules-work/relay-dev-loop-132-signal-active-provider-proof-...`、`docs/evidence/signal-active-proof/PROOF.md`）。#242の証拠系列 | PROOF.md | #242のevidence移行後 | 同左（jules-work branch） |
| #226 | REPLACED_CAN_CLOSE_AFTER_MERGE | #237（修正版として採用、blobは不一致＝修正済みの意） | — | **条件充足**（#237 Merge済み） | 条件充足後に人間判断 |
| #229 | REPLACED_CAN_CLOSE_AFTER_MERGE | #237（1/1 blob一致でmain内） | — | **条件充足** | 同左 |
| #230 / #232 / #233 | REPLACED_CAN_CLOSE_AFTER_MERGE | 内容がmain一致（Loop 128/130/131、#248系） | Loop証拠は data branch | **条件充足** | **削除前に** data branchにevidenceがあることを確認済み |
| #231 | SOURCE_EVIDENCE_KEEP | Loop 129 の **FAIL_MAJOR** 原結果（不採用の証拠）。blob不一致=意図どおり | Loop 129 の inspection は data branch | 人間判断（証拠は data branch に有） | Loop 129 の証拠保存の確認後 |
| #165 / #166 / #167 / #171 | KEEP_ACTIVE | Cloud Work carrier（red/yellow/green/blue）。Draft・不変 | — | — | — |
| その他Jules result PR（`jules-work/**`、open 51 件） | 前回manifestの分類を再利用（前回: 115件中の内訳）。**今回の再分類は未実施 = UNKNOWN** | | | 前回manifest参照 | 前回manifest参照 |
| 旧統合branch・evidence branch（`claude/`19本ほか） | `claude/carrier-main-stack-verification` `claude/full-stack-verification-final` `claude/night-batch-carrier-rehearsal` など = SOURCE_EVIDENCE_KEEP、`claude/final-integration-checkpoint` = #238のbranch | | | | 台帳・evidence移行後に人間が判断 |

## 12. 残りの人間境界・既知UNKNOWN

1. **#249への修正適用**（§3、`git am`）: 私のpushは自動安全判定で拒否された。人間が許可するか、Blue担当が取り込む。これが済むまで #249 は `NEEDS_STATIC_FIX`。
2. #249 のMerge（修正後）。順序は #247 が済んだので #249 のみ。**Merge後に必要な再test**: main上で command_bus full と Relay を再実行。
3. Signal担当: #236の残り6 filesの扱い、`SIGNAL_EXTERNAL_FINDING` 2件。
4. Cleanup（Close / branch削除 / workflow無効化）は全て人間操作。
5. Issue #33 の移行、BWJ-4、Blue新LIVE（別承認）。
6. UNKNOWN: Actions logのテスト件数（#247 / #249）、その他Jules result PR 51件の今回再分類。

## 13. 次の安全な順序

1. #249 に §3 の修正を反映（人間許可 or Blue担当）→ #249のActionsが緑になることを確認。
2. #249 を人間がMerge（Draft解除を含む）。
3. main上で command_bus full / Relay / Node を再実行（この文書の手順で再現可）。
4. #220・#239・#226・#229・#230/#232/#233 などの「条件充足」PRを人間がClose判断（branchは data branch などを除いて後回し）。
5. #203/#217 は #249 Merge後にClose候補。

evidence: `docs/evidence/final-integration-r3-20261003/`（state.json、logs/、patches/）。
