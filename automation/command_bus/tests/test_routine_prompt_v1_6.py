"""Reviewer v1.6 candidate: one paste-ready plain-text file that keeps every v1.5.1 rule and adds LAYER 4.

Static checks only.  Nothing here touches a Routine, a trigger, Jules or GitHub.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shlex
import subprocess
import unittest
import unittest.mock as m
from pathlib import Path

from automation.command_bus import claude_jules_starter_gh as ghs

ROOT = Path(__file__).resolve().parents[3]
EV = ROOT / "docs/evidence/claude-jules-production-starter-20261009"
ORIGINAL = ROOT / "docs/evidence/claude-jules-stop-resistant-20261007/routine-prompt-v1.5.1.md"
CANDIDATE = EV / "routine-prompt-v1.6.CANDIDATE.txt"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_routine_prompt_v1_6", EV / "build_routine_prompt_v1_6.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = ORIGINAL.read_text(encoding="utf-8")
        cls.text = CANDIDATE.read_text(encoding="utf-8")
        cls.lines = cls.text.split("\n")
        cls.builder = load_builder()

    def test_original_is_the_deployed_v1_5_1(self):
        blob = subprocess.run(["git", "hash-object", str(ORIGINAL)], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(blob.stdout.strip(), self.builder.ORIGINAL_BLOB)

    def test_committed_files_equal_a_rebuild(self):
        for path, text in self.builder.outputs().items():
            with self.subTest(path.name):
                self.assertEqual(path.read_text(encoding="utf-8"), text)
        manifest = json.loads((EV / "routine-prompt-v1.6.manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["candidate"]["sha256"], hashlib.sha256(self.text.encode()).hexdigest())

    def test_every_v1_5_1_line_survives_except_the_declared_replacements(self):
        replaced = {old for old, _, _ in self.builder.REPLACE}
        self.assertEqual(len(replaced), 3)
        kept = set(self.lines)
        for line in self.original.split("\n"):
            if line in replaced:
                continue
            self.assertIn(line, kept, line[:80])
        # v1.5.1 order is unchanged: its kept lines appear in the same order
        pos = [self.lines.index(l) for l in self.original.split("\n") if l and l not in replaced]
        self.assertEqual(pos, sorted(pos))

    def test_reviewer_behaviour_layers_1_to_3_and_receipt_are_byte_identical(self):
        def section(text, start, end):
            return text[text.index(start):text.index(end)]
        for start, end in (("LAYER 1 - ", "LAYER 2 - "), ("LAYER 2 - ", "LAYER 3 - "),
                           ("LAYER 3 - ", "RECEIPT ("), ("RECEIPT (", "Build the JSON")):
            with self.subTest(start):
                self.assertEqual(section(self.text, start, end), section(self.original, start, end))
        for rule in ("Writes per wake: at most one receipt comment on the task issue, one `@jules` corrective PR "
                     "comment, one new unlabeled issue (PASS only).",
                     "PASS: no PR comment; create the next_task issue (no labels) unless an open issue with that "
                     "title exists; decision ADOPT_RECORDED.",
                     "a PASS receipt exists -> \"NO-OP: already PASS\", STOP."):
            self.assertIn(rule, self.text)

    def test_placeholders_and_record_markers_are_plain_text(self):
        for token in ("<verdict>", "<n>", "<sha7>", "<round>", "<phase>", "<decision>", "<allowed paths>",
                      "refs/pull/<n>/head", "<!-- claude-closed-loop-receipt v1", "<!-- claude-closed-loop-task v1",
                      "<!-- claude-closed-loop-corrective v1", "-->", "<outcome>", "<count>"):
            self.assertIn(token, self.text)
        self.assertEqual(self.text.count("<!-- claude-closed-loop-receipt v1"),
                         self.original.count("<!-- claude-closed-loop-receipt v1"))

    def test_paste_safety(self):
        raw = CANDIDATE.read_bytes()
        raw.decode("ascii")                                   # no smart quotes or invisible characters
        self.assertNotIn(b"\r", raw)
        self.assertNotIn(b"\t", raw)
        self.assertTrue(raw.endswith(b"\n") and not raw.endswith(b"\n\n"))
        self.assertNotIn("```", self.text)                    # not a Markdown fragment; one file, one copy
        self.assertFalse(any(l != l.rstrip() for l in self.lines))
        self.assertTrue(self.text.startswith("You are the Claude closed-loop reviewer (CLAUDE_CLOSED_LOOP_REVIEWER_"
                                             "V1.6)"))
        self.assertFalse(any(l.startswith("#") for l in self.lines))   # no metadata header to paste by mistake

    def test_section_order(self):
        marks = ["Hard rules", "WAKE ROUTING:", "LAYER 1 - ", "LAYER 2 - ", "LAYER 3 - ", "RECEIPT (",
                 "LAYER 4 - ", "Finish with one line", "When LAYER 4 ran"]
        idx = [self.text.index(x) for x in marks]
        self.assertEqual(idx, sorted(idx))
        for x in marks:
            self.assertEqual(self.text.count(x), 1, x)

    def test_layer3_issue_and_layer4_start_are_separate(self):
        self.assertIn("Preparing an unlabeled issue (LAYER 3 PASS) never starts Jules.", self.text)
        self.assertIn("Never add the `jules` label to any issue yourself", self.text)
        self.assertIn("LAYER 4 never creates the manifest next-task issue that LAYER 3 creates", self.text)
        self.assertIn("Never create, edit, copy or extend an authorization, budget declaration or budget slot file.",
                      self.text)
        self.assertIn("--budget-declaration " + self.builder.DECL, self.text)
        self.assertIn("never authorize LAYER 4 LIVE writes", self.text)

    def test_the_tick_command_is_exact_and_runs_prepare_only(self):
        cmd = [l for l in self.lines if l.startswith("python3 -m automation.command_bus.claude_jules_starter_gh")]
        self.assertEqual(len(cmd), 1)
        self.assertEqual(cmd[0], self.builder.TICK)
        self.assertNotIn("--live-authorization", cmd[0])
        argv = shlex.split(cmd[0].replace("$(date -u +%Y%m%dT%H%M%SZ)", "20261010T000000Z"))
        self.assertEqual(argv[:4], ["python3", "-m", "automation.command_bus.claude_jules_starter_gh", "tick"])
        self.assertTrue((ROOT / argv[argv.index("--route-declaration") + 1]).is_file())
        self.assertEqual(argv[argv.index("--campaign") + 1], self.builder.CAMPAIGN)
        # the active campaign does not exist yet (not activated); parse with an approved-shape stand-in
        argv[argv.index("--campaign") + 1] = str(EV / "campaign-prd-c2.json")
        # the real argument parser accepts it; the preflight is mocked as blocked, so nothing is read or sent
        with m.patch.object(ghs, "gh_get", side_effect=ghs.ReadFailed("mock", 403)), \
                m.patch("builtins.open", side_effect=lambda p, *a, **k: open_rel(p, *a, **k)), \
                m.patch("builtins.print"):
            self.assertEqual(ghs.main_tick([a for a in argv[4:] if a != "--out" and a != "/tmp/layer4-tick.json"]),
                             3)
        self.assertRegex(self.text, re.escape("cat /tmp/layer4-tick.json") + r"\s+\(never cut it with head")

    def test_the_authorization_path_matches_the_template(self):
        self.assertTrue((EV / "live-authorization-prd-c2.TEMPLATE.json").is_file())
        # the three active files are added together by one activation PR, or none exists (LAYER 4 = NOT_INSTALLED)
        present = [(ROOT / active).exists() for active in (self.builder.CAMPAIGN, self.builder.AUTH, self.builder.DECL)]
        self.assertIn(present, ([True] * 3, [False] * 3))
        self.assertIn(self.builder.AUTH, self.text)

    def test_superseded_candidate_cannot_be_pasted_as_a_prompt(self):
        old = (EV / "routine-prompt-v1.6-full-prepare-only.CANDIDATE.txt").read_text(encoding="utf-8")
        self.assertTrue(old.startswith("SUPERSEDED"))
        self.assertNotIn("You are the Claude closed-loop reviewer", old)


_open = open


def open_rel(path, *a, **k):
    p = Path(path)
    return _open(p if p.is_absolute() else ROOT / p, *a, **k)


if __name__ == "__main__":
    unittest.main()
