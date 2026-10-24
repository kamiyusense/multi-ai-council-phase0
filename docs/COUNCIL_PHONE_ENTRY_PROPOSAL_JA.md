# Council：スマホからの入口の提案（S8）

計画 `docs/RELAY_TOWER_PLAN_V4_JA.md` の S8「スマホからの入口の提案」。ここでは提案だけで、何も動かさない。最初の本番（S9）は相棒の明示の OK が別に要る。

## 前提（どちらの案でも同じ）

- Grok・Claude・Codex は公式の CLI を、相棒の PC で、サブスクのログインのまま使う。API キーは使わない（Grok の子プロセスには `XAI_API_KEY` を渡さない。`src/relay/council_grok.py`）。
- だから **PC が起きていて、各 CLI にログイン済み** であることが、どちらの案でも必要。GitHub Actions では動かせない。
- 各 AI の枠は S7 の `quota_gate` で毎回見る。枠が不明・残り少ない AI はその回は聞かない（`plan_council`）。
- Antigravity は自動では聞かない。相棒が定型文（`antigravity_template`）を手で貼り、答えは Council Issue のコメントに書いてもらう（一方通行）。
- 答えは並べるだけ。多数決や取捨選択はしない（`summary_markdown`）。

## 案 (a) Remote Control から Relay を起動する

スマホの Claude アプリから PC の Claude Code（Remote Control）に「この議題で Council して」と頼み、PC 側で Relay を動かす。

- よい点：新しい仕組みがほぼ要らない。今もう PC につながっている（💚 の線）。その場で結果を見られる。
- 気になる点：Remote Control の会話そのものが Claude の枠を使う。PC の Claude の自動安全確認が、Grok や Codex の起動を止める可能性がある（UNKNOWN。止められたら回り道はしない）。会話が切れると途中経過が残りにくい。

## 案 (b) GitHub の Issue に議題を書き、PC の Relay が拾う

相棒がスマホで Council Issue に議題をコメントする。PC で常駐する小さな見張り役が、相棒本人のコメントだけ（S2 と同じ判定）を拾って Relay を動かし、答えとまとめを同じ Issue のコメントに書く。

- よい点：記録が全部 GitHub に残り、途中で止まっても続きから再開できる。スマホは GitHub アプリだけで済む。
- 気になる点：PC に常駐の見張り役が要る（新しい部品と、そのための許可が要る）。GitHub への書き込みが増える。見張りの間隔ぶん、答えが遅れる。

## おすすめ

**最初（S9 の1回目）は (a)。慣れて回数が増えたら (b) を検討。**

理由：S9 は1回きりの試しで、新しい常駐部品を作る前に「3体に聞いて並べる」が本当に回るかを確かめるのが先。(a) なら今ある線だけで試せる。(b) は便利だけど、常駐の見張りと GitHub 書き込みの許可が増えるので、使う回数がはっきりしてから相棒が決めるのがよい。

どちらでも、結果のまとめは Council Issue にコメントとして残す（S9 で相棒の OK を取ってから）。
