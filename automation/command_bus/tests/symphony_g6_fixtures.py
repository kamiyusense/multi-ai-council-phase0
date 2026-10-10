"""Credential-free, persist-across-controller-restart G6 fixture transports."""
from __future__ import annotations

from dataclasses import replace
from .test_symphony_campaign_store import FakeCampaignContents
from ..symphony_attempt_store import GitHubAutonomousAttemptStore
from ..symphony_git_adoption import AppendOnlyAdoptionStore, StaticAdoptionBridge
from ..symphony_result_manifest import (CanonicalTarget, FileEntry, SourceResult, TaskValidity,
    VerificationEvidence, inventory_digest, seal_manifest, classify_mutation, digest)

HEAD = "a" * 40
NEXT = "b" * 40
REPOSITORY = "fixture/council"
TARGET = "proof/g6-static"
NOW = "2026-10-10T00:00:00Z"


class SimulatedCrash(BaseException):
    """A real controller death escapes normal Exception/read failure handling."""


def crash_at(point):
    def hook(actual):
        if actual == point:
            raise SimulatedCrash(point)
    return hook


class MemoryGit:
    static_only = True
    atomic_expected_head = True

    def __init__(self, files):
        self.head = HEAD
        self.base_files = dict(files)
        self.candidates = {}; self.objects = {}
        self.ref_calls = self.ref_mutations = self.object_calls = self.object_creates = 0
        self.target_reads = 0
        self.advance_on_read = None
        self.move_during_cas = False
        self.lose_ref_response = False
        self.fail_reads_after_ref = False
        self.fail_reads = False
        self.before_object_put = None

    def read_target(self):
        self.target_reads += 1
        if self.fail_reads or (self.fail_reads_after_ref and self.ref_calls):
            raise RuntimeError("fixture GET unavailable")
        if self.advance_on_read == self.target_reads:
            self.head = NEXT
        files = self.candidates[self.head].files if self.head in self.candidates else self.base_files
        return CanonicalTarget(REPOSITORY, TARGET, "main", self.head, dict(files), True, True)

    def put_candidate(self, candidate):
        self.object_calls += 1
        if self.before_object_put:
            self.before_object_put()
        for oid, obj in candidate.objects.items():
            if oid in self.objects and self.objects[oid] != obj:
                raise AssertionError("content addressed object overwritten")
            if oid not in self.objects:
                self.object_creates += 1; self.objects[oid] = obj
        self.candidates.setdefault(candidate.commit, candidate)

    def read_candidate(self, commit):
        candidate = self.candidates.get(commit)
        if candidate is None:
            return None
        return replace(candidate, objects={oid: self.objects.get(oid) for oid in candidate.objects})

    def compare_and_swap(self, *, branch, expected_head, candidate_head):
        self.ref_calls += 1
        if self.move_during_cas:
            self.head = NEXT
        if branch != TARGET or self.head != expected_head or self.candidates[candidate_head].parent != expected_head:
            raise RuntimeError("atomic expected HEAD mismatch; no branch mutation")
        self.head = candidate_head; self.ref_mutations += 1
        if self.lose_ref_response:
            raise RuntimeError("successful CAS response lost")


class Fixture:
    def __init__(self, *, task_id="A", campaign="g6-static", client=None, git=None):
        self.client = client or FakeCampaignContents()
        self.scope = {"issue": "STATIC-" + task_id, "allowed_paths": ["src/value.py"],
                      "allowed_prefixes": ["proof"], "required_checks": ["syntax", "tests"],
                      "request_digest": digest({"request": task_id})}
        self.base = {"README.md": FileEntry(b"unchanged\n"), "src/value.py": FileEntry(b"value = 1\n")}
        self.source_files = {**self.base, "src/value.py": FileEntry(b"value = 2\n"), "proof/answer.md": FileEntry(b"G6 synthetic result\n")}
        self.git = git or MemoryGit(self.base)
        self.attempts = GitHubAutonomousAttemptStore(self.client, write_branch="fixture/attempt-ledger")
        intent = self.attempts.append_intent(campaign_id=campaign, task_id=task_id, generation=1,
            attempt_number=1, expected_target_head=HEAD, runner_generation=1, scope=self.scope)
        assert intent.status == "ACCEPTED"
        self.attempt_id = intent.attempt_id; self.campaign = campaign
        self.worker_id = "1" * 32; self.workspace = "2" * 64
        assert self.attempts.append_started(campaign_id=campaign, attempt_id=self.attempt_id,
            provider_kind="OFFICIAL_SYMPHONY_CODEX", provider_attempt_ref=self.worker_id,
            observation_source="STATIC_SIMULATION", workspace_fingerprint=self.workspace).status == "ACCEPTED"
        assert self.attempts.append_terminal(campaign_id=campaign, attempt_id=self.attempt_id,
            result_id="sym-g5-worker:" + self.worker_id, outcome="UNKNOWN", unknown_class="RECOVERABLE_UNKNOWN",
            model_started=None, evidence_refs=["sym-g5:sha256:" + "3" * 64, "sym-g5-status:WORKER_STOPPED"]).status == "ACCEPTED"
        self.manifest = {"protocol": "SYMPHONY_G6_RESULT_V1", "schema_version": 1,
            "repository": REPOSITORY, "target_branch": TARGET, "campaign_id": campaign, "attempt_id": self.attempt_id,
            "generation": 1, "attempt_number": 1, "runner_generation": 1, "task_id": task_id, "issue_id": self.scope["issue"], "worker_run_id": self.worker_id,
            "expected_target_head": HEAD, "workspace_fingerprint": self.workspace, "scope_digest": digest(self.scope),
            "request_digest": self.scope["request_digest"], "source_digest": "", "mutations": [],
            "evidence_refs": ["sha256:" + "4" * 64]}
        self.reseal()
        self.valid = True; self.request_digest = self.scope["request_digest"]
        self.checks = {"syntax": True, "tests": True, "secret_scan": True}
        self.source_available = self.verification_available = self.validity_available = True
        self.store = AppendOnlyAdoptionStore(self.client, write_branch="fixture/g6-ledger")

    def reseal(self):
        changed = sorted(p for p in set(self.base) | set(self.source_files) if self.base.get(p) != self.source_files.get(p))
        entries = []
        for p in changed:
            old, new = self.base.get(p), self.source_files.get(p); entry = new or old
            entries.append({"path": p, "source_path": None, "operation": classify_mutation(old, new).value,
                           "content_sha256": new.sha256 if new else None, "before_sha256": old.sha256 if old else None,
                           "mode": entry.mode, "type": entry.kind})
        self.manifest.update(mutations=entries, source_digest=inventory_digest(self.source_files))
        self.manifest = seal_manifest(self.manifest)

    def attempt_reader(self):
        return self.attempts.restore(self.campaign, self.attempt_id)

    def source_reader(self):
        if not self.source_available:
            raise RuntimeError("fixture source unavailable")
        return SourceResult(self.workspace, dict(self.source_files), True, True)

    def validity_reader(self, target):
        if not self.validity_available:
            raise RuntimeError("fixture task validity unavailable")
        return TaskValidity(self.manifest["task_id"], self.scope["issue"], target.head,
                            digest(self.scope), self.request_digest, self.valid, True)

    def verification_reader(self):
        if not self.verification_available:
            raise RuntimeError("fixture verification unavailable")
        return VerificationEvidence(self.manifest["result_digest"], self.manifest["source_digest"], HEAD,
                                    digest(self.scope), dict(self.checks), tuple(self.manifest["evidence_refs"]), True)

    def bridge(self, **changes):
        inputs = dict(store=self.store, transport=self.git, repository=REPOSITORY, target_branch=TARGET, default_branch="main")
        inputs.update(changes)
        return StaticAdoptionBridge(**inputs)

    def run(self, *, hook=lambda point: None, **changes):
        inputs = dict(manifest=self.manifest, attempt_reader=self.attempt_reader, source_reader=self.source_reader,
                      validity_reader=self.validity_reader, verification_reader=self.verification_reader,
                      now=NOW, crash_hook=hook)
        inputs.update(changes)
        return self.bridge().process(**inputs)


def run_crash_matrix():
    """A-J observed counters from the real STATIC bridge, never a GitHub write."""
    outcomes=[]
    for case in 'ABCDEFGHIJ':
        f=Fixture();before=None;other=None
        if case in 'ABC':
            point={'A':'AFTER_INTENT','B':'AFTER_OBJECTS','C':'AFTER_REF'}[case]
            if case=='C':f.git.lose_ref_response=True
            try:f.run(hook=crash_at(point))
            except SimulatedCrash:before='SIMULATED_CRASH_'+point
            else:raise AssertionError('crash not injected')
        elif case=='D':before=f.run().status
        elif case=='E':f.git.head=NEXT
        elif case=='F':f.valid=False
        elif case=='G':del f.source_files['src/value.py'];f.reseal()
        elif case=='H':f.source_files['outside']=FileEntry(b'scope violation\n');f.reseal()
        elif case=='I':f.manifest['result_digest']='0'*64
        elif case=='J':f.manifest['worker_run_id']='f'*32;f.manifest=seal_manifest(f.manifest)
        refs_before=f.git.ref_calls;objects_before=f.git.object_creates;records_before=f.client.create_calls
        result=f.run()
        if case=='H':
            other=Fixture(task_id='B',client=f.client,git=f.git).run().status
        outcomes.append({'case':case,'before_restart':before,'result':result.status,
            'ref_calls_before_resume':refs_before,'ref_calls_after_resume':f.git.ref_calls,
            'new_ref_calls_during_resume':f.git.ref_calls-refs_before,
            'ref_mutations':f.git.ref_mutations,'unique_object_creates_before_resume':objects_before,
            'unique_object_creates_after_resume':f.git.object_creates,
            'ledger_creates_before_resume':records_before,'ledger_creates_after_resume':f.client.create_calls,
            'independent_task_result':other,'receipt_verified':result.receipt is not None,
            'real_git_adoption_count':0,'model_provider_LIVE_count':0})
    return outcomes
