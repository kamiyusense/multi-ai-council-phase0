"""STATIC correction fixtures. Atomic in-memory create; no real worker/account/write."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import queue
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from automation.command_bus.executor_backend import ExecutorContent
from automation.command_bus.symphony_attempt_store import GitHubAutonomousAttemptStore
from automation.command_bus.symphony_campaign_store import GitHubCampaignStateStore
from automation.command_bus.symphony_codex_app_server import JsonlCodexAppServer
from automation.command_bus.symphony_subscription_boundary import subscription_worker_environment
from automation.command_bus.tests.test_symphony_attempt_store import intent
from automation.command_bus.tests.test_symphony_campaign_store import state


class AtomicContents:
    """Both pre-GETs see absent; create is atomic, like create-only Contents PUT."""
    def __init__(self, race=False, lost_reply=False, read_failure=False, lost_before=False):
        self.files = {}
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(2) if race else None
        self.first_reads = set()
        self.creates = 0
        self.lost_reply = lost_reply
        self.read_failure = read_failure
        self.lost_before = lost_before
        self.submissions = []
        self.race_prefix = ""

    def get(self, path, ref):
        ident = (threading.get_ident(), path)
        with self.lock:
            first = ident not in self.first_reads
            self.first_reads.add(ident)
            snapshot = self.files.get(path)
        if self.barrier and first and (not self.race_prefix or (path.startswith(self.race_prefix) and path.endswith("intent.json"))):
            self.barrier.wait(timeout=5)
            return snapshot
        if self.read_failure and self.creates:
            raise RuntimeError("STATIC read unavailable")
        return snapshot

    def list(self, prefix, ref):
        with self.lock:
            return sorted((x for p, x in self.files.items() if p.startswith(prefix)), key=lambda x: x.path)

    def create(self, path, text, message, branch):
        with self.lock:
            self.creates += 1
            self.submissions.append(json.loads(text))
            if self.lost_before:
                raise RuntimeError("STATIC request uncertain before persistence")
            if path in self.files:
                raise RuntimeError("already exists")
            value = ExecutorContent(path, text, "fake-sha")
            self.files[path] = value
        if self.lost_reply:
            raise RuntimeError("STATIC reply lost after persistence")
        return value

    def update(self, *args):
        raise AssertionError("overwrite forbidden")


def attempt_store(client):
    return GitHubAutonomousAttemptStore(client, write_branch="proof/static-ledger")


def campaign_store(client):
    return GitHubCampaignStateStore(client, write_branch="proof/static-ledger")


class CorrectiveRaceTests(unittest.TestCase):
    def assert_one_owner(self, results, client):
        self.assertEqual(sum(r.status == "ACCEPTED" for r in results), 1)
        self.assertTrue(all(r.status in {"ACCEPTED", "CONFLICT", "AMBIGUOUS"} for r in results))
        self.assertEqual(client.creates, 2)
        self.assertEqual(len(client.files), 1)

    def test_two_attempt_writers_identical_logical_record_have_one_winner(self):
        c = AtomicContents(race=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assert_one_owner(list(pool.map(intent, [attempt_store(c), attempt_store(c)])), c)

    def test_two_campaign_writers_identical_state_have_one_winner(self):
        c = AtomicContents(race=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assert_one_owner(list(pool.map(lambda s: s.save(state(), expected_revision=0),
                                                [campaign_store(c), campaign_store(c)])), c)


    def test_raced_lost_reply_recovers_only_matching_operation_nonce(self):
        for kind in ("attempt", "campaign"):
            with self.subTest(kind=kind):
                c = AtomicContents(race=True, lost_reply=True)
                stores = [attempt_store(c), attempt_store(c)] if kind == "attempt" else [campaign_store(c), campaign_store(c)]
                action = intent if kind == "attempt" else lambda x: x.save(state(), expected_revision=0)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    self.assert_one_owner(list(pool.map(action, stores)), c)
                self.assertEqual(len({r["write_claim_nonce"] for r in c.submissions}), 2)
                for record in c.submissions:
                    self.assertEqual(record["write_claim_version"], 1)
                    self.assertRegex(record["write_claim_nonce"], r"^[0-9a-f]{64}$")

    def test_same_operation_lost_reply_and_read_failure_is_read_only_afterwards(self):
        for kind in ("attempt", "campaign"):
            with self.subTest(kind=kind):
                c = AtomicContents(lost_reply=True, read_failure=True)
                store = attempt_store(c) if kind == "attempt" else campaign_store(c)
                action = (lambda x: intent(x)) if kind == "attempt" else (lambda x: x.save(state(), expected_revision=0))
                self.assertEqual(action(store).status, "AMBIGUOUS")
                original = dict(c.submissions[0])
                # Copying a writer object does not mint another claim or nonce.
                self.assertNotEqual(action(copy.copy(store)).status, "ACCEPTED")
                self.assertEqual(c.creates, 1)
                self.assertEqual(c.submissions[0], original)
                c.read_failure = False
                if kind == "attempt":
                    fresh = attempt_store(c)
                    restored = fresh.restore("campaign-1", original["attempt_id"])
                    self.assertEqual(restored.state, "CLAIMED_UNSTARTED")
                else:
                    self.assertEqual(campaign_store(c).restore("campaign-1").revision, 1)
                self.assertEqual(c.creates, 1)

    def test_uncertain_request_without_persistence_is_not_resent_by_same_instance(self):
        for factory in (attempt_store, campaign_store):
            c = AtomicContents(lost_before=True)
            st = factory(c)
            action = intent if factory is attempt_store else lambda x: x.save(state(), expected_revision=0)
            self.assertEqual(action(st).status, "AMBIGUOUS")
            self.assertNotEqual(action(st).status, "ACCEPTED")
            self.assertEqual(c.creates, 1)
            self.assertEqual(c.files, {})

    def test_forked_store_cannot_copy_claim_authority(self):
        for factory in (attempt_store, campaign_store):
            c = AtomicContents()
            st = factory(c)
            action = intent if factory is attempt_store else lambda x: x.save(state(), expected_revision=0)
            with patch("os.getpid", return_value=st._process_id + 1):
                self.assertEqual(action(st).status, "CONFLICT")
            self.assertEqual(c.creates, 0)

    def test_success_reply_with_foreign_post_write_record_is_conflict(self):
        for factory in (attempt_store, campaign_store):
            c = AtomicContents()
            def foreign_create(path, text, message, branch):
                c.creates += 1
                record = json.loads(text)
                record["write_claim_nonce"] = "f" * 64
                value = ExecutorContent(path, json.dumps(record, sort_keys=True, separators=(",", ":")), "fake")
                c.files[path] = value
                return value
            c.create = foreign_create
            st = factory(c)
            action = intent if factory is attempt_store else lambda x: x.save(state(), expected_revision=0)
            self.assertEqual(action(st).status, "CONFLICT")
            self.assertEqual(c.creates, 1)

    def test_legacy_intent_can_chain_new_started_and_terminal_without_rewriting(self):
        c = AtomicContents()
        st = attempt_store(c)
        created = intent(st)
        path = next(iter(c.files))
        legacy = json.loads(c.files[path].text)
        legacy.pop("write_claim_version")
        legacy.pop("write_claim_nonce")
        raw = json.dumps(legacy, sort_keys=True, separators=(",", ":"))
        c.files[path] = ExecutorContent(path, raw, "legacy")
        fresh = attempt_store(c)
        self.assertEqual(fresh.append_started(campaign_id="campaign-1", attempt_id=created.attempt_id,
                                             provider_kind="STATIC", provider_attempt_ref="STATIC-worker",
                                             observation_source="STATIC_SIMULATION").status, "ACCEPTED")
        self.assertEqual(fresh.append_terminal(campaign_id="campaign-1", attempt_id=created.attempt_id,
                                              result_id="STATIC-terminal", outcome="DONE",
                                              model_started=True).status, "ACCEPTED")
        self.assertEqual(fresh.restore("campaign-1", created.attempt_id).state, "TERMINAL")
        self.assertEqual(c.files[path].text, raw)

    def test_legacy_campaign_checkpoint_extends_same_state_hash_chain(self):
        c = AtomicContents()
        st = campaign_store(c)
        self.assertEqual(st.save(state(), expected_revision=0).status, "ACCEPTED")
        path = next(iter(c.files))
        old = json.loads(c.files[path].text)
        old.pop("write_claim_nonce")
        old.pop("write_claim_version")
        raw = json.dumps(old, sort_keys=True, separators=(",", ":"))
        c.files[path] = ExecutorContent(path, raw, "legacy")
        fresh = campaign_store(c)
        next_state = state()
        next_state.generation = 2
        self.assertEqual(fresh.save(next_state, expected_revision=1).status, "ACCEPTED")
        self.assertEqual(fresh.restore("campaign-1").state.generation, 2)
        self.assertEqual(c.files[path].text, raw)
        self.assertEqual(fresh.save(state(), expected_revision=2).status, "CONFLICT")
        self.assertEqual(len(c.files), 2)

    def test_invalid_versioned_claim_is_not_read_as_legacy(self):
        for factory in (attempt_store, campaign_store):
            for changes in [{"write_claim_nonce": None}, {"write_claim_version": True},
                            {"write_claim_version": 99}, {"write_claim_nonce": "bad"}]:
                with self.subTest(factory=factory.__name__, changes=changes):
                    c = AtomicContents()
                    st = factory(c)
                    (intent(st) if factory is attempt_store else st.save(state(), expected_revision=0))
                    path = next(iter(c.files))
                    record = json.loads(c.files[path].text)
                    record.update(changes)
                    c.files[path] = ExecutorContent(path, json.dumps(record), "tampered")
                    with self.assertRaises((ValueError, RuntimeError)):
                        if factory is attempt_store:
                            st.restore("campaign-1", record["attempt_id"])
                        else:
                            st.restore("campaign-1")

    def test_two_controllers_race_only_one_static_runner_starts(self):
        from automation.command_bus.symphony_autonomous_controller import (
            StaticAutonomousCampaignController, StaticCampaignTaskRunner, StaticTargetObserver,
        )
        c = AtomicContents()
        campaign_store(c).save(state(), expected_revision=0)
        c.barrier = threading.Barrier(2)
        c.race_prefix = "symphony_attempts/"
        runners = [StaticCampaignTaskRunner(), StaticCampaignTaskRunner()]
        bots = [StaticAutonomousCampaignController(campaign_store(c), campaign_id="campaign-1",
                                                   target_observer=StaticTargetObserver("h1"), runner=r)
                for r in runners]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda x: x.run_until_boundary(max_steps=1), bots))
        self.assertEqual(sum(len(r.start_calls) for r in runners), 1)
        self.assertEqual(sum(r.status == "BATCH_LIMIT" for r in results), 1)



class CorrectiveWorkerEnvironmentTests(unittest.TestCase):
    def test_worker_does_not_inherit_controller_authority_and_parent_unchanged(self):
        denied = ["GITHUB_TOKEN", "GH_TOKEN", "SYMPHONY_G5_OBSERVER_KEY_HEX",
                  "SYMPHONY_G5_OBSERVER_EVENTS", "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
                  "ACTIONS_ID_TOKEN_REQUEST_URL", "OPENAI_API_KEY", "CODEX_API_KEY",
                  "AZURE_OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE",
                  "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "AWS_SESSION_TOKEN",
                  "AZURE_CLIENT_SECRET", "SSH_AUTH_SOCK", "ARBITRARY_AUTH", "CODEX_AUTH_JSON"]
        parent = {k: "STATIC_DUMMY" for k in denied}
        parent.update(PATH="/bin", HOME="/STATIC_HOME", LANG="ja_JP.UTF-8")
        original = dict(parent)
        self.assertEqual(subscription_worker_environment(parent),
                         {"PATH": "/bin", "HOME": "/STATIC_HOME", "LANG": "ja_JP.UTF-8"})
        self.assertEqual(parent, original)


class FakeOutput:
    def __init__(self):
        self.lines = queue.Queue()
    def __iter__(self):
        return self
    def __next__(self):
        line = self.lines.get()
        if line is None:
            raise StopIteration
        return line


class FakeProcess:
    def __init__(self, account=None, config=None):
        self.stdout = FakeOutput()
        self.stdin = self
        self.calls = []
        self.account = account or {"requiresOpenaiAuth": True, "account": {"type": "chatgpt", "planType": "plus"}}
        self.config = config or {"config": {"model_provider": "openai"}}
    def write(self, line):
        item = json.loads(line)
        self.calls.append(item)
        method = item.get("method")
        if method == "initialized":
            return
        if method == "account/read":
            result = self.account
        elif method == "config/read":
            result = self.config
        elif method == "thread/start":
            result = {"thread": {"id": "STATIC-thread"}, "modelProvider": "openai"}
        elif method == "turn/start":
            result = {"turn": {"id": "STATIC-turn", "status": "completed"}}
            for event in [
                {"method": "turn/started", "params": {"turn": {"id": "STATIC-turn"}}},
                {"method": "turn/completed", "params": {"turn": {"id": "STATIC-turn", "status": "completed"}}},
            ]:
                self.stdout.lines.put(json.dumps(event) + "\n")
        else:
            result = {}
        self.stdout.lines.put(json.dumps({"id": item["id"], "result": result}) + "\n")
    def flush(self):
        pass
    def close(self):
        pass
    def terminate(self):
        self.stdout.lines.put(None)
    def wait(self, timeout=None):
        return 0
    def kill(self):
        self.terminate()


class CorrectiveAccountAdmissionTests(unittest.TestCase):
    def execute(self, process, **kwargs):
        with patch.dict(os.environ, {"PATH": "/bin", "HOME": "/STATIC_HOME"}, clear=True), \
             patch("automation.command_bus.symphony_codex_app_server.subprocess.Popen", return_value=process):
            return JsonlCodexAppServer().execute_one_turn(cwd=str(Path(__file__).resolve().parents[3]),
                                                       prompt="STATIC", **kwargs)

    def test_missing_account_evidence_never_reaches_turn_start(self):
        process = FakeProcess(account={"requiresOpenaiAuth": True, "account": None})
        result = self.execute(process, live_enabled=True)
        self.assertFalse(result.model_started)
        self.assertNotIn("turn/start", [x["method"] for x in process.calls])


    def test_chatgpt_verified_unknown_quota_is_route_compatible_only(self):
        process = FakeProcess()
        result = self.execute(process, live_enabled=True)
        self.assertEqual(result.status, "DONE")  # STATIC fake transport, not real LIVE evidence.
        calls = [x["method"] for x in process.calls]
        self.assertLess(calls.index("account/read"), calls.index("turn/start"))
        account_call = next(x for x in process.calls if x["method"] == "account/read")
        self.assertEqual(account_call["params"], {"refreshToken": False})
        self.assertNotIn("account/rateLimits/read", calls)

    def test_unverified_api_key_and_self_claimed_account_evidence_block(self):
        for account in [
            {"requiresOpenaiAuth": True, "account": {"type": "apiKey"}},
            {"requiresOpenaiAuth": False, "account": {"type": "chatgpt"}},
            {"auth_state": "CHATGPT_ACCOUNT", "verified": True},
            {"requiresOpenaiAuth": True, "account": {"type": "UNKNOWN"}},
        ]:
            with self.subTest(account=account):
                process = FakeProcess(account=account)
                result = self.execute(process, live_enabled=True)
                self.assertEqual(result.status, "BLOCKED")
                self.assertFalse(result.dispatch_attempted)
                self.assertNotIn("thread/start", [x["method"] for x in process.calls])

    def test_unverified_runtime_or_paid_provider_config_blocks(self):
        for config in [{"UNKNOWN": True}, {"config": {}},
                       {"config": {"model_provider": "azure"}},
                       {"config": {"model_provider": "openai", "model_providers": {"openai": {"env_key": "STATIC"}}}},
                       {"config": {"model_provider": "openai", "paid_credit_fallback_configured": True}},
                       {"config": {"model_provider": "openai", "paid_credit_fallback_configured": 0}},
                       {"config": {"model_provider": "openai", "forced_login_method": "api"}},
                       {"config": {"model_provider": "openai", "service_tier": "fast"}}]:
            with self.subTest(config=config):
                process = FakeProcess(config=config)
                result = self.execute(process, live_enabled=True)
                self.assertEqual(result.status, "BLOCKED")
                self.assertFalse(result.dispatch_attempted)
                self.assertNotIn("thread/start", [x["method"] for x in process.calls])

    def test_evidence_that_ages_during_thread_start_is_not_used_for_dispatch(self):
        process = FakeProcess()
        clock = [0.0]
        original = process.write
        def write(line):
            if json.loads(line).get("method") == "thread/start":
                clock[0] = 61.0
            original(line)
        process.write = write
        with patch("automation.command_bus.symphony_codex_app_server.time.monotonic", side_effect=lambda: clock[0]):
            result = self.execute(process, live_enabled=True)
        self.assertEqual(result.status, "BLOCKED")
        self.assertFalse(result.dispatch_attempted)
        self.assertNotIn("turn/start", [x["method"] for x in process.calls])

    def test_environment_selectors_block_before_any_app_server_launch(self):
        for key in ["OPENAI_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE", "openai_api_key"]:
            with patch.dict(os.environ, {"PATH": "/bin", key: "STATIC_DUMMY"}, clear=True), \
                 patch("automation.command_bus.symphony_codex_app_server.subprocess.Popen") as popen:
                result = JsonlCodexAppServer().execute_one_turn(cwd="/STATIC", prompt="STATIC", live_enabled=True)
            self.assertFalse(result.dispatch_attempted)
            self.assertFalse(result.model_started)
            popen.assert_not_called()

    def test_transport_live_flag_is_off_by_default_even_with_valid_account_fixture(self):
        process = FakeProcess()
        result = self.execute(process)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(process.calls, [])

    def test_authentication_reader_exception_cannot_dispatch_or_log_private_message(self):
        process = FakeProcess()
        old_write = process.write
        def write(line):
            if json.loads(line).get("method") == "account/read":
                raise RuntimeError("STATIC_PRIVATE_MESSAGE_MUST_NOT_ESCAPE")
            old_write(line)
        process.write = write
        result = self.execute(process, live_enabled=True)
        self.assertFalse(result.dispatch_attempted)
        self.assertNotIn("STATIC_PRIVATE", repr(result))



if __name__ == "__main__":
    unittest.main()
