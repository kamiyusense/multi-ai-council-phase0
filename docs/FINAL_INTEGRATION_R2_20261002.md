# 最終統合R2 — 最新Blue反映・#237 Merge直前STATIC再検証 (2026-10-02)

追記専用。前回の [FINAL_INTEGRATION_CHECKPOINT_20261002.md](FINAL_INTEGRATION_CHECKPOINT_20261002.md) と
`docs/evidence/final-integration-20261002/` は消さず、そのまま残す。この文書は前回以降に変わった事実だけを上書きする。

範囲: STATIC / read-only / mock / 使い捨てworktreeでの統合のみ。Merge、Ready化、Close、branch削除、force push、
workflow無効化、権限変更、新規LIVE（Jules / Work / Claude Loop A / Blue）は一切行っていない。
読み取り時刻: 2026-10-02T09:13Z（GitHub fresh readback）。

## 1. fresh state（GitHub readback）

| 対象 | HEAD | 状態 |
|---|---|---|
| main | `ed19f7f` | 前回から不変 |
| carrier `feature/chat-work-command-bus` | `7c83ae9` | 不変 |
| PR #237 | `aa7f686` | Draft・open・mergeable clean・mainに対し ahead 536 / behind 0 |
| PR #238 | 本docの保存前は `40fc47b` | Draft・docs-only |
| PR #4 Relay | `f6072c1` | Ready・open・clean |
| PR #203 Blue base | `66d3665` | Draft・clean |
| **PR #217 Blue** | **`5d17df1`**（前回 `9d2a230`） | Draft・clean。2 commit増（6d7859d, 5d17df1）、35 files / +4380 |
| `feature/signal-observed-v1` | `900ab2c` | |
| PR #236 Signal OIDC | `776d877` | Draft・base=signal canonical |
| **PR #239 Signal issuer（新規）** | `f0f3a0a` | Draft・base=main。**#236と競合する別PR** |
| PR #220 Loop A | `044389e` | Draft・clean・`.github`変更0 |
| Cloud Work #165/#166/#167/#171 | `62ab55d` / `c94de42` / `5f9e210` / `cd16ceb` | 全てDraft・clean・不変 |
| Issue #33 | open、comments 0、updated 05:16Z | 不変（Runtime LIVE変更なし） |
| `claude/claude-jules-autoloop-data` | `1690182` | budget slot-01〜04の4件 |

注: PR #217 本文の「最新HEAD a3e3c2e」は古い記述で、現在HEADと一致しない（本文は更新されていない）。

## 2. PR #220 — FROZEN_WAITING_FOR_GLOBAL_INTEGRATION

fresh readbackで矛盾なし: Draft/open/clean、HEAD `044389e`、`.github`変更0、Actions（signal tests）success、
LIVE台帳 slot 4件＝4/10。追加開発・Ready化・Merge・LIVE枠消費は行わない。

## 3. 最新Blue #217

- 最新Actions（`5d17df1`）: `Blue Work reconciliation offline validation` が **push と pull_request の両方でsuccess**（同一HEADで二重実行）。
- 差分は work_bridge 系（prepare / GitHub preflight / event prepare CLI）、docs、evidence。`.github` の変更は無い。
- Blueのtest数: #217自身の記録は 1045 tests / 1044 OK / skip1（docs記載）。Actions logは本環境から取得できなかったため **数値の再取得はUNKNOWN**（成功/失敗の結論のみ確認）。
- 重要な訂正: 台帳は **10/10消費済み**。Blue自身の最新docs（BLUE_WORK_CONTINUATION / REVIEW_READY）は「Trial10は10/10投入済み・receiptなしUNKNOWN、9/10は過去の記録」と明記。#217本文の「9/10で停止」は履歴。新LIVEは禁止のまま。
- 境界: BWJ-4（本物のresult event→Actions→carrier→Work）= NOT_WIRED、source認証adapter = BLOCKED、Loop125のsource/unique output・YellowのLIVE tree確認 = UNKNOWN。

### 旧patchの再判定（現在のコードを読んだ結果）

| patch | 判定 | 根拠 |
|---|---|---|
| `pr217-blue-e2e-carrier-contract.patch` | **STILL_REQUIRED（順序制約あり）** | patch無しで `test_blue_work_jules_webhook_static_e2e` が `request keys mismatch missing=['work_branch'] extra=['origin_*']` で失敗（実測）。最新#217 `5d17df1` にclean apply可。**ただし** このpatchがimportする `numbered_command_id` 等は #220 の `claude_loop.py` にしか無い。#220より前にpatchを当てるとテスト収集時にImportErrorでredになる → **#220がmainに入った後**に当てる |
| `pr217-blue-reconcile-single-trigger.patch` | **STILL_REQUIRED** | 上記Actionsで同一HEADにpush+pull_requestが両方走っているのを確認。最新#217にclean apply可 |
| `pr220-claude-loop-profile-import.patch` | **STILL_REQUIRED** | carrier側 `jules_api_request` は `PROFILE` のみで `PROFILE_V2` を持たない（実測）。#220の旧importを残すとImportError |

新しいpatchは不要（既存patchが最新HEADに対して有効）。#217 / #220本体にはwriteしていない。

## 4. PR #237 独立再検品

| 確認 | 結果 |
|---|---|
| head / base | `aa7f686` / main `ed19f7f`、behind 0、mergeable clean |
| Actions（`aa7f686`） | `Phase 0 loop status signal tests` pull_request **success**（run 36983418880）。`development lane status` pull_request_target は skipped（設計どおり）。test件数はlog取得不可のためUNKNOWN（前回記録: 843） |
| carrier contract byte identity | `jules_api_request.py` blob `1aebad3`、`loop_id_claim.py` `d7aba1a`、`jules_session_acceptance.py` `c9f5f2c` が carrier と同一。main旧validatorは `jules_api_request_origin.py`(`12d0286`) |
| #226 readback fix / #229 claim quarantine | 内容は #237 に採用済み（`test_loop_id_claim.py` に HISTORICAL_BACKFILL の検査3件）。#226 `6eeea69` / #229 `54a4e85` 自体は両方open・未merge |
| mainに置いた時の意図しない起動 | carrier専用workflow 5本（jules-chat-semiauto、jules-session-readback、jules-session-message、jules-session-stop-message、core-exact-head-validation）は全て `push.branches: feature/chat-work-command-bus` ＋ `paths` 限定。main上では起動しない |
| local STATIC（最新統合stack内） | 下記 §6 |

**`PR237_STATIC_MERGE_READY = YES`**（新しいblockerなし。Mergeは未実行）。

## 5. 一時full-stack統合（使い捨てworktree、remote未変更）

順序A（前回順）: #237 → #4 → #203 → #217 → patch(e2e) → signal → #236 → #220 → patch(PROFILE)。
順序B（#220先）: #237 → #220(+PROFILE) → #203 → #217 → patch(e2e) → #4 → signal → #236。
**2つの順序の最終tree hashが一致**（`0fef0164b5`）。つまり衝突の無い範囲では順序は結果に影響しない。順序が効くのはpatchの前提だけ（§3）。

### 衝突map（実測）

| 統合 | 結果 |
|---|---|
| #237 → #4 | CONFLICT: `docs/JULES_TASK_PROMPT_SPEC.md`（#4が古い版を新規追加、mainは更新済み）。**mainの版を採用**（#4はその文書を変えていない） |
| #237 → #203 → 最新#217 | CLEAN（契約差はe2e testのみ → patch） |
| + signal canonical / #236 | CLEAN |
| #220 | CONFLICT: `claude_loop.py`、`test_claude_loop.py`。解消 = #220側を採用＋PROFILE patch |
| **#239 → #237** | CLEAN |
| **#239 → #236を含むstack** | **CONFLICT**: `lane_identity_adoption.py`、`tests/test_sf8_authority_issuer_candidate.py`。#236と#239は同じSignal領域を別実装しており、**両方は入れられない**。Signal担当の判断が必要（今回は#239をstackに入れていない） |
| Observed Signal / ownership分離、Cloud Work lane identity、Loop番号namespace | stack内testで衝突なし（cross-lane testsが対象） |

## 6. full-stack STATIC（今回実際に実行した件数。Actions結果とは別）

使い捨てstack `r2`（merge順Aの内容、`37668b4`）での **local実行**:

| 項目 | 結果 |
|---|---|
| command_bus full unittest | **1373 tests OK（skip 1）** |
| cross-lane + failure-injection（stack専用test 2ファイル） | **22 tests OK** |
| Relay full unittest | **801 tests OK** |
| Node `--test`（2ファイル） | **16 pass / 0 fail** |
| compileall | OK |
| workflow YAML parse | 19本 OK |
| schema JSON parse | 28本 OK |
| `git diff --check` | 18行・10ファイルで指摘。全て取り込んだ他レーンの文書/evidence/testの行末空白（#4・#217・#236由来）。#237自身の指摘なし。報告のみ |
| Loop A（#220）/ Blue / Signal専用test | 上記command_bus full内で実行済み（個別件数は未分離＝UNKNOWN） |

Actions（GitHub側）: #237 test success、#217 Blue validation success×2（push/PR）、#220 signal tests success。local件数をActions件数として転用していない。

## 7. failure / recovery 分類

| 項目 | 分類 | 根拠 / 残り |
|---|---|---|
| duplicate event | COVERED | Loop A e2e `duplicate_and_redelivered`、cross-lane `DuplicateRunsCollapseToOne`、Blue 32仮想Loop/1280障害 |
| terminal receipt replay | COVERED | `terminal_dispatch_receipt_is_never_replayed` |
| stale generation | COVERED | `stale_owner_generation...cannot_dispatch`、Blue soak |
| expired owner | COVERED | `expired_owner_lease_stops`、`expired_auto_lease_cannot_dispatch` |
| owner-generation race | PARTIAL | testは通るが、backend guardを外しても通る（gitのcreate-only原子性が最後の砦）。guard自体の独立検証は無い |
| claim race | COVERED | `other_lane_wins_the_same_number`、`loop_number_collision`、Blueの同番号4色BLOCKED |
| work-branch collision | COVERED | `WorkBranchIsolation`（stack専用test） |
| target HEAD drift | COVERED | `target_head_mismatch`、failure-injection（head差し替え） |
| target tree drift | COVERED | failure-injection（tree差し替え） |
| malformed request | COVERED | 全必須キー欠落・14種の破損・期限切れ・path traversal |
| blended origin/carrier request | COVERED | failure-injection、`current_carrier_compatibility` |
| receipt mismatch | COVERED | `blue_receipt_binding`、`invalid_adoption_receipt` |
| evidence mismatch | PARTIAL | Loop Aはtampered inspection/footer検査あり。Blueのsource/evidence origin認証はBLOCKED（adapter未接続） |
| missing result | COVERED | `no_result_pr_times_out_fail_closed`、Blueの欠落=UNKNOWN |
| bad Jules result | COVERED | lineage failure matrix、minor/major failure |
| failed candidate superseded | COVERED | `major_failure_prepares_new_corrective_command`、`target_moved...replans`（実履歴でもLoop129→130） |
| crash after claim | PARTIAL | intent有りreceipt無しの再開は検査済み。claim直後だけのcrashを名指しするtestは無い |
| crash after command write | COVERED | `lost_response_after_command_write_is_recovered_by_readback`、`session_loss_mid_dispatch` |
| ambiguous write | COVERED | `ambiguous_command_write_is_read_back_not_resent` ほか多数 |
| recovery from GitHub durable records only | PARTIAL | `recovery_reconstruct.py` drillと再開testはある。SEMI_AUTO側のcheckpointからの安全再開は **GAP**（前回から変わらず） |
| handback AUTO→SEMI_AUTO | COVERED | `handback_only_at_a_boundary`、`round_trip_on_real_git` |
| SEMI_AUTO→AUTO takeover | COVERED | `eligible_takeover_is_a_fenced_handoff`、`time_alone_never_takes_ownership`、in-flight時ブロック |
| expired AUTO reclaim | COVERED | `reclaim_only_after_expiry`、`claude_session_loss_while_owning...` |
| adoption-time owner fence | **GAP** | SafeAdoptionに独自のowner fenceが無い（owner変更を検査するのはcommand書込み前まで） |

COVERED 19 / PARTIAL 4 / GAP 1 / UNKNOWN 0（recovery行のSEMI_AUTO checkpoint再開は前回からのGAPとして残る）（新規LIVE試験では埋めていない）。

## 8. Actions節約

- Blue #217: 同一HEADでpush+pull_requestの二重実行を **現在も確認**（`5d17df1`で2run）。source-level修正案 = `pr217-blue-reconcile-single-trigger.patch`（有効のまま）。適用は#217担当。
- #237/#238のskipped run（development lane status pull_request_target）は各イベント1件。許容範囲。
- #238（docs-only）はtestが走らない（意図どおり）。#237は契約validator変更でtest workflowが走る（path拡張＋guard testあり）。
- workflow登録数（`.github/workflows`のファイル数）: main 10 / #237 13 / #217 12。歴史的registrationの無効化は人間操作（実施なし）。

## 9. 最新merge順（再計算）

1. **#237**（carrier→main。人間のMerge承認が最初の1手）
2. **#4 Relay**（`JULES_TASK_PROMPT_SPEC.md` はmain側を採用）
3. **Signal canonical** `feature/signal-observed-v1`
4. **#236 か #239 のどちらか一方**（Signal担当が選ぶ。両方は競合）
5. **#220**（先にPROFILE patch＋main取り込み解消。#220の担当が実施）
6. **#203 → #217**（e2e patch は #220 の後、single-trigger patch はいつでも）
7. cross-lane / failure-injection testsを最終main上で再実行

前回との違い: 「#217を#220より前に」→ **#217のe2e patchの前提として#220を先に**。#4とSignalの位置は影響なし（tree一致で確認）。

## 10. 人間判断（今回追加・更新）

1. #237のMerge（Draft解除を含む）— 最初に必要な1操作。
2. #236 と #239 のどちらを採るか（Signal担当）。
3. #220担当: PROFILE patch適用＋main取り込み。#217担当: patch 2本（e2e は #220の後）。
4. Blue台帳は10/10消費済み（本文の9/10は古い）。次LIVEは新しい別承認が必要。
5. Issue #33 / BWJ-4 / cleanupは前回の判断パケットのまま。

## 11. cleanup候補（実行なし）

前回の manifest（open PR 115 / branch 355 / workflow 68）を維持。追加: #226 / #229（内容は#237が取り込み済み → #237 Merge後にClose候補）、#236/#239のうち不採用側。

## 12. 再開手順

1. `git fetch origin`、#237 / #217 / #220 / #239 のHEADを読み直す。
2. この文書 §5 の順で使い捨てworktreeに統合し、patchを順に `git apply --check`。
3. command_bus / Relay / Node を再実行して §6と比較。

evidence: `docs/evidence/final-integration-r2-20261002/`（state.json、patch適用確認ログ）。
