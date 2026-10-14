"""Operator-owned OFF preparation joining existing storage and observation seams.

Only the explicitly STATIC host can attach. No launcher, worker reservation,
thread/turn, scheduler, GitHub sender or production installation is supplied.
Review comes from the operator, never from signed worker output. INTENT and
OUTCOME are separate create-only records; uncertain/unfinished intent is GET-only.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import re

from .scripts.symphony_worker_first_preflight import (
    COMMIT, PROOF_BRANCH, _safe_dir, _git, _native_linux_state, _separate,
)
from .symphony_codex_app_server import JsonlCodexAppServer
from .symphony_g73_host import OperatorStaticHost, _read_regular, _root
from .symphony_production_observer import SymphonyProductionObserver
from .symphony_sqlite_storage import ReviewedSQLiteStorage
from .symphony_subscription_boundary import metered_worker_environment_present
from .symphony_result_manifest import digest
from .symphony_native_binary_preparation import directory_chain, _regular_read


@dataclass(frozen=True)
class WorkerPreparationReview:
    preparation_id: str
    repository: str
    issue_id: str
    task_id: str
    campaign_id: str
    generation: int
    runner_generation: int
    scope_digest: str
    workspace: str
    workspace_branch: str
    source_head: str
    target_branch: str
    target_head: str
    executable: str
    executable_sha256: str
    auth_home: str
    expires_at: str


def _clock(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise PermissionError('timezone required')
    return parsed.astimezone(timezone.utc)


def _binding(review, storage, host):
    """Fresh observations only. No account contents or MAC key leave this seam."""
    if (type(review) is not WorkerPreparationReview
            or type(storage) is not ReviewedSQLiteStorage
            or type(host) is not OperatorStaticHost
            or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', review.repository)
            or not re.fullmatch(r'[a-z0-9][a-z0-9-]{7,63}', review.preparation_id)
            or not COMMIT.fullmatch(review.source_head)
            or not COMMIT.fullmatch(review.target_head)
            or not re.fullmatch(r'[0-9a-f]{64}', review.scope_digest)
            or not PROOF_BRANCH.fullmatch(review.workspace_branch)
            or not re.fullmatch(r'codex/[a-z0-9][a-z0-9/-]{5,100}', review.target_branch)
            or '..' in review.target_branch
            or any(type(n) is not int or n < 1 for n in
                   (review.generation, review.runner_generation))):
        raise PermissionError('exact independent preparation review required')
    workspace = _safe_dir(review.workspace)
    auth = _safe_dir(review.auth_home)
    root = _safe_dir(storage.review.root, private=True)
    binary = Path(review.executable)
    if (not _native_linux_state(root) or not _native_linux_state(binary.parent)
            or not all(_separate(a, b) for a, b in
                       ((workspace, root), (workspace, auth), (root, auth)))
            or binary.name != 'codex' or not binary.is_absolute()
            or binary.resolve() != binary or binary.is_symlink()
            or any(p.is_symlink() for p in binary.parents)
            or not os.access(binary, os.X_OK)
            or storage.review.executable != binary
            or storage.review.auth_home != auth
            or workspace not in storage.review.workspace_roots
            or review.executable_sha256 != storage.review.executable_sha256
            or (os.environ.get('CODEX_HOME') or str(Path.home()/'.codex')) != str(auth)
            or metered_worker_environment_present(tuple(os.environ))
            or _git(workspace, 'symbolic-ref', '--quiet', '--short', 'HEAD') != review.workspace_branch
            or _git(workspace, 'rev-parse', '--verify', 'HEAD') != review.source_head
            or _git(workspace, 'status', '--porcelain=v1', '--untracked-files=all')):
        raise PermissionError('local preparation identity changed or unverified')
    with directory_chain(binary.parent) as (fd, parents):
        binary_readback, _ = _regular_read(fd, binary.name, expected_sha256=review.executable_sha256)
        binary_readback['parent_identities'] = parents
    binary_info = binary.stat()
    if (binary_info.st_uid != os.getuid() or binary_info.st_nlink != 1
            or binary_info.st_mode & 0o022):
        raise PermissionError('binary ownership/permissions/links unverified')
    if (type(host.adapter.observer) is not SymphonyProductionObserver
            or type(host.adapter.observer.key) is not bytes or len(host.adapter.observer.key) < 32):
        raise PermissionError('authenticated observer binding unavailable')
    target = host.adapter.target_reader.read()
    bound = host.adapter.observer.issues.get(review.issue_id)
    if (host.workspace != workspace or host.adapter.campaign_id != review.campaign_id
            or host.adapter.generation != review.generation
            or host.adapter.target_reader.repository != review.repository
            or host.adapter.target_reader.branch != review.target_branch
            or review.target_branch == target.default_branch
            or not target.trustworthy or not target.complete or target.head != review.target_head
            or bound is None or bound.task_id != review.task_id
            or bound.generation != review.generation
            or bound.runner_generation != review.runner_generation
            or bound.expected_target_head != review.target_head
            or bound.scope.get('issue') != review.issue_id
            or digest(bound.scope) != review.scope_digest):
        raise PermissionError('observer/task/canonical target binding changed')
    # The operator's event input and all persistence roots stay outside workspace
    # AND auth/storage. This host has no remote client or worker credentials.
    for outside in (host.events, host.adapter.store.client.root, host.adapter.snapshots.root):
        outside = _root(outside)
        if any(not _separate(outside, p) for p in (workspace, root, auth)):
            raise PermissionError('operator root overlaps protected storage')
    operator_directories = []
    for directory in (host.events.parent, host.adapter.store.client.root, host.adapter.snapshots.root):
        _safe_dir(directory, private=True)
        if not _native_linux_state(Path(directory)):
            raise PermissionError('operator storage is not native Linux')
        info = Path(directory).stat()
        operator_directories.append([info.st_dev, info.st_ino])
    _, event_info = _read_regular(_root(host.events), 16*1024*1024)
    if event_info.st_uid != os.getuid() or event_info.st_nlink != 1 or event_info.st_mode & 0o077:
        raise PermissionError('event input ownership/permissions/links unverified')
    view = host.restore()
    if (view['next_action']['kind'].value != 'DISPATCH_TASK'
            or view['next_action']['task_id'] != review.task_id):
        raise PermissionError('operator task is not eligible for preparation')
    return {'review': asdict(review), 'storage': storage.inspect(),
            'storage_readiness': storage.readiness(), 'host': view,
            'operator_directory_identities': operator_directories,
            'observer_key_sha256': hashlib.sha256(host.adapter.observer.key).hexdigest(),
            'binary_readback': binary_readback,
            'events_identity': [event_info.st_dev, event_info.st_ino,
                                event_info.st_size, event_info.st_mtime_ns, event_info.st_ctime_ns]}


def prepare_worker(*, review, storage, host, now):
    """Finite OFF operator call, not launch authority or production readiness.

    A caller cannot use live flags/diagnostic success to grant an installation.
    The existing independently sealed storage must already qualify. No seal is
    created here. Replayed INTENT never launches even a second read-only probe.
    """
    def result(status):
        return {'status': status, 'mode': 'PREPARE_ONLY_OFF',
                'worker_dispatch_authorized': False, 'production_installed': False,
                'model_dispatch': 0, 'thread_starts': 0, 'github_writes': 0}
    try:
        if not callable(now):
            raise PermissionError('operator clock required')
        started = _clock(now())
        remaining = (_clock(review.expires_at)-started).total_seconds()
        if not 0 < remaining <= 600:
            raise PermissionError('preparation expired or unbounded')
        before = _binding(review, storage, host)
        ledger = host.adapter.ledger
        path = 'symphony_worker_preparation/' + review.preparation_id + '/'
        intent = {'protocol': 'SYMPHONY_WORKER_PREPARATION_OFF_V1', 'binding': before}
        old = ledger._get(path+'intent.json')
        if old is not None:
            if old != intent:
                return result('CONFLICT')
            outcome = ledger._get(path+'outcome.json')
            return result('NOOP_DUPLICATE' if outcome == {'binding_digest': digest(before),
                'status': 'PREPARED_STATIC_ONLY_NOT_LAUNCH'} else 'HOLD_INTENT_GET_ONLY')
        if ledger._put(path+'intent.json', intent) != 'ACCEPTED':
            return result('HOLD_INTENT_GET_ONLY')
        # This exact transport can send only initialize/account/config in readonly
        # mode, with isolated reviewed SQLite and filtered authority selectors.
        probe = JsonlCodexAppServer(executable=review.executable,
            production_storage=storage).probe_read_only(cwd=review.workspace)
        route = probe.get('route')
        if (probe.get('status') != 'DONE' or probe.get('model_dispatch') != 0
                or probe.get('thread_starts') != 0 or type(route) is not dict
                or route.get('subscription_route_compatible') is not True
                or route.get('provenance') != 'SAME_PROCESS_FRESH_READ_ONLY_NOT_ADMISSION'
                or _clock(now()) < started or _clock(now()) >= _clock(review.expires_at)
                or _binding(review, storage, host) != before):
            return result('HOLD_CHANGED_OR_UNVERIFIED')
        outcome = {'binding_digest': digest(before), 'status': 'PREPARED_STATIC_ONLY_NOT_LAUNCH'}
        status = ledger._put(path+'outcome.json', outcome)
        return result('PREPARED_STATIC_ONLY_NOT_LAUNCH' if status == 'ACCEPTED'
                      and ledger._get(path+'outcome.json') == outcome else 'HOLD_OUTCOME_GET_ONLY')
    except Exception:
        # Do not emit paths, account data, signing keys or provider exceptions.
        return result('BLOCKED_UNVERIFIED')
