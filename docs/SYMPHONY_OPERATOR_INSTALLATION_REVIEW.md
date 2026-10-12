# Symphony operator installation review

Goal: **INSTALLATION_REVIEW_READY / NOT_INSTALLED / LIVE_NO_GO**.
正式指示: PR343 comment6106213810。方針承認はcomment6104967505。
本PRは非稼働の設置候補と具体的な残契約のレビューであり、稼働可能な本番factoryではない。

## PR topology and dependency closure

fresh main `c90392712d0781dd475acd0f65ceb4746c43dc49`、PR320
`8c53c505a21318c6133da0bef85af18ae3711103`、PR343
`794488c3f4a47d328bcf1109e60c71f97ce9aa3c`。
本PRのbaseはPR343 branch、出発commitはそのfresh HEAD。既存PR変更0。
DAG: main → review #320 → review #343 → review this installer → separately reviewed
activation/runtime patch → new one-run authorization。各Mergeは個別承認が必要。
**本PRを直接mainへMergeしてはいけない。** #343 stack全部の導入をこの承認に含めない。

Python dependency closureは36ファイル（31はmainにない）、exact pathは
`docs/evidence/symphony-operator-installation/dependency-closure.json`。
追加Node helper/RS256 helper、信頼済みsource/tests/scanner config、固定imageも同票に記載。
main独立PRならcoreを重複コピーするため、1件のinstall-only stacked Draftを選択。
bootstrap用の競合architecture・新scheduler・mock campaign・coreコピーは追加しない。
mainの最新AGENTSはPR356後の版を読んだが、その無関係な変更は本PRへコピーしない。

## Exact proposed changes

- `.github/workflows/symphony-operator-authorize.yml`: 手動main issuerの非稼働入口。
- `.github/workflows/symphony-operator-candidate.yml`: 手動candidate staging ref検証の非稼働入口。
- `.github/workflows/symphony-operator-installation-static.yml`: read-onlyのPR専用offline検査。
- `automation/command_bus/symphony_operator_installation.py`: pure stageチェックと同一job
  memory-only署名/capability接続。CLIは常にNOT_INSTALLEDで失敗。
- `automation/command_bus/tests/test_symphony_operator_installation.py`: 既存fixtureの負例。
- 本文書、依存表、machine gate、試験証拠manifest。既存transport/verifier/observer変更0。

Runtime workflowはjob `if: false`、contents:readのみ、id-token/write権限0。
入力review_idもPRコメントもADMINも送信許可ではない。
既存Signal workflowはidentity-onlyのまま。提案をmainに置くだけでも稼働しない。
OFF gateを入力/環境変数/フラグで解除できない。activationは新しい具体的差分レビュー。

## A: exact intention, JWT and same-job boundary

既存 `OperatorEnvelopeVerifier` と `GitHubOIDCEnvelopeSignatureVerifier` を再利用。
`attach_same_job` は未信頼dispatch payloadと、別のoperator review channelから取得した
canonical unsigned envelopeの**全bytes一致**を要求。署名・nonce・candidate receipt・
Git object inventory・target ref・old/new OID・ledger scope・CAS最大1を既存契約で照合。
短い期限（最大600秒）と独立pinしたmain job identityもtoken要求前に照合する。
既存create-only storeの承認namespaceへissuer intentを先に保存し、二重起動・曖昧な
fenceはtoken要求0でGET-onlyへ。token callbackの例外に秘密が混ざっても固定エラーに
置き換える。失われたJWTを回復したふりをせず、次の発行は別途reviewが必要。

将来のreview済み**同一job/process**からopaque `token_once(audience)` を注入。
JWTは一度だけメモリで受け、既存RS256/JWKS/claims verifierを通して限定transportへ。
JWTをenv/argv/artifact/log/file/Issueへ移さない。公開JWKSは独立GET・kid/issuerをpin。
返すauditにはJWT/signature/payloadなし。既存adapter内メモリ以外へ署名を輸送しない。
factoryは別途review済み明示注入のみ。構築自体は自動publicationを実行しない。

**未実装・設置審査の必須契約:** reviewed intentionをmain側から独立取得する実reader、
同一jobのOIDC request implementation、job contextの独立runtime readback、credentialと
台帳storeの実注入。ここをdispatch入力の自己hashやfixtureで代用していない。
したがって本PRはworking production issuer/credential factory READYとは主張しない。

## B: truthful exact-head staging strategy

GitHub公式ではworkflow_dispatchのSHAは**dispatchを受けたrefの最終commit**。
workflowはdefault branchに存在する必要がある。
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch
https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow

将来、operatorが承認した新規非default `codex/symphony-stage-<correlation>` へ実候補を
create-onlyでstageし、そのrefへ手動dispatchする。mainへdispatchして別checkoutする
方式、pushでcandidate-controlled YAMLを自動実行する方式は使わない。
run.head_shaがcandidate.commitと一致することは、実行後の独立GETで最終検証する。
今回staging/ref/dispatchは0。refが既存なら一致時もGET-only、競合ならupdate/deleteなし。
leaseは期限・expected parent・source commit・candidate commit・artifact path・1 dispatch。

**dispatchより前**に独立operatorがcandidate Git全objects/hashを検証し、candidateの
全baseline bytes（全workflow/actions/コード/tests/config含む）がreview済みimmutable
sourceと一致し、唯一の`proofs/` approved artifactだけが変更可能なことを要求する。
検証用YAMLもimmutable baselineに存在・完全一致必須。書き換えYAMLによる自己検品拒否。
候補を取得してからcandidate内コードを起動して検証する順序は採用しない。

future activationはreview済みsource SHAを**固定**checkout（persist-credentials:false）し、
既存 `run_real_verifier_job` に独立pins/contracts/readersを渡す。candidateはread-onlyの
network:none/nonroot/cap-drop/readonly Dockerへ渡す。Node/image/config/tests pinは元の
承認済み固定値を再利用。候補のtest selector・hooks・credentialは実行/共有しない。
strict attestationとreal-format synthetic:falseの2JSONだけuploadし、最終GitHub ZIPを
独立GETでhash確認。local ZIP hashをupload後のarchive hashと同一視しない。
`OperatorCandidateVerifier.read()`のrun/job/steps/head/archive検査を一切緩めない。

**未実装・設置審査の必須契約:** approved stage operator/lease保管、default上のreview済み
workflow、exact trusted source pinと独立run/job/input readerのruntime。実worker前の
candidateは存在しないためREAL_CANDIDATE_NOT_RUN。YAML入口は意図的にOFF、偽の
successful verifierにはしない。実workflowのpost-merge discovery/dispatch/head証明も未実行。

## C: narrow capability and effective permissions

既存 `OperatorCapabilityBoundGitTransport` が必要な3固定メソッドを提供済みなので、
別writerを増やさない。old STATIC transport guardは変更0。nonce/intention/lock/ref fence、
force:false CAS最大1、create-only ledger、lost-reply GET recoveryは既存を再利用。
GitDatabase POST/updateRefs/API credential acquisitionは実装callbackを今回注入しない。

GitHub native job tokenはrepo scopeで、contents:writeはapp内allowlistによるref限定と
同義ではない。OIDC id-token:writeも成果write許可ではない。候補検証jobにはreadのみ。
issuer/限定senderを同一trusted jobにする案でも、contents:write追加には独立レビューが
必要で、最初から設定しない。GitHub Appを新設する場合は新secret/設定審査が必要で
今回の既定案にはしない。既存認証のmetadataと実送信許可を混同しない。
必要endpointはplan-listed POST /git/blobs・/git/trees・/git/commits、exact nondefault
GraphQL updateRefs(beforeOid,afterOid,force:false)、approved ledger branch/pathへの
Contents PUT（shaなしcreate-only）とそのGETだけ。GitHub token自体をbranch限定と
偽らない。Contents permission、workflow-code変更に関係する別権限、effective rulesを
独立審査し、汎用REST/GraphQLをモデルへ渡さない。
REST403のrules/protectionはUNKNOWNのまま、protected:false/ADMINでPASSにしない。
既存tokenを自動取得せず、approved existing operator capabilityの注入先を審査する。

## Installation/activation sequence and final boundary

1. #320/#343依存を独立審査。重複コピーなしのmain統合方針を決定。
2. 本DraftのOFF入口・接続seam・trust/rules/least-privilege契約を一括審査。
3. 個別Merge承認後もOFF。別のactivation diffで実reader、memory-only OIDC callback、
   approved credential/store、immutable source pin、stage/operator lease/rulesを接続。
   必要権限の追加やcredential使用はその具体的レビューまで実施しない。
4. 技術readinessを独立確認後、fresh Issue/campaign/workspace/ref/HEADで一回LIVEを別承認。
   自律continuation/retry/backoff/stall/concurrency/cleanupはOfficial Symphonyに任せる。

このDraftはレビュー可能な**非稼働設置候補**。人間の次の一括判断は上記依存順・OFF
設置差分と最小GitHub能力の独立審査(A)。稼働化・LIVE identity/proof/write scopeは別審査(B)。
本タスクではMerge/main/Secrets/settings/permissions/billing/OIDC/worker/staging/adoption/send0。
試験・CI・remote bytesはevidenceと本PRの最終checkpointでexact HEADごとに記録する。
