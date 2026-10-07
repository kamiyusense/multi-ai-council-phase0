# Official Symphony 最小 LIVE proof 用 Issue（未作成）

対象: `kamiyusense/multi-ai-council-phase0`。このファイルは準備済み文面です。Cloud では Issue を作成しません。作成時に **`symphony-minimal-live-proof`** ラベルを付け、同ラベルを持つ他の open Issue がないことを確かめます。ラベルが未登録なら Local で一度だけ登録します。

## **🔵【以下のタイトルを GitHub Issue の Title 欄へそのまま貼り付けてください】**

```markdown
Official Symphony minimal LIVE proof: isolated workspace and one evidence file
```

## **🔵【以下を GitHub Issue の Body 欄へそのまま貼り付けてください】**

```markdown
## 目的

Official OpenAI Symphony がこの GitHub Issue を tracker candidate として取得し、Codex worker を隔離 workspace で起動する最小実働試験です。複数 turn、continuation、retry/backoff、stall recovery は発生したものだけ観測します。今回の作業は製品完成や PR Merge ではありません。

## 対象

- Repository: `kamiyusense/multi-ai-council-phase0`
- Tracker: この Issue の番号。PR #320 自体は dispatch 対象にしない。
- Source: Local で fresh readback した Draft PR #320 の HEAD。
- Target: `codex/symphony-minimal-live-proof-<このIssue番号>` という専用 non-default branch。Local 手順書に従ってモデル起動前に作成する。
- Workspace: Official Symphony が Issue 単位に作る `SYMPHONY_PROOF_WORKSPACES` 配下の隔離 checkout。既存の PR #320 checkout を作業場所にしない。
- Dispatch label: `symphony-minimal-live-proof`。同ラベル付きの他の open Issue がある場合は起動しない。

## 正確な task

隔離 workspace で `docs/evidence/symphony-minimal-live-proof/issue-<このIssue番号>.md` を **新規作成** する。内容は Issue 番号、開始時の branch/HEAD、作業内容、実行した読み取り・検証コマンド、結果、未観測の項目を簡潔に記録する。既存ファイルは編集しない。`git diff --check` を実行する。commit/push はしない。

## 完了条件と期待する artifact

1. Symphony の tracker readback にこの Issue が候補として現れ、Codex worker の開始がログまたは状態表示で確認できる。
2. 専用 workspace の branch が上記 target であり、`main` と PR #320 branch の HEAD は動いていない。
3. 許可された新規 Markdown 一つだけが workspace に存在し、`git diff --check` が成功する。
4. worker の結果と workspace の差分を Local operator が読み取れる。複数 turn / retry / stall が発生しなければ「未観測」と記録する。
5. 結果の採用は自動で行わず、Local operator が fresh canonical HEAD と差分を確認するまで保留する。

## 許可される変更

- 専用 workspace 内で上記 Markdown ファイルを一つ新規作成する。
- 読み取り、状態確認、非破壊 test、`git diff --check`。

## 禁止事項・停止条件

- API key、metered API、paid provider、credits、overage、auto-recharge への fallback/変更。
- `main`、PR #320 branch、他の repository/Issue への write。push、Merge、force push、history rewrite、reset、clean、ファイル削除、Secret/permission/Billing の操作。
- 既存ファイルの変更、Issue を閉じること、GitHub への自動成果採用、曖昧な副作用の盲目的な再送。
- 認証経路が ChatGPT subscription と確認できない、専用 branch/workspace が違う、許可外変更が必要、canonical HEAD が信用できない、paid route の可能性がある場合は新しい model work を止めて証拠を残す。

## 必要な証拠

Issue URL/番号、開始時と終了時の PR #320 HEAD・proof branch HEAD、Symphony upstream commit、workflow digest、Codex の認証方式（秘密値は記録しない）、worker start/turn/continuation/retry/stall の観測ログ、workspace path、`git status --short`、`git diff --check`、成果ファイル、発生した UNKNOWN と stop 理由。未発生の挙動を PASS と書かない。
```
