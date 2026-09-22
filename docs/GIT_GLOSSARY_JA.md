# Git / GitHub 用語メモ（初心者向け）

## main（メイン）

正式採用されている本線。

ゲームでいう「正式セーブデータ」に近い。

## branch（ブランチ）

mainから分岐して作る作業用の線。

例:

```text
main
  └─ feature/case-runner
```

branch側で失敗しても、Mergeするまではmainを直接壊さずに作業できる。

## commit（コミット）

Gitで作る「セーブポイント」。

その時点でGitが追跡しているファイル群の状態が固定され、commit SHAが付く。

例:

`a1b2c3d...`

このSHAを指定すると、後から同じ版を特定できる。

注意: commitしていないローカル変更はcommit SHAには含まれない。

## push（プッシュ）

PC/作業環境にあるcommitをGitHub側へ送ること。

```text
手元のGit
  -- push -->
GitHub
```

commitだけでは、必ずしもGitHubに届いているとは限らない。

## Pull Request / PR（プルリクエスト）

「このbranchの変更をmainへ入れていいですか？」という提出・レビュー画面。

初心者向けには:

**PR = 提出**

でOK。

## merge（マージ）

PRの変更をmainへ取り込んで正式採用すること。

初心者向けには:

**Merge = 採用確定**

でOK。

## clone（クローン）

GitHubのrepository一式を新しく手元へ複製すること。

## fetch（フェッチ）

GitHub側にどんな新しいcommit/branchがあるかを取得すること。
通常は自分の作業ファイルをいきなり書き換えない。

## pull（プル）

GitHub側の更新を手元へ取り込むこと。
大ざっぱには `fetch + 取り込み`。

## checkout / switch

使うbranchを切り替える操作。

最近はbranch切替には `git switch` が分かりやすい。

## diff（ディフ）

変更前と変更後の差分。

「何が変わった？」を見るもの。

## repository / repo（リポジトリ / レポ）

プロジェクトのGit管理単位。

今の役割:

- AIBO本体 repo
- Council RAW repo
- Phase 0実装 repo

## remote（リモート）

GitHubなど、手元Gitの外にある接続先repository。

よく `origin` という名前が使われる。

## HEAD（ヘッド）

「いまそのbranchが指している最新commit」。

branchの現在地だと思えばよい。

## SHA

commitやblobなどGitオブジェクトを識別するID。

開発引き継ぎでは、commit SHAを「この版」と指定するのが重要。

## conflict（コンフリクト）

同じ場所を別々に変更して、Gitが自動ではどちらを採用すべきか決められない状態。

人間または実装担当が内容を確認して解決する。

## revert（リバート）

過去の変更を打ち消す新しいcommitを作ること。

履歴を残したまま戻したいときに使う。

## reset

branchの位置や作業状態を過去へ戻す操作。
使い方によっては変更を失うため、初心者運用ではrevertより慎重に扱う。

## force push

GitHub側のbranch履歴を強制的に書き換えるpush。

事故範囲が大きいため、このPhase 0開発では禁止。
