"""M9 one-shot runner: STATIC tests with fixture backends only (no real Codex, no provider)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from relay import m9_codex_first_live as m
from relay import m9_live_state as st
from relay.acp_stdio_relay_transport import AcpStdioStaticTransport, OfficialAdapterLaunch
from providers.codex_acp import build_codex_profile

REPO = Path(__file__).resolve().parents[2]
HEAD = "a" * 40
PHRASE = f"APPROVE_FIRST_LIVE_POC {HEAD[:7]}"
SECRETS = ("secret.person@example.invalid", "acct-SECRET-0001", "tok-SECRET-0002")


def git_ok(repo, branch):
    return {"head": HEAD, "branch": m.EXPECTED_BRANCH, "clean": True, "remote_head": HEAD}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="m9 test "))  # a space on purpose
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.backend_dir = self.tmp / "codex bin dir"          # outside fixtures/relay, with spaces
        self.backend_dir.mkdir()
        self.backend = self.backend_dir / "fake_codex_app_server.py"
        shutil.copy(REPO / "fixtures" / "relay" / "fake_codex_app_server.py", self.backend)
        (self.tmp / "codex home").mkdir()
        self.log = self.tmp / "backend.log"
        self.lines = []

    def cfg(self, **over):
        env = {"FAKE_CODEX_LOG": str(self.log)}
        env.update(over.pop("extra_env", {}))
        launcher = REPO / "src" / "relay" / ("codex_turn_gate.cmd" if os.name == "nt" else "codex_turn_gate.py")
        base = dict(
            repo_root=REPO, state_dir=self.tmp / "state dir", codex_path=str(self.backend),
            codex_home=self.tmp / "codex home", node_path=shutil.which("node") or "node", npm_path=None,
            gate_launcher=launcher, git_probe=git_ok, confirm=lambda prompt: PHRASE,
            out=self.lines.append, install_adapter=False, extra_env=env,
            adapter_dir=Path(os.environ["RELAY_CODEX_ACP_DIR"]) if os.environ.get("RELAY_CODEX_ACP_DIR") else None,
        )
        base.update(over)
        return m.Config(**base)

    def backend_methods(self):
        return self.log.read_text().split() if self.log.exists() else []

    def state_files(self):
        d = self.tmp / "state dir"
        return {p.name for p in d.iterdir()} if d.exists() else set()


class TestPreflightAndStops(Base):
    def run_stub(self, cfg):
        """run() with the adapter/live turn stubbed out; asserts whether the live turn was reached."""
        with mock.patch.object(m, "ensure_adapter", return_value=Path("unused")), \
                mock.patch.object(m, "run_live_turn", side_effect=AssertionError("live turn must not run")) as live:
            rc = m.run(cfg)
        return rc, live

    def test_missing_codex_stops_without_install_or_login(self):
        rc, _ = self.run_stub(self.cfg(codex_path=None))
        self.assertEqual(rc, 2)
        self.assertTrue(any("見つかりません" in line for line in self.lines))
        self.assertEqual(self.backend_methods(), [])

    def test_missing_login_directory_stops(self):
        rc, _ = self.run_stub(self.cfg(codex_home=self.tmp / "no such home"))
        self.assertEqual(rc, 2)
        self.assertTrue(any("ログイン" in line for line in self.lines))
        self.assertEqual(self.backend_methods(), [])

    def test_head_not_latest_dirty_or_wrong_branch_stop(self):
        for probe in (
            lambda r, b: {**git_ok(r, b), "remote_head": "b" * 40},
            lambda r, b: {**git_ok(r, b), "clean": False},
            lambda r, b: {**git_ok(r, b), "branch": "main"},
        ):
            with self.subTest():
                rc, _ = self.run_stub(self.cfg(git_probe=probe))
                self.assertEqual(rc, 2)

    def test_git_unknown_stops(self):
        def boom(r, b):
            raise RuntimeError("no git")
        rc, _ = self.run_stub(self.cfg(git_probe=boom))
        self.assertEqual(rc, 2)

    def test_wrong_confirmation_stops_before_any_backend_contact(self):
        rc, _ = self.run_stub(self.cfg(confirm=lambda p: "yes"))
        self.assertEqual(rc, 5)
        self.assertEqual(self.backend_methods(), [])
        self.assertNotIn(st.CONSUMED_FILE, self.state_files())

    def test_no_interactive_console_stops(self):
        with mock.patch.object(m.sys, "stdin", None):
            rc, _ = self.run_stub(self.cfg(confirm=None))
        self.assertEqual(rc, 5)

    def test_account_variants_stop_with_zero_model_turns(self):
        for kind in ("apikey", "none", "malformed", "error"):
            with self.subTest(kind):
                self.log.unlink(missing_ok=True)
                rc, live = self.run_stub(self.cfg(extra_env={"FAKE_CODEX_ACCOUNT": kind}))
                self.assertEqual(rc, 4)
                live.assert_not_called()
                self.assertNotIn("turn/start", self.backend_methods())
                self.assertNotIn(st.CONSUMED_FILE, self.state_files())
                self.assertNotIn(st.TERMINAL_FILE, self.state_files())
                self.assertEqual(self.backend_methods().count("account/read"), 1)  # exactly one read-only query

    def test_account_probe_pass_returns_only_sanitized_fields(self):
        cfg = self.cfg()
        env = m.child_env(cfg, self.tmp / "g.log", self.tmp)
        summary = m.probe_account(cfg, env)
        self.assertEqual(summary, {"auth_state": "CHATGPT_ACCOUNT", "plan_type": "plus", "side_effects": 0})
        self.assertEqual(self.backend_methods(), ["initialize", "account/read"])
        self.assertNotIn("turn/start", self.backend_methods())

    def test_terminal_receipt_makes_rerun_a_noop(self):
        cfg = self.cfg()
        (self.tmp / "state dir").mkdir()
        (self.tmp / "state dir" / st.TERMINAL_FILE).write_text('{"terminal_state":"UNKNOWN_ERROR"}', encoding="utf-8")
        rc, live = self.run_stub(cfg)
        self.assertEqual(rc, 0)
        live.assert_not_called()
        self.assertEqual(self.backend_methods(), [])

    def test_consumed_without_terminal_is_unknown_and_not_rerun(self):
        (self.tmp / "state dir").mkdir()
        (self.tmp / "state dir" / st.CONSUMED_FILE).write_text("{}", encoding="utf-8")
        rc, live = self.run_stub(self.cfg())
        self.assertEqual(rc, 3)
        live.assert_not_called()
        self.assertEqual(self.backend_methods(), [])


class TestContractAndGuards(Base):
    def test_checklist_is_the_runtime_contract(self):
        data = m.load_checklist(REPO)
        self.assertEqual((m.TIMEOUT_SECONDS, m.PROVIDER if hasattr(m, "PROVIDER") else st.PROVIDER), (60, "openai"))
        self.assertEqual(data["scope"]["max_generations"], 1)
        bad = self.tmp / "repo"
        (bad / "fixtures" / "relay").mkdir(parents=True)
        broken = json.loads((REPO / m.CHECKLIST_REL).read_text())
        broken["scope"]["max_generations"] = 2
        (bad / m.CHECKLIST_REL).write_text(json.dumps(broken))
        with self.assertRaises(ValueError):
            m.load_checklist(bad)

    def test_fixed_prompt_and_no_auto_live_entry_point(self):
        self.assertEqual(m.PROMPT, "M9_OK とだけ返答してください。ファイルを読まない、ファイルを書かない、commandを実行しない、toolを使用しない。")
        script = (REPO / "RUN_M9_CODEX_FIRST_LIVE.cmd").read_text()
        self.assertIn("relay.m9_codex_first_live", script)
        self.assertNotIn("APPROVE_FIRST_LIVE_POC", script)  # the approval phrase is typed by the human, never scripted

    def _approval(self, **changes):
        record = {
            "decision": st.DECISION, "scope": st.SCOPE, "one_shot": True, "provider": st.PROVIDER,
            "max_dispatches": 1, "max_prompts": 1, "max_generations": 1, "retry": 0, "fallback": "disabled"}
        record.update(changes)
        return {"record": record, "approval_sha256": st.canonical_sha256(record)}

    def test_approval_record_validation(self):
        st.verify_approval_record(self._approval())
        for bad in ({"decision": "REJECT"}, {"scope": "ANY"}, {"one_shot": False}, {"provider": "anthropic"},
                    {"max_generations": 2}, {"retry": 1}, {"fallback": "enabled"}):
            with self.subTest(bad), self.assertRaises(ValueError):
                st.verify_approval_record(self._approval(**bad))
        tampered = self._approval()
        tampered["record"]["max_prompts"] = 1
        tampered["record"]["nonce"] = "changed"
        with self.assertRaises(ValueError):
            st.verify_approval_record(tampered)

    def _launch(self, auth):
        launcher = REPO / "src" / "relay" / ("codex_turn_gate.cmd" if os.name == "nt" else "codex_turn_gate.py")
        env = {"CODEX_PATH": str(launcher), "RELAY_GATE_BACKEND": str(self.backend)}
        return OfficialAdapterLaunch(("node", "x/codex-acp/dist/index.js"), env, REPO / "fixtures" / "relay", auth)

    def _profile(self):
        return build_codex_profile("account", {
            "api_key_present": False, "gateway_configured": False, "external_cloud_configured": False,
            "custom_model_provider_configured": False, "arbitrary_codex_config_present": False})

    def test_real_backend_needs_a_consumed_matching_approval(self):
        state = self.tmp / "state dir"
        state.mkdir()
        approval = self._approval()
        auth = st.LiveAuthorization(state, approval["approval_sha256"])
        with self.assertRaises(ValueError):                       # no authorization at all
            AcpStdioStaticTransport(self._profile(), official=self._launch(None))
        with self.assertRaisesRegex(ValueError, "APPROVAL_PROVENANCE_NOT_VERIFIED"):  # no approval file
            AcpStdioStaticTransport(self._profile(), official=self._launch(auth))
        (state / st.APPROVAL_FILE).write_text(json.dumps(approval))
        with self.assertRaisesRegex(ValueError, "APPROVAL_PROVENANCE_NOT_VERIFIED"):  # not consumed
            AcpStdioStaticTransport(self._profile(), official=self._launch(auth))
        (state / st.CONSUMED_FILE).write_text(json.dumps({"approval_sha256": "0" * 64}))
        with self.assertRaisesRegex(ValueError, "APPROVAL_PROVENANCE_NOT_VERIFIED"):  # consumed for another approval
            AcpStdioStaticTransport(self._profile(), official=self._launch(auth))
        (state / st.CONSUMED_FILE).write_text(json.dumps({"approval_sha256": approval["approval_sha256"]}))
        transport = AcpStdioStaticTransport(self._profile(), official=self._launch(auth))
        self.assertTrue(transport.live)
        (state / st.TERMINAL_FILE).write_text("{}")
        with self.assertRaises(ValueError):                       # finished one-shot cannot launch again
            AcpStdioStaticTransport(self._profile(), official=self._launch(auth))

    def test_other_provider_cannot_use_live_authorization(self):
        with self.assertRaises(ValueError):
            st.verify_live_authorization(st.LiveAuthorization(self.tmp, "0" * 64), "anthropic")

    def test_exclusive_write_is_single_use(self):
        path = self.tmp / "once.json"
        self.assertTrue(st.write_exclusive(path, {"a": 1}))
        self.assertFalse(st.write_exclusive(path, {"a": 2}))
        self.assertEqual(json.loads(path.read_text()), {"a": 1})

    def test_secret_like_content_is_refused(self):
        for text in SECRETS + ("sk-abcdefgh12345",):
            with self.assertRaises(ValueError):
                m._assert_no_secret({"x": text})
        m._assert_no_secret({"auth_state": "CHATGPT_ACCOUNT", "plan_type": "plus"})

    def test_default_git_probe_with_real_repo(self):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e.x")

        def git(*args, cwd):
            subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)
        remote, work = self.tmp / "remote.git", self.tmp / "work tree"
        git("init", "--bare", str(remote), cwd=self.tmp)
        git("clone", str(remote), str(work), cwd=self.tmp)
        git("checkout", "-b", m.EXPECTED_BRANCH, cwd=work)
        (work / "f.txt").write_text("1")
        git("add", ".", cwd=work)
        git("commit", "-m", "c1", cwd=work)
        git("push", "origin", m.EXPECTED_BRANCH, cwd=work)
        probe = m.default_git_probe(work, m.EXPECTED_BRANCH)
        self.assertEqual((probe["branch"], probe["clean"], probe["head"] == probe["remote_head"]),
                         (m.EXPECTED_BRANCH, True, True))
        (work / "f.txt").write_text("2")
        self.assertFalse(m.default_git_probe(work, m.EXPECTED_BRANCH)["clean"])


@unittest.skipUnless(os.environ.get("RELAY_CODEX_ACP_DIR") and shutil.which("node"),
                     "RELAY_CODEX_ACP_DIR / node not available (TEST_ENVIRONMENT_NOT_PREPARED)")
class TestFullFlowWithOfficialAdapterAndFixtureBackend(Base):
    """Real codex-acp 2.1.0 + Relay gate + a fixture standing in for the 'real' backend (outside fixtures/)."""

    def terminal(self):
        return json.loads((self.tmp / "state dir" / st.TERMINAL_FILE).read_text(encoding="utf-8"))

    def test_success_one_generation_and_receipt_has_no_secrets(self):
        before = set(Path(tempfile.gettempdir()).glob("m9_applogs_*"))
        rc = m.run(self.cfg(extra_env={"FAKE_CODEX_LOG": str(self.log), "FAKE_CODEX_REPLY": "M9_OK", "FAKE_CODEX_DELTAS": "5"}))
        self.assertEqual(rc, 0, "\n".join(self.lines))
        receipt = self.terminal()
        self.assertEqual(receipt["terminal_state"], "SUCCESS_M9_OK")
        self.assertTrue(receipt["response_was_M9_OK"])
        self.assertEqual((receipt["dispatch_count"], receipt["prompt_count"], receipt["gate_allowed_generations"],
                          receipt["backend_generations_reached"], receipt["retry_count"], receipt["fallback_state"],
                          receipt["timeout_seconds"], receipt["account_auth_state"]),
                         (1, 1, 1, 1, 0, "disabled", 60, "CHATGPT_ACCOUNT"))
        self.assertEqual(self.backend_methods().count("turn/start"), 1)
        self.assertEqual(self.backend_methods().count("initialize"), 2)  # one account probe + one live adapter
        self.assertEqual(self.backend_methods().count("account/read"), 3)  # probe 1 + adapter's own session/new reads
        blob = "\n".join(self.lines) + "".join(
            p.read_text(encoding="utf-8", errors="ignore") for p in (self.tmp / "state dir").iterdir() if p.is_file())
        for secret in SECRETS:
            self.assertNotIn(secret, blob)
        self.assertEqual(set(Path(tempfile.gettempdir()).glob("m9_applogs_*")), before)  # raw adapter logs removed

    def test_duplicate_run_is_noop_and_terminal_is_final(self):
        extra = {"FAKE_CODEX_LOG": str(self.log), "FAKE_CODEX_REPLY": "M9_OK"}
        self.assertEqual(m.run(self.cfg(extra_env=extra)), 0)
        calls = self.backend_methods()
        self.assertEqual(m.run(self.cfg(extra_env=extra)), 0)       # NO-OP
        self.assertEqual(self.backend_methods(), calls)             # nothing reached the backend again

    def test_unexpected_text_is_terminal_not_retried(self):
        rc = m.run(self.cfg(extra_env={"FAKE_CODEX_LOG": str(self.log), "FAKE_CODEX_REPLY": "hello"}))
        self.assertEqual(rc, 1)
        self.assertEqual(self.terminal()["terminal_state"], "COMPLETED_UNEXPECTED_TEXT")
        self.assertEqual(self.backend_methods().count("turn/start"), 1)

    def test_timeout_is_terminal_with_no_retry_or_relaunch(self):
        extra = {"FAKE_CODEX_LOG": str(self.log), "FAKE_CODEX_NO_COMPLETE": "1"}
        rc = m.run(self.cfg(timeout_seconds=3, extra_env=extra))
        self.assertEqual(rc, 1)
        self.assertEqual(self.terminal()["terminal_state"], "TIMEOUT")
        calls = self.backend_methods()
        self.assertEqual(calls.count("turn/start"), 1)
        self.assertEqual(m.run(self.cfg(timeout_seconds=3, extra_env=extra)), 0)  # NO-OP: terminal receipt exists
        self.assertEqual(self.backend_methods(), calls)

    def test_api_key_route_stops_before_any_model_turn(self):
        rc = m.run(self.cfg(extra_env={"FAKE_CODEX_LOG": str(self.log), "FAKE_CODEX_ACCOUNT": "apikey"}))
        self.assertEqual(rc, 4)
        self.assertNotIn("turn/start", self.backend_methods())
        self.assertNotIn(st.CONSUMED_FILE, self.state_files())

    def test_second_generation_is_blocked_by_the_gate(self):
        rc = m.run(self.cfg(extra_env={"FAKE_CODEX_LOG": str(self.log), "FAKE_CODEX_REPLY": "M9_OK"}))
        self.assertEqual(rc, 0)
        gate = m.count_gate_decisions(self.tmp / "state dir" / "gate.log")
        self.assertEqual(gate["allowed"], 1)
        self.assertEqual(self.backend_methods().count("turn/start"), 1)


if __name__ == "__main__":
    unittest.main()
