> Implementation mirror copied from `kamiyusense/multi-ai-council-raw-records/PHASE0_IMPLEMENTATION_CHECKLIST.md`.
> Source blob SHA: `9cf692286a3165ad7850892f955b90f5c334d593`.
> Keep substantive changes traceable back to Council decisions.

# Multi-AI Council Phase 0 実装チェックリスト

## 固定ルール
- [ ] auto retry = 0
- [ ] model fallback = disabled
- [ ] paid fallback = disabled
- [ ] API key route = disabled
- [ ] GitHub write = disabled
- [ ] Browserを主経路にしない
- [ ] 2/3一致はユーザー確認
- [ ] safety warningは多数決より優先
- [ ] 5案件checkpoint

## Workspace
- [ ] Providerごとに別snapshot
- [ ] 専用run workspace配下のみ
- [ ] `.git`なし
- [ ] SSH keyなし
- [ ] GitHub tokenなし
- [ ] secretsなし
- [ ] Provider間共有なし
- [ ] capability_state初期値はUNKNOWN
- [ ] fan-out gate通過前にuser input / packetをProvider別snapshotへ書き込まない
- [ ] `phase0-runs/` 配下を秘密情報同等として扱う（共有・commit・外部送信・外部添付なし）

## Fan-out
- [ ] 秘密情報検査
- [ ] 個人情報検査
- [ ] 非公開コード検査
- [ ] 判定不能なら停止
- [ ] 人間確認まで送信しない

## Provider Adapter
- [ ] process分離
- [ ] timeout分離
- [ ] permission最小化
- [ ] tool権限固定
- [ ] file write範囲固定
- [ ] git禁止
- [ ] settings変更禁止
- [ ] 任意shell禁止

## Evidence
- [ ] stdout raw保存
- [ ] stderr raw保存
- [ ] exit code保存
- [ ] raw response保存
- [ ] input hash
- [ ] packet hash
- [ ] CLI version
- [ ] auth route
- [ ] requested model
- [ ] executed model verified / UNKNOWN
- [ ] retry_count
- [ ] fallback_state
- [ ] permission profile
- [ ] RAW本体は改変せず保存
- [ ] レポート/画面表示では既知の鍵形式をマスク
- [ ] Council公開時は原RAWを直接持ち出さず、人間確認済み全文派生物を使用
- [ ] 公開派生物には元RAW SHA-256を併記

## Provider Response Contract
- [ ] response envelope schema定義済み
- [ ] answer_state必須
- [ ] conclusion_code必須
- [ ] safety_warning必須
- [ ] safety_reason必須
- [ ] evidence_refs必須
- [ ] marker_echoes必須
- [ ] answer_text必須
- [ ] 必須field欠落はINVALID_OUTPUT
- [ ] safety_warning UNKNOWN / 欠落時に「警告なし」と推測しない
- [ ] free textからsemantic一致を自動確定しない
- [ ] conclusion_match_state / evidence_match_stateを分離

## Manifest / Timeout
- [ ] run_manifestとProvider別manifestを分離
- [ ] Providerごとのmanifest/stateが独立
- [ ] Providerごとに正の有限timeout設定済み
- [ ] timeout null / 0 / 負数 / UNSETではlive実行不可
- [ ] timeout値をAI出力から変更しない

## State Machine
- [ ] execution_state
- [ ] participation_state
- [ ] answer_state
- [ ] capability_state
- [ ] ERROR_UNKNOWN
- [ ] USER_DISABLED
- [ ] ANSWER_UNKNOWN
- [ ] REFUSAL
- [ ] QUOTA_CONFIRMEDは証拠あり時のみ

## Integrity
- [ ] nonce/marker fixture
- [ ] markerは補助検査と明記
- [ ] PARTIAL検知
- [ ] INVALID_OUTPUT検知
- [ ] fs_before
- [ ] fs_after
- [ ] fs_diff
- [ ] 想定外差分は人間へ返す

## Stop / Abort
- [ ] 子process停止
- [ ] stop flag
- [ ] 全子process停止fixture
- [ ] 停止後に新規dispatchなし
- [ ] 停止後retryなし
- [ ] 停止後fallbackなし

## Model Verification
- [ ] requested/configured分離
- [ ] externally verified executed model
- [ ] self-reportのみで確定しない
- [ ] mismatchでfail-loud
- [ ] verification不能で停止

## Failure Isolation
- [ ] 1社failureでも他社RAW保持
- [ ] timeoutで他Provider巻き込みなし
- [ ] NONPARTICIPANT分離
- [ ] partial success report

## Tests
- [ ] unit
- [ ] fixture
- [ ] regression
- [ ] retry=0
- [ ] fallback禁止
- [ ] timeout
- [ ] ERROR_UNKNOWN
- [ ] quota confirmed
- [ ] model mismatch
- [ ] filesystem unexpected write
- [ ] stop during dispatch
- [ ] provider partial failure

## Live前ゲート
- [ ] static preflight PASS
- [ ] mock stop PASS
- [ ] fan-out gate PASS
- [ ] permission profile PASS
- [ ] raw-first evidence PASS
- [ ] state machine PASS
- [ ] model verification PASS
- [ ] fs diff PASS
- [ ] marker fixture PASS
- [ ] failure isolation PASS
- [ ] Provider Response Contract PASS
- [ ] Provider別manifest独立 PASS
- [ ] Provider別finite timeout PASS
- [ ] timeout null / 0 / 負数 / UNSET拒否 PASS
- [ ] secret masking PASS
- [ ] phase0-runs隔離 PASS
- [ ] UNKNOWNなし（安全境界関連）
- [ ] ユーザー明示承認あり

