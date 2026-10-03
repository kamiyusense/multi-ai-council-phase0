# Signal Step 7: proof 4 の事後分析と、人手待ちのない proof 5 の経路（STATIC）

状態: **STATIC で検証済み。LIVE は 1 回も実行していません。** Jules POST 0 / Jules GET 0 / issuer dispatch 0 / retry 0。
production registry は PLACEHOLDER のまま、Issue #33 は STOPPED のままです。

## 1. proof 4（Loop 135）の事後分析 — 確定事項

| 項目 | 値 |
| --- | --- |
| Jules session | `569271609782168660`（carrier が作成。publish は自動で正しい ID を読んだ） |
| issuer run | `37098007717`（成功、1 回だけ） |
| carrier run | `37098060038`（成功） |
| publish run | `37098873248`（失敗 = UNKNOWN） |
| 失敗理由 | `PROVIDER_NOT_ACTIVE: provider_get:COMPLETED` |
| 使用回数 | Jules POST 1 / GET 2 / retry 0。`rerun_allowed=false`、追加の POST・GET は不可 |
| Jules の成果 | PR #275。対象は `docs/evidence/signal-active-proof-4/PROOF.md` の 1 ファイルだけ、内容は `signal active proof 4\n`。未 Merge、判定には昇格しない |

時系列（UTC）: session 作成 04:54:06 → Jules 完了・PR #275 作成 05:01:44（約 7.5 分後）→ 人が publish を実行 05:08:47（完了の約 7 分後）→ GET で `COMPLETED`。

**原因は Jules の出力でも入力ミスでもなく、carrier 成功から人手の publish dispatch までの時間差です。** 公開側の GET は「セッションがまだ作業中」であることを要求します。Jules は約 7 分で終わるため、人が画面操作を挟むと間に合いません。proof 2・3 は別原因（秒未満の時刻、手入力の session id）で、どちらも修正済みです。

## 2. 新しい経路（人手の 2 回目 dispatch が不要）

```
人: issuer を 1 回 dispatch ──▶ 成功を確認
Claude: carrier command を create-only で push（claim → command の順に 1 回ずつ）
carrier: Jules POST 1 + 作成時刻の GET 1 ──▶ SUCCESS
        └─ workflow_run (completed / success)
publish workflow（自動起動）
  prepare job（読み取り専用トークン、Jules key なし）
     └─ イベントの run を API で再取得 → 計画 → carrier の session と command → authority run → preflight
  publish job（prepare が go のときだけ。contents:write と Jules key はここだけ）
     └─ もう一度すべて再計算し、prepare の結果と食い違えば停止
        → fresh Jules GET 1 → publisher → collector → レーン登録 → 採用前ゲート → terminal receipt
```

provider session の作成から fresh GET まで、人の操作待ちはありません。

### トリガーの選択
第一候補だった `workflow_run`（対象 `Phase 0 Chat to Jules semi-auto`、completed / success のみ、branch `feature/chat-work-command-bus`）を採用しました。workflow ファイルは main のものが使われるため、人が Merge した内容しか動きません。

### generic な carrier run が Signal LIVE を起こさない仕組み
carrier の成功イベントはすべて publish workflow を起動します（他レーンの Loop も含む）。そこで次の順に絞り、**どこかで外れたら Jules にも書き込みにも触れずに NOOP（exit 0、go=false）** にします。

1. job の `if`（イベント内容）: repository / workflow 名 / path / event=push / branch / conclusion=success / run_attempt=1 / head_repository / actor と triggering_actor が owner
2. CLI がイベントの run を API で再取得して同じ項目を再検査（イベント本文だけを信用しない）
3. data branch に固定済み計画があること
4. carrier run のログの `COMMAND_ID` が、固定済み計画の command id とちょうど一致すること
5. terminal receipt と attempt marker が無いこと（重複イベントは NOOP）

4 を通った時点で「この証明の carrier 成功」と確定するので、以降の不一致は **STOPPED（exit 1）** です。

### fail-closed の一覧（すべて Jules GET の前、attempt marker の前）
repository / workflow / branch / event / conclusion / attempt / command id / proof task / target PR・HEAD・tree / work branch / data branch / lane id（fixture 含む）/ carrier lane J-YELLOW / receipt・marker の有無 / 旧 session（4 件を禁止）/ session がちょうど 1 つ / authority run がちょうど 1 つ（owner、issuer workflow、attempt 1、成功、計画の `not_before` 以後、carrier より前、1 時間以内、予約済み run でない）/ retry=0 / fallback disabled。

### concurrency
グループは carrier run ごと（`signal-step7-live-publish-<run id>`）です。共通の 1 グループにすると、無関係な carrier イベントが待機中の本命を取り消す可能性があるためです。二重実行は data branch の create-only marker と terminal receipt が防ぎます。

### 手動 dispatch（非常用）
残していますが主経路ではありません。`EMERGENCY_MANUAL_PUBLISH` の入力が必須で、自動経路と同じ duplicate guard（receipt と marker）を共有するため、同じ証明を二重に実行できません。typed の session / authority / digest は照合のみで、食い違えば停止します。

## 3. main drift の扱い — 採用方式と理由

**採用: 「契約パスが変わらない前進」だけを許容する束縛方式。authority 契約は弱めていません。**

- 問題: issuer 成功から publish までの間に、無関係なレーンが main に Merge すると、従来の「authority run の SHA == 現在の main」で止まり、LIVE 予算を無駄にします。proof 5 の準備中にも main は 2 回進みました（Relay、Blue）。
- 方式: authority issuer が証明した SHA を X、実際に動いているコードの SHA（`GITHUB_SHA`）を Y、現在の main を Z とします。Y と Z のそれぞれが「X と同一」か、GitHub compare で「X より厳密に ahead かつ契約パスの変更なし」のときだけ通します。
- 契約パス: `.github/` 全体、`docs/evidence/signal-sf8/`、`automation/command_bus/` のうち `tests/`・`jules_api_requests/`・`loop_id_claims/` 以外。
- 次はすべて停止: diverged / behind / compare 取得失敗 / ファイル一覧が 100 件以上（切り詰めの可能性）/ ファイル名が読めない / 改名元が契約パス。compare ポートが無い場合は従来どおり厳密一致を要求します。
- 検査は 2 回: prepare 側の preflight（attempt marker の前）と publish 側の authority 段階。
- 保守的方式（POST 前に drift で停止）も併用できます。carrier command を push する前に Claude が同じ読み取りを行い、契約パスが変わっていれば push しません。

## 4. proof 5 の候補（準備のみ。LIVE 承認ではありません）

- proof task: `signal-active-proof-5`、Loop **136**（`loop_id_claims/136.json` は未使用を確認）
- 許可パス `docs/evidence/signal-active-proof-5/PROOF.md`、内容は `signal active proof 5\n` の 1 行
- module 定数、計画テンプレート、テストは proof 5 に切り替え済み
- proof 4 の承認と予算は流用できません。コードにも承認の持ち越しはありません（テストで確認）。開始時に必要なもの: **新しい人の承認、新しい issuer、新しい proof 5 の固定済み計画、新しい Loop claim、新しい Jules session**

## 5. 開始手順（人の操作は issuer の 1 回だけ）

1. 人: successor PR を Merge（workflow は main のものしか動かない）。
2. Claude（LIVE ではない準備）: target / work / data ブランチと Draft target PR を確認し、計画を固定して data branch に保存。
3. 人: 新しい LIVE 承認（Loop 136、POST 1・GET 2・issuer 1・retry 0・fallback なし）。
4. 人: issuer workflow を 1 回 dispatch。Claude が実行回数を読み戻す。
5. Claude: main drift の事前確認 → carrier command を push（claim → command）。
6. 自動: carrier 成功 → publish が自動起動 → 結果が data branch に記録される。人の操作はありません。
7. Claude: 結果を読み戻して報告。Merge はしない。再実行はしない。

## 6. テスト（実 GitHub / Jules への通信なし）

- `test_signal_step7_auto_publish.py`: 自動経路の E2E（1 回だけ GET）、prepare-only が読み取り専用で Jules key 不要なこと、NOOP 一覧（別 repo / 別 workflow / 別 path / 別 event / 別 branch / 未完了 / 失敗 / キャンセル / 再実行 / 別 actor / 無関係な command / 計画なし / receipt・marker 既存 / 重複イベント）、STOPPED 一覧（session なし・複数・旧 session / authority の 0 件・複数・carrier 後・計画前・期限切れ・別 actor / target・work branch・tree の drift / 別 lane・fixture lane・別 task・別 digest）、main drift（許容 1 件、停止 15 件）、実行コード SHA の束縛、provider の COMPLETED・FAILED・UNKNOWN・HTTP エラー、`workflow_run` イベントの fixture（各項目を 1 つずつ変えると guard が外れる）。
- `test_signal_step7_live_workflow.py`: workflow の静的検査（トリガーは `workflow_run` と非常用の dispatch だけ、prepare に Jules key と write 権限がない、write は publish だけ、artifact は sanitized のみ、Action は SHA 固定）。
- 従来の `test_signal_step7_live_proof.py`: target 状態、出力の逸脱（追加ファイル・別内容）、書き込み結果不明、重複 evidence・receipt、GET 上限、旧 session、秘密の非漏えい。

## 7. まだ残っている BLOCKED / UNKNOWN

- 本物の GitHub / Jules でこの自動経路を動かしたことはありません（STATIC のみ）。`workflow_run` のイベント内容は fixture による検証で、実イベントでの確認は LIVE 時になります。
- Jules が carrier 作成後に極端に早く終わる場合は、自動経路でも `PROVIDER_NOT_ACTIVE` になり得ます（その場合は UNKNOWN で、再実行はできません）。
- DURABLE 採用は NOT_READY のままです。`READY_FOR_HUMAN_APPROVAL` になっても `registry_write_allowed=false` で、採用の判断は人です。
