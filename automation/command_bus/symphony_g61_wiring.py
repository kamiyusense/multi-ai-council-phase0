"""G6.1 production-shaped wiring of the G6 adoption bridge (STATIC only).

Composition, no new policy:

    pre-close snapshot (bytes outside workspace)  -> source_reader
    GitHubTargetReader (fresh HEAD + inventory)   -> transport.read_target
    GitHubTaskValidityReader (Issue revision)     -> validity_reader
    assemble_verification (independent checks)    -> verification_reader
    GitHubGitTransport (Git DB + updateRefs CAS)  -> StaticAdoptionBridge

The bridge, inspector, records, recovery and campaign seams are the G6 ones,
unchanged. ``GitHubGitTransport`` rejects non-static HTTP, so this wiring is
executable only against a simulated GitHub in this batch; the LIVE flip is a
separate, reviewed, explicitly approved step. Nothing here touches Official
Symphony polling/scheduling/retry/cleanup or worker turns.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from .symphony_attempt_store import AttemptSnapshot
from .symphony_git_adoption import AppendOnlyAdoptionStore, StaticAdoptionBridge
from .symphony_github_git_transport import GitHubGitTransport, GitHubHttp
from .symphony_github_readers import GitHubTargetReader, GitHubTaskValidityReader, bind_validity_reader
from .symphony_result_manifest import (CanonicalTarget, ProofMutationPolicy, SourceResult, classify_mutation,
                                       digest, inventory_digest, seal_manifest)
from .symphony_result_verification import DEFAULT_REQUIRED, assemble_verification, manifest_check_refs
from .symphony_workspace_snapshot import WorkspaceSnapshotStore


def generate_result_manifest(*, attempt: AttemptSnapshot, repository: str, target_branch: str,
                             base: CanonicalTarget, source: SourceResult,
                             required_checks: Iterable[str] = DEFAULT_REQUIRED) -> dict:
    """Actual RESULT manifest from trusted snapshot bytes and the base tree.

    ``base`` is the inventory at the attempt's expected HEAD
    (``GitHubTargetReader.read_at``), so a target that has since advanced
    still yields a manifest and the bridge records a durable STALE_REPLAN.

    Mutations are derived by comparing bytes; renames are not guessed and so
    appear as DELETE + ADD (held by the conservative profile). Identity comes
    from the durable attempt records, never from worker self-report.
    """
    if type(attempt) is not AttemptSnapshot or attempt.started is None or attempt.terminal is None:
        raise ValueError("durable STARTED/TERMINAL attempt required")
    if source.trustworthy is not True or source.complete is not True:
        raise ValueError("complete trusted source snapshot required")
    if base.trustworthy is not True or base.complete is not True or base.head != attempt.identity.expected_target_head:
        raise ValueError("complete base inventory at the attempt's expected HEAD required")
    identity, scope = attempt.identity, attempt.intent["scope"]
    mutations = []
    for path in sorted(p for p in set(base.files) | set(source.files) if base.files.get(p) != source.files.get(p)):
        old, new = base.files.get(path), source.files.get(path); entry = new or old
        mutations.append({"path": path, "source_path": None, "operation": classify_mutation(old, new).value,
                          "content_sha256": new.sha256 if new else None, "before_sha256": old.sha256 if old else None,
                          "mode": entry.mode, "type": entry.kind})
    return seal_manifest({"protocol": "SYMPHONY_G6_RESULT_V1", "schema_version": 1, "repository": repository,
        "target_branch": target_branch, "campaign_id": identity.campaign_id, "attempt_id": identity.attempt_id,
        "generation": identity.generation, "attempt_number": identity.attempt_number,
        "runner_generation": identity.runner_generation, "task_id": identity.task_id, "issue_id": scope["issue"],
        "worker_run_id": attempt.started["provider_attempt_ref"], "expected_target_head": identity.expected_target_head,
        "workspace_fingerprint": source.workspace_fingerprint, "scope_digest": digest(scope),
        "request_digest": scope.get("request_digest"), "source_digest": inventory_digest(source.files),
        "mutations": mutations, "evidence_refs": manifest_check_refs(required_checks)})


@dataclass
class WiredAdoption:
    bridge: StaticAdoptionBridge
    transport: GitHubGitTransport
    attempt_reader: Callable[[], AttemptSnapshot | None]
    source_reader: Callable[[], SourceResult]
    validity_reader: Callable[[CanonicalTarget], object]
    verification_reader: Callable[[], object]

    def process(self, manifest: dict, *, now: str, crash_hook=lambda point: None):
        return self.bridge.process(manifest=manifest, attempt_reader=self.attempt_reader,
            source_reader=self.source_reader, validity_reader=self.validity_reader,
            verification_reader=self.verification_reader, now=now, crash_hook=crash_hook)


def wire_adoption(*, http: GitHubHttp, repository: str, repository_id: str, target_branch: str,
                  default_branch: str, ledger: AppendOnlyAdoptionStore, attempt_reader,
                  snapshots: WorkspaceSnapshotStore, snapshot_id: str, worker_run_id: str,
                  issue_id: str, task_id: str, trusted_issue_logins: Iterable[str],
                  verification_records: Callable[[], Iterable[dict]], trusted_verifiers: Mapping[str, str],
                  manifest_ref: Callable[[], dict], required_checks: Iterable[str] = DEFAULT_REQUIRED,
                  policy: ProofMutationPolicy | None = None, target_limits: Mapping | None = None) -> WiredAdoption:
    """Compose readers and transport. ``manifest_ref`` returns the sealed
    manifest the verification records must bind to."""
    required = tuple(required_checks)
    target_reader = GitHubTargetReader(http, repository=repository, branch=target_branch,
                                       default_branch=default_branch, **dict(target_limits or {}))
    transport = GitHubGitTransport(http, repository=repository, repository_id=repository_id,
        target_branch=target_branch, default_branch=default_branch, target_reader=target_reader)
    policy = policy or ProofMutationPolicy()
    bridge = StaticAdoptionBridge(store=ledger, transport=transport, repository=repository,
                                  target_branch=target_branch, default_branch=default_branch, policy=policy)
    validity = bind_validity_reader(GitHubTaskValidityReader(http, repository=repository,
        trusted_logins=trusted_issue_logins), issue_id=issue_id, task_id=task_id)
    def verification_reader():
        return assemble_verification(manifest_ref(), verification_records(), trusted_verifiers=trusted_verifiers,
                                     worker_run_id=worker_run_id, required=required).evidence
    def source_reader():
        attempt = attempt_reader()
        if attempt is None or attempt.started is None:
            raise ValueError("durable source identity unavailable")
        return snapshots.load(snapshot_id, expected_worker_run_id=worker_run_id,
            expected_campaign_id=attempt.identity.campaign_id, expected_attempt_id=attempt.identity.attempt_id,
            expected_workspace_fingerprint=attempt.started["workspace_fingerprint"])
    return WiredAdoption(bridge, transport, attempt_reader,
                         source_reader,
                         validity, verification_reader)
