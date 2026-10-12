# Symphony / New Chinponey — PRELIVE_READINESS

判定: **STATIC実装・Local検証 PASS / LIVE NO-GO**。
`PRELIVE_BLOCKED_ONE_OR_MORE_OPERATOR_CAPABILITIES`。
本資料は本番起動・成果採用・OIDC発行・本番送信の承認ではない。

正式仕様: PR343コメント6104065023、6103625550、6103763038全文。
開始HEAD `8bfe01b64cdf9206dc47af32b5f25c85ab1be8ed`、作業先
`claude/symphony-g61-production-wiring-static`。mainは
`abb5402079d4af341c349ea9e8b6a8a5c3f2d37c`、親320は
`8c53c505a21318c6133da0bef85af18ae3711103`。未保存5ファイルは
Windows永続フォルダへ最初に保全。後続の完了済み作業指示は見つからなかった。

## 残条件の分類と最小接続

| 条件 | 開始時の分類 | 今回の結果 |
| --- | --- | --- |
| Snapshot / immutable objects / strict CI provenance / intent・lock・fence・GET recovery | 実装済み | 既存実装をそのまま再利用 |
| Exact payloadへの外部署名binding | 必須の接続不足 | 既存RS256/JWKS/claims policyを結ぶoffline adapterを追加 |
| Operatorだけが持つ限定送信capability | 必須の接続不足＋人間の権限レビュー | 固定操作だけの別adapterを追加、実factoryは未接続 |
| Real candidateの検証job入口・ZIP出力 | 必須の接続不足 | 既存Dockerコマンドとstrict＋real attestationを結ぶ明示呼び出し入口を追加 |
| Actual issuer/main workflow、実write capability、exact-candidate CI/staging | 人間／システムの承認が必要 | 未実施、BLOCKED |
| Real worker / candidate / eligible run / attestation | 実worker前には存在しない | NOT_RUN。fixtureを本番証拠へ昇格させない |
| Docker・subscription・ledger・owner/ref/rules | 実機の読み取り確認 | Docker/GET復旧/subscription/owner/refは確認、rulesは403 UNKNOWN |
| One-run approvalとfresh proof | 人間の承認が必要 | NONE / PROPOSED_NOT_CREATED |

### 外部署名

`symphony_operator_oidc.py`と小さいNode helperだけを追加した。
署名済みJWTのaudienceは `SHA256(DOMAIN + canonical envelope)` を含み、
exact payload、issuer/key ID、nonce、candidate receipt、object operations、
ledger namespaces、固定一回CASを結ぶ。既存のGitHub RS256検証とclaims policyを
再利用し、manual main SHA/workflow/run attempt1/allowlisted actor/短い期限を検証。
既存Signalの固定audienceは本人・workflowの確認だけで、送信許可には使用できない。
main/PRのSignal workflow・署名検証・claims policy・過去checkpointはbyte一致で無変更。

GitHub issuer metadataと公開JWKSはHTTPS GETで独立取得した。実JWT/OIDC発行は0。
暗号試験は既存テストのメモリ内RSA fixtureだけを再利用し、新しい本番鍵・Secret・
長期signerを作っていない。JWTはpipe内だけ、保存・ログ・環境変数・argvには出さない。
期限切れ署名の再確認は既存のdurable fenceを持つGET復旧だけ。新しい送信は拒否する。

必要な人間レビュー: exact envelope digestをaudienceとして要求するmanual main
issuer workflowの設置／承認と、独立したmain SHA・actor・runのpin。
現在のSignal proofを許可へ昇格させたり、PRコメントの自己hashを権限にしない。

### 限定送信口

`symphony_operator_capability.py`は別のoperator専用adapter。
既存STATIC transport/bridge/mockのguardは無変更で、このadapterを旧STATIC bridgeへ
渡すと拒否される。real candidate reader結果＋外部署名＋別途レビュー済みfactoryが
全部そろわなければ使用できない。default factory、token lookup、汎用REST/GraphQL、
automatic publication/adoption entrypointは存在しない。

独立readerでrepo/node/default/owner/target HEAD/task/scopeと保護規則・必要能力を
送信直前に再確認する。403／不明を許可へ変換しない。exact object inventory、
create-only signed ledger namespace、exact before/after・force:falseの一回CASに限定。
元のintent/lock/ref fenceを再利用し、ledger応答不明も元のappend-only storeへ先に
fenceを保存する。再起動後はGETだけ、CAS・object・ledgerのblind resendなし。
実credential factoryは未接続。ADMIN metadataは送信権限の代用品ではない。

### Real verifierの入口

`symphony_operator_verifier_route.py`はprepareと明示呼び出しjob入口だけ。
real-format completed lifetime、pre-close snapshot、immutable candidate objects、
独立取得した全operator source treeとtests/config/workflow/image pinを照合する。
candidateが選んだtests/configを実行しない。実行前後もsource/candidate全bytesを確認。
元のstrict check attestationと`SYMPHONY_OPERATOR_REAL_CANDIDATE_V1 / synthetic:false`
を同じZIPへ出し、ZIP全体SHA256は外側へ出す。出力だけではqualificationにならず、
元のGitHub run/job/artifact GET provenanceと`OperatorCandidateVerifier.read()`が必須。
Upload artifactには出力されたJSON 2件をルートへ置き、ZIPを入れ子でuploadしない。
local bundle SHAとGitHubが返す最終archive SHAを同一視せず、upload後のGETで取得した
actual whole ZIP digestを最終contractへpinする。
failed check・wrong job/head・source変更ではattestationを出さない。

現在のsynthetic CIはsyntheticのまま。本番eligible jobは起動していない。
元のstrict readerが要求するrun.head_sha == candidate.commitを緩めていない。
そのため将来の実jobには、exact candidate HEADをremoteで参照できる承認済みstagingと
reviewed workflowが必要。mainをHEADにしてcandidateを別checkoutするだけでは不合格。
workflow/mainの設置とstaging/ref権限はこのbatchの承認外であり、自動では追加しない。

将来の順序: STARTED → work/通常continuation → cleanup前snapshot → genuine TERMINAL
→ immutable candidate → 承認済みstaging/exact-head CI → original strict＋real ZIPのGET検証
→ 外部発行one-run envelope → narrow publication（新しい承認時のみ）→ GET receipt
→ observer/controllerだけrestart、duplicate NOOP、新規model dispatch0。

## Local実測と回帰

- WSL Ubuntu、subscription loginはChatGPT。選択modelはgpt-6.1-sol。
  API key/base URLの環境selector0、selected providerのcustom API route/fallback設定0。
  quotaはUNKNOWNで、EXHAUSTEDと判定しない。起動直前に再確認が必要。
- 元の固定Python/Gitleaks imageをpull=neverで使用。nonroot、network none、readonly
  root/source/candidate、cap drop ALL、no-new-privileges、CPU2/256MiB/PIDs64/tmpfs64MiB。
  実コンテナ内の隔離確認と新しい14件を実行、PASS。provider/model0。
  新しいverifier job入口自体も実Dockerでsyntax/tests/scanner 3コマンドを通し、
  元のstrict readerへ接続した。入力とGit/CI provenanceは明記したSTATIC fixtureで、
  actual real candidate qualificationには使用していない。
- このWSLには常設`/usr/bin/node`がない。offline暗号試験は既存cached imageから
  Node binaryだけを一時抽出して使用した。image entrypoint/container/providerは起動せず、
  新しいpull・install・設定変更0。本番はoperatorがNode path/hashを明示pinする必要がある。
- Production ledger `codex/symphony-g5-proof-ledger`のHEADは
  `1e7333caf91c556a48f423a802c48678962e1cbc`。54 GET/queryで正規store/hostへ復元。
  G5はSTARTED unresolvedのまま、G5.1はTERMINAL UNKNOWNのまま。
  historical campaign checkpointがないためadviceはHOLD。存在しないDONEを作らない。
- 保護規則4 endpointは403でUNKNOWN。metadata protected:falseを「規則なし」と扱わない。
  課金・公開範囲・設定を変更しない。所有者/identityは独立GET/queryで確認。
- Focused 420 PASS、full 2200 PASS（skip1）、Node crypto 8 PASS、Docker新規境界14 PASS。
  wrong digest/audience/issuer/workflow/actor/run/attempt/expiry/signature/payload/replayを検証。
  compileall、diff、秘密スキャン、固定upstream patch check、歴史manifest検証はPASS。
- Official Symphony pin be10a1b79df723d6d7612b5651c8522704dafb2e。
  observer patch SHA256 404b4001d279351c8b800816142862ee47dfd209615b0f9211fbe6ccc5170f3b、無変更。
  scheduling/polling/continuation/retry/backoff/stall/concurrency/workspace lifecycleの変更0。

## 証拠と承認境界

`docs/evidence/symphony-prelive-convergence/`に全文work orders、machine gates、
checkpoint、実機readback、試験ログgzip、公開metadata/JWKS、SHA256 manifestを保存。
過去G4/G5/G5.1記録・refs・manifestは無変更。古いCI/source bytesは元の8bfe01b...
commitを用いて認証し直す。新しい現行source/evidenceは新しいmanifestで照合する。

このcommit自身のHEADとexact-head CIのrun/jobs/steps/log/artifact/digest・remote blob一致は、
push後のPR343 final receipt `prelive-convergence-final-998806e722`に保存する。
commit前のCIを最終HEADのPASSとは記載しない。baselineのterminal CIは再実行しない。
Windows永続証拠: work/prelive-convergence/20261011T013220Z-998806e722。

future-proof.jsonはdeterministic proposalでIssue/ref/workspaceを作成していない。
最大worker lifetime1、publication CAS1、observer restart1（追加model0）、approval NONE。
実worker、実成果、OIDC本番発行、Git Database POST/updateRefs、proof Issue/ref、main、
Merge、Secrets/権限/設定/課金変更はすべて0。

**人間に必要な一括判断:** exact-payload issuer、exact-candidate verifier/staging、
既存credentialのoperator限定capabilityと独立rules確認のレビュー・接続方針を承認する。
新しい鍵・課金・権限拡大を既定の解決策にしない。その接続が実機で成立した後に、
fresh identityと対象HEADを読み直して一回LIVEの範囲を別途承認する。
現時点ではREADY_FOR_ONE_RUN_LIVE_EXCEPT_EXPLICIT_APPROVALを証明できない。
