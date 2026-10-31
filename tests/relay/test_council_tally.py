"""Tests for tools/council_tally/council_tally.py (pure stdlib, no network, no process)."""
import ast
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "council_tally" / "council_tally.py"
_spec = importlib.util.spec_from_file_location("council_tally", TOOL)
ct = importlib.util.module_from_spec(_spec)
sys.modules["council_tally"] = ct
_spec.loader.exec_module(ct)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = ct.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class _TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text, bom=False):
        path = self.dir / name
        path.write_text(text, encoding="utf-8-sig" if bom else "utf-8")
        return str(path)


class StaticBoundaryTest(unittest.TestCase):
    def test_stdlib_only_no_network_no_process(self):
        tree = ast.parse(TOOL.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertLessEqual(imported, {"__future__", "argparse", "json", "re", "sys", "pathlib"})
        for bad in ("subprocess", "socket", "urllib", "http", "requests", "os"):
            self.assertNotIn(bad, imported)


class JuryTest(_TmpCase):
    def test_member_name(self):
        self.assertEqual(ct.member_name("x/r1_Claude.md"), "Claude")
        self.assertEqual(ct.member_name("r1_手動_ChatGPT.md"), "手動_ChatGPT")
        self.assertEqual(ct.member_name("Solo.md"), "Solo")

    def test_same_split_missing_and_summary(self):
        a = self.write("r1_Claude.md", "# board header\n番号|判定|理由\n1|○|ok\n2|×|no\n3|UNKNOWN|?\n")
        b = self.write("r1_Codex.md", "1|○|yes\n2|○|differs\n")
        code, out, _ = run(["jury", a, b])
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "一致: 1 / 割れた: 1 / 無回答あり: 1")
        self.assertEqual(lines[1], "有効な行がないファイル: なし")
        self.assertIn("| 番号 | Claude | Codex | 結果 |", out)
        self.assertIn("| 1 | ○ | ○ | 一致 |", out)
        self.assertIn("| 2 | × | ○ | 割れた |", out)
        self.assertIn("| 3 | UNKNOWN | - | 無回答あり |", out)

    def test_header_lines_ignored_and_duplicate_keeps_first(self):
        rows = ct.parse_jury("番号|判定|理由\n|---|---|---|\n1|○|first\n1|×|second\nfoo|○|x\n2|△|bad\n")
        self.assertEqual(rows, {1: "○"})

    def test_bom_and_file_without_valid_row(self):
        a = self.write("r1_Claude.md", "1|○|ok\n", bom=True)
        b = self.write("r1_Grok.md", "nothing useful here\n")
        code, out, _ = run(["jury", a, b])
        self.assertEqual(code, 0)
        self.assertIn("有効な行がないファイル: r1_Grok.md", out)
        self.assertIn("| 1 | ○ | - | 無回答あり |", out)
        self.assertTrue(out.startswith("一致: 0 / 割れた: 0 / 無回答あり: 1"))

    def test_rows_sorted_numerically(self):
        a = self.write("r_A.md", "10|○|x\n2|○|x\n")
        _, out, _ = run(["jury", a])
        self.assertLess(out.index("| 2 |"), out.index("| 10 |"))


class RankParseTest(unittest.TestCase):
    def test_last_line_wins(self):
        text = "順位: A > B > C\n本文\n順位: C > A > B\n"
        self.assertEqual(ct.parse_rank(text), (["C", "A", "B"], None))

    def test_full_width_and_decoration(self):
        self.assertEqual(ct.parse_rank("順位：B＞A＞C")[0], ["B", "A", "C"])
        self.assertEqual(ct.parse_rank("**順位: B > A**")[0], ["B", "A"])
        self.assertEqual(ct.parse_rank("`順位: A > C`")[0], ["A", "C"])

    def test_invalid_lines(self):
        letters, why = ct.parse_rank("順位: A > A > B")
        self.assertIsNone(letters)
        self.assertIn("2回", why)
        self.assertIsNone(ct.parse_rank("順位: A > b > C")[0])
        self.assertIsNone(ct.parse_rank("順位: AB > C")[0])
        self.assertIsNone(ct.parse_rank("順位: A > > C")[0])
        letters, why = ct.parse_rank("no ranking here")
        self.assertIsNone(letters)
        self.assertIn("ない", why)

    def test_invalid_last_line_is_not_replaced_by_earlier(self):
        self.assertIsNone(ct.parse_rank("順位: A > B\n順位: A > A\n")[0])

    def test_parse_key(self):
        key = ct.parse_key("# key\nA=Codex\nB = 手動ChatGPT\nA=Other\nbad line\nc=x\n")
        self.assertEqual(key, {"A": "Codex", "B": "手動ChatGPT"})


class RankCliTest(_TmpCase):
    def _reviews(self):
        r1 = self.write("rv_Claude.md", "感想\n順位: A > B > C\n")
        r2 = self.write("rv_Codex.md", "順位: B > A\n")
        r3 = self.write("rv_Grok.md", "**順位：B＞C＞A**\n")
        bad = self.write("rv_Bad.md", "順位: A > A > C\n")
        none = self.write("rv_None.md", "no line\n")
        return [r1, r2, r3, bad, none]

    def test_average_places_and_counts(self):
        code, out, _ = run(["rank"] + self._reviews())
        self.assertEqual(code, 0)
        self.assertIn("rv_Bad.md（同じ記号が2回以上ある）", out)
        self.assertIn("rv_None.md（順位の行がない）", out)
        # B: 2,1,1 -> 1.33 (3); A: 1,2,3 -> 2.00 (3); C: 3,2 -> 2.50 (2)
        b, a, c = out.index("| B | 1.33 | 3 |"), out.index("| A | 2.00 | 3 |"), out.index("| C | 2.50 | 2 |")
        self.assertLess(b, a)
        self.assertLess(a, c)

    def test_key_groups_and_group_averages(self):
        key = self.write("key.txt", "A=Codex\nB=手動ChatGPT\n")
        code, out, _ = run(["rank", "--key", key] + self._reviews())
        self.assertEqual(code, 0)
        self.assertIn("| B | 手動ChatGPT | 手動 | 1.33 | 3 |", out)
        self.assertIn("| A | Codex | 自動 | 2.00 | 3 |", out)
        self.assertIn("| C | UNKNOWN | UNKNOWN | 2.50 | 2 |", out)
        self.assertIn("- 手動: 1.33", out)
        self.assertIn("- 自動: 2.00", out)
        self.assertIn("- UNKNOWN: 2.50", out)

    def test_record_appends_json_lines(self):
        key = self.write("key.txt", "A=Codex\nB=手動ChatGPT\n")
        rec = self.dir / "rec.jsonl"
        rec.write_text('{"existing": true}\n', encoding="utf-8")
        files = self._reviews()
        self.assertEqual(run(["rank", "--key", key, "--record", str(rec), "--topic", "t1"] + files)[0], 0)
        self.assertEqual(run(["rank", "--key", key, "--record", str(rec), "--topic", "t2"] + files)[0], 0)
        raw = rec.read_text(encoding="utf-8")
        self.assertIn("手動ChatGPT", raw)  # ensure_ascii=False
        lines = [json.loads(x) for x in raw.splitlines()]
        self.assertEqual(lines[0], {"existing": True})
        self.assertEqual(len(lines), 7)
        self.assertEqual(lines[1], {"topic": "t1", "letter": "B", "who": "手動ChatGPT", "group": "手動",
                                    "average_place": 1.33, "reviewers": 3})
        self.assertEqual(lines[6]["topic"], "t2")
        self.assertEqual(lines[6]["group"], "UNKNOWN")

    def test_record_refused_without_key_or_topic(self):
        files = self._reviews()
        rec = self.dir / "rec.jsonl"
        key = self.write("key.txt", "A=Codex\n")
        self.assertEqual(run(["rank", "--record", str(rec), "--topic", "t"] + files)[0], 2)
        self.assertEqual(run(["rank", "--key", key, "--record", str(rec)] + files)[0], 2)
        self.assertEqual(run(["rank", "--topic", "t"] + files)[0], 2)
        self.assertFalse(rec.exists())

    def test_missing_input_file_exits_2(self):
        self.assertEqual(run(["rank", str(self.dir / "nope.md")])[0], 2)


if __name__ == "__main__":
    unittest.main()
