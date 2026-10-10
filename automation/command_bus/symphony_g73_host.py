"""Callable OFF operator host. Record orchestration only, no scheduler or sender.

A local create-only Contents implementation exercises the unchanged G5/G6/G7
stores across real process death. Its records are explicitly STATIC, never the
real GitHub ledger. The future host attachment is configured by the operator,
not by worker output; no import/factory/command is accepted from an event.
"""
import hashlib
import hmac
import os
import stat
import uuid
from pathlib import Path
from dataclasses import asdict
from .executor_backend import ExecutorContent
from .symphony_workspace_snapshot import WorkspaceSnapshotStore, _sync_directory
from .symphony_result_manifest import safe_path
from .symphony_g63_snapshot import StrictWorkspaceSnapshotStore
from .symphony_g72_runtime import StaticObservationReceiptAdapter
from .symphony_autonomous_runtime import AutonomousCampaignKernel
from .symphony_autonomous_policy import QuotaState
from .symphony_g63_archive import strict_json


def _read_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('operator input is not a bounded regular file')
        data = source.read(limit + 1)
        if len(data) > limit:
            raise ValueError('operator input exceeded bound')
        return data, info


def _root(path):
    p = Path(path).absolute()
    if any(x.is_symlink() for x in (p, *p.parents)):
        raise ValueError('operator attachment symlink')
    return p


class LocalStaticContents:
    """Same create/get/list protocol, disk only; no update or remote capability.

    Snapshot object publication already uses fsync + atomic create-only links.
    Each branch/path pointer is likewise published only after its object exists.
    """
    def __init__(self, root):
        self.root = _root(root)
        self.objects = WorkspaceSnapshotStore(str(self.root / 'payloads'))
        self.root.chmod(0o700)

    def _path(self, path, ref):
        if not safe_path(path) or not ref or type(ref) is not str:
            raise ValueError('invalid static record identity')
        return self.root / 'records' / hashlib.sha256(ref.encode()).hexdigest() / path

    def get(self, path, ref):
        pointer = self._path(path, ref)
        if not pointer.exists():
            return None
        _root(pointer)
        raw, _ = _read_regular(pointer, 64)
        sha = raw.decode('ascii')
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('corrupt local record pointer')
        data, _ = _read_regular(self.objects._object_path(sha), 16 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != sha:
            raise ValueError('corrupt local record payload')
        return ExecutorContent(path, data.decode('utf-8'), sha)

    def list(self, prefix, ref):
        path = self._path(prefix.rstrip('/'), ref)
        if not path.exists():
            return []
        _root(path)
        files = []
        for directory, dirs, names in os.walk(path, followlinks=False):
            for name in dirs + names:
                if (Path(directory) / name).is_symlink():
                    raise ValueError('linked static record')
            for name in sorted(names):
                if name.startswith('.'):  # interrupted atomic publications are not records
                    continue
                full = Path(directory) / name
                rel = full.relative_to(self.root / 'records' / hashlib.sha256(ref.encode()).hexdigest())
                files.append(self.get(rel.as_posix(), ref))
        return sorted(files, key=lambda x: x.path)

    def create(self, path, text, message, branch):
        target = self._path(path, branch)
        _root(target)
        sha = self.objects._put_object(text.encode('utf-8'))
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        temp = target.with_name('.' + uuid.uuid4().hex + '.tmp')
        with open(temp, 'xb') as f:
            os.chmod(temp, 0o600)
            f.write(sha.encode()); f.flush(); os.fsync(f.fileno())
        try:
            os.link(temp, target)  # collision is never overwritten
            for directory in (target.parent, *target.parent.parents):
                _sync_directory(directory)
                if directory == self.root:
                    break
        finally:
            temp.unlink(missing_ok=True)
        return self.get(path, branch)

    def update(self, *args, **kwargs):
        raise PermissionError('STATIC local records are create-only')


class OperatorStaticHost:
    """Directly callable library entry point with externally driven finite calls.

    Actual CLI fixture runner is separately named and can only compose fake IO.
    Host roots and observer key never appear in its return values. No worker
    launch, Issue close, production adoption, network writes or LIVE toggle.
    """
    def __init__(self, adapter, *, events, workspace):
        if (type(adapter) is not StaticObservationReceiptAdapter
                or type(adapter.store.client) is not LocalStaticContents
                or type(adapter.snapshots) is not StrictWorkspaceSnapshotStore):
            raise ValueError('local STATIC stores and exact reviewed adapter required')
        self.adapter = adapter
        self.events = _root(events)
        workspace = _root(workspace)
        for outside in (self.events, adapter.store.client.root, _root(adapter.snapshots.root)):
            if outside == workspace or workspace in outside.parents:
                raise ValueError('operator inputs must stay outside model workspace')
        self.workspace = workspace

    def restore(self):
        cp = self.adapter._cp()
        target = self.adapter.target_reader.read()
        if not target.trustworthy or not target.complete:
            raise ValueError('fresh canonical target unavailable')
        advice = AutonomousCampaignKernel(cp.state, policy=self.adapter.policy).next_action(
            canonical_head=target.head, quota_state=QuotaState.UNKNOWN)
        return {'protocol': 'SYMPHONY_G73_HOST_VIEW_V1', 'mode': 'OFF',
                'revision': cp.revision, 'checkpoint_digest': cp.state_digest,
                'next_action': asdict(advice), 'advice_only': True,
                'model_dispatch': 0, 'real_publication': 0}

    def replay(self):
        """One bounded complete-line read. Restart replays; durable stores dedupe.

        A partial final append is left pending. No tail loop, timer or gate on
        upstream continuation. No raw signed payload or key is returned/logged.
        """
        _root(self.events)
        raw, info = _read_regular(self.events, 16 * 1024 * 1024)
        if info.st_mode & 0o077:
            raise ValueError('event file must have restrictive permissions')
        lines = raw.splitlines(keepends=True)
        results = []
        for line in lines:
            if not line.endswith(b'\n'):
                break
            # Verify MAC before interpreting any worker-controlled contents.
            try:
                text = line.decode('utf-8')
                envelope = strict_json(line)
                if type(envelope) is not dict or set(envelope) != {'payload_json', 'mac'}:
                    raise ValueError('invalid signed envelope')
                payload = envelope['payload_json']
                if type(payload) is not str or type(envelope['mac']) is not str:
                    raise ValueError('invalid signed envelope types')
                mac = hmac.new(self.adapter.observer.key, payload.encode('utf-8'), hashlib.sha256).hexdigest()
                if (not hmac.compare_digest(mac, envelope['mac'])
                        or strict_json(payload.encode())['workspace'] != str(self.workspace)):
                    raise ValueError('event not bound to this host workspace')
            except (ValueError, TypeError, KeyError):
                results.append({'status': 'CONFLICT', 'attempt_id': None})
                continue
            result = self.adapter.capture(text)
            results.append(asdict(result))
        return {'results': results, 'partial_tail': bool(lines and not lines[-1].endswith(b'\n')),
                'model_dispatch': 0, 'real_publication': 0}

    def handle(self, operation, **inputs):
        """Explicit operator call; no command/function names supplied by worker."""
        self.restore()  # every call starts with durable authority + canonical read
        if operation == 'replay':
            if inputs:
                raise ValueError('replay accepts no worker-selected configuration')
            return self.replay()
        methods = {'admission': self.adapter.admission, 'snapshot': self.adapter.snapshot,
                   'settle': self.adapter.settle, 'recover': self.adapter.settle,
                   'corrective': self.adapter.corrective}
        if operation not in methods:
            raise PermissionError('host OFF: no worker/sender capability')
        if operation == 'recover':
            inputs['recover_only'] = True
        result = methods[operation](**inputs)
        return {'result': asdict(result), 'view': self.restore()}

    def execute(self, *args, **kwargs):
        raise PermissionError('operator host OFF; publication capability NOT_WIRED')
