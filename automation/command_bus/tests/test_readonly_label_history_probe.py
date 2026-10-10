"""The read-only label-history probe (evidence script) on mocked ``gh``: GET only, UTF-8 on any console code page,
complete JSON in a file, one ASCII stdout line, fail-closed pagination.  No real ``gh`` and no network."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import unittest.mock as m
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "docs/evidence/claude-jules-production-starter-20261009/readonly_label_history_probe.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "starter_gh" / "issue_events_per_page_2.json"
REPO = "kamiyusense/multi-ai-council-phase0"


def load():
    spec = importlib.util.spec_from_file_location("readonly_label_history_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def http(data, *, status=200, links=None):
    head = [f"HTTP/2.0 {status} X"]
    if links:
        head.append("Link: " + ", ".join(
            f'<https://api.github.com/repositories/1048576/issues/1/events?per_page=2&page={p}>; rel="{r}"'
            for r, p in links.items()))
    return SimpleNamespace(returncode=0 if status == 200 else 1, stdout="\r\n".join(head) + "\r\n\r\n" +
                           json.dumps(data, ensure_ascii=False), stderr="" if status == 200 else f"(HTTP {status})")


class FakeGh:
    """Answers the probe's commands from the recorded fixture; records every command."""

    def __init__(self, pages_by_issue, *, overrides=None):
        self.pages, self.overrides, self.calls = pages_by_issue, overrides or {}, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[:2] == ["gh", "--version"]:
            return SimpleNamespace(returncode=0, stdout="gh version 2.89.0 (2026-09-01)\n", stderr="")
        if cmd[:3] == ["gh", "auth", "status"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="github.com\n  X Failed to log in using token "
                                                                   "(GH_TOKEN) ghp_SECRETSECRET123 is invalid\n")
        assert cmd[:5] == ["gh", "api", "--method", "GET", "--include"], cmd
        path = cmd[5]
        if path in self.overrides:
            return self.overrides[path]
        if path == f"repos/{REPO}":
            return http({"full_name": REPO, "private": True})
        parts = path.split("?")[0].split("/")
        n = parts[4]
        if len(parts) == 5:
            return http({"number": int(n), "state": "open", "labels": [], "body": "本文 ünïcode",
                         "updated_at": "2026-10-08T18:04:22Z"})
        page = int(path.rsplit("page=", 1)[1])
        pages = self.pages[n]
        links = {}
        if page < len(pages):
            links.update(next=page + 1, last=len(pages))
        return http(pages[page - 1], links=links)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.mod = load()
        self.fx = json.loads(FIXTURE.read_text(encoding="utf-8"))["issues"]

    def run_probe(self, gh, *extra):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "full.json"
            buf = io.StringIO()
            with m.patch.object(self.mod.subprocess, "run", side_effect=gh), redirect_stdout(buf):
                self.assertEqual(self.mod.main(["--issues", "335,338", "--per-page", "2", "--out", str(out), *extra]), 0)
            raw = out.read_bytes()
            return json.loads(raw.decode("utf-8")), buf.getvalue(), raw

    def test_complete_histories_file_and_one_ascii_line(self):
        gh = FakeGh(self.fx)
        full, stdout, raw = self.run_probe(gh)
        i338, i335 = full["issues"]["338"], full["issues"]["335"]
        self.assertTrue(i338["events_complete"])
        self.assertEqual(i338["event_ids"], [32814810366, 32838071056, 32839285361, 32863022962])
        self.assertIs(i338["ever_labeled_jules"], False)
        self.assertTrue(i335["events_complete"])
        self.assertEqual(i335["event_count"], 6)
        self.assertIs(i335["ever_labeled_jules"], True)
        self.assertEqual(full["repo_get"], {"status": 200, "private": True, "error": None})
        self.assertEqual(full["gh_auth_status_exit"], 1)        # reported, but the real GET decided
        # stdout: exactly one line, pure ASCII (a cp932 console prints it), never cut by `head`
        self.assertEqual(stdout.count("\n"), 1)
        stdout.encode("ascii")
        line = json.loads(stdout)
        self.assertEqual(line["out_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(line["issues"]["338"], {"complete": True, "events": 4, "pages": [200, 200],
                                                 "ever_labeled_jules": False, "labels": []})
        self.assertLess(len(stdout), 1000)
        # no token anywhere
        self.assertNotIn("SECRETSECRET", stdout + raw.decode("utf-8"))
        # every subprocess decodes UTF-8 with replacement, and every API call is a GET on repos/...
        for cmd, kw in gh.calls:
            self.assertEqual((kw.get("encoding"), kw.get("errors")), ("utf-8", "replace"))
            if cmd[:2] == ["gh", "api"]:
                self.assertEqual(cmd[2:4], ["--method", "GET"])
                self.assertTrue(cmd[5].startswith("repos/"))

    def test_default_output_goes_to_a_temp_file(self):
        buf = io.StringIO()
        with m.patch.object(self.mod.subprocess, "run", side_effect=FakeGh(self.fx)), redirect_stdout(buf):
            self.mod.main(["--issues", "338", "--per-page", "2"])
        line = json.loads(buf.getvalue())
        p = Path(line["out"])
        try:
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), line["out_sha256"])
        finally:
            p.unlink()

    def test_cp932_undecodable_bytes_do_not_crash(self):
        # v1 used the console code page; bytes like these raised UnicodeDecodeError on Windows cp932.
        raw = "テスト ❤ \U0001f600".encode("utf-8")
        with self.assertRaises(UnicodeDecodeError):
            raw.decode("cp932")
        # with encoding="utf-8", errors="replace", subprocess decodes them; the probe passes these kwargs
        gh = FakeGh(self.fx)
        self.run_probe(gh)
        self.assertTrue(all(kw.get("errors") == "replace" for _, kw in gh.calls))

    def unknown_when(self, override_page, response):
        path = f"repos/{REPO}/issues/338/events?per_page=2&page={override_page}"
        full, stdout, _ = self.run_probe(FakeGh(self.fx, overrides={path: response}))
        i = full["issues"]["338"]
        self.assertFalse(i["events_complete"])
        self.assertIsNone(i["ever_labeled_jules"])              # UNKNOWN, never "never labeled"
        self.assertIsNone(i["event_count"])
        self.assertIsNone(json.loads(stdout)["issues"]["338"]["ever_labeled_jules"])
        return i

    def test_middle_page_403_is_unknown(self):
        i = self.unknown_when(2, http({"message": "denied"}, status=403))
        self.assertEqual([p["status"] for p in i["pages"]], [200, 403])

    def test_skipped_page_is_unknown(self):
        self.unknown_when(1, http(self.fx["338"][0], links={"next": 3, "last": 3}))

    def test_repeated_event_is_unknown(self):
        self.unknown_when(2, http(self.fx["338"][0]))

    def test_early_stop_before_announced_last_is_unknown(self):
        self.unknown_when(1, http(self.fx["338"][0], links={"next": 2, "last": 3}))

    def test_static_get_only(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for verb in ("POST", "PATCH", "PUT", "DELETE"):
            self.assertNotIn(verb, literals)
        self.assertIn("GET", literals)
        self.assertNotIn("--paginate", literals)
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("for attempt", src)                   # no retry loop
        self.assertIn('encoding="utf-8", errors="replace"', src)


if __name__ == "__main__":
    unittest.main()
