# Jules Controller Operating Guide

Status: current carrier-branch controller operating policy.
適用: Chat主導のJules半Loop / Cloud WORK Loop。将来のClaude-origin AUTO runtimeを変更しない。

## 1. 正本と読む順序

mainの [development router](https://github.com/kamiyusense/multi-ai-council-phase0/blob/main/docs/DEVELOPMENT_EXECUTION_ROUTER.md)
→ main workflowの `push.branches` からcurrent Jules carrierをfresh discovery
→ carrier上の [Color Lane](JULES_PARALLEL_COLOR_LANES.md)
→ [Semi-Auto](CHAT_JULES_API_SEMIAUTO.md)
→ [Task Prompt](JULES_TASK_PROMPT_SPEC.md)
→ このGuide、task固有仕様、current claims/commands/work branch/target HEAD/tree。

このGuideはControllerの判断・適応運用の詳細正本。dispatchのschema、claim、
workflow、Cloud Work protocolや安全仕様は各々の正本を読む。
旧Chat、PR番号、固定SHA、前回のworker選択は現在の実行権限にならない。

## 2. 役割と通常の候補

| 担当 | 役割 |
| --- | --- |
| Chat / Controller | fresh read、bounded task設計、独立検品、PASS / FAIL / UNKNOWN、明白で安全な小修正、test、integration、routing、canonical publication判断 |
| Jules | 通常のbounded code / tests / docs実装。通常missionはMEDIUMを基準に評価 |
| Cloud WORK | 広いcontext・強い相互依存を一括処理する方が安全なcloud-safe missionを担当。権限や安全境界は拡張しない |
| Local Work | PC固有資源が必要な場合のみ。Controllerが完成済みpromptをユーザーに渡し、ユーザーが貼る |

通常の**新規mission**はJulesを標準候補にする。
`default_candidate = JULES` は「必ず一度Julesへdispatch」ではない。
明白なsmall repairはControllerで行ってよい。通常MEDIUMの実装を理由なく
Chatが大規模に抱えたり、WORKへ流したりしない。

ユーザーがWORKを明示した場合は、その指示の範囲とcloud-only能力境界を確認する。
Windows/WSL filesystem、local checkout、Docker Desktop/daemon、local terminal、
desktop GUI、local credential/volumeが必要なら**どのCloud Work laneにも送らない**。
main routerの完全な🔵Local Work prompt経路を使う。勝手なLocal Work handoffは禁止。

## 3. 独立検品FAIL後の必須判断順序

FAILを見つけても直ちに新Jules correctiveを出さない。

1. requirementと実際のdiff/test/evidenceを照合し、失敗原因を具体化する。
   typo/docs、assertion、fixture、import、deterministic value、path fence、
   localized validation/logic、semantic/test design、architecture、
   broad cross-file correction、unknown requirementを区別する。
2. 第4節のController-safe small repairが可能か先に判断する。
3. 可能なら最小修正し、第5節の検証を終えてからPASS/採用を判断する。
4. 不可能なら第6節のJules corrective、または第9節のWORK適性を評価する。
5. requirementや安全境界が不明ならUNKNOWN/BLOCKED。worker変更で不明点を隠さない。

environment/evidence取得不能を実装FAILと混同しない。
「FAIL = 必ずJules再投入」は禁止。

## 4. Controller-safe small repairの条件

次を**すべて**満たす場合、Controller修正を優先する。

- 修正意味が仕様から一意またはほぼ一意に決まる。
- authorized non-default branchで、明示されたallowed paths内。
- 小規模で、unrelated refactor・architecture判断・主要設計の作り直しが不要。
- live/provider/billing/permission/credential境界を触らない。
- focused/direct testと必要な全体検証で独立に確かめられる。
- fail-closed semanticsや正式acceptanceを弱めない。
- 既存のclaim、command、session、履歴を改変して合格に見せかけない。

典型例: typo、docs短文、assertion文言、fixtureの明白な誤値、import漏れ、
deterministic timestampの誤り、数行のvalidation条件、仕様から一意なnegative test、
局所的vacuous test修正。

unauthorized extra fileだけが問題なら、原Jules成果を証拠として残し、
fresh targetから許可済みintegration candidateを作り、allowed contentだけを安全に
再構成できる場合に限りControllerでsalvageしてよい。source/resultを破壊したり、
未検証変更を混ぜたり、ancestry/lineageを偽装したりしない。再構成が許可されず、
安全なdiff/lineageを説明できない場合はUNKNOWN/BLOCKED。

## 5. 修正したController自身にも必要な独立検証

`focused test → full required test → semantic review → diff →
exact candidate HEAD/tree → remote readback → publication gate`

- requirementからdiffを読む。Julesの自己申告も自分の修正もPASS根拠にしない。
- 修正後のexact HEADでnegative case・path fence・必要なtestsを確認する。
- full required testはmissionで指定した必須suite。無関係な大規模suiteを追加し続けない。
  docs-onlyならlink/path/diff検査が適切。code変更はfocused testだけでfull required testを代替しない。
- before/after SHA、changed paths、failure cause、修正理由、実行したtests/results、
  semantic acceptance、lineage、残るUNKNOWNをsecret-free evidenceに残す。
- canonical targetをfresh readし、ancestry、許可paths、semantics、tests、
  fast-forward安全性を再確認する。canonical採用は1件ずつ直列。
- 並列laneがtargetを進めたら古いbaseのまま採用しない。publication後もremote readback。

Reviewerが局所修正をしただけで独立性を失うわけではない。
独立性は、自己申告に依存せずrequirementと直接の検証証拠から判断することにある。
大規模な意味論を書き換える必要が出たら、workerへbounded missionとして分離する。

## 6. Julesへcorrectiveを戻す条件

substantial implementation、多数fileへの波及、architecture/design判断、
複数の妥当解、mission再設計、allowed paths再設計、clean base再実装の方が安全、
またはControllerが最小修正の正しさを確信できない場合はJules corrective候補。

current task制限がdesign判断を人間に留保していれば、人間判断をworkerへ丸投げしない。
Julesに適したbounded correctiveでない場合はWORK適性またはBLOCKED/redesignを評価する。
既存claim/commandを再送しない。correctiveは原因分析・fresh task設計・current権限のもとで
新しいclaim/command/isolated branchを持つ別missionであり、transport retryではない。

## 7. Adaptive task sizing

| 判断 | size class / 表示 |
| --- | --- |
| 明白で小さい独立task | SHORT / 短 |
| 通常のまとまったbounded mission | MEDIUM / 中（基準） |
| 大きいがgoal・allowed paths・acceptance・terminal pointが明確 | LONG / 長も可 |
| 分割で整合性が壊れる、広いcontextが不可欠 | sizeを無理に縮めずWORK適性を評価 |

MEDIUMは通常基準であり固定値ではない。sizeを満たすために別missionを混ぜない。
one missionを常に最小taskへ砕く必要はない。
難所で一時MEDIUM→SHORTにした場合、その難所PASS後は**次の通常missionのsizeをfresh評価**。
過去FAILやlane設定を理由に永久SHORTへ固定しない。LONG禁止・MEDIUM絶対固定も禁止。

## 8. Repeated FAILとprompt改善

同一missionでJules correctiveが**2回以上**続いたら、3回目を機械的に出す前に
原因分析を必須にする。FAIL種別・対象requirement・改善履歴をGitHub evidenceから読む。
回数だけで自動WORK化しない。

確認する点:
task過大、prompt曖昧、複数mission混在、allowed paths過大、Read first不足、
negative cases不足、validator到達条件不明、reuse-first/Do Not Touch不足。

対処候補:
prompt具体化、mission分離、paths限定、具体的negative cases/direct assertions、
一時size縮小、Controller small repair、WORK escalation。
同じ文面を再送せず、何を改善したか説明する。
難所をPASSしたら通常missionを改めてMEDIUM基準から評価する。

## 9. WORK escalationと事前選択

WORKは**現在のmissionでJulesより安全・効率的に進められる具体的理由**があるときに選ぶ。
能力・利用可能性とcloud-safe範囲はfresh確認する。
`work_escalation_reason` はController evidenceに短く記録し、protocolへ新fieldを勝手に追加しない。

候補となる条件:
- 同一missionで2回以上の同種/近接したsemantic FAILが続き、
  prompt改善・size縮小でも本質的理解不足が続く。
- docs/code/tests/state/protocolを横断する多数fileの強いcoupling。
- migration、多段state transition、複数仕様の同時整合、大量context比較。
- 自然なMEDIUM分割でsemantic assumptionsや前後整合性が失われる。
- Controller small repairで収まらず、広いcontextを一括処理する価値が高い。

上記が事前に合理的に説明できれば**最初からWORKを選んでよい**。
Julesを必ず一度失敗させる必要はない。広大なmissionもbounded goal /
allowed scope / terminal conditionは維持する。

単独のtypo、docs数行、import、fixture、assertion、単純path fence、
localized validation、通常MEDIUM、Julesの1回FAILだけ、
Controllerが安全に直せること、少しのprompt改善で足りることは、
原則としてWORK escalation理由にならない。
WORK利用枠を節約し、Julesで十分な仕事を理由なくWORKへ送らない。

## 10. Fresh routingとWORKをstickyにしない規則

新規mission:
`fresh read → complexity/coupling/権限/能力を評価 →
Controller small repair / Jules / WORK / Local Work / UNKNOWN`

Jules result FAIL:
`small repair可能? → YES: Controller修正と検証 →
NO: prompt/size改善でJules継続が合理的? →
YES: Jules corrective → NO: WORK適性? →
YES: WORK → NO: BLOCKED / HUMAN / redesign`

毎missionごとにJulesを標準候補へ戻してfresh routingする。
`previous_work_choice_is_authority = false`
`fresh_work_escalation_reason_required = true`

「前回WORKだった」「WORKが成功した」「直前Julesが失敗した」
「一度そのlaneを使った」「WORKの方が楽」だけでは継続しない。
**routing reset != forced Jules dispatch**。
WORK終了後に形式的なJulesの1taskを挟むことは禁止。
fresh評価でWORK条件が継続するなら連続WORKが正常。

## 11. WORK連続利用と同じ難所のterminal point

次missionも次を満たすなら、fresh理由として記録しWORKを連続利用してよい。

- 前missionと強く結合した難所の続き。
- 同じmigration/protocol transitionの次section。
- 広いcross-file contextを保持する価値が高い。
- Julesへ戻すと不自然な細分化や前後整合性喪失が起こる。
- 次mission単独でも第9節の条件を満たす。

同じ難所のbounded WORK batchは安全なterminal pointまで同じWORKで扱ってよい。
形式的なWORK→Jules→WORK往復を強制しない。
batchは無制限に拡張せず、scope/terminal point変更にはcurrent権限の再確認が必要。
terminal receipt済みcommandを続行/再送しない。別missionはfresh targetと新command identity。
通常の独立docs/testsへ移ったら、fresh評価でJules向きならJulesを選ぶ。

## 12. 色の維持と別control plane

assigned heart colorがあるControllerはWORK escalationでも原則同じ色を維持する。

| Jules lane | 対応するCloud WORK |
| --- | --- |
| ❤️ J-RED | ❤️ Red |
| 💙 J-BLUE | 💙 Blue |
| 💛 J-YELLOW | 💛 Yellow |
| 💚 J-GREEN | 💚 Green |

明示されたCloud Work色は尊重し、assigned colorがなければmain routerのdefaultを使う。
色はrouting/presentation metadata。correctness evidenceではない。
Julesのglobal Loop claim / command / session / work branch / exact HEAD/treeと、
WORKのcarrier / worker generation / command / terminal receiptは**別control plane**。
WORK利用でJulesのclaimを再利用・変更しない。番号をlaneごとに採番しない。

Cloud Work dispatch/recoveryはcurrent mainの
[4-lane index](https://github.com/kamiyusense/multi-ai-council-phase0/blob/main/docs/CLOUD_WORK_LANES_INDEX.md)
からselected labelのOPEN carrierを一意にfresh discoveryし、protocol/state/reviews/
receiptsとtargetを読む。0件/複数/identity不一致はUNKNOWN、dispatchしない。
同じ色だからgenerationやsessionが共通だと推測しない。

## 13. ETAはhuman planning hint

ユーザーの推定完了目安は「何時ごろ結果を見に戻ればよいか」の非保証planning hint。
Jules公式SLA/remaining-time APIではない。
**official ETA absence alone != UNKNOWN**。

accepted Jules session/timeがverifiedで、dispatch状態がknown、task sizeを合理的に
分類できる通常bounded taskなら、原則レンジを表示する。
priority:
1. 同種・同程度の最近のverified Jules taskの実測。
2. 同sizeの最近のverified実績。
3. 実績不足なら下記の保守的初期レンジ。

| 初期heuristic（実測値ではない） | acceptance後の結果確認目安 |
| --- | --- |
| SHORT / 短 | 10〜20分 |
| MEDIUM / 中 | 20〜40分 |
| LONG / 長 | 40〜90分 |

これらは初期planning policyとして設定した値で、実績が得られたら優先順位1/2を使う。
過去の所要時間と称してこの表を使わない。遅延が予想されれば根拠を記録してレンジを広げる。
過去タスクのsize/開始/結果参照先が不明なら実績に混ぜない。

実測はverified session accepted timeから最初の検品可能な結果が得られるまで。
completion/result availabilityのtimestampとsession/result identityを記録する。
pollingの確認時刻しかない場合は観測上限として扱い、正確な完了時刻を捏造しない。
Controller検品・修正・canonical直列採用の時間はJules task ETAと区別する。

Controller evidenceに `eta_basis = historical estimate | heuristic estimate`、
使用した実績または初期range、size、verified accepted_at、`non_guaranteed = true`
を記録する。command/claim schemaやcorrectness authorityにETA fieldを追加しない。
短いユーザーfooterではレンジと「ごろ」で示し、保証ではないことを必要時本文で説明する。

例: accepted_at=03:20 JST、MEDIUM、最近の類似task実測15〜30分
→ 推定完了目安03:35〜03:50ごろ。
初期MEDIUMを使う例なら03:40〜04:00ごろ。同じ「実測」として説明しない。

受付時刻はcommand commit/Action queue/現在時計ではない。
current workflowのverified Jules Session GET `createTime` readback等、正式なprovenanceを読む。
session IDがあるだけで受付時刻を推測しない。
既存 [Semi-Auto entry](https://github.com/kamiyusense/multi-ai-council-phase0/blob/main/docs/CHAT_JULES_API_SEMIAUTO.md)
のJST・heart lane・global Loop・size・last-line footer規則を維持する。
予定時刻を過ぎたらfresh resultを確認し、未完了なら遅延とレンジ見直しを報告する。
ETA到達だけでCOMPLETE/PASS/次dispatchと判断しない。

## 14. UNKNOWN / BLOCKED境界

ETAをUNKNOWNにする主な条件:
- acceptanceまたはその時刻の証拠が確認不能。
- submit/dispatch状態がUNKNOWN。
- task sizeを合理的に分類不能。
- 通常bounded taskでなく予測レンジを示す意味がない。

公式remaining-time ETAが無いだけならUNKNOWNにしない。
accepted_atがUNKNOWNなら投入時刻もレンジもinventしない。
verified受付と未確認completionを混同しない。

routing/repairはtarget identity、requirement、権限、能力、安全境界、証拠が不明なら
UNKNOWN/BLOCKED。live/billing/permissionは人間の明示承認境界を維持する。
workerが合わなければBLOCKED/HUMAN/redesign。毎回無理にworkerを選ばない。

## 15. 維持する安全契約

- retry=0、fallback=disabled。曖昧write/submitはremote readback、盲目的再送しない。
- exact target HEAD/tree、non-default isolated work branch、create-only schema-v3 claim、
  global Loop namespace、append-only command、one Jules REST submitを維持。
- Jules tasksはparallel可、workflow API dispatchはcurrent concurrencyで直列、
  canonical publicationは独立検品後1件ずつ直列。
- Cloud Workはcurrent protocolのexact target HEAD、generation fencing、unique command、
  matching terminal receiptとcloud-only能力境界を維持。
- Mergeは自動化しない。main/default直接write、force push、branch delete、history rewrite、
  Billing/Credits/Overages、API key作成/表示/変更、permissions/settings変更は禁止。
- current user restrictionと正式安全仕様がこのGuideより優先する。
  適応運用は権限・live・安全条件を緩めるものではない。

## 16. 具体例

| 状況 | 選択 |
| --- | --- |
| assertionの1行誤り、意味が一意 | Controller修正→focused/full required test→semantic review→readback→publication判定 |
| 不要plan.mdだけが追加された | 許可されたclean candidate再構成が安全ならController salvage。元成果は残す |
| negative testの検証層に設計判断が必要 | Jules corrective候補。判断留保ならHUMAN |
| validator難所でMEDIUM FAILが続く | 原因分析・prompt改善・一時SHORT。難所PASS後は次missionのsizeをfresh評価 |
| 多数file/protocol/state/testsの強結合migration | 事前理由とcloud-safe確認でWORK選択可 |
| そのmigrationのcross-file整合修正が続く | fresh評価で同じ難所の理由が成立すればWORK継続可 |
| migration終了後の通常独立docs/test | Julesを標準候補としてfresh選択。MEDIUM基準 |
| WORKが前回成功しただけ | 継続理由にならない。次mission fresh routing |
| WORK後に一度Julesへ戻すためだけのtask | 作らない。forced Jules dispatch禁止 |
| 公式ETAなし、verified acceptanceとMEDIUM scopeあり | 実績または保守的初期rangeで非保証ETA。UNKNOWNに固定しない |

## 17. Controller decision evidence（短い記録）

mission / target HEAD/tree / selected worker / sizeと理由 / failure cause /
small-repair判断 / corrective回数とprompt改善 / work_escalation_reason /
eta_basisとnon-guaranteed / tests・semantic evidence / exact final HEAD /
publication/readback / remaining UNKNOWNを、必要な項目だけsecret-freeに記録する。
schemaの追加や巨大な自動化コードは必要ない。
