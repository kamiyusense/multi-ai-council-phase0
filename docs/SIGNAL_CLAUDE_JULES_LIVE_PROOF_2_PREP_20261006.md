# Claude→Jules 2回目 bounded LIVE 直前までの STATIC 準備 (2026-10-06)

状態: STATIC のみ。LIVE 0 / Jules POST 0 / Jules GET 0 / provider 0。この文書は LIVE の承認ではない。

## 事実 (GitHub readback, 2026-10-06 ~05:45Z)

- main = `4007f0c`。`claude/claude-jules-autoloop-data` = `1be31f6`。
- Loop A budget = `slot-01`〜`slot-06` = **6/10**(残り 4)。slot-05 = Loop 137(証明 1, 結果 UNKNOWN, Jules PR #310)、slot-06 = Loop 139(owner stream `claude-auto-loop-a-003`, Jules PR #322, 💚 スレッドが所有)。
- 証明 1 は使用済み(attempt marker + terminal receipt UNKNOWN)。再実行しない。#310 / #322 は merge・編集しない。
- 本番 registry は不変(5 行, DURABLE は `chatgpt-semi-auto` のみ)。Issue #33 は STOPPED のまま。

## この PR が変えたこと(コードは STATIC のみ)

| 変更 | 内容 |
| --- | --- |
| `RUN_PROFILES` | 既知の証明 run を明示列挙。run 1 は従来どおり(ledger 4)。run 2 = `claude-jules-stable-lane-proof-2` は ledger **6**・使用済み Loop `128-131,137,138,139`。それ以外の run id は `PLAN_UNKNOWN_RUN` で拒否(無制限な一般化はしない)。 |
| ledger 件数チェック | CLI の固定値 `4` をやめ、検証済み plan の `loop_a_slots_used_before` と一致しない限り `BUDGET_COUNT_UNEXPECTED`(fail closed)。再署名した改ざん plan も拒否。 |
| 証拠パス | run ごとに専用の `docs/evidence/<proof_task_id>/{attempt-marker,terminal-receipt}.json`。run 1 の使用済みファイルとは衝突しない。 |
| 使用済み session | proof 1 の Jules session `17540857576922617403` を `OLD_SESSION_IDS` に追加(今後読まない・使わない)。 |
| テスト | `test_claude_jules_lane_proof_run2.py`(plan 束縛、改ざん、証拠パス分離、marker 再実行拒否、使用済み Loop 拒否、CLI 件数 0/4/5/7/10 拒否、run 1 plan は ledger 6 で拒否)。 |

## 次の LIVE が必要とするもの(まだ何も実施していない)

- 新しい Loop 番号(137/138/139 は使用済み)、新しい origin(例 `claude-auto-loop-a-004`)、ledger slot-07。
- 新しい人間承認(`live_dispatch_authorization`: approved_by / approval_ref / scope / `max_dispatches` が使用数 6 を超える / expires_at)。承認文は相棒だけが書ける。
- 💚 スレッドの Loop 139 の検査・handback の完了(完了前は新 dispatch を作らない)。
- 相棒の PC 操作(下記)。

## Windows PC 準備手順(prepare-only。ここでは LIVE を実行しない)

1. 新しい PowerShell を 1 つだけ開く(前回の窓は閉じる)。
2. `cd C:\Users\yuuki\mac-live3` ではなく、このPRのブランチを fetch したクリーンなコピーを使う。`$env:PYTHONUTF8 = "1"`。
3. `py -m unittest discover -s automation/command_bus/tests -t .` が全 OK であることだけ確認する。
4. `py -m automation.command_bus.claude_jules_lane_proof_cli plan ...` は GitHub 読み取りのみ。承認を含む plan を作る前に止まる。
5. JULES_API_KEY はその窓の環境変数にだけ入れる(値をチャット・ファイル・記録に出さない)。LIVE 承認を相棒が決めるまで入れない。
6. 終わったら窓を閉じる。

## Deferred Decisions(相棒の判断待ち。この PR は決めない)

1. 2 回目 bounded LIVE をやるか(予算 slot-07、新承認、新 origin)。
2. 💚 の Loop 139 を先に検査・handback するか(推奨: 先に完了)。
3. PR のマージ(明示承認が必要)。
