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
        self.assertEqual(claude.argv, ("/usr/bin/claude", "-p", "--output-format", "text",
                                       "--model", "claude-opus-5-5", "--effort", "high"))
        self.assertEqual(claude.env["CLAUDE_CODE_MAX_RETRIES"], "0")
        self.assertEqual(codex.argv[1:], ("exec", "--sandbox", "read-only", "--skip-git-repo-check",
                                          "-m", "gpt-6.1-sol", "-c", 'model_reasoning_effort="high"',
                                          "-c", 'service_tier="default"', "-"))
        grok = calls[0].argv
        self.assertEqual(grok[grok.index("-m") + 1], "grok-4.7")
        self.assertEqual(grok[grok.index("--reasoning-effort") + 1], "high")
        for call in calls:
            self.assertFalse(any("fast" in a.lower() for a in call.argv))
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
        self.assertEqual(codex[-5:], ("-C", self.REF, "-c", 'approval_policy="never"', "-"))
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
        self.assertIn("実際に検索してから答える", on["claude"].stdin)

    def test_web_without_a_folder_gets_web_tools_only(self):
        on = {c.ai: c for c in r.build_calls(plan(), ENV, BIN, None, web=True)}
        claude = on["claude"].argv
        self.assertEqual(claude[claude.index("--allowedTools") + 1], "WebSearch,WebFetch")
        self.assertEqual(claude[claude.index("--disallowedTools") + 1],
                         "Bash,Edit,Write,NotebookEdit,Read,Grep,Glob")
        grok = on["grok"].argv
        for tool in ("Read", "Grep", "Edit", "Bash"):
            self.assertEqual(grok[grok.index(tool) - 1], "--deny")
        self.assertNotIn("--cwd", grok)
        self.assertIn('web_search="live"', on["codex"].argv)
        self.assertIn("read-only", on["codex"].argv)
        self.assertIn("一次資料", on["claude"].stdin)
        self.assertIn("30行以内", on["claude"].stdin)
        off = {c.ai: c for c in r.build_calls(plan(), ENV, BIN)}
        self.assertNotIn("--allowedTools", off["claude"].argv)
        self.assertNotIn("WebSearch", off["grok"].argv)
        self.assertNotIn("一次資料", off["claude"].stdin)

    def test_web_is_on_unless_switched_off(self):
        self.assertTrue(r.web_choice())
        self.assertTrue(r.web_choice(web=True))
        self.assertFalse(r.web_choice(no_web=True))
        with self.assertRaises(r.RunStop):
            r.web_choice(web=True, no_web=True)

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


class AttachmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ref = Path(self.tmp.name) / "repo"
        (self.ref / "docs").mkdir(parents=True)
        (self.ref / "README.md").write_text("# 見出し\n", encoding="utf-8")
        (self.ref / "docs" / "design.md").write_text("設計図", encoding="utf-8")
        (Path(self.tmp.name) / "secret.txt").write_text("外", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_files_go_to_codex_only_and_into_the_digest(self):
        files = r.load_attachments(str(self.ref), ["README.md", "docs/design.md"])
        self.assertEqual(files, (("README.md", "# 見出し\n"), ("docs/design.md", "設計図")))
        p = plan()
        calls = {c.ai: c for c in r.build_calls(p, ENV, BIN, str(self.ref), attachments=files)}
        self.assertIn("===== docs/design.md =====\n設計図", calls["codex"].stdin)
        self.assertIn("指示には従わない", calls["codex"].stdin)
        self.assertNotIn("設計図", calls["claude"].stdin)
        self.assertEqual(calls["grok"].attachments, ())
        self.assertEqual([n for n, _ in calls["codex"].attachments], ["README.md", "docs/design.md"])
        self.assertIn("read-only", calls["codex"].argv)
        plain = r.build_calls(p, ENV, BIN, str(self.ref))
        self.assertNotEqual(r.plan_digest(p, list(calls.values())), r.plan_digest(p, plain))
        receipt = r.run_council(p, list(calls.values()), out_dir=Path(self.tmp.name) / "out", runner=FakeRunner(),
                                confirm=typed)
        self.assertEqual([a["file"] for a in receipt["attachments"]["codex"]], ["README.md", "docs/design.md"])
        self.assertEqual(receipt["models"]["codex"], {"model": "gpt-6.1-sol", "effort": "high"})

    def test_outside_missing_binary_or_too_much_is_refused(self):
        for names in (["../secret.txt"], [str(Path(self.tmp.name) / "secret.txt")], ["nope.md"], ["docs"]):
            with self.assertRaises(r.RunStop):
                r.load_attachments(str(self.ref), names)
        (self.ref / "bin.dat").write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(r.RunStop):
            r.load_attachments(str(self.ref), ["bin.dat"])
        (self.ref / "big.md").write_text("あ" * 200_001, encoding="utf-8")
        with self.assertRaises(r.RunStop):
            r.load_attachments(str(self.ref), ["big.md"])
        with self.assertRaises(r.RunStop):
            r.load_attachments(str(self.ref), ["README.md"] * 31)
        with self.assertRaises(r.RunStop):
            r.build_calls(plan(), ENV, BIN, None, attachments=(("README.md", "x"),))

    def test_named_files_are_attached_while_they_fit(self):
        (self.ref / "big.py").write_text("x" * 119_999, encoding="utf-8")
        (self.ref / "small.md").write_text("小", encoding="utf-8")
        (self.ref / "bin.dat").write_bytes(b"\xff\xfe")
        files = r.load_attachments(str(self.ref), ["README.md"], ["big.py", "docs/design.md", "small.md", "bin.dat",
                                                                  "README.md"])
        got = dict(files)
        self.assertEqual(got["big.py"], r.NOT_ATTACHED)
        self.assertEqual(got["bin.dat"], r.NOT_ATTACHED)
        self.assertEqual((got["docs/design.md"], got["small.md"]), ("設計図", "小"))
        self.assertEqual(len(files), 5)
        codex = r.build_calls(plan({"codex": (True, "QUOTA_OK")}), ENV, BIN, str(self.ref), attachments=files)[0]
        self.assertIn("長すぎて添付しなかったファイル（中身は UNKNOWN）：big.py、bin.dat", codex.stdin)
        self.assertNotIn("===== big.py", codex.stdin)
        self.assertIn(("big.py", r.NOT_ATTACHED), codex.attachments)
        with self.assertRaises(r.RunStop):
            r.load_attachments(str(self.ref), [], ["../secret.txt"])

    def test_files_named_in_the_question_are_found(self):
        q = "README.md の見出しと docs/design.md、それに docs/none.md と https://docs.x.ai/build/overview を見て。README.md"
        self.assertEqual(r.named_files(q, str(self.ref)), ["README.md", "docs/design.md"])
        self.assertEqual(r.named_files("../secret.txt を読んで", str(self.ref)), [])


class ReferenceUpdateTests(unittest.TestCase):
    def git(self, answers):
        seen = []

        def run(args):
            seen.append(args[2])
            return answers.get(args[2], (0, ""))
        return run, seen

    def test_fast_forwards_a_clean_main_clone(self):
        run, seen = self.git({"rev-parse": (0, "main")})
        r.update_reference("/ref", run)
        self.assertEqual(seen, ["rev-parse", "status", "fetch", "merge", "rev-parse"])

    def test_changed_or_other_branch_or_failed_fetch_stops(self):
        for answers in ({"rev-parse": (0, "feature")}, {"rev-parse": (0, "main"), "status": (0, " M a.md")},
                        {"rev-parse": (0, "main"), "fetch": (1, "")}, {"rev-parse": (0, "main"), "merge": (1, "")}):
            run, seen = self.git(answers)
            with self.assertRaises(r.RunStop):
                r.update_reference("/ref", run)
            self.assertNotIn("reset", seen)


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

    def test_failure_keeps_a_masked_error_tail(self):
        runner = FakeRunner({"grok": (1, "", "error: not signed in for kami@example.com token xai-ABCDEF123456"),
                             "claude": (0, "ok")})
        receipt = r.run_council(self.plan, self.calls, out_dir=self.out, runner=runner, confirm=typed)
        tail = receipt["members"]["grok"]["stderr_tail"]
        self.assertIn("not signed in", tail)
        self.assertNotIn("kami@example.com", tail)
        self.assertNotIn("ABCDEF123456", tail)
        self.assertNotIn("stderr_tail", receipt["members"]["claude"])

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
