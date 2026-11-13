# Symphony 正式凍結（2026-11-14）

オーナー決定（2026-11-14 01:35 JST）：「凍結お願い、Symphonyリポジトリもそうしといて」。Symphony は今後使わない。

## 変更したこと
- `automation/command_bus/config/lane_catalog_v4.json`：`symphony-codex-auto` を `FROZEN` にした。旧台帳 `control_tower_registry.json` は封印済みの記録なので変えない（優先順位はレーン目録に従う）。
- GitHub：`kamiyusense/symphony`、`kamiyusense/symphony-sandbox`、`kamiyusense/symphony-e2e-one-issue-20261017` をアーカイブ（読み取り専用。設定画面から元に戻せる）。何も削除していない。未マージのPR（symphony #1、symphony-sandbox #3・#4）はそのまま凍結。

## PC（WSL Ubuntu）
- Ubuntu を使っていたのは Symphony だけ。字幕アプリ・Claude・Orca は使わない。予約タスクなし。
- Symphony の実験記録（/home/yuuki の symphony-* など、Ubuntu全体で約12.7GB）は Ubuntu の中にだけある。消さない。Ubuntu を削除する場合は先に `wsl --export` で控えを取る。
- Codex を Windows だけで動かすには、Codex の設定で WSL 実行（`runCodexInWindowsSubsystemForLinux`）をオフにする。設定ファイルの控え：`C:\Users\yuuki\.codex\config.toml.bak-20261114-wsl`。

## 元に戻すとき
リポジトリのアーカイブ解除、レーン目録を `ACTIVE` に戻す、Codex の WSL 実行をオンに戻す。

AI-Agent: claude
