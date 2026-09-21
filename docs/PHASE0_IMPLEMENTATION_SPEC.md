> Implementation mirror copied from `kamiyusense/multi-ai-council-raw-records/PHASE0_IMPLEMENTATION_SPEC_DRAFT.md`.
> Source blob SHA: `1eba28e1b944f05e9ee7e5f7a05401e5b8998714`.
> The Council RAW repository remains the design-record source of truth. Do not silently diverge this mirror.

# Multi-AI Council Phase 0 統合実装仕様書（Draft）

作成日: 2026-09-21  
状態: Draft / 実装着手用  
根拠:
- `R5-B_FINAL_INTEGRATION_V2.md`
- `COUNCIL_PRINCIPLES_RAW.md`
- `R5B_PRIVATE_EVIDENCE_HANDOVER.md`
- `COUNCIL_CLI_BROWSER_RESEARCH_PRIVATE_DRAFT.md`
- R5-B後の先駆者比較で三社が採用方向に合意した追加9項目

---

## 1. 目的

Phase 0では、ユーザーが1回入力した設問を、決定論的なOrchestratorが3社Provider CLIへ配布し、各社回答を独立に回収し、RAW・実行証拠・状態を保存し、人間向け日本語レポートを返す。

目標フロー:

```text
User Input
  ↓
Deterministic Orchestrator
  ├─ OpenAI / Codex CLI
  ├─ Anthropic / Claude CLI
  └─ Google / agy
  ↓
Provider別RAW / stdout / stderr / exit code / manifest
  ↓
Deterministic validation / comparison
  ↓
Japanese report
  ↓
Human final decision
```

Orchestratorは最終判断を行わない。

---

## 2. 非目的

Phase 0では以下を目的にしない。

- GitHub branch / commit / push / PR / Merge の自動化
- 任意shell commandの自動実行
- API key経路の利用
- paid fallback
- 自動retry
- 自動デプロイ
- Browser UI自動操作を3社共通主経路にすること
- AIによる最終裁定
- 2/3一致を自動的に正式Council合意へ昇格すること
- 秘密情報・個人情報・非公開コードを自動fan-outすること
- baseline未取得状態で厳密な改善率を主張すること

---

## 3. Phase 0の固定ルール

以下はPhase 0の固定条件とする。

1. 自動retry = 0
2. 最初の5案件を試用期間とする
3. 5案件終了時にユーザーが継続 / 修正 / 縮小 / 撤回を判断する
4. GitHub writeは禁止
5. API key利用は禁止
6. paid fallbackは禁止
7. fan-outはfail-closed
8. 安全警告は多数決より上位
9. 2/3一致は初期状態では正式合意としない
10. 人間が最終判断する
11. Provider CLIのみ原則8の限定例外
12. Browserは3社共通の主経路にしない
13. model fallbackは禁止
14. requested modelと実行modelが不一致、または実行model検証不能なら停止して人間へ返す
15. 課金経路・権限・データ送信可否がUNKNOWNなら実行しない

---

## 4. 信頼境界

### 4.1 Orchestrator

Orchestratorは決定論的であり、以下のみを担当する。

- 入力検査
- Provider別packet生成
- disposable workspace作成
- Provider adapter起動
- timeout管理
- 停止制御
- RAW保存
- hash計算
- manifest保存
- state machine更新
- deterministic comparison
- 日本語レポート生成

OrchestratorにLLM判断を持たせない。

### 4.2 Provider CLI

各Provider CLIは別process・別workspace・別timeoutで扱う。

Provider CLI自身が持つtool / file write / git / shell権限は、Phase 0で必要な最小限に固定する。

許可状態はrun manifestへ記録する。

### 4.3 外部サービス

外部Providerへ送るデータは、fan-out gate通過済みの入力だけに限定する。

### 4.4 GitHub

Phase 0のOrchestratorはGitHub readのみ許可する。GitHub writeは別段階とする。

---

## 5. ディレクトリ構造

すべての実行物は専用run workspace配下に限定する。

```text
phase0-runs/
└─ 20260921T120000Z-case-0001/
   ├─ run_manifest.json
   ├─ input/
   │  ├─ user_input.txt
   │  ├─ packet.txt
   │  └─ hashes.json
   ├─ providers/
   │  ├─ openai/
   │  │  ├─ manifest.json
   │  │  ├─ snapshot/
   │  │  ├─ stdout.raw
   │  │  ├─ stderr.raw
   │  │  ├─ response.raw
   │  │  ├─ exit_code.txt
   │  │  ├─ fs_before.json
   │  │  ├─ fs_after.json
   │  │  ├─ fs_diff.json
   │  │  └─ provider_state.json
   │  ├─ anthropic/
   │  │  ├─ manifest.json
   │  └─ google/
   ├─ comparison/
   │  ├─ parsed.json
   │  ├─ differences.json
   │  └─ summary_ja.md
   └─ evidence/
      ├─ checks.json
      └─ checkpoint.json
```

### 5.1 snapshotルール

- 専用run workspace配下に作成
- Provider間で共有しない
- 固定commit / 固定packetからの複製
- 実cloneを渡さない
- `.git`を含めない
- SSH keyを含めない
- GitHub tokenを含めない
- secretsを含めない
- fan-out境界に抵触するデータを含めない

---

## 6. 主要コンポーネント

### 6.1 Case Runner

責務:

- case_id発番
- run directory作成
- manifest初期化
- preflight
- fan-out gate
- Provider別snapshot作成
- Provider dispatch
- timeout / abort
- evidence保存
- report生成

実行順を固定する。fan-out gateが通過するまで、`user input`・`packet`をProvider別snapshotへ書き込まない。Provider別snapshotの作成と入力展開はfan-out gate通過後にのみ行う。

### 6.2 Fan-out Gate

送信前に以下を検査する。

停止対象:

- 秘密情報
- 認証情報
- 個人情報
- 非公開コード
- 外部Providerへ送ってよいか判断不能な内容
- 含有可能性を安全に否定できない内容

判定不能はfail-closed。

Phase 0では高度なAI判定器を必須にしない。
決定論的簡易検査で該当または判定不能なら人間確認へ返す。

### 6.3 Provider Adapter

最低契約:

```text
prepare(case_context) -> prepared_context
preflight(prepared_context) -> preflight_result
dispatch(prepared_context) -> process_handle
collect(process_handle) -> raw_result
abort(process_handle) -> abort_result
classify(raw_result) -> provider_state
```

Adapterは以下を勝手に行わない。

- retry
- fallback
- git write
- settings変更
- permission変更
- API key利用
- paid route切替
- 任意shell構築
- user input / AI outputからコマンド文字列を生成して実行

### 6.4 Provider Response Contract

deterministic comparisonの入力として、各Providerは自由文本文とは別に、最低限次の機械可読envelopeを返す。

```json
{
  "schema_version": "phase0-response-v1",
  "answer_state": "ANSWER",
  "conclusion_code": "CASE_DEFINED_CODE",
  "safety_warning": "ABSENT",
  "safety_reason": null,
  "evidence_refs": [],
  "marker_echoes": {
    "head": null,
    "middle": null,
    "tail": null
  },
  "answer_text": "..."
}
```

必須field:

- `answer_state`
- `conclusion_code`
- `safety_warning`
- `safety_reason`
- `evidence_refs`
- `marker_echoes`
- `answer_text`

`answer_state` は `ANSWER / ANSWER_UNKNOWN / REFUSAL` のいずれかとする。

`safety_warning` は `PRESENT / ABSENT / UNKNOWN` のいずれかとする。
`PRESENT` または `UNKNOWN` の場合、自動合意へ進めず人間へ返す。
field欠落・型不正・未定義値の場合に「警告なし」と推測しない。

`conclusion_code` は案件packet側で許可された列挙値だけを使用する。
自由文の意味からOrchestratorが結論codeを推測してはならない。

`evidence_refs` は案件内で定義された参照ID / hash等の機械可読値を使う。
自由文の意味から「根拠が同じ」と推測してはならない。

必須field欠落またはschema不正は `INVALID_OUTPUT` とする。
RAWは保存するが、自動retryはしない。

deterministic comparisonは少なくとも次を分離する。

- `conclusion_match_state`: `EXACT / DIFFERENT / UNKNOWN`
- `evidence_match_state`: `EXACT / DIFFERENT / UNKNOWN`

`EXACT` は許可済みcode / evidence_refsの決定論的一致でのみ付与する。
semantic一致をfree textから自動確定しない。

---


## 7. Safety Preflight

### 7.1 静的preflight

- 対象CLIがallowlist内
- requested modelがallowlist内
- API key経路が存在しない
- API keyを生成・取得・使用しない
- paid fallback無効
- auth routeがsubscription系として確認済み
- workspaceが専用run配下
- `.git` / key / token / secretなし
- Git write禁止
- overwrite / delete禁止
- retry=0
- fallback=disabled
- stop flagが初期状態でfalse
- Provider CLI権限が最小化済み
- model fallback禁止設定
- 課金経路 / 権限がUNKNOWNでない

不合格またはUNKNOWNならdispatchしない。

### 7.2 実行を伴う確認

新しいlive AI turnが必要な確認はstatic preflightと分離する。
preflightという名称だけを理由にlive model実行を自動開始しない。

---

## 8. Provider CLI 権限最小化

各Provider CLIについて、実行前に以下を固定する。

- tool execution: 必要最小限
- file write: 専用snapshot内のみ、または可能なら無効
- git operation: 禁止
- shell: 固定CLI起動以外は禁止
- network: Provider本体通信以外は可能な限り禁止
- external browser: 禁止
- settings変更: 禁止

Providerがこれらを明示的に制御できない場合は `UNKNOWN` とし、自動dispatchを開始しない。

---

## 9. Run Manifest

manifestはrun共通情報とProvider別情報を分離する。

### 9.1 Run Manifest

run rootには `run_manifest.json` を1つ置く。

最低項目:

```json
{
  "schema_version": "phase0-run-v1",
  "case_id": "case-0001",
  "started_at": "ISO-8601",
  "finished_at": null,
  "base_commit": "...",
  "input_sha256": "...",
  "packet_sha256": "...",
  "providers": {
    "openai": "providers/openai/manifest.json",
    "anthropic": "providers/anthropic/manifest.json",
    "google": "providers/google/manifest.json"
  }
}
```

### 9.2 Provider Manifest

各Providerは独立した `providers/<provider>/manifest.json` を持つ。
Provider間でstate / model / auth / timeout等を上書き共有しない。

最低項目:

```json
{
  "schema_version": "phase0-provider-v1",
  "provider": "openai",
  "cli_name": "codex",
  "cli_version": "...",
  "auth_route": "subscription",
  "requested_model": "...",
  "configured_model": "...",
  "executed_model_verified": null,
  "executed_model_verification_source": null,
  "retry_count": 0,
  "fallback_state": "disabled",
  "permission_profile": {
    "shell": "fixed-only",
    "git_write": false,
    "file_write_scope": "snapshot-only",
    "settings_change": false
  },
  "timeout_seconds": null,
  "execution_state": "READY",
  "participation_state": null,
  "answer_state": null,
  "capability_state": "UNKNOWN"
}
```

### 9.3 Timeout契約

`timeout_seconds` はProviderごとに独立して設定する。

- 未設定は `null / UNSET`
- live実行前には正の有限整数が必須
- `null / UNSET / 0 / 負数 / 非数` はlive gate FAIL
- timeout値はrun開始前にProvider manifestへ固定し、実行中にAI出力から変更しない

### 9.4 監査ルール

- `retry_count != 0` → 異常
- `fallback_state != disabled` → 異常
- requested / configured / executed model不一致 → 停止
- executed model検証不能 → UNKNOWNとして停止
- `capability_state` の初期値は `UNKNOWN`
- preflightでCapabilityを検証できた場合のみ `CONFIRMED` へ昇格する
- 検証手段が未確定または検証不能なProviderは `UNKNOWN` のままとし、自動dispatchを開始しない
- secret値そのものはmanifestやレポートへ記録しない

---

## 10. 状態機械

### execution_state
- READY
- RUNNING
- COMPLETE
- TIMEOUT
- AUTH_REQUIRED
- QUOTA_CONFIRMED
- INVALID_OUTPUT
- PARTIAL
- ERROR_UNKNOWN
- USER_DISABLED

`QUOTA_CONFIRMED` は明示証拠がある場合のみ使う。原因不明をquotaへ寄せない。

### participation_state
- PARTICIPANT
- NONPARTICIPANT

### answer_state
- ANSWER
- ANSWER_UNKNOWN
- REFUSAL

### capability_state
- CONFIRMED
- UNKNOWN
- UNAVAILABLE

以下を混同しない:
- execution ERROR_UNKNOWN
- answer ANSWER_UNKNOWN
- capability UNKNOWN
- NONPARTICIPANT

---

## 11. RAW-first Evidence Preservation

加工前に保存する。

- stdout
- stderr
- exit code
- raw response
- timestamp
- process metadata
- requested model
- auth route種別
- packet hash
- input hash

parser / comparison / summaryは後段の派生物として扱う。
加工後データだけを証拠にしない。

stderr等のRAWは、証拠保全のため改変せずそのまま保存する。
そのうえで `phase0-runs/` 配下全体を秘密情報と同等の取り扱い領域とし、共有・commit・外部送信・外部サービスへの添付を行わない。
ユーザー向けレポートや画面表示では、既知の鍵形式・token形式等をマスクして表示する。
RAW本体にはマスクを適用しない。raw-first evidenceを維持しつつ、表示・持ち出し境界で秘密値を保護する。

### 11.1 Council記録用の公開派生物

Council記録として外へ出す場合、`phase0-runs/` 配下の原RAWを直接持ち出さない。

人間が内容を確認したうえで、既知の鍵形式・token形式のみをマスクした全文派生物を `phase0-runs/` の外へ出力し、記録・公開に使用する。
派生物には元RAWのSHA-256とredaction有無を併記し、後から原RAWと突き合わせ可能にする。
要約への置換は行わない。

Phase 0 Orchestrator自身はGitHub writeを行わない。
公開・commit等は人間が別段階で行う。

---

## 12. 長文完全性検査

nonce / markerは「全文完全性の証明」ではなく、「切断・位置ずれ等の検出補助」とする。

検査対象:
- 冒頭marker
- 中央marker
- 末尾marker

marker欠落時:
- `PARTIAL` または `INVALID_OUTPUT`
- RAW保存
- retryしない
- 人間へ返す

制約:
- fixtureで先に検証
- この検査のためだけに新しいlive AI実行を増やさない
- marker成功を「意味的に全文を理解した証明」としない

---

## 13. Filesystem Diff

各Provider実行について、snapshot領域の実行前後差分を保存する。

保存:
- file path
- created / modified / deleted
- size
- hash

想定外差分時:
- 自動削除しない
- 自動rollbackしない
- read-only前提違反として記録
- 人間へ返す

---

## 14. Model Verification

分離記録:
- requested model
- configured model
- externally verified executed model
- verification source
- UNKNOWN

停止条件:
- requested modelとconfigured model不一致
- executed modelがrequested modelと不一致
- model fallback疑い
- executed modelを外部検証不能

AI自身の自己申告だけでは実行modelを確定しない。

---

## 15. Timeout / Retry / Fallback

Providerごとに独立timeoutを持つ。

自動retry = 0  
model fallback = 禁止  
paid fallback = 禁止  
API fallback = 禁止

timeout後も自動retryしない。

---

## 16. Failure Isolation

1社失敗でCouncil全体の成功RAWを失わない。

例:

```text
OpenAI     COMPLETE
Anthropic  TIMEOUT
Google     COMPLETE
```

この場合:
- OpenAI RAW保存
- Google RAW保存
- Anthropic timeout証拠保存
- Anthropic = NONPARTICIPANT
- Council全体は「部分成功」
- 人間へ返す

---

## 17. Stop / Abort

最低2系統:
1. 実行中子process停止
2. 新規dispatch停止フラグ

停止時:
- 新しいProvider dispatchを開始しない
- retryしない
- fallbackしない
- 取得済みRAWを消さない
- evidence保存後に停止

CLI live実行前にmock / fixtureで以下を検証:
- 全子processが停止する
- stop flag有効中は新規dispatchされない
- stop後にretry / fallbackが発生しない

---

## 18. Comparison / Report

比較器は §6.4 のProvider Response Contractだけを機械判定入力として使う。
自由文 `answer_text` の意味から、結論一致・根拠一致・安全警告有無を自動推測しない。

最低出力:
- 各Provider参加状態
- 各Provider回答状態
- 一致 / 不一致
- 2社一致
- 3社一致
- safety warning有無
- UNKNOWN種別
- evidence欠落
- model verification状態
- conclusion_match_state
- evidence_match_state

2/3一致:
```text
2社一致
1社未参加
正式採用: ユーザー判断待ち
```

1社でも重大安全警告がある場合、多数決より優先して人間へ返す。

---

## 19. 5案件Checkpoint

各案件で最低記録:
- user操作回数
- user拘束時間
- AI側error回数
- 人間確認回数
- timeout
- RAW欠落
- filesystem差分
- model mismatch
- billing / permission異常
- fan-out gate停止
- stop / abort利用有無

5案件終了後、ユーザーが判断:
- 継続
- 修正
- 縮小
- 撤回

重大事故時は5件終了を待たず停止する。

---

## 20. Fixture / Test Plan

### Unit
- fan-out gate
- secret pattern detection
- hash生成
- state transition
- retry=0保証
- fallback禁止
- manifest schema
- stop flag
- model mismatch検知
- fs diff
- marker検査
- Provider Response Contract schema
- conclusion/evidence matchの決定論的判定
- Provider別manifest分離
- finite timeout validation

### Fixture
- 正常COMPLETE
- TIMEOUT
- ERROR_UNKNOWN
- AUTH_REQUIRED
- QUOTA_CONFIRMED
- INVALID_OUTPUT
- PARTIAL
- ANSWER_UNKNOWN
- REFUSAL
- USER_DISABLED
- Provider1社失敗 / 他2社成功
- unexpected filesystem write
- requested/executed model mismatch
- executed model UNKNOWN
- stop during dispatch
- stop before second provider dispatch
- response必須field欠落
- safety_warning UNKNOWN
- conclusion_code未定義値
- Provider manifest上書き混線
- timeout null / 0 / 負数 / UNSET

### Regression
- long RAW truncation
- model fallback疑い
- retry不整合
- summary state誤記
- UNKNOWNをquotaへ誤分類
- provider failureで全RAW消失
- shell権限過大

---

## 21. 受入条件

Phase 0 CLI自動実行へ進む前に以下を満たす。

- static preflight PASS
- mock stop PASS
- fan-out gate PASS
- retry=0 PASS
- fallback disabled PASS
- provider CLI permission profile PASS
- filesystem diff検知 PASS
- marker検査fixture PASS
- state machine fixture PASS
- raw-first evidence PASS
- manifest schema PASS
- model mismatch fail-loud PASS
- failure isolation PASS
- Provider Response Contract schema fixture PASS
- 必須field欠落 → INVALID_OUTPUT PASS
- safety_warning UNKNOWN / 欠落時にfail-safe PASS
- conclusion_match_state / evidence_match_state分離 PASS
- Providerごとのmanifest / state独立 PASS
- Providerごとの正の有限timeout設定 PASS
- timeout `null / 0 / 負数 / UNSET` でlive gate FAIL
- secret masking（表示・レポート側）PASS
- `phase0-runs/` 隔離（共有・commit・外部送信・外部添付なし）PASS

安全境界に関係するUNKNOWNが1つでもあれば、live実行へ進まない。

---

## 22. Recovery / Rollback

問題時:
1. 対象Provider adapter停止
2. stop flag ON
3. evidence保存
4. L1またはL0へ縮退
5. 人間確認
6. 明示承認なしに再開しない

Phase 0ではGitHub writeしないため、外部正本のrollbackは不要。
workspace内差分は証拠として保持し、勝手に削除・rollbackしない。

---

## 23. 実装順序

1. Case Runner骨格
2. run directory / manifest
3. state machine
4. fan-out gate
5. disposable workspace
6. filesystem diff
7. raw-first evidence layer
8. stop / abort
9. provider adapter interface
10. mock providers
11. timeout isolation
12. model verification
13. nonce / marker fixture
14. report generator
15. full dry-run
16. static safety review
17. human review
18. 初回live実行（別途明示承認がある場合のみ）

---

## 24. 禁止事項

- `--dangerously-skip-permissions` 等の安全機構回避
- API key自動利用
- Cloud Billing / Credits / Overages変更
- settings / permissions変更
- GitHub write
- 自動retry
- model auto-fallback
- paid fallback
- 原因不明エラーをquotaと断定
- secret値をmanifest・比較レポート・画面表示へ平文で転記すること
- `phase0-runs/` 配下のRAWを共有・commit・外部送信・外部添付すること
- Provider間workspace共有
- `.git`付きcloneをProviderへ渡す
- AI自己申告だけでexecuted model確定
- marker成功だけで全文完全性証明
- filesystem差分を勝手に削除 / rollback
- safety warningを多数決で無視

---

## 25. UNKNOWN / Deferred Decisions

1. 各Provider CLIの具体的timeout仮値
2. 各Provider CLIの最小permission profile
3. 各CLIのexecuted model検証手段
4. OpenAI / Claude / agyそれぞれのsubscription auth検証方法
5. Provider CLIのnetwork制限可否
6. marker具体形式
7. secret簡易検査パターン
8. user-facing report format
9. 5案件checkpointの表示UI

これらは不明のまま危険側へ進めない。

---

## 26. 実装完了の定義

Phase 0実装完了とは、コードが存在するだけではなく、以下が揃った状態を指す。

- deterministic Case Runner
- 3 Provider adapter
- mock/fixture test
- safety preflight
- fan-out fail-closed
- raw-first evidence
- multi-axis state machine
- stop / abort
- model verification
- fs diff
- marker補助検査
- failure isolation
- manifest
- Japanese report
- 5案件checkpoint
- README / recovery / known limitations
- test evidence
- artifact hash

live AI実行は別承認事項とする。

