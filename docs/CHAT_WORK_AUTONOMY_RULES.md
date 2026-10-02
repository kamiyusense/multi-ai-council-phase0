# Chat ⇄ Work 長時間自律実行ルール（全自動コピペ卒業マシーン / Phase 0統合版）

更新: 2026-09-21  
適用先: `kamiyusense/multi-ai-council-phase0`

> この文書はPhase 0開発の**運用ルール**であり、Council正式原則・Phase 0安全仕様・ChatGPT/Codex本体の承認機構を上書きしない。

## 0. 目的

ユーザーを「進捗確認係」「伝書鳩」「手動コピペ係」にしない。

標準は次とする。

```text
大きな安全バッチ
→ 検証
→ 証拠保存
→ 残りの安全作業も継続
→ 本当に必要な場合だけChatへ相談
→ 返答を安全に取得できた場合は同一Work内で続行
→ 安全作業を使い切ってからまとめて報告
```

## 1. 優先順位

衝突時は次を優先する。

1. プラットフォームの安全機構・承認ダイアログ
2. Multi-AI Council正式原則
3. Phase 0実装仕様・安全境界
4. この運用ルール
5. 個別作業上の軽微な最適化

この文書を理由に、課金・権限・live実行・GitHub境界を迂回してはならない。

## 2. Work利用条件

### 2.1 開発worker選択

[canonical execution router](DEVELOPMENT_EXECUTION_ROUTER.md) が現在の開発worker選択の正本。
旧「Chat-first / Work fallback」は開発worker選択についてsuperseded。
ChatはGitHubのfresh readback、独立検品、設計、次タスク作成、PASS / FAIL /
UNKNOWN判定と人間のMerge境界を維持する。FAIL後は安全な小修正を先に評価し、
修正したChat自身もtest・semantic review・exact HEAD・remote readbackで検証する。
詳細はdiscovered carrierの [Controller Operating Guide](https://github.com/kamiyusense/multi-ai-council-phase0/blob/feature/chat-work-command-bus/docs/JULES_CONTROLLER_OPERATING_GUIDE.md)。

- 通常のGitHub実装・test・docs変更: Chat-driven Jules半Loopをデフォルトにする。
- 明示されたCloud Work色laneはそのlaneへ。緑LINEはGreenを指定する。
  色指定なしのWorkやJulesに不向きなcloud-safe missionへのescalationは
  assigned heart colorを維持し、色未選択の場合のみGreenをdefaultとする。
  [4-lane・交換索引](CLOUD_WORK_LANES_INDEX.md)から選択laneのcarrierを一意に
  fresh discoveryし、protocolとworker-stateを確認してから送る。
- Work交換・故障・再作成は同索引からChatGPT support manualを先に読む。
  PR番号・generation・SHA・automation IDをユーザーの記憶に依存させない。
- Windows/WSL/Docker/ローカル認証情報などPC固有資源が必要な場合:
  Green laneを使用せず、GitHub側で可能な確認後、ユーザーがそのまま貼れる
  完全なLocal Work用指示文を
  「## **🔵【以下をLocal Workへそのまま貼り付けてください】**」
  の見出しと1つのコードブロックで渡す。ChatからLocal Workへ勝手にhandoffしない。
- identityまたは能力を確認できない場合: UNKNOWN、dispatchしない。

WORKを前回使ったことだけで次もWORKにしない。毎missionでfresh routingし、
Julesを標準候補へ戻す。routing resetはJulesへの強制dispatchではなく、
難所・強結合などのWORK条件が続けばbounded WORKの連続利用を認める。

これらのworker選択は、Work内の自律処理ルールや将来のClaude-origin
AUTO Loopのruntimeを変更しない。

### 2.2 現在の既知制約
Windows環境でProject → local Work handoff時に

`Could not use this project for a local chat`

が発生した実績がある。

そのため:
- Work利用可否を推測しない
- 同じhandoffを理由確認なしに再試行しない
- Local Workが使えなければUNKNOWNとして、安全なGitHub確認とrouterに従う他の独立作業だけ継続
- reply retrieval不能は `UNKNOWN`
- ユーザーが明示的に再試験を指示するまでChat側から勝手にWorkへ飛ばさない

## 3. Safe-Work Exhaustion

既に許可された目的・範囲内では、追加確認なしで安全作業を使い切る。

途中確認不要の代表例:
- read-only確認
- Project内整理
- 静的解析
- 可逆なローカル編集
- コード修正
- fixture / unit / regression test
- mock / dry-run
- syntax / schema check
- prepare-only
- artifact / ZIP / SHA-256
- log / evidence整理
- README / DESIGN / RECOVERY / KNOWN_LIMITATIONS更新
- modelを起動しない検証
- 既存成果物の再検品

単なる進捗区切りで「続けますか」「次に進みますか」「実行してよいですか」を聞かない。

Chat/ユーザーへ戻る前に、現在の権限・情報・安全条件だけでまだ安全にできる作業がないか確認する。残っていれば続行する。

## 4. Blocker Isolation / Deferred Decisions

1つのsubtaskがblockedでも、独立して安全に進められる作業は先に完了する。

判断事項が安全作業を妨げない場合は `Deferred Decision` として保留し、可能なら以下を記録する。

```text
decision_id:
内容:
判断が必要な理由:
選択肢:
安全なdefault:
影響範囲:
```

安全なdefaultがあり上位ルールに反しない場合は採用して続行してよい。

ただし次はdefaultで進めない:
- 課金
- 権限変更
- 不可逆操作
- GitHub Merge
- live外部model turn
- アカウント状態変更
- 安全性UNKNOWNの操作

軽微な曖昧さは最も保守的・可逆な解釈で進める。重大な危険や誤りにつながる不明点のみUNKNOWNとする。UNKNOWNがあっても独立した安全作業は続ける。

## 5. Evidence / Completion / Checkpoint

AI自身の「完了」「PASS」だけを証拠にしない。

可能な範囲で:
- test
- fixture
- parser
- diff
- hash
- artifact
- readback
- log
- receipt
- direct inspection

を取得する。

証拠が取れなければPASSと推測せず `UNKNOWN` とする。

長時間作業では途中経過を逐次Chatへ送らず、可能ならartifact / log / state / checkpointへ保存する。

checkpointには可能な範囲で以下を含める。

```text
completed:
remaining:
PASS:
FAIL:
UNKNOWN:
artifact:
hash:
blocker:
deferred_decisions:
next_safe_work:
live_turn_executed:
git_checkpoint:
```

## 6. Work Batch Length

1回のWorkは可能な限り大きな安全バッチにする。

```text
調査 → 実装 → test → 修正 → 再test → artifact → hash → 再検品
```

工程数ではなく、人間へ戻る必要性で区切る。安全作業が残る限り同一Workバッチ内で続行する。

## 7. send_message_to_thread

利用可能なWork環境では各小工程ごとに使わない。

原則:
```text
安全なローカル作業を使い切る
→ 証拠を揃える
→ Chat判断が本当に必要なら1回送信
```

1 Workバッチにつき原則1回以下を目標とする。

送信内容:
- 実施内容
- PASS / FAIL / UNKNOWN
- artifact / SHA-256
- blocker
- Deferred Decisions
- 次に必要な判断
- ユーザー操作の要否
- live turn実行有無

ChatGPT/Codex本体の承認ダイアログは回避・代理承認・自動クリックしない。

## 8. Work主導 Closed Loop

WorkがChatへ相談し、その返答をWork自身が安全に取得できた場合は、Chat→Workへの新しい手動配送を待たず、その返答を同一Work内の次指示として扱ってよい。

推奨フロー:

```text
Workで安全作業を使い切る
→ Chat判断が必要なら1回送信
→ Chat返答完了を待つ
→ Work自身が返答を取得
→ thread / round / correlationを確認
→ 安全な指示なら同一Work内で次バッチへ進む
```

## 9. 最大6ラウンド

1ラウンド:

```text
Work安全作業1バッチ
→ Chatへ1回送信
→ Chat返答を1回取得
→ 安全なら続行
```

1回の開始につき最大6ラウンド。6は目標ではなく上限。1〜2ラウンドで完了するなら終了する。

## 10. Reply Retrieval Safety

返答取得時は可能な範囲で:
- thread
- round
- correlation / receipt
- 返答内容整合性

を確認する。

以下では推測して続行しない:
- 返答が空
- 取得不能
- thread不一致
- correlation不一致
- 返答内容を検証できない

その場合:

```text
UNKNOWN:
reply retrieval unavailable or unverified
```

として停止する。同じmessageを取得失敗だけを理由に自動再送しない。

## 11. Retry Policy

理由確認なしの自動retryは禁止。

特に:
- message配送
- 外部サービス操作
- live relay test
- GitHub操作
- permission操作
- billing関連
- provider live turn

失敗したように見えても、成功済みの可能性があればreadback / log / receipt / hash / backend stateを先に確認する。確認不能ならUNKNOWN。

## 12. Relay / app-server開発

このProjectではChat ⇄ Work自動連携およびRelay / app-serverの研究・静的実装を行ってよい。

追加確認なしで可能:
- app-server仕様調査
- Relay設計
- SQLite ledger
- mock client
- fixture
- dry-run
- duplicate guard
- state machine
- receipt / correlation設計
- disposable thread用テストコード作成
- artifact作成
- parser / validator
- static integration test

ただし、外部controllerから
- `thread/resume`
- `turn/start`
- その他の新しいbackend live turn

を開始するPOCはユーザーの明示承認なしに行わない。

live POCでは:
- 本番重要threadを最初から使わない
- 可能な限り捨てthreadを使う
- UI表示だけで配送成功と断定しない
- backend readback / turn情報 / receiptで確認する
- exactly-onceを推測しない
- 不明ならUNKNOWN
- 自動再送しない

## 13. System Approval Boundary

「許可を求めない」は、AI自身の不要な確認質問を減らす意味である。

システム承認が必要な場合は:
- 回避しない
- 代理承認しない
- 自動クリックしない

## 14. 自動で停止する操作

以下は自動実行しない:
- API従量課金につながる操作
- Billing / Credits / Overages変更
- API key作成・変更・表示
- settings / permissions変更
- 管理者権限取得
- 未承認範囲のGitHub write / commit / push / PR、および承認のないMerge
- branch削除
- remote変更
- force push
- 不可逆な削除
- 重要データ上書き
- 新規外部サービスへの送信
- アカウント状態変更
- 未承認のlive relay / app-server POC
- 未承認のprovider live turn
- 安全性UNKNOWNのまま危険操作へ進むこと

### 14.1 明示承認済みGitHub開発範囲の例外

ユーザーが対象repositoryと境界を明示承認した場合、その範囲内のGitHub開発作業は行ってよい。

**現在のPhase 0 repositoryに対する承認境界は「PRまで」。**

現在許可:
- 専用feature branchへのwrite
- commit
- push / branch update
- PR作成・更新

現在不許可:
- Merge
- force push
- branch削除
- unrelated repoへのwrite

これはPhase 0 runtime自身のGitHub write禁止とは別概念。

## 15. Approval Bundling

ユーザー判断が複数ある場合、安全上可能なら最後にまとめる。

可能なら:
- 何をするか
- なぜ必要か
- 外部副作用
- 課金可能性
- 可逆性
- 対象

を明示する。

承認が最後に必要な場合、その直前まで安全作業を先に完了する。

## 16. 最大6ラウンド到達時

停止して、可能な範囲で以下を1回にまとめる。

- 完了したこと
- 現在状態
- PASS / FAIL / UNKNOWN
- artifact path / SHA-256
- Deferred Decisions
- blocker
- 次の安全作業
- ユーザー操作の要否
- live turn実行有無
- GitHub checkpoint / commit SHA

## 17. 表示ルール

引き継ぎ・ユーザーが貼る完成promptは、全Chat・Work共通の
[コピー文章の必須表示規則](USER_COPY_TEXT_FORMAT.md)に従う。
全文を1つの `markdown` コードブロックで出し、次の引き継ぎにも継承する。
別の文章編集UIや、章ごとの複数ブロックで代用しない。

- 🔴 = 必読・危険・停止・重大注意 / 上位モデル推奨
- 🟡 = 注意・不確実 / 一部上位モデル推奨
- 🟢 = 問題なし・進行可能 / 現モデルで十分
- 🔵 = ユーザーがそのままコピペする文章専用。直下にコードブロック
- 🟠 = ユーザー本人の操作・確認・承認待ち

ユーザー操作:
```text
# 🟠【ユーザーの操作が必要です】
```

重大・不可逆・課金・権限変更:
```text
# 🔴【ユーザーの操作が必要です・ここで停止】
```

モデル表示:
```text
# 🟢【このモデルのままでOK】
# 🟡【ここだけ上位モデル推奨】
# 🔴【モデルを上げた方がいい】
# 🟢【ここからモデルを下げてOK】
```

## 18. 役割境界

worker選択と復旧手順は
[canonical router](DEVELOPMENT_EXECUTION_ROUTER.md) を読む。

### Chat
- GitHub current stateのfresh readback、設計と次のbounded task
- Jules/Cloud Work成果の独立検品（diff、ancestry、tests、evidence）
- Controller-safe small repairと再検証（詳細は上記Guide）
- PASS / FAIL / UNKNOWN、安全・Merge等の人間判断境界
- 許可済みfeature branch / PR範囲のwriteとremote readback

### Jules
- 通常開発のデフォルト実装担当。正確なnon-default branchと範囲で
  静的実装、tests、docs、GitHub checkpointを作る。

### Cloud Work 4色lane
- 💛 Yellow / 💚 Green / 💙 Blue / ❤️ Redは独立したCloud Work carrier。
  escalationではassigned heart colorを維持し、色未選択時のみGreenをdefaultとする。現在の一覧と交換入口は
  [4-lane・交換索引](CLOUD_WORK_LANES_INDEX.md)。
- 選択laneのcarrier/protocol/worker-stateをfresh discovery。
  Local Work固有資源は扱わない。carrier PRはMergeしない。

### Local Work
- ユーザーPC固有資源が必要なときのみ、Chatから完全な🔵promptを渡し、
  ユーザーが貼り付ける。勝手なhandoffはしない。

### Relay
transport / dispatch担当。Council最終判断をしない。
詳細は docs/ARCHITECTURE.md。

## 19. 新しいChatへの必須読込順

1. current main の README.md と HANDOVER_CURRENT.md
2. [development execution router](DEVELOPMENT_EXECUTION_ROUTER.md)
3. 選択したJulesまたは[Cloud Work 4色lane仕様](CLOUD_WORK_LANES_INDEX.md)とcurrent GitHub target identity（交換依頼ではChatGPT support manualを最初に読む）
4. docs/PHASE0_IMPLEMENTATION_SPEC.md、checklist、architectureなどのtask資料
5. このWork自律処理文書（Work / Closed Loopを使う場合）

過去PR番号、Chat/thread/session IDやsnapshot SHAをcorrectnessの入口にしない。
retry=0、fallback=disabled、成功不明writeの再送禁止、Mergeは明示承認のみ。

## 20. Final Principle

**人間を進捗確認係・伝書鳩として使わない。**

```text
作業可能 → 続行
検証可能 → 検証
修正可能 → 修正
別の安全作業が残る → 続行
Chat返答を安全に取得可能 → Work自身で取得して続行
安全作業を使い切った → まとめて報告
本当に人間が必要 → 初めて停止
```

この原則は安全境界を弱めるためではなく、**安全な範囲で人間の手作業を最大限減らすため**に使う。
