# Claude Loop への依頼のしかた（オーナー向け）

Claude Loop は GitHub の Issue を「作業依頼の受付箱」として使う。決まった形で Issue を立てると、Claude が自分で作業して PR を出す。

## 1. タイトル

先頭を `[claude loop] ` で始める（例：`[claude loop] 使い方ページを追加`）。この印がない Issue は受付されない。

## 2. 本文の4項目

```
goal: やってほしいことを1〜2文で書く
allowed_paths:
- docs/howto/example.md (ADD)
- automation/command_bus/example.py (MODIFY)
acceptance:
- できあがりの条件を1行ずつ書く
test_commands:
- python3 -m unittest automation.command_bus.tests.test_example
AI-Agent: claude
```

- `goal`：目的。
- `allowed_paths`：触ってよいファイル。新規は `(ADD)`、既存の変更は `(MODIFY)`。最大10ファイル。削除や名前変更はできない。
- `acceptance`：合格条件。
- `test_commands`：確認に使うテストのコマンド。
- 最後に `AI-Agent:` の署名行を入れる。署名がない依頼は受付されない。

## 3. ループを止めるとき

管理用の Issue `#494` を閉じる（または `loop-stop` ラベルを付ける）と、新しい作業の開始が止まる。再開は `#494` を開き直す。

## 4. 注意

- マージは自動では行われない。レビュー役の PASS を確認してからオーナーが判断する。
