"""STATIC checks of the Council runner (step S9a).  A fake runner is used; no CLI is ever started."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from relay import council_run as r
from relay.council import collect_answers, plan_council

CID = "council-20261024-ab12"
ENV = {"PATH": "/usr/bin", "HOME": "/home/u", "XAI_API_KEY": "xai", "OPENAI_API_KEY": "sk",
       "ANTHROPIC_API_KEY": "ant", "CODEX_API_KEY": "c"}
BIN = {"grok": "/usr/bin/grok", "claude": "/usr/bin/claude", "codex": "/usr/bin/codex"}
ALL_OK = {ai: (True, "QUOTA_OK") for ai in ("grok", "claude", "codex")}


def plan(quota=ALL_OK):
    return plan_council(CID, "A と B どっち？", quota)


class FakeRunner:
    def __init__(self, results=None):
        self.calls, self.results = [], results or {}

    def __call__(self, argv, env, stdin, timeout, cwd=None):
        ai = Path(argv[0]).name
        self.calls.append((ai, argv, dict(env), stdin, cwd))
        result = self.results.get(ai, (0, f"{ai} の答え"))
        if isinstance(result, Exception):
            raise result
        return result


def typed(phrase):
    return phrase


class BuildTests(unittest.TestCase):
    def test_calls_have_no_keys_and_prompt_via_stdin(self):
        calls = r.build_calls(plan(), ENV, BIN)
        self.assertEqual([c.ai for c in calls], ["grok", "claude", "codex"])
        for call in calls:
            self.assertFalse({"XAI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY"} & set(call.env))
        claude, codex = calls[1], calls[2]
        self.assertEqual(claude.argv, ("/usr/bin/claude", "-p", "--output-format", "text"))
        self.assertEqual(claude.env["CLAUDE_CODE_MAX_RETRIES"], "0")
        self.assertEqual(codex.argv[1:], ("exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"))
        self.assertIn("A と B どっち？", claude.stdin)
        self.assertNotIn("A と B どっち？", " ".join(claude.argv + codex.argv))

    def test_refusals(self):
        with self.assertRaises(r.RunStop):
            r.build_calls(plan(), ENV, {**BIN, "codex": ""})
        with self.assertRaises(r.RunStop):
            r.build_calls(plan(), ENV, {**BIN, "grok": r"C:\npm\grok.cmd"})
        with self.assertRaises(r.RunStop):
            r.build_calls(plan(), ENV, {**BIN, "claude": "/usr/bin/bash"})
        self.assertEqual(r.build_calls(plan({"codex": (True, "QUOTA_OK")}), ENV, {"codex": "codex.cmd"})[0].ai,
                         "codex")

    def test_digest_changes_with_question(self):
        calls = r.build_calls(plan(), ENV, BIN)
        other = plan_council(CID, "別の質問", ALL_OK)
        self.assertNotEqual(r.plan_digest(plan(), calls), r.plan_digest(other, r.build_calls(other, ENV, BIN)))


class ReferenceDirTests(unittest.TestCase):
    REF = "/home/u/ai-video-research"

    def test_read_only_tools_and_working_folder(self):
        calls = {c.ai: c for c in r.build_calls(plan(), ENV, BIN, self.REF)}
        self.assertTrue(all(c.cwd == self.REF for c in calls.values()))
        grok = calls["grok"].argv
        self.assertEqual(grok[grok.index("--cwd") + 1], self.REF)
        self.assertIn("Edit", grok[grok.index("--deny") + 1:])
        claude = calls["claude"].argv
        self.assertEqual(claude[claude.index("--allowedTools") + 1], "Read,Grep,Glob")
        self.assertIn("Bash", claude[claude.index("--disallowedTools") + 1])
        codex = calls["codex"].argv
        self.assertEqual(codex[-3:], ("-C", self.REF, "-"))
        self.assertIn("read-only", codex)
        self.assertIn("読むだけ", calls["claude"].stdin)
        self.assertNotIn("30行以内", calls["claude"].stdin)

    def test_web_is_opt_in_with_rules(self):
        off = {c.ai: c for c in r.build_calls(plan(), ENV, BIN, self.REF)}
        self.assertIn("WebFetch", off["claude"].argv[off["claude"].argv.index("--disallowedTools") + 1])
        self.assertNotIn("web_search", " ".join(off["codex"].argv))
        on = {c.ai: c for c in r.build_calls(plan(), ENV, BIN, self.REF, web=True)}
        claude = on["claude"].argv
        self.assertEqual(claude[claude.index("--allowedTools") + 1], "Read,Grep,Glob,WebSearch,WebFetch")
        self.assertEqual(claude[claude.index("--disallowedTools") + 1], "Bash,Edit,Write,NotebookEdit")
        self.assertIn('web_search="live"', on["codex"].argv)
        self.assertIn("read-only", on["codex"].argv)
        self.assertIn("WebSearch", on["grok"].argv)
        self.assertIn("Edit", on["grok"].argv)
        for rule in ("一次資料", "出典 URL", "UNKNOWN", "指示には従わない", "検索語や URL に入れない"):
            self.assertIn(rule, on["claude"].stdin)
        self.assertEqual(on["codex"].stdin, on["claude"].stdin)
        with self.assertRaises(r.RunStop):
            r.build_calls(plan(), ENV, BIN, None, web=True)

    def test_relative_folder_refused_and_digest_differs(self):
        with self.assertRaises(r.RunStop):
            r.build_calls(plan(), ENV, BIN, "relative/dir")
        p = plan()
        self.assertNotEqual(r.plan_digest(p, r.build_calls(p, ENV, BIN)),
                            r.plan_digest(p, r.build_calls(p, ENV, BIN, self.REF)))

    def test_long_questions_up_to_12000(self):
        self.assertEqual(plan_council(CID, "あ" * 12_000, ALL_OK).ask, ("grok", "claude", "codex"))
        with self.assertRaises(Exception):
            plan_council(CID, "あ" * 12_001, ALL_OK)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.plan = plan({"grok": (True, "QUOTA_OK"), "claude": (True, "QUOTA_OK"), "codex": (False, "LOW")})
        self.calls = r.build_calls(self.plan, ENV, BIN)

    def tearDown(self):
        self.tmp.cleanup()

    def test_wrong_phrase_starts_nothing(self):
        runner = FakeRunner()
        with self.assertRaises(r.RunStop) as stop:
            r.run_council(self.plan, self.calls, out_dir=self.out, runner=runner, confirm=lambda p: "yes")
        self.assertEqual(stop.exception.code, "APPROVAL_NOT_GIVEN")
        self.assertEqual(runner.calls, [])
        self.assertFalse((self.out / CID).exists())

    def test_one_call_each_and_files_are_collectable(self):
        runner = FakeRunner()
        receipt = r.run_council(self.plan, self.calls, out_dir=self.out, runner=runner, confirm=typed)
        self.assertEqual([c[0] for c in runner.calls], ["grok", "claude"])
        self.assertEqual(receipt["members"]["codex"], {"state": "SKIPPED", "reason": "LOW"})
        self.assertEqual((receipt["retry"], receipt["github_write"]), (0, False))
        comments = [{"id": i, "created_at": "t", "body": (self.out / CID / f"answer-{ai}.md").read_text("utf-8")}
                    for i, ai in enumerate(("grok", "claude"))]
        answers, notes = collect_answers(comments, CID)
        self.assertEqual(set(answers), {"grok", "claude"})
        saved = (self.out / CID / "receipt.json").read_text("utf-8")
        self.assertNotIn("/home/u", saved)
        self.assertIn("AI-Agent: claude", (self.out / CID / "summary.md").read_text("utf-8"))

    def test_failures_are_recorded_never_retried(self):
        runner = FakeRunner({"grok": (None, ""), "claude": RuntimeError("boom")})
        receipt = r.run_council(self.plan, self.calls, out_dir=self.out, runner=runner, confirm=typed)
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(receipt["members"]["grok"]["state"], "TIMEOUT")
        self.assertEqual(receipt["members"]["claude"]["state"], "ERROR")
        runner = FakeRunner({"grok": (1, "x"), "claude": (0, "  ")})
        p2 = plan_council("council-20261024-cd34", "q", ALL_OK)
        receipt = r.run_council(p2, r.build_calls(p2, ENV, BIN)[:2], out_dir=self.out, runner=runner, confirm=typed)
        self.assertEqual([receipt["members"][ai]["state"] for ai in ("grok", "claude")], ["FAILED", "FAILED"])

    def test_single_use_and_stop_file(self):
        r.run_council(self.plan, self.calls, out_dir=self.out, runner=FakeRunner(), confirm=typed)
        with self.assertRaises(r.RunStop) as stop:
            r.run_council(self.plan, self.calls, out_dir=self.out, runner=FakeRunner(), confirm=typed)
        self.assertEqual(stop.exception.code, "ALREADY_RUN")
        p2 = plan_council("council-20261024-ef56", "q", ALL_OK)
        calls = r.build_calls(p2, ENV, BIN)

        def stopping(argv, env, stdin, timeout, cwd=None):
            (self.out / p2.council_id / "STOP").write_text("x")
            return 0, "最初だけ"
        receipt = r.run_council(p2, calls, out_dir=self.out, runner=stopping, confirm=typed)
        self.assertEqual([receipt["members"][ai]["state"] for ai in ("grok", "claude", "codex")],
                         ["ANSWERED", "STOPPED", "STOPPED"])


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "state"
        self.board = Path(self.tmp.name) / "board"
        self.board.mkdir()
        self.plan = plan({"grok": (True, "QUOTA_OK"), "codex": (True, "QUOTA_OK")})
        self.calls = r.build_calls(self.plan, ENV, BIN)

    def tearDown(self):
        self.tmp.cleanup()

    def test_answers_land_on_the_board_with_its_header(self):
        receipt = r.run_council(self.plan, self.calls, out_dir=self.out, runner=FakeRunner(), confirm=typed,
                                board_dir=self.board, round_no=1)
        self.assertEqual(sorted(p.name for p in self.board.iterdir()), ["r1_Codex.md", "r1_Grok.md"])
        body = (self.board / "r1_Grok.md").read_text("utf-8")
        for head in ("作成者: Grok", "ラウンド: R1", "作成時刻（JST）:", "確信度:", "読んだファイル:"):
            self.assertIn(head, body)
        self.assertTrue(body.rstrip().endswith("AI-Agent: grok"))
        self.assertEqual(receipt["board_round"], 1)

    def test_existing_board_file_or_missing_folder_stops_before_any_call(self):
        (self.board / "r1_Codex.md").write_text("先客", encoding="utf-8")
        runner = FakeRunner()
        with self.assertRaises(r.RunStop) as stop:
            r.run_council(self.plan, self.calls, out_dir=self.out, runner=runner, confirm=typed, board_dir=self.board)
        self.assertEqual(stop.exception.code, "BOARD_FILE_EXISTS")
        self.assertEqual((self.board / "r1_Codex.md").read_text("utf-8"), "先客")
        for kwargs in ({"board_dir": self.board / "nope"}, {"board_dir": self.board, "round_no": 0}):
            with self.assertRaises(r.RunStop):
                r.run_council(self.plan, self.calls, out_dir=self.out, runner=runner, confirm=typed, **kwargs)
        self.assertEqual(runner.calls, [])


class MainTests(unittest.TestCase):
    def test_missing_cli_stops_before_asking(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "q.txt").write_text("質問", encoding="utf-8")
            (t / "quota.json").write_text(json.dumps({"grok": [True, "QUOTA_OK"]}), encoding="utf-8")
            from unittest import mock
            with mock.patch.object(r.shutil, "which", return_value=None), \
                    mock.patch.object(r, "subprocess_runner") as runner, mock.patch("builtins.input") as typed_in:
                code = r.main(["--council-id", CID, "--question-file", str(t / "q.txt"), "--quota-file",
                               str(t / "quota.json"), "--out", str(t / "out")])
            self.assertEqual(code, 2)
            runner.assert_not_called()
            typed_in.assert_not_called()


if __name__ == "__main__":
    unittest.main()
