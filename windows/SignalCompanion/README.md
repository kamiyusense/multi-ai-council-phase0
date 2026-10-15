# Windows Signal Companion

Signal Companion は、Control Tower のスナップショット状態を Windows システムトレイに表示するデスクトップ通知アプリです。

## 機能

- **トレイアイコン表示**: スナップショットの状態に応じてアイコンの色（RED / PURPLE / GREEN / YELLOW / BLACK / WHITE）を変更し、ツールチップに理由コード（`reason_code`）を表示します。
- **バルーン通知**: TURN_COMPLETE や HUMAN_NEEDED などの通知イベントが発生した際にデスクトップのバルーン通知を表示します。
- **読み取り専用設計**: 本アプリは**読み取り専用**（Read-Only）です。CLI (`automation.command_bus.signal_companion_cli`) を介してスナップショット情報を取得するのみで、リポジトリやスナップショットファイルへの変更・書き込みは一切行いません。唯一作成・更新を許可されているファイルは、通知の既読状態を記録する `%LOCALAPPDATA%\SignalCompanion\seen.json` のみです。

## 前提条件

- .NET 8 SDK
- Python 3.x (`automation.command_bus.signal_companion_cli` モジュールが実行可能な環境)

## 起動方法

以下のコマンドで起動します：

```cmd
dotnet run --project windows/SignalCompanion -- --snapshot <スナップショットファイルのパス> --repo <リポジトリルートのパス>
```

※ `--snapshot` および `--repo` の指定がない場合は、環境変数 `SIGNAL_SNAPSHOT_PATH` および `SIGNAL_REPO_ROOT`（未指定時はカレントディレクトリエリア）が使用されます。
