# Official Symphony 最小 LIVE proof — Cloud STATIC checkpoint

対象: Draft PR #320、branch `codex/symphony-inspired-minimal-controller`。開始時 remote HEAD は `31bbf0aa8a867d3b95940a82acd8daca0589765d`。この文書中の SHA は履歴であり、再開時は必ず remote PR HEAD を fresh readback する。

## この batch の完了内容

- [Issue title/body](SYMPHONY_MINIMAL_LIVE_PROOF_ISSUE.md) を作成準備した。Issue は未作成。専用ラベル `symphony-minimal-live-proof` で tracker 候補を一件に絞る。
- [WORKFLOW.md](SYMPHONY_MINIMAL_LIVE_PROOF_WORKFLOW.md) は固定版 Official Symphony の GitHub tracker、workspace hook、Codex child の API selector 除去を設定した。scheduler、polling、multi-turn、retry/backoff、stall/workspace は upstream のまま使う。
- [Local runbook](SYMPHONY_MINIMAL_LIVE_PROOF_RUNBOOK.md) に WSL、fresh fetch、clean tree、fast-forward-only、認証、Issue、isolated proof branch、起動、観測、停止、曖昧な副作用の readback を順番に記載した。
- STATIC controller は新 worker の INTENT 直前に optional subscription route fixture を一度確認する。既存の strict one-turn profile はそのまま残した。upstream 内部 turn/continuation/retry を gate しない。
- fake protocol fixture は Issue candidate → route rejection/no attempt → route admission → INTENT/STARTED/TERMINAL → fresh HEAD の STALE discard → fresh controller restore → new result adoption を通す。全体は fake、provider/model 起動なし。

## 検証

- Focused Python tests: **138 PASS**。
- Full command-bus regression: **1897 PASS、1 platform skip**。
- Official Symphony `be10a1b79df723d6d7612b5651c8522704dafb2e` の Elixir `Workflow.load`、`Schema.parse`、`Config.validate_settings`: **PASS**。偽 GitHub token で設定を parse/validate しただけで tracker API は呼んでいない。
- 同じ upstream の `CLI.evaluate` を偽起動関数で確認: acknowledgement flag、port、workflow path の引数 parse **PASS**。実 Symphony process は起動していない。
- [機械可読 evidence](../automation/command_bus/evidence/symphony-minimal-live-preflight-static.json) に入力 pin、SHA-256、テスト件数、未実施 LIVE を記録した。
- 本 batch の exact-head CI は push 後に別途 GitHub Actions readback で判定する。ここに将来の PASS を先取りしない。

## UNKNOWN / Deferred Decisions

- Official Symphony 実 process、Codex App Server/worker、実 ChatGPT subscription auth、実 workspace/turn/retry/stall は **未実施**。Local LIVE 前にのみ判定可能。
- Official Symphony の production event transport と New Chinponey durable attempt ledger は未接続。初回 proof は Original Symphony の実働観測を優先し、STATIC fixture 成功を production durable 接続の証明とは呼ばない。
- 自動 Git ref adoption は未実装で、この最小 proof では行わない。成果採用が必要になれば current canonical HEAD/task validity/diff を読み直して別途設計する。
- proof Issue の番号と Local host の認証状態は Issue 未作成・LIVE 未実施のため UNKNOWN。quota 数字の取得不能だけでは campaign 全停止にしないが、paid route の可能性が排除できなければ新 worker は開始しない。

## Cloud → Local 境界

Cloud は実装、fake fixture、STATIC tests、Official workflow parse、Issue 文面、runbook、CI、checkpoint まで。**ここから先は明示承認後の Local LIVE**: proof Issue 作成、専用 branch、Official Symphony 実 process、Codex App Server/worker、ChatGPT subscription route、実 workspace と turn/continuation/retry/stall の観測。Merge、main write、paid fallback、destructive Git、曖昧な副作用の blind resend は許可しない。
