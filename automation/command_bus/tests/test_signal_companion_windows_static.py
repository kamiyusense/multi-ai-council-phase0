"""Static contract tests for SF-12 Windows Signal Companion (.NET 8 read-only tray app).

Validates C# project properties, Program.cs line count and security boundaries,
and README.md documentation without requiring dotnet executable.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CSPROJ_PATH = REPO_ROOT / "windows" / "SignalCompanion" / "SignalCompanion.csproj"
PROGRAM_PATH = REPO_ROOT / "windows" / "SignalCompanion" / "Program.cs"
README_PATH = REPO_ROOT / "windows" / "SignalCompanion" / "README.md"


class TestSignalCompanionWindowsStatic(unittest.TestCase):

    def test_csproj_contract(self) -> None:
        self.assertTrue(CSPROJ_PATH.exists(), f"Missing {CSPROJ_PATH}")
        content = CSPROJ_PATH.read_text(encoding="utf-8")

        self.assertIn("<TargetFramework>net8.0-windows</TargetFramework>", content)
        self.assertIn("<UseWindowsForms>true</UseWindowsForms>", content)
        self.assertNotIn("PackageReference", content)

    def test_program_line_count(self) -> None:
        self.assertTrue(PROGRAM_PATH.exists(), f"Missing {PROGRAM_PATH}")
        lines = PROGRAM_PATH.read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(
            len(lines),
            250,
            f"Program.cs must be at most 250 lines, found {len(lines)}",
        )

    def test_program_forbidden_apis(self) -> None:
        content = PROGRAM_PATH.read_text(encoding="utf-8")
        forbidden_terms = [
            "System.Net",
            "HttpClient",
            "WebClient",
            "Socket",
            "TcpClient",
            "Registry",
        ]
        for term in forbidden_terms:
            self.assertNotIn(term, content, f"Forbidden API '{term}' found in Program.cs")

        # Check UseShellExecute is not true
        self.assertFalse(
            re.search(r"UseShellExecute\s*=\s*true", content, re.IGNORECASE),
            "UseShellExecute = true is forbidden in Program.cs",
        )

    def test_program_process_start_info_and_modules(self) -> None:
        content = PROGRAM_PATH.read_text(encoding="utf-8")

        # ProcessStartInfo FileName must be python
        fn_matches = re.findall(r'FileName\s*=\s*"([^"]+)"', content)
        self.assertTrue(fn_matches, "No ProcessStartInfo.FileName setting found in Program.cs")
        for fn in fn_matches:
            self.assertEqual(fn, "python", f"ProcessStartInfo FileName must be 'python', got '{fn}'")

        # Module named must only be automation.command_bus.signal_companion_cli
        modules = re.findall(r'["\']([a-zA-Z0-9._-]+)["\']', content)
        cli_modules = [m for m in modules if "signal_companion" in m or "command_bus" in m]
        self.assertTrue(cli_modules, "No module referenced in Program.cs")
        for mod in cli_modules:
            self.assertEqual(
                mod,
                "automation.command_bus.signal_companion_cli",
                f"Only automation.command_bus.signal_companion_cli is allowed, got '{mod}'",
            )

    def test_program_arguments_property_not_used(self) -> None:
        content = PROGRAM_PATH.read_text(encoding="utf-8")
        self.assertIn("ArgumentList", content, "Program.cs must use ArgumentList")
        self.assertFalse(
            re.search(r"\.Arguments\b", content) or re.search(r"\bArguments\s*=", content),
            "ProcessStartInfo.Arguments string property must not be used (use ArgumentList instead)",
        )

    def test_program_file_write_targets_only_seen_path(self) -> None:
        content = PROGRAM_PATH.read_text(encoding="utf-8")

        self.assertNotIn("StreamWriter", content, "StreamWriter is forbidden in Program.cs")
        self.assertNotIn("File.Create(", content, "File.Create is forbidden in Program.cs")

        write_matches = re.findall(r"File\.WriteAll[a-zA-Z]*\(([^)]+)\)", content)
        for match in write_matches:
            target_arg = match.split(",")[0].strip()
            self.assertIn(
                "_seenPath",
                target_arg,
                f"File write operations must only target _seenPath, got '{target_arg}'",
            )

    def test_readme_contract(self) -> None:
        self.assertTrue(README_PATH.exists(), f"Missing {README_PATH}")
        content = README_PATH.read_text(encoding="utf-8")

        self.assertIn("読み取り専用", content)
        self.assertIn("dotnet run", content)

    def test_program_icon_caching_and_cleanup(self) -> None:
        content = PROGRAM_PATH.read_text(encoding="utf-8")

        # Program.cs declares a Dictionary cache for icons
        self.assertTrue(
            re.search(r"Dictionary\s*<\s*string\s*,\s*Icon\s*>", content),
            "Program.cs must declare a Dictionary<string, Icon> cache",
        )

        # GetHicon appears at most once in Program.cs
        get_hicon_count = len(re.findall(r"\bGetHicon\s*\(", content))
        self.assertLessEqual(
            get_hicon_count,
            1,
            f"GetHicon must appear at most once in Program.cs, found {get_hicon_count}",
        )

        # CreateColorIcon reads the cache before building a new icon
        create_color_icon_match = re.search(
            r"private static Icon CreateColorIcon\s*\(\s*string\s+([a-zA-Z0-9_]+)\s*\)\s*\{([^}]+)",
            content,
            re.DOTALL,
        )
        self.assertIsNotNone(
            create_color_icon_match,
            "CreateColorIcon method not found in Program.cs",
        )
        body_start = create_color_icon_match.group(2)
        self.assertTrue(
            "TryGetValue" in body_start or "ContainsKey" in body_start or "[]" in body_start,
            "CreateColorIcon must check the cache before building a new icon",
        )


if __name__ == "__main__":
    unittest.main()
