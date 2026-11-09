"""Operator-injected Official Symphony callbacks, uninstalled by default.

No launcher/scheduler, credential lookup, env/CLI activation, model admission,
observer or cleanup implementation. The installer must independently review
command/storage/OS authority. Same-process account/config remain in the existing
Elixir startup patch. Tests feed the actual pinned AppServer a Python fake only.
"""
from dataclasses import dataclass
import re
import hashlib
import shlex

from .scripts.symphony_worker_first_preflight import _safe_dir, _git
from .symphony_native_binary_preparation import qualify_native_binary, identity
from .symphony_sqlite_preparation import prepare_sqlite_review
from .symphony_sqlite_storage import ReviewedSQLiteStorage
from .symphony_result_manifest import digest, SourceResult
from .symphony_g72_runtime import BoundaryResult


@dataclass(frozen=True)
class OfficialRuntimeReview:
    workspace: str
    branch: str
    source_head: str
    upstream_commit: str
    expires_at: int
    isolation_receipt_sha256: str


class ReviewedOfficialRuntimeCallbacks:
    """Finite Config.codex.command / pre-cleanup call sites, not launch authority.

    The explicit callbacks are trusted operator injection, never packet flags.
    No installed factory is supplied. Default/missing authority always refuses.
    Snapshot callback and full-byte reader must bind the exact signed lifetime;
    late TERMINAL remains UNKNOWN in the existing G5/G7 components.
    """
    def __init__(self, *, review, storage, expected_schema, clock,
                 command_approval=None, isolation_check=None,
                 snapshot_callback=None, snapshot_readback=None):
        if (type(review) is not OfficialRuntimeReview
                or type(storage) is not ReviewedSQLiteStorage
                or not callable(clock)):
            raise PermissionError("independent runtime/storage review required")
        self.review, self.storage = review, storage
        self.expected_schema, self.clock = expected_schema, clock
        self.command_approval, self.isolation_check = command_approval, isolation_check
        self.snapshot_callback, self.snapshot_readback = snapshot_callback, snapshot_readback

    def _binding(self, workspace):
        r = self.review
        now = self.clock()
        if (type(now) is not int or type(r.expires_at) is not int
                or not 0 < r.expires_at-now <= 600
                or r.upstream_commit != "be10a1b79df723d6d7612b5651c8522704dafb2e"
                or not re.fullmatch(r"[0-9a-f]{40}", r.source_head or "")
                or not re.fullmatch(r"[0-9a-f]{64}", r.isolation_receipt_sha256 or "")
                or not r.branch.startswith("codex/symphony-worker-proof-")
                or str(_safe_dir(workspace)) != r.workspace):
            raise PermissionError("runtime review stale or scope differs")
        work = _safe_dir(r.workspace)
        if (work not in self.storage.review.workspace_roots
                or _git(work, "branch", "--show-current") != r.branch
                or _git(work, "rev-parse", "HEAD") != r.source_head
                or _git(work, "status", "--porcelain=v1", "--untracked-files=all")):
            raise PermissionError("workspace changed; preserve changes")
        binary = qualify_native_binary(self.storage.review.executable,
                                       self.storage.review.executable_sha256)
        packet = prepare_sqlite_review(self.storage, expected_schema=self.expected_schema)
        if not packet["existing_seal_verified"] or packet["schema_review"] != "EXACT_EXPECTED_SCHEMA_MATCH":
            raise PermissionError("independent sealed schema review required")
        return {"workspace": r.workspace, "branch": r.branch, "source_head": r.source_head,
                "upstream_commit": r.upstream_commit, "expires_at": r.expires_at,
                "isolation_receipt_sha256": r.isolation_receipt_sha256,
                "auth_home_identity": identity(_safe_dir(self.storage.review.auth_home).stat()),
                "binary": binary, "storage_packet_sha256": packet["packet_sha256"]}

    def command_for_workspace(self, workspace):
        """Return only the fixed upstream command; never execute it."""
        before = self._binding(workspace)
        if not callable(self.command_approval) or not callable(self.isolation_check):
            raise PermissionError("uninstalled operator command/OS callbacks")
        # Authority is checked independently; no PREPARE receipt licenses it.
        try:
            approved = self.command_approval(digest(before)) is True
            isolated = self.isolation_check(self.review.isolation_receipt_sha256) is True
        except Exception:
            raise PermissionError("runtime approval unavailable") from None
        if not approved or not isolated:
            raise PermissionError("runtime approval or OS isolation unverified")
        argv = self.storage.app_server_args(executable=self.storage.review.executable,
                                           auth_home=self.storage.review.auth_home,
                                           readonly=False)
        if self._binding(workspace) != before:
            raise PermissionError("runtime binding changed; readback only")
        # Official AppServer's command path is a shell string. Quote each fixed
        # operator path, never append task/model/worker-supplied commands.
        return shlex.join(argv)

    def before_cleanup(self, *, attempt_id, snapshot_id, captured_at):
        """Caller invokes before original cleanup; HOLD never permits deletion.

        No automatic invocation is installed by this module. Snapshot identities
        come from the authenticated operator issue map, not arbitrary worker data.
        """
        if not callable(self.snapshot_callback) or not callable(self.snapshot_readback):
            raise PermissionError("uninstalled snapshot callbacks")
        try:
            result = self.snapshot_callback(attempt_id, snapshot_id=snapshot_id,
                                            captured_at=captured_at)
        except Exception:
            raise PermissionError("snapshot callback unavailable; hold cleanup") from None
        if (type(result) is not BoundaryResult or result.attempt_id != attempt_id
                or result.close_ready is not True
                or result.status not in ("ACCEPTED", "NOOP_DUPLICATE")):
            raise PermissionError("snapshot unresolved; hold original cleanup")
        try:
            source = self.snapshot_readback(attempt_id, snapshot_id)
        except Exception:
            raise PermissionError("snapshot readback unavailable; hold cleanup") from None
        if (type(source) is not SourceResult or source.complete is not True
                or source.trustworthy is not True
                or source.workspace_fingerprint != hashlib.sha256(self.review.workspace.encode()).hexdigest()):
            raise PermissionError("full-byte snapshot readback unavailable")
        return {"status": "SNAPSHOT_READBACK_BEFORE_CLEANUP",
                "attempt_id": attempt_id, "snapshot_id": snapshot_id,
                "cleanup_executed": False, "model_dispatch": 0}
