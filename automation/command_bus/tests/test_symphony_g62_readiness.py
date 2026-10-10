"""G6.2 negative/fault/restart qualification. All GitHub calls are mocks."""
from __future__ import annotations

import base64
import copy
import concurrent.futures
import threading
import hashlib
import io
import json
import os
import shutil
import zipfile
from dataclasses import replace
from unittest import mock

from .test_symphony_g61_production_wiring import World, TempCase, NOW, REPO, REPO_ID, TARGET, TRUSTED
from ..symphony_g62_prepare import PrepareOnlyGitHubTransport
from ..symphony_g62_attestation import CIContract, CIArtifactVerificationReader, AttestationUnavailable
from ..symphony_github_git_transport import prepare_candidate_requests, TransportIntegrityError, GitHubGitTransport
from ..symphony_github_readers import GitHubTaskValidityReader, bind_validity_reader
from ..symphony_git_adoption import construct_candidate, make_adoption_id
from ..symphony_result_manifest import FileEntry, digest
from ..symphony_result_verification import assemble_verification
from ..symphony_workspace_snapshot import SnapshotIntegrityError


def preparer(w, **extra):
    return PrepareOnlyGitHubTransport(repository=REPO, repository_id=REPO_ID, target_branch=TARGET,
        default_branch="main", target_reader=w.target_reader(), validity_reader=bind_validity_reader(
            GitHubTaskValidityReader(w.gh, repository=REPO, trusted_logins={"owner"}), issue_id=w.issue_id,
            task_id=w.task_id), **extra)


def prepare(w, adapter=None, records=None):
    v = assemble_verification(w.manifest, w.records() if records is None else records,
                              trusted_verifiers=TRUSTED, worker_run_id=w.worker).evidence
    return (adapter or preparer(w)).prepare(manifest=w.manifest, attempt=w.attempt(),
        source=w.snapshots.load(w.snapshot_id), verification=v, now=NOW)


class SnapshotBoundaryTests(TempCase):
    def test_arbitrary_exclusion_cannot_hide_unapproved_file(self):
        w = World(self.tmp); (w.workspace / "outside.txt").write_bytes(b"unapproved")
        with self.assertRaises(ValueError):
            w.snapshots.capture(workspace=str(w.workspace), snapshot_id=w.snapshot_id, campaign_id="g61-static",
                attempt_id=w.attempt_id, worker_run_id=w.worker, captured_at=NOW, exclude_top=(".git", "outside.txt"))
        self.assertFalse(w.snapshots._manifest_path(w.snapshot_id).exists())

    def test_same_id_different_campaign_or_attempt_conflicts_no_overwrite(self):
        w = World(self.tmp); w.capture(); before = w.snapshots.manifest_sha256(w.snapshot_id)
        for change in ({"campaign_id": "other"}, {"attempt_id": "other"}):
            args = dict(workspace=str(w.workspace), snapshot_id=w.snapshot_id, campaign_id="g61-static",
                attempt_id=w.attempt_id, worker_run_id=w.worker, captured_at=NOW); args.update(change)
            self.assertEqual(w.snapshots.capture(**args).status, "CONFLICT")
            self.assertEqual(w.snapshots.manifest_sha256(w.snapshot_id), before)

    def test_load_campaign_attempt_workspace_all_bound(self):
        w = World(self.tmp).ready()
        for args in ({"expected_campaign_id": "other"}, {"expected_attempt_id": "other"},
                     {"expected_workspace_fingerprint": "f" * 64}):
            with self.assertRaises(SnapshotIntegrityError):
                w.snapshots.load(w.snapshot_id, **args)

    def test_incomplete_nested_git_keeps_close_gate_shut(self):
        w = World(self.tmp); (w.workspace / "proof/sub/.git").mkdir(parents=True)
        r = w.capture(); self.assertEqual(r.status, "VERIFIED"); self.assertFalse(r.close_gate_open)
        self.assertFalse(w.capture().close_gate_open)

    def test_crash_before_manifest_never_opens_close_gate_restart_recovers(self):
        w = World(self.tmp)
        with mock.patch.object(w.snapshots, "_put_object", side_effect=RuntimeError("simulated crash")):
            with self.assertRaises(RuntimeError): w.capture()
        self.assertFalse(w.snapshots._manifest_path(w.snapshot_id).exists())
        self.assertEqual(w.capture().status, "VERIFIED")
        shutil.rmtree(w.workspace)
        self.assertEqual(w.snapshots.load(w.snapshot_id).files["src/value.py"].data, b"value = 2\n")

    def test_stale_partial_temp_never_becomes_canonical_object(self):
        w = World(self.tmp); sha = FileEntry(b"value = 2\n").sha256
        p = w.snapshots._object_path(sha); p.parent.mkdir(parents=True)
        stale = p.with_name("." + sha + ".crashed.tmp"); stale.write_bytes(b"partial")
        self.assertEqual(w.capture().status, "VERIFIED")
        self.assertEqual(p.read_bytes(), b"value = 2\n"); self.assertEqual(stale.read_bytes(), b"partial")

    def test_file_swapped_to_symlink_before_open_is_not_read(self):
        w = World(self.tmp); secret = w.tmp / "outside"; secret.write_bytes(b"must never copy")
        real_open = os.open; swapped = []
        def opening(name, flags, *args, **kwargs):
            if name == "value.py" and kwargs.get("dir_fd") is not None and not swapped:
                swapped.append(True); (w.workspace / "src/value.py").unlink()
                os.symlink(secret, w.workspace / "src/value.py")
            return real_open(name, flags, *args, **kwargs)
        with mock.patch("automation.command_bus.symphony_workspace_snapshot.os.open", opening):
            # supports_dir_fd contains the original function, so retain the
            # secure-platform capability while injecting the actual race.
            with mock.patch("os.supports_dir_fd", {opening}):
                with self.assertRaises(SnapshotIntegrityError): w.capture()
        self.assertTrue(swapped); self.assertFalse(w.snapshots._manifest_path(w.snapshot_id).exists())
        self.assertFalse(w.snapshots._object_path(FileEntry(secret.read_bytes()).sha256).exists())

    def test_platform_without_no_follow_fails_closed(self):
        w = World(self.tmp)
        with mock.patch("os.supports_dir_fd", set()):
            with self.assertRaisesRegex(SnapshotIntegrityError, "unsupported"): w.capture()
        self.assertFalse(w.snapshots._manifest_path(w.snapshot_id).exists())

    def test_junction_reparse_attribute_keeps_gate_shut_no_follow(self):
        w = World(self.tmp); real_stat = os.stat
        def info(name, *args, **kwargs):
            value = real_stat(name, *args, **kwargs)
            if name == "src" and kwargs.get("dir_fd") is not None:
                # Windows reparse-point/junction fixture; no Windows link is
                # needed to verify that this branch cannot traverse it.
                class Reparse:
                    st_file_attributes = 1024
                    def __getattr__(self, key): return getattr(value, key)
                return Reparse()
            return value
        with mock.patch("automation.command_bus.symphony_workspace_snapshot.os.stat", info), \
             mock.patch("stat.FILE_ATTRIBUTE_REPARSE_POINT", 1024, create=True):
            r = w.capture()
        self.assertIn("junction:src", r.anomalies); self.assertFalse(r.close_gate_open)
        self.assertNotIn("src/value.py", w.snapshots.load(w.snapshot_id).files)

    def test_concurrent_snapshot_publish_keeps_one_canonical_manifest(self):
        w = World(self.tmp); original = w.snapshots._put_object; barrier = threading.Barrier(2)
        first = threading.local()
        def put(data):
            if not getattr(first, "entered", False):
                first.entered = True; barrier.wait(timeout=5)
            return original(data)
        with mock.patch.object(w.snapshots, "_put_object", put):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: w.capture(), range(2)))
        self.assertEqual(sum(r.status == "VERIFIED" for r in results), 1)
        self.assertEqual(sum(r.status == "CONFLICT" for r in results), 1)
        self.assertTrue(w.snapshots.load(w.snapshot_id).complete)
        self.assertEqual(w.capture().status, "NOOP_DUPLICATE")


class PreparationTests(TempCase):
    def test_complete_verified_result_prepares_deterministically_zero_writes(self):
        w = World(self.tmp).ready(); a = prepare(w); b = prepare(w)
        self.assertEqual(a.status, "PREPARED_OFF"); self.assertEqual(a.plan, b.plan)
        self.assertFalse(a.plan["authorized_to_send"])
        u = a.plan["single_ref_request"]["variables"]["input"]["refUpdates"]
        self.assertEqual(len(u), 1); self.assertFalse(u[0]["force"]); self.assertEqual(u[0]["beforeOid"], w.head)
        self.assertEqual((w.gh.object_posts, w.gh.update_refs_requests, w.gh.ref_mutations), (0, 0, 0))

    def test_off_cannot_execute_even_if_mode_or_static_flag_changed(self):
        w = World(self.tmp).ready(); a = preparer(w); plan = prepare(w, a).plan
        a.mode = "LIVE"; a.static_only = True
        for fn in (a.execute, a.put_candidate, a.compare_and_swap):
            with self.assertRaises(PermissionError): fn(plan)
        with self.assertRaises(PermissionError): preparer(w, mode="LIVE")
        self.assertEqual((w.gh.object_posts, w.gh.update_refs_requests), (0, 0))

    def test_stale_target_missing_or_false_verification_never_prepares(self):
        w = World(self.tmp).ready()
        self.assertEqual(prepare(w, records=[]).status, "HOLD_AUTHORITY")
        w.external["tests"] = "FAIL"; self.assertEqual(prepare(w).status, "HOLD_AUTHORITY")
        w.external["tests"] = "PASS"; w.gh.advance(TARGET, w.gh.tree_files(w.head))
        self.assertEqual(prepare(w).status, "STALE_REPLAN"); self.assertEqual(w.gh.object_posts, 0)

    def test_head_changes_during_preparation_invalidates_plan(self):
        w = World(self.tmp).ready(); a = preparer(w); original = a.target_reader.read; calls = []
        def read():
            calls.append(1)
            if len(calls) == 2: w.gh.advance(TARGET, w.gh.tree_files(w.head))
            return original()
        a.target_reader.read = read
        self.assertEqual(prepare(w, a).status, "STALE_REPLAN"); self.assertEqual(w.gh.update_refs_requests, 0)

    def test_invalidated_task_isolates_prepare(self):
        w = World(self.tmp).ready(); w.gh.issues[w.number]["labels"] = {"totalCount": 1, "nodes": [{"name": "symphony:invalid"}]}
        self.assertEqual(prepare(w).status, "ISOLATE_TASK"); self.assertEqual(w.gh.object_posts, 0)

    def test_default_target_drift_cannot_prepare(self):
        w = World(self.tmp).ready(); w.gh.default_branch = TARGET
        with self.assertRaises(RuntimeError): prepare(w)
        self.assertEqual(w.gh.object_posts, 0)

    def test_corrupt_candidate_object_or_inventory_refuses_before_any_post(self):
        w = World(self.tmp).ready(); c = construct_candidate(parent=w.head, files=w.snapshots.load(w.snapshot_id).files,
                                                            created_at=NOW, adoption_id=make_adoption_id(w.manifest))
        bad = dict(c.objects); oid = next(o for o, (k, _) in bad.items() if k == "blob"); bad[oid] = ("blob", b"forged")
        t = w.wired().transport
        for altered in [replace(c, objects=bad), replace(c, files={"fake": FileEntry(b"fake")})]:
            with self.assertRaises(TransportIntegrityError): t.put_candidate(altered)
        self.assertEqual((w.gh.object_posts, w.gh.update_refs_requests), (0, 0))

    def test_post_success_get_failure_restart_only_reads_then_receipt(self):
        w = World(self.tmp).ready()
        def hook(point):
            if point == "AFTER_REF": w.gh.fail_get = lambda path: True
        first = w.run(hook); self.assertEqual(first.status, "UNKNOWN"); self.assertEqual(w.gh.update_refs_requests, 1)
        w.gh.fail_get = None; shutil.rmtree(w.workspace)
        before = w.gh.object_posts; second = w.run()
        self.assertEqual(second.status, "ADOPTED"); self.assertEqual(w.gh.update_refs_requests, 1)
        self.assertEqual(w.gh.object_posts, before); self.assertEqual(w.run().status, "NOOP_DUPLICATE")

    def test_default_branch_changes_after_fence_zero_ref_calls(self):
        w = World(self.tmp).ready()
        def hook(point):
            if point == "AFTER_REF_INTENT": w.gh.default_branch = TARGET
        self.assertEqual(w.run(hook).status, "UNKNOWN")
        self.assertEqual(w.gh.update_refs_requests, 0)
        self.assertEqual(w.gh.head(TARGET), w.head)

    def test_prepare_isolation_does_not_stop_independent_task(self):
        w = World(self.tmp).ready(); w.extra_records = []
        other = World(w.tmp / "second", task_id="B", gh=w.gh).ready()
        w.external["tests"] = "FAIL"
        self.assertEqual(prepare(w).status, "HOLD_AUTHORITY")
        self.assertEqual(prepare(other).status, "PREPARED_OFF")
        self.assertEqual(w.gh.update_refs_requests, 0)

    def test_false_target_size_metadata_cannot_bypass_inventory_limit(self):
        w = World(self.tmp).ready(); original = w.gh.request
        def request(method, path, body=None):
            status, data = original(method, path, body)
            if "?recursive=1" in path:
                data = copy.deepcopy(data)
                for e in data["tree"]:
                    if e["type"] == "blob": e["size"] = 0
            return status, data
        w.gh.request = request
        with self.assertRaises(TransportIntegrityError): w.target_reader().read()
        self.assertEqual(w.gh.object_posts, 0)


class CIWorld:
    def __init__(self, w):
        self.w = w; self.workflow = b"name: independently pinned verifier\npermissions: {contents: read}\n"
        candidate = prepare(w).plan["candidate_commit"]
        self.contract = CIContract(REPO, 7001, candidate, ".github/workflows/g62-independent.yml",
            hashlib.sha256(self.workflow).hexdigest(), "g62-independent", "ci-runner")
        c = self.contract
        self.run = {"id": c.run_id, "run_attempt": 1, "head_sha": candidate, "path": c.workflow_path,
                    "repository": {"full_name": REPO}, "status": "completed", "conclusion": "success"}
        self.job = {"id": 7101, "head_sha": candidate, "conclusion": "success", "steps": [
            {"name": n, "status": "completed", "conclusion": "success"} for n in c.required_steps]}
        self.attestation = {"protocol": "SYMPHONY_G62_CI_ATTESTATION_V1", "run_id": 7001, "run_attempt": 1,
            "job_id": 7101, "candidate_commit": candidate, "records": w.records(),
            **{k: w.manifest[k] for k in ("result_digest", "source_digest", "scope_digest", "expected_target_head")}}
        self.log = []; self.reseal()

    def reseal(self):
        self.attestation["attestation_digest"] = digest({k: v for k, v in self.attestation.items() if k != "attestation_digest"})
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z: z.writestr("attestation.json", json.dumps(self.attestation))
        self.archive = out.getvalue(); c = self.contract
        self.artifact = {"id": 7201, "name": c.artifact_name, "expired": False,
            "workflow_run": {"id": c.run_id, "head_sha": c.candidate_commit},
            "digest": "sha256:" + hashlib.sha256(self.archive).hexdigest()}

    def request(self, method, path, body=None):
        self.log.append((method, path)); assert method == "GET" and body is None
        if "/contents/" in path: return 200, {"encoding": "base64", "content": base64.b64encode(self.workflow).decode()}
        if "/jobs?" in path: return 200, {"total_count": 1, "jobs": [self.job]}
        if "/artifacts?" in path: return 200, {"total_count": 1, "artifacts": [self.artifact]}
        return 200, self.run

    def reader(self, **changes):
        return CIArtifactVerificationReader(self, replace(self.contract, **changes),
            archive_get=lambda repo, aid: self.archive, trusted_verifiers=TRUSTED, worker_run_id=self.w.worker)


class AttestationTests(TempCase):
    def test_authenticated_pinned_ci_binds_artifact_records_to_exact_candidate(self):
        w = World(self.tmp).ready(); ci = CIWorld(w); b = ci.reader().read(w.manifest)
        self.assertTrue(b.evidence.trustworthy); self.assertTrue(all(b.evidence.checks.values()))
        self.assertTrue(all(method == "GET" for method, _ in ci.log)); self.assertEqual(w.gh.object_posts, 0)

    def test_wrong_run_head_repository_workflow_or_attempt_refused(self):
        for change in ({"head_sha": "f" * 40}, {"repository": {"full_name": "other/repo"}},
                       {"path": ".github/workflows/worker.yml"}, {"conclusion": "failure"}, {"status": "in_progress"},
                       {"id": 7002}, {"run_attempt": None}):
            w = World(self.tmp).ready(); ci = CIWorld(w); ci.run.update(change)
            with self.subTest(change=change), self.assertRaises(AttestationUnavailable): ci.reader().read(w.manifest)

    def test_skipped_failed_or_missing_secret_scan_step_refused(self):
        for status in ["skipped", "failure", None]:
            w = World(self.tmp).ready(); ci = CIWorld(w); ci.job["steps"][-1]["conclusion"] = status
            with self.assertRaises(AttestationUnavailable): ci.reader().read(w.manifest)

    def test_changed_verifier_workflow_pin_refused(self):
        w = World(self.tmp).ready(); ci = CIWorld(w); ci.workflow += b"# changed\n"
        with self.assertRaises(AttestationUnavailable): ci.reader().read(w.manifest)

    def test_artifact_bytes_run_and_head_tamper_refused(self):
        w = World(self.tmp).ready()
        for change in ["bytes", "head", "run", "expired"]:
            ci = CIWorld(w)
            if change == "bytes": ci.archive += b"tampered"
            elif change == "expired": ci.artifact["expired"] = True
            else: ci.artifact["workflow_run"]["head_sha" if change == "head" else "id"] = "wrong"
            with self.subTest(change=change), self.assertRaises(AttestationUnavailable): ci.reader().read(w.manifest)

    def test_stale_rebound_attestation_rejected_even_with_valid_archive_and_seal(self):
        w = World(self.tmp).ready()
        for key in ["candidate_commit", "expected_target_head", "result_digest", "source_digest", "scope_digest", "run_attempt", "job_id"]:
            ci = CIWorld(w); ci.attestation[key] = "wrong"; ci.reseal()
            with self.subTest(key=key), self.assertRaises(AttestationUnavailable): ci.reader().read(w.manifest)

    def test_missing_false_or_worker_self_pass_refused(self):
        w = World(self.tmp).ready()
        for case in ["missing", "false", "worker"]:
            ci = CIWorld(w)
            if case == "missing": ci.attestation["records"] = []
            else:
                r = next(r for r in ci.attestation["records"] if r["check"] == "tests")
                r["status" if case == "false" else "verifier_id"] = "FAIL" if case == "false" else w.worker
                r["record_digest"] = digest({k: v for k, v in r.items() if k != "record_digest"})
            ci.reseal()
            with self.subTest(case=case), self.assertRaises(AttestationUnavailable): ci.reader().read(w.manifest)

    def test_incomplete_paginated_jobs_cannot_claim_pass(self):
        w = World(self.tmp).ready(); ci = CIWorld(w); original = ci.request
        def request(method, path, body=None):
            if "/jobs?" in path: return 200, {"total_count": 101, "jobs": [ci.job] if "page=1" in path else []}
            return original(method, path, body)
        ci.request = request
        with self.assertRaises(AttestationUnavailable): ci.reader().read(w.manifest)


def run_g62_matrix():
    """Machine-readable observations, not predeclared PASS values."""
    from .test_symphony_g61_production_wiring import run_g61_matrix
    import tempfile
    from pathlib import Path
    outcomes = run_g61_matrix()
    with tempfile.TemporaryDirectory() as tmp:
        for case in ("L01", "L02", "L03", "L04", "L05"):
            w = World(Path(tmp) / case).ready(); extra = {}
            if case == "L01":
                first = prepare(w).status; shutil.rmtree(w.workspace); restarted = prepare(w).status
            elif case == "L02":
                w.external["tests"] = "FAIL"; first = prepare(w).status
                other = World(Path(tmp) / (case + "-B"), task_id="B", gh=w.gh).ready()
                restarted = prepare(other).status
            elif case == "L03":
                def hook(point):
                    if point == "AFTER_REF_INTENT": w.gh.default_branch = TARGET
                first = w.run(hook).status; w.gh.default_branch = "main"; restarted = w.run().status
            elif case == "L04":
                def hook(point):
                    if point == "AFTER_REF": w.gh.fail_get = lambda _: True
                first = w.run(hook).status; w.gh.fail_get = None; shutil.rmtree(w.workspace)
                posts = w.gh.object_posts; restarted = w.run().status
                extra = {"restart_extra_object_posts": w.gh.object_posts - posts,
                         "replay": w.run().status, "synthetic_ledger_records": [
                             json.loads(c.text) for p, c in sorted(w.client.files.items()) if p.startswith("symphony_adoptions/")]}
            else:
                ci = CIWorld(w); first = "PASS" if ci.reader().read(w.manifest).evidence.trustworthy else "FAIL"
                ci.attestation["source_digest"] = "f" * 64; ci.reseal()
                try: ci.reader().read(w.manifest); restarted = "UNEXPECTED_ACCEPT"
                except AttestationUnavailable: restarted = "REJECTED"
            outcomes.append({"case": case, "first": first, "after_cleanup_restart": restarted,
                "update_refs_requests": w.gh.update_refs_requests, "our_ref_mutations": w.gh.ref_mutations,
                "object_posts": w.gh.object_posts, "default_branch_unchanged": w.gh.head("main") == w.head,
                "real_github_writes": 0, "model_provider_LIVE": 0, **extra})
        for root, _, files in os.walk(tmp):
            for name in files: os.chmod(os.path.join(root, name), 0o600)
    return outcomes


class MatrixTests(TempCase):
    def test_committed_fault_matrix_matches_observed_restarts(self):
        from pathlib import Path
        expected = json.loads((Path(__file__).parent / "fixtures/symphony_g62/regression-matrix.json").read_text())
        observed = run_g62_matrix()
        actual = {x["case"]: [x["first"], x["after_cleanup_restart"], x["update_refs_requests"], x["our_ref_mutations"]]
                  for x in observed}
        self.assertEqual(actual, expected)
        self.assertTrue(all(x["default_branch_unchanged"] and x["update_refs_requests"] <= 1 for x in observed))
        l04 = next(x for x in observed if x["case"] == "L04")
        self.assertEqual(l04["restart_extra_object_posts"], 0); self.assertEqual(l04["replay"], "NOOP_DUPLICATE")
        self.assertTrue(l04["synthetic_ledger_records"])
