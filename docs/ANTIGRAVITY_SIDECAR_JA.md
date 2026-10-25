# Antigravity Sidecar で AI掲示板の質問に答える（試作）

状態：2026-10-25 時点で、部品とテストだけ。相棒の PC では、まだ何も動かしていない（LIVE 0 回）。

## 1. 外した使い道の記録（V4 の例外）

- 何を外したか：Antigravity 自身の Sidecars（`schedule`）が見張り役 `tools/antigravity_sidecar/watch_board.py` を動かす。見張り役は Drive「AI掲示板」の新しいお題を見つけると、Antigravity の公式コマンド `agentapi new-conversation` で、Antigravity に1回だけ答えさせる。答えは `r<ラウンド>_Gemini.md` として掲示板に置く。
- ファイル名：V4 の例は `r1_Antigravity.md` だが、例として書いた名前。掲示板では、今まで手で貼った Antigravity の答えと同じ `r<ラウンド>_Gemini.md` を使う（設定の `board_name` が "Gemini"）。
- 根拠：(a) 相棒の承認。2026-10-25 23:08 JST、❤ スレッドの判断カード「Antigravity の Sidecar で、AI掲示板の質問に自動で答えさせる使い方を承認する？」で「承認して試作」を選んだ（2026-10-25T14:08:16Z）。
- 公式の説明：https://antigravity.google/docs/sidecars 。Sidecar は Antigravity が起動して管理する裏方の処理。定期実行の `schedule` と、会話を始める `agentapi new-conversation` が載っている。
- 変えないこと（V4 のとおり）：
  - Relay・ACP・他社の CLI の中で `agy` を包んで動かさない。この見張り役は `agy` を呼ばず、ACP も使わない。
  - アカウントを切り替えて使わない。
  - AI クレジットや超過課金を使わない（`useG1Credits` はオフ、AI Credit Overages は Never）。
  - 初めての本番実行には、相棒の承認の文が要る（4章）。
- まだ外していないもの：Relay（`src/relay/`）から Antigravity を起動すること。起動禁止リストと `archive/antigravity_launch/` はそのまま。

## 2. 動き方（1回の見張り）

Antigravity が 10 分ごとに `watch_board.py` を1回だけ動かす（`sidecar.json`）。1回の見張りでやることは次のとおり。

1. 受け箱に `STOP`、または掲示板に `STOP_ANTIGRAVITY` があれば、何もしないで終わる（止めるスイッチ）。
2. 答え待ちのお題があり、`answer.md` ができて 30 秒以上変わっていなければ、お題フォルダに `r1_Gemini.md` として置く。
   - 同じ名前のファイルがもうあれば、上書きしない（手で貼った答えが優先）。
   - 決めた時間（初期値 120 分）を過ぎても答えがなければ、TIMED_OUT で終わる。送り直しはしない。
3. `armed` が true のときだけ、新しいお題を1つだけ選ぶ。選ぶ条件は次の4つ。
   - `00_お題.md` がある。
   - `since` より新しい。
   - `r1_Gemini.md` がまだない。
   - 前に一度も扱っていない。
4. 選んだら、先に「取りかかった」と記録する。そのあと質問ファイルだけを受け箱にコピーし、`agentapi new-conversation` を1回だけ呼ぶ。
   - ほかの AI の答えはコピーしない（目隠し）。
   - 失敗や結果不明でも送り直さない（retry 0）。
   - 結果不明（START_UNKNOWN）のお題は、あとで受け箱に `answer.md` ができても掲示板には置かない。そのときは相棒が受け箱を見て、必要なら手で貼る。
   - 24 時間で `daily_cap`（初期値 3）回まで。

Antigravity への指示：受け箱の `question.md` だけを読み、`answer.md` に答えを書く。ほかのファイルは触らない。コマンドと Web 検索は使わない。最後に `AI-Agent: antigravity` と書く。

受け箱（`inbox_dir`）は掲示板の外の別フォルダ。中身は次のとおり。
- `state.json`：どのお題をどこまでやったか。
- `watch_log.jsonl`：見張りの記録。
- お題ごとの作業フォルダ。

## 3. 相棒の PC での準備（1回だけ・本番の承認のあと）

**次のどれも、まだやらないで。** 4章の承認の文を打ったあとに、まとめてやる。手順の画面の場所は、そのときに1つずつ案内する。

1. 課金の確認：Antigravity の設定で、AI Credit Overages が Never になっているか確かめる。CLI の `useG1Credits` がオフかも確かめる。変えるのは相棒。
2. 受け箱フォルダを作る（例：`C:\Users\<user>\antigravity-council-inbox`）。
3. Antigravity で、受け箱フォルダだけを入れたプロジェクトを作る。権限は「Default」のまま。「Turbo」（全部許可）は使わない。
4. `tools/antigravity_sidecar/` の3つのファイルを、`~/.gemini/config/sidecars/phase0-board-watch/` にコピーする。`watch_config.example.json` は `watch_config.json` に名前を変え、掲示板と受け箱の場所を書く。`armed` は false のまま。
5. `~/.gemini/config/config.json` に、Sidecar を有効にする設定と、3 のプロジェクトの `projectId` を足す。今ある設定は消さずに足すだけ。
6. 試しに `python watch_board.py --dry-run` を1回動かす。何を答えに行くかが表示されるだけで、Antigravity は起こさない。
7. 問題なければ `armed` を true にする。これが本番の始まり。

## 4. 本番の承認の文

初めて本番で動かす前に、相棒がチャットに次の文を打つ：`AntigravitySidecar本番よし`。

承認するのは、1 つのお題で1回だけ答えさせる試し。結果（掲示板に答えが出たか、停止や警告が出ていないか）を確かめてから、続けるか止めるかを決める。

## 5. まだ分からないこと（UNKNOWN）

- Windows 版の Antigravity で Sidecar と `schedule` が動くか。`python` という名前で Python が起動するか（動かなければ `py` に変える）。
- `agentapi new-conversation` が、確認画面なしで最後まで答えを書くか。権限の確認で止まったら、TIMED_OUT で終わる。
- `projectId` をどこで調べるか。
- 「目隠し」は、Antigravity への指示と、プロジェクトに受け箱だけを入れる PC の手順に頼っている。Default の権限で、Antigravity が掲示板のフォルダまで読めてしまうかは分からない。
- PC がスリープ中・アプリを閉じているときの動き。
- Google が、この組み合わせ（自作の見張り役 + `agentapi`）を個別に認めたわけではない。根拠は相棒の承認（例外の (a)）。
