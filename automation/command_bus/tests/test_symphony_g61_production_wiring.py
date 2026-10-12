"""G6.1 production-wiring STATIC tests: real adapter code, simulated GitHub."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import tempfile
import unittest
from unittest import mock

from .symphony_g6_fixtures import SimulatedCrash, crash_at
from .symphony_g61_github_sim import LostReply, REPO, REPO_ID, SimulatedGitHub
from .test_symphony_campaign_store import FakeCampaignContents
from ..symphony_attempt_store import GitHubAutonomousAttemptStore
from ..symphony_g61_wiring import generate_result_manifest, wire_adoption
from ..symphony_git_adoption import AppendOnlyAdoptionStore, StaticAdoptionBridge, construct_candidate
from ..symphony_github_git_transport import (UPDATE_REFS_DOCUMENT, GitHubGitTransport, classify_update_refs_reply,
                                             prepare_update_refs)
from ..symphony_github_readers import (GitHubTargetReader, GitHubTaskValidityReader, ReadOnlyGitHubHttp,
                                       parse_task_block, read_repository_identity)
from ..symphony_result_manifest import FileEntry, digest, seal_manifest
from ..symphony_result_verification import (assemble_verification, builtin_secret_patterns, builtin_syntax,
                                            external_record)
from ..symphony_workspace_snapshot import SnapshotIntegrityError, WorkspaceSnapshotStore, scan_workspace, workspace_fingerprint

TARGET = "proof/g61-static"
NOW = "2026-10-10T01:00:00Z"
FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "symphony_g61"
BASE = {"README.md": FileEntry(b"unchanged\n"), "src/value.py": FileEntry(b"value = 1\n")}
TRUSTED = {"ci-runner": "EXTERNAL_CI", "g61-syntax": "G61_BUILTIN_SYNTAX", "g61-patterns": "G61_BUILTIN_SECRET_PATTERNS"}


def issue_body(task_id, scope, request):
    block = json.dumps({"protocol": "SYMPHONY_G61_TASK_V1", "task_id": task_id, "request": request, "scope": scope})
    return f"Proof task.\n\n```symphony-task\n{block}\n```\n"


class World:
    """One campaign attempt with a real temp workspace and a simulated GitHub."""

    def __init__(self, tmp, *, task_id="A", gh=None, client=None, changes=None):
        self.tmp, self.task_id = pathlib.Path(tmp), task_id
        self.gh = gh or SimulatedGitHub()
        if self.gh.head(TARGET) is None:
            head = self.gh.commit_files(BASE)
            self.gh.set_branch("main", head); self.gh.set_branch(TARGET, head)
        self.head = self.gh.head(TARGET)
        self.number = 100 + ord(task_id[0])
        self.issue_id = f"{REPO}#{self.number}"
        self.request = {"ask": "update value and add proof note", "task": task_id}
        self.scope = {"issue": self.issue_id, "allowed_paths": ["src/value.py"], "allowed_prefixes": ["proof"],
                      "required_checks": ["syntax", "tests"], "request_digest": digest(self.request)}
        self.gh.issues[self.number] = {"number": self.number, "title": "G6.1 STATIC " + task_id,
            "body": issue_body(task_id, self.scope, self.request), "state": "OPEN", "stateReason": None,
            "locked": False, "author": {"login": "owner"}, "editor": None, "lastEditedAt": None,
            "labels": {"totalCount": 0, "nodes": []}}
        # Workspace as Official Symphony would leave it: a clone plus edits.
        self.workspace = self.tmp / f"workspace-{task_id}"
        files = {"README.md": b"unchanged\n", "src/value.py": b"value = 2\n", f"proof/{task_id}.md": b"G6.1 synthetic result\n"}
        files.update(changes or {})
        for path, data in files.items():
            target = self.workspace / path; target.parent.mkdir(parents=True, exist_ok=True)
            if data is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(data)
        (self.workspace / ".git").mkdir(exist_ok=True); (self.workspace / ".git" / "HEAD").write_text("ref: refs/heads/x\n")
        self.client = client or FakeCampaignContents()
        self.attempts = GitHubAutonomousAttemptStore(self.client, write_branch="fixture/attempt-ledger")
        intent = self.attempts.append_intent(campaign_id="g61-static", task_id=task_id, generation=1, attempt_number=1,
                                             expected_target_head=self.head, runner_generation=1, scope=self.scope)
        self.attempt_id = intent.attempt_id
        self.worker = (format(ord(task_id[0]), "x") * 32)[:32]
        self.attempts.append_started(campaign_id="g61-static", attempt_id=self.attempt_id,
            provider_kind="OFFICIAL_SYMPHONY_CODEX", provider_attempt_ref=self.worker, observation_source="STATIC_SIMULATION",
            workspace_fingerprint=workspace_fingerprint(str(self.workspace)))
        self.attempts.append_terminal(campaign_id="g61-static", attempt_id=self.attempt_id,
            result_id="sym-g5-worker:" + self.worker, outcome="UNKNOWN", unknown_class="RECOVERABLE_UNKNOWN",
            model_started=None, evidence_refs=["sym-g5:sha256:" + "3" * 64, "sym-g5-status:WORKER_STOPPED"])
        self.snapshots = WorkspaceSnapshotStore(str(self.tmp / "snapshots"))
        self.snapshot_id = "snap-" + self.attempt_id[:40]
        self.ledger = AppendOnlyAdoptionStore(self.client, write_branch="fixture/g61-ledger")
        self.external = {"tests": "PASS", "secret_scan": "PASS"}
        self.extra_records = []
        self.manifest = None

    def attempt(self):
        return self.attempts.restore("g61-static", self.attempt_id)

    def capture(self):
        return self.snapshots.capture(workspace=str(self.workspace), snapshot_id=self.snapshot_id, campaign_id="g61-static",
                                      attempt_id=self.attempt_id, worker_run_id=self.worker, captured_at=NOW)

    def target_reader(self, **limits):
        return GitHubTargetReader(self.gh, repository=REPO, branch=TARGET, default_branch="main", **limits)

    def make_manifest(self):
        base = self.target_reader().read_at(self.head)
        self.manifest = generate_result_manifest(attempt=self.attempt(), repository=REPO, target_branch=TARGET,
            base=base, source=self.snapshots.load(self.snapshot_id))
        return self.manifest

    def records(self):
        source = self.snapshots.load(self.snapshot_id)
        out = [builtin_syntax(self.manifest, source, verifier_id="g61-syntax", observed_at=NOW)[0],
               builtin_secret_patterns(self.manifest, source, verifier_id="g61-patterns", observed_at=NOW)[0]]
        out += [external_record(self.manifest, check=c, verifier_id="ci-runner", status=s, details={"run": "fixture"}, observed_at=NOW)
                for c, s in self.external.items()]
        return out + self.extra_records

    def wired(self, trusted=TRUSTED, **changes):
        args = dict(http=self.gh, repository=REPO, repository_id=REPO_ID, target_branch=TARGET, default_branch="main",
            ledger=self.ledger, attempt_reader=self.attempt, snapshots=self.snapshots, snapshot_id=self.snapshot_id,
            worker_run_id=self.worker, issue_id=self.issue_id, task_id=self.task_id, trusted_issue_logins={"owner"},
            verification_records=self.records, trusted_verifiers=trusted, manifest_ref=lambda: self.manifest)
        args.update(changes)
        return wire_adoption(**args)

    def ready(self):
        self.capture(); self.make_manifest(); return self

    def run(self, hook=lambda point: None):
        return self.wired().process(self.manifest, now=NOW, crash_hook=hook)


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(); self.tmp = self._tmp.name

    def tearDown(self):
        for root, dirs, files in os.walk(self.tmp):
            for name in files:
                os.chmod(os.path.join(root, name), stat.S_IWRITE | stat.S_IREAD)
        self._tmp.cleanup()


class UpdateRefsContractTests(unittest.TestCase):
    def test_official_schema_readback_documents_atomic_beforeOid(self):
        schema = json.loads((FIXTURES / "graphql-updaterefs-schema.json").read_text(encoding="utf-8"))
        text = schema["mutations"]["updateRefs"]["description"]
        self.assertIn("All updates are performed atomically", text)
        self.assertIn("beforeOid` specifies that the given reference needs to point", text)
        self.assertFalse(schema["mutations"]["updateRefs"]["isDeprecated"])
        fields = {f["name"]: f for f in schema["RefUpdate"]["inputFields"]}
        self.assertEqual(set(fields), {"name", "afterOid", "beforeOid", "force"})
        self.assertEqual(fields["force"]["defaultValue"], "false")
        # beforeOid is optional in the schema: the adapter must always supply it.
        self.assertEqual(fields["beforeOid"]["type"]["kind"], "SCALAR")
        self.assertEqual({f["name"] for f in schema["UpdateRefsInput"]["inputFields"]}, {"clientMutationId", "repositoryId", "refUpdates"})
        self.assertNotIn("before", json.dumps(schema["UpdateRefInput"]).lower().replace("beforeoid", ""))

    def test_prepare_is_single_non_force_expected_head_update(self):
        req = prepare_update_refs(repository_id=REPO_ID, branch=TARGET, default_branch="main",
                                  before_oid="a" * 40, after_oid="b" * 40, client_mutation_id="sym-g61-x")
        self.assertEqual(req["document"], UPDATE_REFS_DOCUMENT)
        self.assertEqual(req["variables"]["input"]["refUpdates"],
                         [{"name": "refs/heads/" + TARGET, "beforeOid": "a" * 40, "afterOid": "b" * 40, "force": False}])
        self.assertEqual(req["request_digest"], prepare_update_refs(repository_id=REPO_ID, branch=TARGET, default_branch="main",
                         before_oid="a" * 40, after_oid="b" * 40, client_mutation_id="sym-g61-x")["request_digest"])

    def test_prepare_rejects_default_zero_create_delete_noop_and_bad_ids(self):
        good = dict(repository_id=REPO_ID, branch=TARGET, default_branch="main", before_oid="a" * 40,
                    after_oid="b" * 40, client_mutation_id="x")
        bad = [dict(branch="main"), dict(branch="master"), dict(branch="HEAD"), dict(branch="refs/heads/x"),
               dict(branch="trunk", default_branch="trunk"), dict(before_oid="0" * 40), dict(after_oid="0" * 40),
               dict(before_oid=None), dict(before_oid="A" * 40), dict(after_oid="a" * 40), dict(repository_id=""),
               dict(repository_id="x y"), dict(client_mutation_id="")]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare_update_refs(**{**good, **change})

    def test_reply_classification_never_trusts_ambiguous_success(self):
        ok = {"data": {"updateRefs": {"clientMutationId": "c"}}}
        self.assertEqual(classify_update_refs_reply(200, ok, "c"), "SUCCESS_REPLY")
        self.assertEqual(classify_update_refs_reply(200, {"data": {"updateRefs": {"clientMutationId": "d"}}}, "c"), "UNKNOWN_REPLY")
        self.assertEqual(classify_update_refs_reply(200, {"errors": [{}], **ok}, "c"), "REJECTED_REPLY")
        for status, body in [(502, ok), (200, None), (200, {"data": None}), (403, {"message": "rate limit"})]:
            self.assertEqual(classify_update_refs_reply(status, body, "c"), "UNKNOWN_REPLY")

    def test_live_http_cannot_be_wired_and_read_only_client_refuses_writes_offline(self):
        live = ReadOnlyGitHubHttp("token-for-shape-only")
        with self.assertRaisesRegex(ValueError, "NOT_WIRED"):
            GitHubGitTransport(live, repository=REPO, repository_id=REPO_ID, target_branch=TARGET,
                               default_branch="main", target_reader=None)
        with mock.patch.object(ReadOnlyGitHubHttp, "_send", side_effect=AssertionError("network used")):
            for method in ["POST", "PATCH", "PUT", "DELETE"]:
                with self.assertRaises(PermissionError):
                    live.request(method, "repos/x/y/git/refs", {})
            for doc in [UPDATE_REFS_DOCUMENT, "  mutation { x }", "# c\nmutation X { y }", "query Q { a } mutation M { b }",
                        "subscription S { a }"]:
                with self.assertRaises(PermissionError):
                    live.graphql(doc, {})
        self.assertNotIn("token-for-shape-only", repr(live))
        self.assertEqual(live.requests, 0)

    def test_simulated_atomic_cas_has_exactly_one_winner(self):
        gh = SimulatedGitHub(); head = gh.commit_files(BASE); gh.set_branch(TARGET, head)
        a = gh.commit_files({**BASE, "proof/a": FileEntry(b"a\n")}, parent=head)
        b = gh.commit_files({**BASE, "proof/b": FileEntry(b"b\n")}, parent=head)
        t = GitHubGitTransport(gh, repository=REPO, repository_id=REPO_ID, target_branch=TARGET,
                               default_branch="main", target_reader=None)
        t.compare_and_swap(branch=TARGET, expected_head=head, candidate_head=a)
        with self.assertRaises(RuntimeError):
            t.compare_and_swap(branch=TARGET, expected_head=head, candidate_head=b)
        self.assertEqual(gh.head(TARGET), a)
        self.assertEqual(t.ref_replies, ["SUCCESS_REPLY", "REJECTED_REPLY"])
        with self.assertRaises(ValueError):
            t.compare_and_swap(branch="other", expected_head=a, candidate_head=b)
        self.assertEqual(gh.update_refs_requests, 2)


class ReaderTests(TempCase):
    def test_target_reader_verifies_every_tree_and_blob_hash(self):
        w = World(self.tmp); target = w.target_reader().read()
        self.assertTrue(target.complete and target.trustworthy)
        self.assertEqual(target.head, w.head); self.assertEqual(dict(target.files), BASE)
        oid = next(o for o, (k, raw) in w.gh.objects.items() if k == "blob" and raw == b"value = 1\n")
        w.gh.tamper_blob_reads[oid] = b"value = 666\n"
        with self.assertRaisesRegex(RuntimeError, "hash"):
            w.target_reader().read()

    def test_target_reader_truncated_or_over_limit_is_incomplete_not_smaller(self):
        w = World(self.tmp); w.gh.truncate_trees = True
        t = w.target_reader().read(); self.assertFalse(t.complete); self.assertEqual(dict(t.files), {})
        w.gh.truncate_trees = False
        self.assertFalse(w.target_reader(max_files=1).read().complete)
        self.assertFalse(w.target_reader(max_bytes=5).read().complete)

    def test_target_reader_default_branch_drift_and_missing_ref_raise(self):
        w = World(self.tmp); w.gh.default_branch = TARGET
        with self.assertRaises(RuntimeError):
            w.target_reader().read()
        w.gh.default_branch = "main"; del w.gh.refs["refs/heads/" + TARGET]
        with self.assertRaises(RuntimeError):
            w.target_reader().read()
        with self.assertRaises(ValueError):
            GitHubTargetReader(w.gh, repository=REPO, branch="main", default_branch="main")

    def test_repository_identity_query(self):
        ident = read_repository_identity(SimulatedGitHub(), REPO)
        self.assertEqual(ident["repository_id"], REPO_ID); self.assertEqual(ident["default_branch"], "main")

    def validity(self, w, **issue):
        w.gh.issues[w.number].update(issue)
        reader = GitHubTaskValidityReader(w.gh, repository=REPO, trusted_logins={"owner"})
        return reader.read(w.target_reader().read(), issue_id=w.issue_id, task_id=w.task_id)

    def test_validity_open_closed_labels_and_trust(self):
        w = World(self.tmp)
        v = self.validity(w)
        self.assertEqual((v.valid, v.trustworthy, v.scope_digest, v.request_digest), (True, True, digest(w.scope), w.scope["request_digest"]))
        self.assertIsNone(self.validity(w, state="CLOSED", stateReason="COMPLETED").valid)
        self.assertTrue(self.validity(w, labels={"totalCount": 1, "nodes": [{"name": "symphony:adopt-after-close"}]}).valid)
        self.assertFalse(self.validity(w, stateReason="NOT_PLANNED").valid)
        w = World(self.tmp, task_id="B")
        self.assertFalse(self.validity(w, labels={"totalCount": 1, "nodes": [{"name": "symphony:superseded"}]}).valid)
        self.assertFalse(self.validity(w, labels={"totalCount": 99, "nodes": []}).trustworthy)
        w = World(self.tmp, task_id="C")
        self.assertFalse(self.validity(w, editor={"login": "stranger"}).trustworthy)
        self.assertFalse(self.validity(w, editor=None, author={"login": "stranger"}).trustworthy)

    def test_validity_changed_request_or_scope_and_block_shape(self):
        w = World(self.tmp)
        request = {**w.request, "ask": "something else"}
        v = self.validity(w, body=issue_body("A", {**w.scope, "request_digest": digest(request)}, request))
        self.assertNotEqual(v.request_digest, w.scope["request_digest"])
        v = self.validity(w, body=issue_body("A", {**w.scope, "allowed_prefixes": ["proof", "src"]}, w.request))
        self.assertNotEqual(v.scope_digest, digest(w.scope))
        for body in ["no block", issue_body("A", w.scope, w.request) * 2, issue_body("A", {**w.scope, "request_digest": "0" * 64}, w.request),
                     issue_body("OTHER", w.scope, w.request)]:
            with self.subTest(body=body[:20]):
                self.assertFalse(self.validity(w, body=body).trustworthy)
        with self.assertRaises(ValueError):
            parse_task_block("```symphony-task\n[]\n```")


class SnapshotTests(TempCase):
    def test_capture_outside_workspace_survives_workspace_deletion(self):
        w = World(self.tmp); result = w.capture()
        self.assertEqual(result.status, "VERIFIED"); self.assertTrue(result.close_gate_open)
        before = w.snapshots.load(w.snapshot_id)
        self.assertNotIn(".git/HEAD", before.files)
        shutil.rmtree(w.workspace)  # Official Symphony cleanup after Issue close
        after = w.snapshots.load(w.snapshot_id)
        self.assertEqual(dict(after.files), dict(before.files))
        self.assertEqual(after.files["src/value.py"].sha256, FileEntry(b"value = 2\n").sha256)
        self.assertEqual(after.workspace_fingerprint, workspace_fingerprint(str(w.workspace)))
        self.assertEqual(result.manifest_sha256, w.snapshots.manifest_sha256(w.snapshot_id))

    def test_store_inside_workspace_or_workspace_inside_store_rejected(self):
        w = World(self.tmp)
        for root in [w.workspace / "snap", self.tmp]:
            with self.subTest(root=root), self.assertRaises(ValueError):
                WorkspaceSnapshotStore(str(root)).capture(workspace=str(w.workspace), snapshot_id="s1", campaign_id="c",
                    attempt_id="a", worker_run_id=w.worker, captured_at=NOW)

    def test_duplicate_capture_noop_and_reused_id_with_new_bytes_conflicts(self):
        w = World(self.tmp); self.assertEqual(w.capture().status, "VERIFIED")
        self.assertEqual(w.capture().status, "NOOP_DUPLICATE")
        (w.workspace / "proof" / "A.md").write_bytes(b"changed later\n")
        r = w.capture(); self.assertEqual(r.status, "CONFLICT"); self.assertFalse(r.close_gate_open)

    def test_workspace_change_during_capture_is_unstable(self):
        w = World(self.tmp); real = scan_workspace; calls = []
        def scan(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                (w.workspace / "proof" / "late.md").write_bytes(b"late\n")
            return real(*a, **k)
        with mock.patch("automation.command_bus.symphony_workspace_snapshot.scan_workspace", scan):
            r = w.capture()
        self.assertEqual(r.status, "UNSTABLE"); self.assertFalse(r.close_gate_open)
        with self.assertRaises(SnapshotIntegrityError):
            w.snapshots.load(w.snapshot_id)

    def test_object_or_manifest_tamper_detected(self):
        w = World(self.tmp); w.capture()
        obj = w.snapshots._object_path(FileEntry(b"value = 2\n").sha256)
        os.chmod(obj, stat.S_IWRITE | stat.S_IREAD); obj.write_bytes(b"value = 3\n")
        with self.assertRaises(SnapshotIntegrityError):
            w.snapshots.load(w.snapshot_id)
        self.assertEqual(w.capture().status, "CONFLICT")  # never re-stores over a bad object
        w2 = World(tempfile.mkdtemp(dir=self.tmp), task_id="B"); w2.capture()
        path = w2.snapshots._manifest_path(w2.snapshot_id); os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        data = json.loads(path.read_text()); data["worker_run_id"] = "f" * 32; path.write_text(json.dumps(data))
        with self.assertRaises(SnapshotIntegrityError):
            w2.snapshots.load(w2.snapshot_id)
        w3 = World(tempfile.mkdtemp(dir=self.tmp), task_id="C"); w3.capture()
        missing = w3.snapshots._object_path(FileEntry(b"G6.1 synthetic result\n").sha256)
        os.chmod(missing, stat.S_IWRITE | stat.S_IREAD); os.unlink(missing)
        with self.assertRaises(SnapshotIntegrityError):
            w3.snapshots.load(w3.snapshot_id)

    def test_nested_git_is_kept_but_incomplete(self):
        w = World(self.tmp); (w.workspace / "proof" / "sub" / ".git").mkdir(parents=True)
        r = w.capture(); self.assertEqual(r.status, "VERIFIED"); self.assertEqual(r.anomalies, ("nested_git:proof/sub/.git",))
        self.assertFalse(w.snapshots.load(w.snapshot_id).complete)

    def test_symlink_recorded_not_followed(self):
        w = World(self.tmp); outside = pathlib.Path(self.tmp) / "outside-secret"; outside.write_bytes(b"do not copy\n")
        try:
            os.symlink(str(outside), w.workspace / "proof" / "link")
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted on this platform")
        w.capture(); entry = w.snapshots.load(w.snapshot_id).files["proof/link"]
        self.assertEqual((entry.mode, entry.kind), ("120000", "symlink"))
        self.assertNotIn(b"do not copy", entry.data)

    def test_wrong_worker_cannot_load_snapshot(self):
        w = World(self.tmp); w.capture()
        with self.assertRaises(SnapshotIntegrityError):
            w.snapshots.load(w.snapshot_id, expected_worker_run_id="e" * 32)


class VerificationTests(TempCase):
    def bundle(self, w, records=None, **kw):
        return assemble_verification(w.manifest, w.records() if records is None else records, trusted_verifiers=kw.pop("trusted", TRUSTED),
                                     worker_run_id=w.worker, **kw)

    def test_complete_independent_bundle_trusted(self):
        w = World(self.tmp).ready(); b = self.bundle(w)
        self.assertTrue(b.evidence.trustworthy, b.reasons)
        self.assertEqual(dict(b.evidence.checks), {"syntax": True, "tests": True, "secret_scan": True, "secret_pattern_scan": True})
        self.assertTrue(set(b.evidence.evidence_refs) <= set(w.manifest["evidence_refs"]))

    def test_builtin_cannot_satisfy_external_checks_and_worker_cannot_verify(self):
        w = World(self.tmp).ready()
        fake = [r for r in w.records() if r["check"] != "secret_scan"]
        fake.append({**external_record(w.manifest, check="secret_scan", verifier_id="g61-patterns", status="PASS", details={}, observed_at=NOW)})
        self.assertFalse(self.bundle(w, fake).evidence.trustworthy)
        trusted = {**TRUSTED, w.worker: "EXTERNAL_CI"}
        own = w.records() + [external_record(w.manifest, check="tests", verifier_id=w.worker, status="PASS", details={}, observed_at=NOW)]
        self.assertFalse(self.bundle(w, own, trusted=trusted).evidence.trustworthy)

    def test_missing_failed_conflicting_rebound_or_tampered_records_hold(self):
        w = World(self.tmp).ready(); good = w.records()
        cases = {"missing": good[:-1],
                 "conflict": good + [external_record(w.manifest, check="tests", verifier_id="ci-runner", status="FAIL", details={}, observed_at=NOW)],
                 "rebound": good[:-1] + [external_record({**w.manifest, "result_digest": "0" * 64}, check="secret_scan",
                                                         verifier_id="ci-runner", status="PASS", details={}, observed_at=NOW)],
                 "tampered": good[:-1] + [{**good[-1], "status": "PASS", "observed_at": "later"}],
                 "unknown": good + [{"protocol": "x"}]}
        for name, records in cases.items():
            with self.subTest(name):
                self.assertFalse(self.bundle(w, records).evidence.trustworthy)
        w.external["tests"] = "FAIL"; b = self.bundle(w)
        self.assertTrue(b.evidence.trustworthy); self.assertFalse(b.evidence.checks["tests"])

    def test_builtin_syntax_and_pattern_scan_detect_without_execution(self):
        w = World(self.tmp, changes={"src/value.py": b"def broken(:\n", "proof/k.md": b"key AKIA" + b"A" * 16 + b"\n"}).ready()
        source = w.snapshots.load(w.snapshot_id)
        rec, details = builtin_syntax(w.manifest, source, verifier_id="g61-syntax", observed_at=NOW)
        self.assertEqual(rec["status"], "FAIL"); self.assertEqual(details["failures"][0]["path"], "src/value.py")
        rec, details = builtin_secret_patterns(w.manifest, source, verifier_id="g61-patterns", observed_at=NOW)
        self.assertEqual(rec["status"], "FAIL"); self.assertEqual(details["hit_paths"], ["proof/k.md"])
        self.assertNotIn("AKIA", json.dumps(details))
        w2 = World(self.tmp, task_id="B", changes={"src/value.py": b"raise SystemExit('executed')\n"}).ready()
        rec, _ = builtin_syntax(w2.manifest, w2.snapshots.load(w2.snapshot_id), verifier_id="g61-syntax", observed_at=NOW)
        self.assertEqual(rec["status"], "PASS")  # parsed only; never executed


class WiredAdoptionTests(TempCase):
    def counters(self, w):
        return (w.gh.update_refs_requests, w.gh.ref_mutations, w.gh.object_posts)

    def test_end_to_end_adopt_then_cleanup_then_replay_noop(self):
        w = World(self.tmp).ready(); r = w.run()
        self.assertEqual(r.status, "ADOPTED", r.reason)
        head = w.gh.head(TARGET)
        self.assertEqual(r.receipt["head_after"], head); self.assertEqual(r.receipt["head_before"], w.head)
        self.assertEqual(w.gh.tree_files(head), dict(w.snapshots.load(w.snapshot_id).files))
        self.assertEqual((w.gh.update_refs_requests, w.gh.ref_mutations), (1, 1))
        self.assertEqual(w.gh.head("main"), w.head)  # default branch untouched
        shutil.rmtree(w.workspace)  # Symphony workspace cleanup after close
        before = self.counters(w)
        again = w.run(); self.assertEqual(again.status, "NOOP_DUPLICATE")
        self.assertEqual(self.counters(w), before)

    def test_candidate_identity_matches_local_construction(self):
        w = World(self.tmp).ready(); r = w.run()
        local = construct_candidate(parent=w.head, files=w.snapshots.load(w.snapshot_id).files, created_at=NOW, adoption_id=r.adoption_id)
        self.assertEqual(r.receipt["head_after"], local.commit); self.assertEqual(r.receipt["tree_after"], local.tree)

    def test_commit_message_echo_variants_both_verify(self):
        for strip in (True, False):
            with self.subTest(strip=strip):
                tmp = tempfile.mkdtemp(dir=self.tmp)
                w = World(tmp).ready(); w.gh.strip_commit_newline = strip
                self.assertEqual(w.run().status, "ADOPTED")

    def test_crash_restart_points_never_resend_ref_update(self):
        for point, expected in [("AFTER_INTENT", "ADOPTED"), ("AFTER_OBJECTS", "ADOPTED"),
                                ("AFTER_REF_INTENT", "UNKNOWN"), ("AFTER_REF", "ADOPTED")]:
            with self.subTest(point=point):
                w = World(tempfile.mkdtemp(dir=self.tmp)).ready()
                with self.assertRaises(SimulatedCrash):
                    w.run(hook=crash_at(point))
                before = w.gh.update_refs_requests
                shutil.rmtree(w.workspace)  # restart after cleanup: snapshot is the source
                r = w.run()  # fresh WiredAdoption == controller restart
                self.assertEqual(r.status, expected, r.reason)
                self.assertEqual(w.gh.update_refs_requests, before if point in {"AFTER_REF_INTENT", "AFTER_REF"} else 1)
                self.assertLessEqual(w.gh.update_refs_requests, 1)
                self.assertEqual(w.run().status, "NOOP_DUPLICATE" if expected == "ADOPTED" else "UNKNOWN")
                self.assertLessEqual(w.gh.update_refs_requests, 1)

    def test_lost_reply_after_apply_resolved_by_GET_only(self):
        w = World(self.tmp).ready(); w.gh.lose_reply_after_apply = True
        r = w.run(); self.assertEqual(r.status, "ADOPTED", r.reason)
        self.assertEqual((w.gh.update_refs_requests, w.gh.ref_mutations), (1, 1))

    def test_lost_request_before_apply_stays_unknown_without_resend(self):
        w = World(self.tmp).ready(); w.gh.lose_reply_before_apply = True
        self.assertEqual(w.run().status, "UNKNOWN")
        w.gh.lose_reply_before_apply = False
        for _ in range(2):
            self.assertEqual(w.run().status, "UNKNOWN")
        self.assertEqual((w.gh.update_refs_requests, w.gh.ref_mutations, w.gh.head(TARGET)), (1, 0, w.head))

    def test_cas_race_other_writer_preserved_and_no_resend(self):
        w = World(self.tmp).ready()
        w.gh.race_before_update_refs = lambda: w.gh.advance(TARGET, {**BASE, "other.md": FileEntry(b"x\n")})
        r = w.run(); self.assertEqual(r.status, "UNKNOWN")
        other = w.gh.head(TARGET); w.gh.race_before_update_refs = None
        self.assertNotEqual(other, w.head)
        self.assertEqual(w.run().status, "UNKNOWN")
        self.assertEqual((w.gh.update_refs_requests, w.gh.ref_mutations, w.gh.head(TARGET)), (1, 0, other))

    def test_stale_head_before_inspection_zero_writes(self):
        w = World(self.tmp).ready(); w.gh.advance(TARGET, {**BASE, "other.md": FileEntry(b"x\n")})
        r = w.run(); self.assertEqual(r.status, "STALE_REPLAN")
        self.assertEqual(self.counters(w), (0, 0, 0))

    def test_head_advanced_before_manifest_generation_is_durable_stale_replan(self):
        w = World(self.tmp); w.capture()
        w.gh.advance(TARGET, {**BASE, "other.md": FileEntry(b"x\n")})
        w.make_manifest()  # base read at the attempt's expected HEAD, not the new tip
        self.assertEqual(w.manifest["expected_target_head"], w.head)
        r = w.run(); self.assertEqual(r.status, "STALE_REPLAN")
        self.assertIsNotNone(r.decision_evidence); self.assertEqual(self.counters(w), (0, 0, 0))
        saved = w.ledger.get("g61-static", r.adoption_id, "inspection-" + digest(r.decision_evidence))
        self.assertEqual(saved["action"], "STALE_REPLAN")
        with self.assertRaises(ValueError):
            generate_result_manifest(attempt=w.attempt(), repository=REPO, target_branch=TARGET,
                                     base=w.target_reader().read(), source=w.snapshots.load(w.snapshot_id))

    def test_head_moves_between_objects_and_ref_no_ref_call(self):
        w = World(self.tmp).ready(); wired = w.wired(); real = wired.transport.put_candidate
        def put_then_move(candidate):
            real(candidate); w.gh.advance(TARGET, {**BASE, "other.md": FileEntry(b"x\n")})
        wired.transport.put_candidate = put_then_move
        self.assertEqual(wired.process(w.manifest, now=NOW).status, "STALE_REPLAN")
        self.assertEqual(w.gh.update_refs_requests, 0)

    def test_scope_outside_and_protected_files_isolate_with_zero_writes(self):
        for i, (path, status) in enumerate([("outside.txt", "ISOLATE_TASK"), (".github/workflows/x.yml", "ISOLATE_TASK"),
                                            ("AGENTS.md", "ISOLATE_TASK")]):
            with self.subTest(path=path):
                w = World(tempfile.mkdtemp(dir=self.tmp), changes={path: b"x\n"}).ready()
                self.assertEqual(w.run().status, status); self.assertEqual(self.counters(w), (0, 0, 0))

    def test_scope_violation_isolates_one_task_and_independent_task_adopts(self):
        gh = SimulatedGitHub(); client = FakeCampaignContents()
        bad = World(self.tmp, task_id="A", gh=gh, client=client, changes={"outside.txt": b"x\n"}).ready()
        good = World(self.tmp, task_id="B", gh=gh, client=client).ready()
        self.assertEqual(bad.run().status, "ISOLATE_TASK")
        self.assertEqual(good.run().status, "ADOPTED")

    def test_delete_and_binary_held_by_profile(self):
        for changes in [{"src/value.py": None}, {"proof/A.md": b"\0binary"}]:
            with self.subTest(changes=list(changes)):
                w = World(tempfile.mkdtemp(dir=self.tmp), changes=changes).ready()
                self.assertEqual(w.run().status, "ISOLATE_TASK"); self.assertEqual(self.counters(w), (0, 0, 0))

    def test_result_tampering_variants(self):
        w = World(self.tmp).ready(); w.manifest = {**w.manifest, "source_digest": "0" * 64}
        self.assertEqual(w.run().status, "CONFLICT")
        w = World(tempfile.mkdtemp(dir=self.tmp)).ready()
        forged = seal_manifest({**w.manifest, "worker_run_id": "e" * 32}); w.manifest = forged
        self.assertEqual(w.run().status, "CONFLICT")
        w = World(tempfile.mkdtemp(dir=self.tmp)).ready()
        obj = w.snapshots._object_path(FileEntry(b"value = 2\n").sha256); os.chmod(obj, stat.S_IWRITE | stat.S_IREAD)
        obj.write_bytes(b"value = 9\n")
        self.assertEqual(w.run().status, "HOLD_AUTHORITY")
        self.assertEqual(self.counters(w), (0, 0, 0))

    def test_remote_object_tamper_after_adoption_detected_on_replay(self):
        w = World(self.tmp).ready(); self.assertEqual(w.run().status, "ADOPTED")
        oid = next(o for o, (k, raw) in w.gh.objects.items() if k == "blob" and raw == b"value = 2\n")
        w.gh.tamper_blob_reads[oid] = b"value = 7\n"
        self.assertEqual(w.run().status, "CONFLICT")
        self.assertEqual(w.gh.update_refs_requests, 1)

    def test_github_returns_foreign_object_sha_no_ref_write(self):
        w = World(self.tmp).ready(); w.gh.tamper_created_sha = True
        self.assertEqual(w.run().status, "UNKNOWN"); self.assertEqual(w.gh.update_refs_requests, 0)

    def test_untrusted_or_missing_verification_and_validity_hold(self):
        w = World(self.tmp).ready(); w.external = {"tests": "PASS"}
        self.assertEqual(w.run().status, "HOLD_AUTHORITY")
        w = World(tempfile.mkdtemp(dir=self.tmp)).ready()
        self.assertEqual(w.wired(trusted={}).process(w.manifest, now=NOW).status, "HOLD_AUTHORITY")
        w = World(tempfile.mkdtemp(dir=self.tmp)).ready(); w.gh.issues[w.number]["state"] = "CLOSED"
        self.assertEqual(w.run().status, "HOLD_AUTHORITY")
        w = World(tempfile.mkdtemp(dir=self.tmp)).ready(); w.gh.issues[w.number].update(state="CLOSED", stateReason="NOT_PLANNED")
        self.assertEqual(w.run().status, "ISOLATE_TASK")
        w = World(tempfile.mkdtemp(dir=self.tmp)).ready(); w.gh.fail_get = lambda path: "/git/trees/" in path
        self.assertEqual(w.run().status, "HOLD_AUTHORITY")

    def test_closed_issue_with_explicit_label_still_adopts_after_cleanup(self):
        w = World(self.tmp).ready(); shutil.rmtree(w.workspace)
        w.gh.issues[w.number].update(state="CLOSED", stateReason="COMPLETED",
                                     labels={"totalCount": 1, "nodes": [{"name": "symphony:adopt-after-close"}]})
        self.assertEqual(w.run().status, "ADOPTED")

    def test_target_lock_and_atomic_cas_against_two_ledgers(self):
        gh = SimulatedGitHub()
        a = World(self.tmp, task_id="A", gh=gh).ready(); b = World(self.tmp, task_id="B", gh=gh).ready()
        # Separate ledgers: the per-ledger target lock cannot see each other,
        # so only GitHub's atomic beforeOid decides. B races A at the write.
        wired = b.wired(); real = wired.transport.compare_and_swap
        def a_wins_first(**kw):
            self.assertEqual(a.run().status, "ADOPTED"); return real(**kw)
        wired.transport.compare_and_swap = a_wins_first
        self.assertEqual(wired.process(b.manifest, now=NOW).status, "UNKNOWN")
        self.assertEqual(gh.ref_mutations, 1); self.assertEqual(gh.update_refs_requests, 2)
        self.assertEqual(wired.transport.ref_replies, ["REJECTED_REPLY"])


if __name__ == "__main__":
    unittest.main()


def run_g61_matrix():
    """Observed outcomes through real G6.1 adapters + simulated GitHub."""
    def tamper_manifest(w):
        w.manifest = {**w.manifest, "source_digest": "0" * 64}
    def tamper_snapshot(w):
        obj = w.snapshots._object_path(FileEntry(b"value = 2\n").sha256)
        os.chmod(obj, stat.S_IWRITE | stat.S_IREAD); obj.write_bytes(b"value = 9\n")
    def race(w):
        w.gh.race_before_update_refs = lambda: (w.gh.advance(TARGET, {**BASE, "other.md": FileEntry(b"x\n")}),
                                                setattr(w.gh, "race_before_update_refs", None))
    cases = [
        ("K01", "adopt, workspace cleanup, replay", None, None, {}),
        ("K02", "crash after intent", "AFTER_INTENT", None, {}),
        ("K03", "crash after objects", "AFTER_OBJECTS", None, {}),
        ("K04", "crash after pre-ref fence", "AFTER_REF_INTENT", None, {}),
        ("K05", "crash after applied ref", "AFTER_REF", None, {}),
        ("K06", "updateRefs reply lost after apply", None, lambda w: setattr(w.gh, "lose_reply_after_apply", True), {}),
        ("K07", "updateRefs request lost before apply", None, lambda w: setattr(w.gh, "lose_reply_before_apply", True), {}),
        ("K08", "CAS race: other writer at write time", None, race, {}),
        ("K09", "stale HEAD before inspection", None, lambda w: w.gh.advance(TARGET, {**BASE, "other.md": FileEntry(b"x\n")}), {}),
        ("K10", "scope-outside file", None, None, {"outside.txt": b"x\n"}),
        ("K11", "result manifest tampered", None, tamper_manifest, {}),
        ("K12", "snapshot bytes tampered", None, tamper_snapshot, {}),
        ("K13", "GitHub returns foreign object sha", None, lambda w: setattr(w.gh, "tamper_created_sha", True), {}),
    ]
    outcomes = []
    with tempfile.TemporaryDirectory() as root:
        for case, label, crash, fault, changes in cases:
            w = World(tempfile.mkdtemp(dir=root), changes=changes).ready()
            if fault:
                fault(w)
            first = None
            if crash:
                try:
                    w.run(hook=crash_at(crash))
                except SimulatedCrash:
                    first = "SIMULATED_CRASH_" + crash
            else:
                first = w.run().status
            w.gh.lose_reply_before_apply = False
            if w.workspace.exists():
                shutil.rmtree(w.workspace)  # Symphony cleanup; snapshot remains the source
            restart = w.run().status
            outcomes.append({"case": case, "label": label, "first": first, "after_cleanup_restart": restart,
                             "update_refs_requests": w.gh.update_refs_requests, "our_ref_mutations": w.gh.ref_mutations,
                             "object_posts": w.gh.object_posts, "default_branch_unchanged": w.gh.head("main") == w.head,
                             "real_github_writes": 0, "model_provider_LIVE": 0})
        for root_dir, _, files in os.walk(root):
            for name in files:
                os.chmod(os.path.join(root_dir, name), stat.S_IWRITE | stat.S_IREAD)
    return outcomes


class MatrixTests(unittest.TestCase):
    def test_committed_matrix_matches_executed(self):
        expected = json.loads((FIXTURES / "regression-matrix.json").read_text(encoding="utf-8"))
        observed = {o["case"]: [o["first"], o["after_cleanup_restart"], o["update_refs_requests"], o["our_ref_mutations"]]
                    for o in run_g61_matrix()}
        self.assertEqual(observed, expected)
        self.assertTrue(all(v[2] <= 1 for v in observed.values()))  # never a second updateRefs
