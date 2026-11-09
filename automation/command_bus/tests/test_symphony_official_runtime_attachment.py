"""Actual existing SQLite/snapshot components; fake Codex qualification only."""
from dataclasses import replace
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from . import test_symphony_sqlite_preparation as fixture
from . import test_symphony_g72_runtime as observation
from .. import symphony_official_runtime_attachment as subject
from ..symphony_sqlite_preparation import SQLiteSchemaPin, prepare_sqlite_review
from ..symphony_g72_runtime import BoundaryResult
from ..symphony_result_manifest import SourceResult
from ..scripts.check_symphony_subscription_startup import ROOT, RELATIVE, SOURCE_SHA256


class OfficialRuntimeCallbackTests(TestCase):
    def setUp(self):
        fixture.SQLitePreparationTests.setUp(self)
        self.branch="codex/symphony-worker-proof-fixture"
        subprocess.run(["git","init","-q","-b",self.branch,str(self.workspace)],check=True)
        subprocess.run(["git","-C",str(self.workspace),"-c","user.name=Fixture",
                        "-c","user.email=fixture@example.invalid","commit","--allow-empty","-qm","fixture"],check=True)
        self.head=subprocess.check_output(["git","-C",str(self.workspace),"rev-parse","HEAD"],text=True).strip()
        self.approval.return_value=True
        self.store._worker_check=Mock(return_value=True)
        if self._testMethodName=="test_real_elixir_consumes_storage_callback_with_fake_only":
            f=ROOT/"automation/command_bus/tests/fixtures/symphony_sqlite_installation/codex_jsonl_fixture.py"
            script=("#!/usr/bin/python3\nimport json,os,runpy,sys\n"
                    "with open(os.environ['SYMPHONY_STATIC_ARGV'],'w') as out:json.dump(sys.argv[1:],out)\n"
                    "sys.argv=["+repr(str(f))+",'good',os.environ['SYMPHONY_STATIC_LOG']]\n"
                    "runpy.run_path("+repr(str(f))+",run_name='__main__')\n")
            self.binary.write_text(script)
            self.store.review=replace(self.review,executable_sha256=hashlib.sha256(self.binary.read_bytes()).hexdigest())
        self.store.seal_initialized()  # synthetic fixture only, before independent expected pins
        # Independent fixture authority fixes schema before exercising the adapter.
        # No production expected schema is inferred from a live database.
        with patch("automation.command_bus.symphony_sqlite_preparation.qualify_native_binary",return_value={"fixture":True}):
            packet=prepare_sqlite_review(self.store)
        self.pins=tuple(SQLiteSchemaPin(**row) for row in packet["schema"])
        self.runtime_review=subject.OfficialRuntimeReview(str(self.workspace),self.branch,self.head,
            "be10a1b79df723d6d7612b5651c8522704dafb2e",1200,"a"*64)
        self.authority=Mock(return_value=True)
        self.isolation=Mock(return_value=True)

    def callbacks(self, **changes):
        args=dict(review=self.runtime_review,storage=self.store,expected_schema=self.pins,
                  clock=lambda:1000,command_approval=self.authority,isolation_check=self.isolation)
        args.update(changes)
        return subject.ReviewedOfficialRuntimeCallbacks(**args)

    def test_default_command_and_isolation_callbacks_refuse(self):
        for args in ({"command_approval":None},{"isolation_check":None},
                     {"command_approval":lambda _:False},{"isolation_check":lambda _:False}):
            with self.subTest(args=args),self.assertRaises(PermissionError):
                self.callbacks(**args).command_for_workspace(self.workspace)

    def test_fixed_command_contains_only_exact_storage_override_no_secret(self):
        command=self.callbacks().command_for_workspace(self.workspace)
        self.assertEqual(shlex.split(command),
                         [str(self.binary),"app-server","-c",'sqlite_home='+json.dumps(str(self.root))])
        self.authority.assert_called_once();self.isolation.assert_called_once_with("a"*64)
        self.assertNotIn("SYNTHETIC_AUTH",command)

    def test_expired_wrong_workspace_head_or_separate_storage_approval_refused(self):
        for review in (replace(self.runtime_review,expires_at=1000),
                       replace(self.runtime_review,source_head="b"*40),
                       replace(self.runtime_review,branch="main")):
            with self.subTest(review=review),self.assertRaises(PermissionError):
                self.callbacks(review=review).command_for_workspace(self.workspace)
        self.store._worker_check.return_value=False
        with self.assertRaises(PermissionError):self.callbacks().command_for_workspace(self.workspace)

    def test_schema_missing_or_changed_with_same_migrations_refused(self):
        with self.assertRaises(PermissionError):
            self.callbacks(expected_schema=None).command_for_workspace(self.workspace)
        bad=(replace(self.pins[0],schema_sha256="f"*64),)
        with self.assertRaises(PermissionError):
            self.callbacks(expected_schema=bad).command_for_workspace(self.workspace)

    def test_approval_time_workspace_drift_refused_preserved(self):
        def drift(_):
            (self.workspace/"uncommitted").write_text("PRESERVE")
            return True
        with self.assertRaises(PermissionError):
            self.callbacks(command_approval=drift).command_for_workspace(self.workspace)
        self.assertEqual((self.workspace/"uncommitted").read_text(),"PRESERVE")

    def test_snapshot_hold_or_untrusted_readback_never_releases_cleanup(self):
        for result in (BoundaryResult("HOLD_SNAPSHOT","A"),
                       BoundaryResult("ACCEPTED","A",close_ready=False),
                       BoundaryResult("ACCEPTED","OTHER_ATTEMPT",close_ready=True)):
            reader=Mock()
            with self.assertRaises(PermissionError):
                self.callbacks(snapshot_callback=Mock(return_value=result),snapshot_readback=reader).before_cleanup(
                    attempt_id="A",snapshot_id="S",captured_at="fixture")
            reader.assert_not_called()
        with self.assertRaises(PermissionError):
            self.callbacks(snapshot_callback=Mock(return_value=BoundaryResult("ACCEPTED","A",close_ready=True)),
                snapshot_readback=Mock(return_value=SourceResult("x",{},False,False))).before_cleanup(
                    attempt_id="A",snapshot_id="S",captured_at="fixture")

    def test_snapshot_callback_exceptions_are_sanitized_without_replay(self):
        for during in ('capture','readback'):
            capture=Mock(return_value=BoundaryResult("ACCEPTED","A",close_ready=True))
            reader=Mock(return_value=SourceResult("x",{},True,True))
            failing=capture if during=='capture' else reader
            failing.side_effect=RuntimeError("SYNTHETIC_PRIVATE_SENTINEL")
            with self.subTest(during=during),self.assertRaises(PermissionError) as found:
                self.callbacks(snapshot_callback=capture,snapshot_readback=reader).before_cleanup(
                    attempt_id="A",snapshot_id="S",captured_at="fixture")
            self.assertNotIn("SYNTHETIC_PRIVATE_SENTINEL",str(found.exception))
            self.assertIsNone(found.exception.__cause__)
            failing.assert_called_once()

    def test_existing_signed_observer_snapshot_full_readback_survives_cleanup_and_restart(self):
        w=observation.ObservedWorld(self.base/"observed").reserve()
        adapter=w.adapter()
        def readback(attempt_id,snapshot_id):
            return w.snapshots.load(snapshot_id,expected_campaign_id="g61-static",
                expected_attempt_id=attempt_id,expected_worker_run_id=w.worker)
        scoped_review=replace(self.runtime_review,workspace=str(w.workspace))
        callback=self.callbacks(review=scoped_review,snapshot_callback=adapter.snapshot,snapshot_readback=readback)
        result=callback.before_cleanup(attempt_id=w.attempt_id,snapshot_id=w.snapshot_id,captured_at=observation.NOW)
        self.assertFalse(result["cleanup_executed"])
        before=readback(w.attempt_id,w.snapshot_id)
        shutil.rmtree(w.workspace)  # only disposable fixture, after verified gate
        self.assertEqual(readback(w.attempt_id,w.snapshot_id).files,before.files)
        restarted=self.callbacks(review=scoped_review,snapshot_callback=w.adapter().snapshot,snapshot_readback=readback)
        self.assertEqual(restarted.before_cleanup(attempt_id=w.attempt_id,snapshot_id=w.snapshot_id,
                                                 captured_at=observation.NOW)["status"],
                         "SNAPSHOT_READBACK_BEFORE_CLEANUP")

    @skipUnless(os.environ.get("SYMPHONY_TEST_ELIXIR") and os.environ.get("SYMPHONY_TEST_JASON_EBIN"),
                "explicit existing Elixir/Jason unavailable")
    def test_real_elixir_consumes_storage_callback_with_fake_only(self):
        fixture_root=ROOT/"automation/command_bus/tests/fixtures/symphony_sqlite_installation"
        raw=gzip.decompress((fixture_root/"pinned_app_server.ex.gz").read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(),SOURCE_SHA256)
        upstream=self.base/"upstream";source=upstream/RELATIVE
        source.parent.mkdir(parents=True);source.write_bytes(raw)
        subprocess.run(["git","init","-q",str(upstream)],check=True)
        patch_file=ROOT/"automation/command_bus/symphony_subscription_startup.patch"
        subprocess.run(["git","-C",str(upstream),"apply","--check",str(patch_file)],check=True)
        subprocess.run(["git","-C",str(upstream),"apply",str(patch_file)],check=True)
        # This qualification seam applies ONLY to a Python fake, never production.
        with patch.object(subject,"qualify_native_binary",return_value={"fixture_only":True}), \
             patch("automation.command_bus.symphony_sqlite_preparation.qualify_native_binary",
                   return_value={"fixture_only":True}):
            command=self.callbacks().command_for_workspace(self.workspace)
        runner=self.base/"callback_fixture.exs"
        fixture_text=(fixture_root/"startup_fixture.exs").read_text()
        fixture_text=fixture_text.replace("[source, script, root, scenario, log] = System.argv()",
            "[source, script, root, scenario, log, reviewed_command] = System.argv()")
        fixture_text=fixture_text.replace('"/usr/bin/python3 #{script} #{scenario} #{log}"',
            'reviewed_command')
        runner.write_text(fixture_text)  # isolated copy; sealed original bytes unchanged
        log=self.base/"calls.jsonl";argv_log=self.base/"argv.json"
        blocked=("GH_TOKEN","GITHUB_TOKEN","OPENAI_API_KEY","CODEX_API_KEY","AZURE_OPENAI_API_KEY",
                 "OPENAI_BASE_URL","OPENAI_API_BASE","SYMPHONY_G5_OBSERVER_KEY_HEX","SYMPHONY_G5_OBSERVER_EVENTS")
        env={k:v for k,v in os.environ.items() if k not in blocked}
        env.update({"SYMPHONY_STATIC_LOG":str(log),"SYMPHONY_STATIC_ARGV":str(argv_log)})
        run=subprocess.run([os.environ["SYMPHONY_TEST_ELIXIR"],"-pa",os.environ["SYMPHONY_TEST_JASON_EBIN"],
            str(runner),str(source),str(fixture_root/"codex_jsonl_fixture.py"),
            str(self.base),"good",str(log),command],env=env,capture_output=True,text=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr)
        calls=[json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([x["method"] for x in calls[:5]],
                         ["initialize","initialized","account/read","config/read","thread/start"])
        self.assertEqual(sum(x["method"]=="thread/start" for x in calls),1)
        self.assertEqual(sum(x["method"]=="turn/start" for x in calls),3)
        self.assertFalse(any(x["blocked_environment_names_present"] for x in calls))
        self.assertEqual(json.loads(argv_log.read_text()),
                         ["app-server","-c",'sqlite_home='+json.dumps(str(self.root))])
        subprocess.run(["git","-C",str(upstream),"apply","--reverse",str(patch_file)],check=True)
        self.assertEqual(source.read_bytes(),raw)
