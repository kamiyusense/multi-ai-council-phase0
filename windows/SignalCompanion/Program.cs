namespace SignalCompanion;

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows.Forms;

static class Program
{
    [DllImport("user32.dll")]
    private static extern bool DestroyIcon(IntPtr hIcon);

    private static readonly Dictionary<string, Icon> _iconCache = new();
    private static string _snapshotPath = "";
    private static string _repoRoot = "";
    private static string _pythonPath = "python";
    private static string _seenPath = "";
    private static bool _isFirstRun;
    private static NotifyIcon? _trayIcon;
    private static System.Windows.Forms.Timer? _timer;

    [STAThread]
    static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();

        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--snapshot" && i + 1 < args.Length)
            {
                _snapshotPath = args[++i];
            }
            else if (args[i] == "--repo" && i + 1 < args.Length)
            {
                _repoRoot = args[++i];
            }
        }

        if (string.IsNullOrEmpty(_snapshotPath))
        {
            _snapshotPath = Environment.GetEnvironmentVariable("SIGNAL_SNAPSHOT_PATH") ?? "";
        }

        if (string.IsNullOrEmpty(_repoRoot))
        {
            _repoRoot = Environment.GetEnvironmentVariable("SIGNAL_REPO_ROOT") ?? Directory.GetCurrentDirectory();
        }

        string? python = Environment.GetEnvironmentVariable("SIGNAL_PYTHON");
        if (!string.IsNullOrWhiteSpace(python))
        {
            _pythonPath = python;
        }

        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        string seenDir = Path.Combine(localAppData, "SignalCompanion");
        _seenPath = Path.Combine(seenDir, "seen.json");

        _isFirstRun = !File.Exists(_seenPath);
        if (_isFirstRun && !Directory.Exists(seenDir))
        {
            Directory.CreateDirectory(seenDir);
        }

        ContextMenuStrip menu = new ContextMenuStrip();
        menu.Items.Add("Exit", null, (s, e) => Application.Exit());

        _trayIcon = new NotifyIcon
        {
            Icon = CreateColorIcon("WHITE"),
            Text = "Signal Companion: INITIALIZING",
            ContextMenuStrip = menu,
            Visible = true
        };

        _timer = new System.Windows.Forms.Timer { Interval = 60000 };
        _timer.Tick += (s, e) => PollCLI();
        _timer.Start();

        PollCLI();

        Application.Run();

        _trayIcon.Dispose();
        foreach (var icon in _iconCache.Values)
        {
            icon.Dispose();
        }
        _iconCache.Clear();
    }

    private static void PollCLI()
    {
        UpdateState();
        CheckNotifications();
    }

    private static void UpdateState()
    {
        string nowUtc = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
        string[] cliArgs = ["-m", "automation.command_bus.signal_companion_cli", "state", "--snapshot", _snapshotPath, "--now", nowUtc];
        string? output = RunPython(cliArgs);
        string color = "WHITE";
        string reason = "CLI_ERROR";

        if (output != null)
        {
            try
            {
                using var doc = JsonDocument.Parse(output);
                var root = doc.RootElement;
                if (root.TryGetProperty("color", out var cElem) && cElem.GetString() is string c)
                {
                    color = c;
                }
                if (root.TryGetProperty("reason_code", out var rElem) && rElem.GetString() is string r)
                {
                    reason = r;
                }
            }
            catch
            {
                color = "WHITE";
                reason = "CLI_ERROR";
            }
        }

        if (_trayIcon != null)
        {
            _trayIcon.Icon = CreateColorIcon(color);
            string text = $"Signal Companion: {reason}";
            _trayIcon.Text = text.Length > 63 ? text[..63] : text;
        }
    }

    private static void CheckNotifications()
    {
        List<string> cliArgs = ["-m", "automation.command_bus.signal_companion_cli", "notify", "--snapshot", _snapshotPath, "--seen", _seenPath];
        if (_isFirstRun)
        {
            cliArgs.Add("--first-run");
        }

        string? output = RunPython([.. cliArgs]);
        if (output != null)
        {
            try
            {
                using var doc = JsonDocument.Parse(output);
                var root = doc.RootElement;
                if (root.TryGetProperty("notifications", out var notifsElem) && notifsElem.ValueKind == JsonValueKind.Array)
                {
                    foreach (var item in notifsElem.EnumerateArray())
                    {
                        string kind = item.TryGetProperty("kind", out var k) ? k.GetString() ?? "" : "";
                        string loopId = item.TryGetProperty("loop_id", out var l) ? l.GetString() ?? "" : "";
                        string displayState = item.TryGetProperty("display_state", out var d) ? d.GetString() ?? "" : "";
                        string action = item.TryGetProperty("human_action", out var h) ? h.GetString() ?? "" : "";

                        string title = $"[{kind}] {loopId}";
                        string msg = $"{displayState} - {action}";
                        _trayIcon?.ShowBalloonTip(3000, title, msg, ToolTipIcon.Info);
                    }
                }

                if (root.TryGetProperty("seen_state", out var seenElem))
                {
                    string json = JsonSerializer.Serialize(seenElem);
                    File.WriteAllText(_seenPath, json);
                    _isFirstRun = false;
                }
            }
            catch
            {
            }
        }
    }

    private static string? RunPython(string[] args)
    {
        try
        {
            var psi = new ProcessStartInfo
            {
                FileName = _pythonPath,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                CreateNoWindow = true,
                WorkingDirectory = _repoRoot
            };
            foreach (var arg in args)
            {
                psi.ArgumentList.Add(arg);
            }

            using var proc = Process.Start(psi);
            if (proc == null) return null;
            if (!proc.WaitForExit(10000))
            {
                proc.Kill();
                return null;
            }
            if (proc.ExitCode != 0) return null;
            return proc.StandardOutput.ReadLine();
        }
        catch
        {
            return null;
        }
    }

    private static Icon CreateColorIcon(string colorName)
    {
        if (_iconCache.TryGetValue(colorName, out Icon? cached))
        {
            return cached;
        }

        Color color = colorName switch
        {
            "RED" => Color.Red,
            "PURPLE" => Color.Purple,
            "GREEN" => Color.Green,
            "YELLOW" => Color.Yellow,
            "BLACK" => Color.Black,
            _ => Color.White
        };

        using Bitmap bmp = new Bitmap(16, 16);
        using (Graphics g = Graphics.FromImage(bmp))
        {
            g.Clear(color);
            using Pen pen = new Pen(Color.Gray, 1);
            g.DrawRectangle(pen, 0, 0, 15, 15);
        }

        IntPtr hIcon = bmp.GetHicon();
        using Icon temp = Icon.FromHandle(hIcon);
        Icon icon = (Icon)temp.Clone();
        DestroyIcon(hIcon);

        _iconCache[colorName] = icon;
        return icon;
    }
}
