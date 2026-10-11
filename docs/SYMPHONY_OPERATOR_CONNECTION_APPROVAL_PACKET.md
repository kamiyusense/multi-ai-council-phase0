# Symphony / New Chinponey — 本番接続方針・設置レビュー票

状態: **POLICY_APPROVED / INSTALLATION_NOT_AUTHORIZED / LIVE_NO_GO**
記録日: 2026-10-11 (JST)
レビュー対象: Draft PR #343 (`claude/symphony-g61-production-wiring-static`)
出典: PR #343 最終実装checkpoint comment 6104550287、及び
`docs/SYMPHONY_PRELIVE_READINESS.md` と
`docs/evidence/symphony-prelive-convergence/gates.json`。

## 0. 今回の人間の承認範囲

利用者は「既存GitHub認証を最大限再利用し、3つの本番接続を最小権限・追加課金なし原則で進める方針」を承認した。
**この承認は安全な調査・設計・文書保存・既存の開発PRにおける非破壊準備だけ**を認める。

この記録自体は次の承認ではない:
- 新しい GitHub Actions `workflow_dispatch` の本番設置・起動、OIDC token取得
- GitHub main/default へのwrite、PR Merge、Secrets/permissions/settingsの変更
- 既存tokenを実送信用へ転用すること、tokenの値の取得・表示・保存
- 実成果のGit Database POST、GraphQL `updateRefs`、staging/ref/Issue新設
- Official Symphony/Codex workerの新LIVE、API従量課金・有料fallback
- これらの迂回・代理承認

何かが別途承認を必要とする場合は**許可される独立作業だけを完了してから**、ひとつのレビュー依頼としてまとめる。システムによる承認も省略しない。

## 1. 現時点の確認済み技術状態

- 作業前のremote: #343 OPEN/DRAFT HEAD `db4ed6861c6bfb4e2ea2287f11c848bff3dae1a2`、親 #320 `8c53c505a21318c6133da0bef85af18ae3711103`、main `abb5402079d4af341c349ea9e8b6a8a5c3f2d37c`。いずれも固定の将来値として使わず、実作業直前にfresh GETすること。
- #343 HEADに対応するCI 38103541994 / 38103541925 / 38103541923 / 38103541920 はいずれも SUCCESS / 同一HEAD。実worker・実候補のqualificationや本番送信の証明ではない。
- SHA/契約: `automation/command_bus/symphony_operator_oidc.py` は exact canonical envelope digest をGitHub署名JWTの audience に結ぶOFFLINE検証部品。既存 Signal SF-8 は**identity-only**であり権限へ昇格できない。
- `symphony_operator_capability.py` は検証済み実候補・外部署名付き1回許可・独立した能力注入の全てを必須にするが、本番 credential factory は未設置。
- `symphony_operator_verifier_route.py` は独立trusted sourceと固定Dockerの検証コマンドを準備するが、本番のexact-candidate-head workflow/stagingは未設置。
- REAL candidate: NOT_RUN。実worker、snapshot、candidate、eligible CI archive は未存在。合成artifactから本番合格は出さない。
- rules/protection REST GETの一部が403。metadataの `protected:false` だけで「規則なし」と判定しない。
- 常設WSL Node実行パスは未確定。本番はoperator側でpath/hashを固定する。
- コスト・subscription quotaの完全な保証はない。実run前に残枠とprovider selectorを再GETし、UNKNOWNを「無制限」と解釈しない。

## 2. 接続①: 外部署名付きの「人間による1回許可」

採用候補: GitHubの標準OIDC RS256/JWKS/claimsと、本人が明示実行する `workflow_dispatch` を使う。**新しい長期署名鍵・PAT・APIキーは既定案として作成しない。**

必要な承認後設置:
1. **独立レビューを通した新しい main 専用手動workflow** を、default branchに適切なPRのMerge承認経由で設置する。既存 `.github/workflows/signal-sf8-authority-issuer.yml` はidentity-onlyのまま変更しない。
2. `github.repository`、所有者/actor ID、`refs/heads/main`、workflow SHA、`workflow_dispatch`、`run_attempt == 1`、短い有効期限、一意nonce、候補/receipt/台帳/対象ref/old/new OID/固定操作を厳密にbindする。
3. GitHub発行JWTが `aud=urn:symphony:operator-direct-authorization-v1:sha256:<exact DOMAIN+canonical envelope SHA256>` を署名していることを、既存のJWKS検証器とclaim policyで検査。PR本文、合成JSON、自己hash、成功コメントで置き換えない。
4. **JWT自体をartifact、ログ、Issue、環境変数、永続ファイル、別threadへ残さない。** OIDC verifierとoperator送信が別環境になるなら、署名証拠を安全に受け渡す具体的方法を別途セキュリティレビューする。単にsanitized Signal evidenceを渡すだけでは**外部署名の保全にならない**。
5. 現時点で有力なのは、ユーザーが直接起動した**review済み同一operator jobのメモリ内でJWTを検証し、後述の条件付き送信口にだけ能力を渡す方法**。これは設計候補であって、本番のGITHUB_TOKEN write権限・branch scope・workflow実装とruntime連携が証明されるまでREADYではない。
6. `workflow_dispatch` は workflow file がdefault branchに存在する必要がある。Draft #343のファイルを用意するだけでは有効化・本番実証にはならない（GitHub公式仕様）。

必要な独立negative試験: wrong audience/digest/issuer/key ID/actor/repository/run/run_attempt/workflow SHA/expiry/nonce/対象ref/操作scope、JWT記録漏れ、workflowの二重起動と期限切れ。曖昧な送信結果を盲再送しない。

判定: **OFFLINE_CRYPTO_PASS / RUNTIME_ISSUER_NOT_INSTALLED**。

## 3. 接続②: exact-candidate-head独立検品

採用候補: 既存 `OperatorCandidateVerifier.read` / `PinnedSourceCIVerifier` / `symphony_operator_verifier_route.py` を再利用し、新しい検証アーキテクチャを作らない。

必要な承認後設置:
1. one-run proofの実workerが通常のOfficial Symphonyの挙動で動くまで実候補は存在しない。自然continuation/retry/backoff/stall/concurrency/cleanupは変更しない。
2. 実STARTED、実TERMINAL、cleanup前の署名付きsnapshot、immutable candidate objectsを別々に証明する。STOPPED/UNKNOWNをDONEに昇格しない。
3. 候補と同一SHAのGitHub Actions run `head_sha == candidate.commit` を満たすための、**review済み検証workflowと非defaultの候補staging ref** が必要。検査だけ別checkoutしてCI workflowをmain上で走らせる代替は契約不合格。
4. 候補stagingは実GitHubへのwriteなので、作成・更新権限と範囲を**一回LIVE/real-write承認の時点で**固定する。今回作成しない。検査workflow自身はmainから信頼済み固定source/tests/config/imageを取得し、候補に入った変更可能なテスト選択やworkflow変更を許さない。
5. 実run/job/step/artifactをGitHubからGETし、actual uploaded ZIP digestを改めてpinし、strict attestationと`SYMPHONY_OPERATOR_REAL_CANDIDATE_V1`/`synthetic:false`を読み戻す。ローカルZIPのhashをGitHub artifact hashと仮定しない。
6. candidate verification PASS は公開の必要条件であり、それだけで採用許可は発行されない。本人の一回承認と独立credential能力を追加で要求する。

negative試験: untrusted candidate selectors、失敗step、wrong run/job/head、差し替えZIP、stale snapshot、CI期限切れ、staging競合、raw secret漏出。

判定: **VERIFIER_CODE_READY_OFF / TRUSTED_RUNTIME_WORKFLOW_AND_STAGING_NOT_INSTALLED / REAL_CANDIDATE_NOT_RUN**。

## 4. 接続③: operator専用・固定対象だけのGitHub送信

採用候補: G6.1 `symphony_github_git_transport.py` のdeterministic object plan、既存 create-only ledger / intent / target lock / CAS fence / GET-only recovery、および `symphony_operator_capability.py` の制限付きadapterを再利用。汎用HTTP writerは提供しない。

必要な承認後設置:
1. 既存GitHub認証の**権限metadataのみ**をoperator側で確認し、Credentialの値を読み出して保存したり、権限を広げたりしない。
2. 認証credentialがAPIとしてrepo-wide writeを持つ場合、アプリ内allowlistだけでcredential自身がbranch限定になったとは主張しない。**トークンの許可範囲とアプリの操作範囲を区別**して独立レビューし、現時点のworkflow/job/target branch保護の有効性も確認する。
3. 本番factoryはcredential取得機構をworker/model/candidateに渡さず、exact repo/node/非default ref/object paths/OID/ledger namespace/nonce/receiptに固定された3メソッドのみを提供。既存STATIC transportのguardを外さない。
4. fresh default/owner/rules/expected old head/Issue/task/scopeを照合できなければ送信しない。 `updateRefs(beforeOid,afterOid,force:false)` は許可された一回だけ。
5. HTTP応答が不明なら追加POST/CASを自動再送しない。原本へGETで照合し、証明できないscopeをUNKNOWN隔離し、無関係の安全な作業は継続する。
6. **mainへのwriteは常に禁止**。非default refへの新規staging/actual publicationは既存の開発branchへの通常FF pushと別種の操作であり、今回の方針承認では許可されない。

判定: **CAPABILITY_BOUND_ADAPTER_PASS_OFF / REAL_CREDENTIAL_FACTORY_NOT_REVIEWED_OR_INSTALLED / RULES_EFFECTIVE_AUTHORITY_UNKNOWN**。

## 5. 推奨接続順と次のレビュー境界

**第1段階: 現在許可される開発（この票の保存を含む）**
- fresh readbackと技術レビュー、既存ソースの再利用、設置手順・差分案・negative tests・決定項目の永続保存
- 開発branchへの非破壊な文書保存とremote readback
- 実workflow dispatch・JWT取得・候補staging・新live model・実writeは0のまま

**第2段階: 別途承認が必要な設置**
- mainへ導入するtrustworthy manual issuerとreal verifier workflowの**具体的PR差分と導入順**をレビュー
- 必要なら既存operator credentialのfactoryと実効的なGitHub rules/permissionsを独立確認する方法をレビュー
- この段階の作業許可は「安全な設置・接続」に限定し、workflowのdispatch、実モデル起動、実結果採用には波及させない
- mainへ反映するMerge自体は個別のシステム/ユーザー承認が必要。既存Stack #343全部を安易にmainへMergeしない。最小ファイルをmain起点の独立PRでレビューする

**第3段階: 接続済みのfresh proof前検査**
- 既存GitHub branch protection/rulesの有効状態、owner/identity/credential path、subscription selector、残枠・課金境界、厳密なworker/candidate/CI/one-run envelopesを最新HEADでチェック
- 全技術ゲートがPASSになって初めて `READY_FOR_ONE_RUN_LIVE_EXCEPT_EXPLICIT_APPROVAL` とする。利用者の一般的な方針承認をone-run authorizationに転用しない

**第4段階: 将来の独立した一回LIVE承認後のみ**
- exact correlation/campaign/Issue/workspace/nonce/expected_target_headを明示
- Official Symphony/Codex lifetime1、real result verification1、実Git送信は最大1 force:false CAS、observer/controller restart1・追加model dispatch0
- FAIL/UNKNOWNで新LIVE再投入を勝手にしない。GET-only復旧と証拠保全

## 6. 人間が次にレビューすべき一括決定（今回の承認だけで自動実行しない）

1. **新しいmain専用手動issuer/operator workflow** と **exact-candidate-head verifier workflow** の具体的設置PRをレビューしてmainに反映するか。
2. **既存GitHub認証をoperatorに限定注入**する方式・実効rules/保護境界をレビューし、許可可能なwrite classを確定するか（新規secret/PAT/権限拡大は別判断）。
3. staging refの対象・expiry・proof identityと、一回LIVEを**後日別承認**にする境界を維持するか。

最小の推奨は、**既存GitHub OIDC + reviewed manual main workflow + immutable exact-head independent verifier + operator-only bounded writer**。GitHub native runner内で完結できるかは、JWT運搬とcredential権限のレビュー後に決定。安全性を推測してPASSにしない。

## 7. 受入・検品

- 現在の証拠: `docs/SYMPHONY_PRELIVE_READINESS.md`、`docs/evidence/symphony-prelive-convergence/gates.json`、PR343 comment 6104550287。
- この文書は**レビュー用提案**であり、実装済みLIVE機能や新CI PASSを主張しない。
- GitHub公式: https://docs.github.com/en/actions/reference/security/oidc
- GitHub公式: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onworkflow_dispatch
- GitHub artifacts: https://github.com/actions/upload-artifact

次の実装担当は「方針承認」と「設置・起動の承認」を分離して扱い、各境界の真の承認だけをまとめて問い合わせる。安全な作業が残る場合は問い合わせ前に継続する。
