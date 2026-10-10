"""G6 result inspection after an upstream-owned worker lifetime.

No dispatch, scheduler, subscription route or Git write lives here. Inputs are
read-only, independently supplied complete Git inventories and verification
contracts; a worker's manifest/status alone is never adoption authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .symphony_attempt_store import AttemptSnapshot, _validate_record
from .symphony_result_adoption import AdoptionAction, AdoptionDecision

PROTOCOL = "SYMPHONY_G6_RESULT_V1"
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
SECRET = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----)")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def safe_path(value: str) -> bool:
    # Reject aliases rather than silently normalizing worker-controlled paths.
    return (type(value) is str and bool(value) and not value.startswith("/")
            and "\\" not in value and ":" not in value
            and all(ord(c) >= 32 and ord(c) != 127 for c in value)
            and all(p not in {"", ".", ".."} and p.casefold() != ".git"
                    for p in value.split("/")))


def safe_branch(value: str, default: str) -> bool:
    return (type(default) is str and bool(default) and type(value) is str
            and value not in {default, "main", "master", "HEAD"}
            and safe_path(value) and not value.startswith("refs/")
            and not value.startswith("-") and ".." not in value and "@{" not in value
            and not any(c in value for c in " ~^?*[")
            and all(not p.startswith(".") and not p.endswith((".", ".lock")) for p in value.split("/")))


class MutationOperation(str, Enum):
    ADD = "ADD"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    RENAME = "RENAME"
    COPY = "COPY"
    MODE_CHANGE = "MODE_CHANGE"
    SYMLINK = "SYMLINK"
    SUBMODULE = "SUBMODULE"
    BINARY = "BINARY"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True)
class FileEntry:
    data: bytes
    mode: str = "100644"
    kind: str = "blob"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def description(self) -> dict:
        return {"sha256": self.sha256, "mode": self.mode, "type": self.kind}


def inventory_digest(files: Mapping[str, FileEntry]) -> str:
    return digest({p: e.description() for p, e in sorted(files.items())})


def classify_mutation(before: FileEntry | None, after: FileEntry | None,
                      *, source_path: str | None = None, source_retained: bool = False) -> MutationOperation:
    entries = [e for e in (before, after) if e is not None]
    if not entries or any(type(e) is not FileEntry or type(e.data) is not bytes for e in entries):
        return MutationOperation.UNCLASSIFIED
    if any(e.kind == "symlink" or e.mode == "120000" for e in entries):
        return MutationOperation.SYMLINK
    if any(e.kind == "gitlink" or e.mode == "160000" for e in entries):
        return MutationOperation.SUBMODULE
    if any(e.kind != "blob" or e.mode not in {"100644", "100755"} for e in entries):
        return MutationOperation.UNCLASSIFIED
    try:
        for e in entries:
            if b"\0" in e.data:
                return MutationOperation.BINARY
            e.data.decode("utf-8")
    except UnicodeDecodeError:
        return MutationOperation.BINARY
    if source_path is not None:
        return MutationOperation.COPY if source_retained else MutationOperation.RENAME
    if before is None:
        return MutationOperation.ADD
    if after is None:
        return MutationOperation.DELETE
    if before.mode != after.mode:
        return MutationOperation.MODE_CHANGE
    return MutationOperation.MODIFY


@dataclass(frozen=True)
class ProofMutationPolicy:
    # Profile policy, not a permanent prohibition of other mutation classes.
    allowed_operations: frozenset[MutationOperation] = frozenset({MutationOperation.ADD, MutationOperation.MODIFY})
    allowed_modes: frozenset[str] = frozenset({"100644"})
    required_verifications: tuple[str, ...] = ("secret_scan",)
    protected_paths: tuple[str, ...] = ("AGENTS.md", ".env", ".github", "secrets")

    def to_dict(self) -> dict:
        return {"operations": sorted(x.value for x in self.allowed_operations),
                "modes": sorted(self.allowed_modes), "protected_paths": list(self.protected_paths), "required_verifications": list(self.required_verifications)}


@dataclass(frozen=True)
class CanonicalTarget:
    repository: str
    branch: str
    default_branch: str
    head: str
    files: Mapping[str, FileEntry]
    trustworthy: bool = False
    complete: bool = False


@dataclass(frozen=True)
class SourceResult:
    workspace_fingerprint: str
    files: Mapping[str, FileEntry]
    trustworthy: bool = False
    complete: bool = False


@dataclass(frozen=True)
class TaskValidity:
    task_id: str
    issue_id: str
    canonical_head: str
    scope_digest: str
    request_digest: str
    valid: bool | None
    trustworthy: bool = False


@dataclass(frozen=True)
class VerificationEvidence:
    result_digest: str
    source_digest: str
    expected_target_head: str
    scope_digest: str
    checks: Mapping[str, bool]
    evidence_refs: tuple[str, ...]
    trustworthy: bool = False


@dataclass(frozen=True)
class ResultInspection:
    decision: AdoptionDecision
    evidence: dict = field(default_factory=dict)


def seal_manifest(fields: dict) -> dict:
    result = dict(fields)
    result.pop("result_digest", None)
    return {**result, "result_digest": digest(result)}


MANIFEST_KEYS = {"protocol", "schema_version", "repository", "target_branch", "campaign_id", "attempt_id",
                 "generation", "attempt_number", "runner_generation", "task_id", "issue_id", "worker_run_id", "expected_target_head",
                 "workspace_fingerprint", "scope_digest", "request_digest", "source_digest", "mutations", "evidence_refs", "result_digest"}
MUTATION_KEYS = {"path", "operation", "source_path", "content_sha256", "before_sha256", "mode", "type"}


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def _scope_valid(scope: dict) -> bool:
    if type(scope) is not dict or set(scope) - {"issue", "allowed_paths", "allowed_prefixes", "required_checks", "request_digest"}:
        return False
    if type(scope.get("issue")) is not str or not scope["issue"]:
        return False
    if not scope.get("allowed_paths") and not scope.get("allowed_prefixes"):
        return False
    for key in ("allowed_paths", "allowed_prefixes"):
        values = scope.get(key, [])
        if type(values) is not list or len(values) != len(set(values)) or any(not safe_path(x) for x in values):
            return False
    checks = scope.get("required_checks", [])
    return type(checks) is list and all(type(x) is str and ID.fullmatch(x) for x in checks)


def _inventory_valid(files: Mapping[str, FileEntry]) -> bool:
    if not isinstance(files, Mapping):
        return False
    for path, entry in files.items():
        if not safe_path(path) or type(entry) is not FileEntry or type(entry.data) is not bytes:
            return False
        if any(parent in files for parent in ["/".join(path.split("/")[:n]) for n in range(1, len(path.split("/")))]):
            return False
        if entry.mode == "160000" and (entry.kind != "gitlink" or not SHA.fullmatch(entry.data.decode("ascii", errors="replace"))):
            return False
        if entry.mode == "120000" and entry.kind != "symlink":
            return False
        if entry.mode not in {"100644", "100755", "120000", "160000"}:
            return False
    return True


def inspect_result(*, manifest: dict | None, attempt: AttemptSnapshot | None,
                   target: CanonicalTarget | None, source: SourceResult | None,
                   validity: TaskValidity | None, verification: VerificationEvidence | None,
                   policy: ProofMutationPolicy = ProofMutationPolicy()) -> ResultInspection:
    """Deterministic decision; all authority/read failures remain typed holds.

    ``attempt`` must come from the existing validated create-only attempt store.
    Its hash chain is checked again, but no worker terminal is promoted to DONE.
    A closed Issue is not automatically valid: the explicit validity reader owns
    relevance, completion elsewhere and changed-request/scope interpretation.
    """
    facts = {"protocol": "SYMPHONY_G6_INSPECTION_V1", "policy": policy.to_dict()}
    def end(action, reason):
        return ResultInspection(AdoptionDecision(action, reason), {**facts, "action": action.value, "reason": reason})
    if manifest is None or attempt is None:
        return end(AdoptionAction.HOLD_AUTHORITY, "actual result and durable worker terminal required")
    try:
        if type(manifest) is not dict or set(manifest) != MANIFEST_KEYS or manifest["protocol"] != PROTOCOL or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
            raise ValueError("manifest schema")
        if SECRET.search(canonical(manifest).encode()):
            return end(AdoptionAction.ISOLATE_TASK, "secret material detected in result evidence")
        fields = {k: v for k, v in manifest.items() if k != "result_digest"}
        if not DIGEST.fullmatch(manifest["result_digest"]) or digest(fields) != manifest["result_digest"]:
            raise ValueError("result digest")
        for key in ("campaign_id", "attempt_id"):
            if not ID.fullmatch(manifest[key]):
                raise ValueError("result identity")
        if type(manifest["task_id"]) is not str or not manifest["task_id"] or any(ord(c) < 32 for c in manifest["task_id"]):
            raise ValueError("task identity")
        if any(type(manifest[k]) is not int or manifest[k] < 1 for k in ("generation", "attempt_number", "runner_generation")) or not re.fullmatch(r"[0-9a-f]{32}", manifest["worker_run_id"]):
            raise ValueError("worker generation/identity")
        if not SHA.fullmatch(manifest["expected_target_head"]) or any(not DIGEST.fullmatch(manifest[k]) for k in ("workspace_fingerprint", "source_digest", "scope_digest", "request_digest")):
            raise ValueError("result hashes")
        if type(manifest["evidence_refs"]) is not list or not manifest["evidence_refs"] or any(type(x) is not str or not x for x in manifest["evidence_refs"]):
            raise ValueError("result evidence refs")
        if type(attempt) is not AttemptSnapshot or attempt.state != "TERMINAL" or attempt.started is None or attempt.terminal is None:
            return end(AdoptionAction.HOLD_AUTHORITY, "verified STARTED and TERMINAL required")
        identity = attempt.identity
        for record, kind in [(attempt.intent, "intent"), (attempt.started, "started"), (attempt.terminal, "terminal")]:
            if _validate_record(record, kind=kind) != identity:
                raise ValueError("attempt record identity")
        if attempt.started["intent_digest"] != digest(attempt.intent) or attempt.terminal["predecessor_digest"] != digest(attempt.started):
            raise ValueError("attempt predecessor digest")
        for field_name in ("campaign_id", "attempt_id", "task_id", "generation", "attempt_number", "runner_generation", "expected_target_head"):
            if manifest[field_name] != getattr(identity, field_name) or type(manifest[field_name]) is not type(getattr(identity, field_name)):
                raise ValueError("result/attempt identity")
        if attempt.started["provider_attempt_ref"] != manifest["worker_run_id"] or attempt.started["workspace_fingerprint"] != manifest["workspace_fingerprint"]:
            raise ValueError("worker/workspace identity")
        if attempt.terminal["result_id"] != "sym-g5-worker:" + manifest["worker_run_id"]:
            raise ValueError("worker terminal result identity")
        statuses = [x for x in attempt.terminal["evidence_refs"] if x.startswith("sym-g5-status:")]
        if len(statuses) != 1 or statuses[0] not in {"sym-g5-status:WORKER_COMPLETED", "sym-g5-status:WORKER_FAILED", "sym-g5-status:WORKER_STOPPED"}:
            raise ValueError("worker lifecycle evidence")
        scope = attempt.intent["scope"]
        if not _scope_valid(scope) or manifest["scope_digest"] != digest(scope) or manifest["issue_id"] != scope["issue"]:
            raise ValueError("task/Issue/scope identity")
        if scope.get("request_digest") != manifest["request_digest"]:
            return end(AdoptionAction.HOLD_AUTHORITY, "durable task request revision unavailable")
        facts.update(result_digest=manifest["result_digest"], attempt_id=identity.attempt_id,
                     source_digest=manifest["source_digest"], scope_digest=manifest["scope_digest"],
                     lifecycle_status=statuses[0], expected_target_head=identity.expected_target_head)
    except (TypeError, ValueError, KeyError, AttributeError):
        return end(AdoptionAction.CONFLICT, "result manifest or worker binding mismatch")
    if (type(target) is not CanonicalTarget or target.trustworthy is not True or target.complete is not True
            or type(target.head) is not str or not SHA.fullmatch(target.head or "") or not target.default_branch
            or target.repository != manifest["repository"] or target.branch != manifest["target_branch"]
            or not safe_branch(target.branch, target.default_branch)):
        return end(AdoptionAction.HOLD_AUTHORITY, "fresh non-default canonical target authority unavailable")
    facts["canonical_head"] = target.head
    if target.head != manifest["expected_target_head"]:
        return end(AdoptionAction.STALE_REPLAN, "canonical HEAD advanced; replan this task without Git write")
    if (type(validity) is not TaskValidity or validity.trustworthy is not True or type(validity.valid) is not bool
            or (validity.task_id, validity.issue_id, validity.canonical_head, validity.scope_digest)
            != (manifest["task_id"], manifest["issue_id"], target.head, manifest["scope_digest"])):
        return end(AdoptionAction.HOLD_AUTHORITY, "fresh task-validity authority unavailable or scope changed")
    if validity.request_digest != manifest["request_digest"]:
        return end(AdoptionAction.ISOLATE_TASK, "task request changed since worker result")
    if not validity.valid:
        return end(AdoptionAction.ISOLATE_TASK, "task invalid/completed elsewhere on fresh target")
    if (type(source) is not SourceResult or source.trustworthy is not True or source.complete is not True
            or source.workspace_fingerprint != manifest["workspace_fingerprint"]):
        return end(AdoptionAction.HOLD_AUTHORITY, "complete bound source inventory unavailable")
    try:
        if not _inventory_valid(source.files) or not _inventory_valid(target.files):
            return end(AdoptionAction.ISOLATE_TASK, "unsafe path/type or unconstructible repository tree")
        if inventory_digest(source.files) != manifest["source_digest"]:
            raise ValueError("source bytes digest")
        mutations = manifest["mutations"]
        if type(mutations) is not list or not mutations:
            raise ValueError("mutation manifest required")
        changed = {p for p in set(source.files) | set(target.files) if source.files.get(p) != target.files.get(p)}
        declared = [m["path"] for m in mutations]
        if len(declared) != len(set(declared)):
            raise ValueError("duplicate mutation path")
        observed_paths = set(declared)
        for m in mutations:
            if set(m) != MUTATION_KEYS:
                raise ValueError("mutation shape")
            path, origin = m["path"], m["source_path"]
            if not safe_path(path) or (origin is not None and not safe_path(origin)):
                return end(AdoptionAction.ISOLATE_TASK, "unsafe result path")
            for p in [path] + ([origin] if origin is not None else []):
                if (p not in scope.get("allowed_paths", []) and not any(_under(p, root) for root in scope.get("allowed_prefixes", []))) or any(_under(p, root) for root in policy.protected_paths):
                    return end(AdoptionAction.ISOLATE_TASK, "scope-outside or protected path mutation")
            before, after = target.files.get(path), source.files.get(path)
            if origin is not None:
                if origin == path or path in target.files or origin not in target.files:
                    raise ValueError("rename/copy source binding")
                before = target.files[origin]
                if origin not in source.files:
                    observed_paths.add(origin)
            operation = classify_mutation(before, after, source_path=origin, source_retained=origin in source.files if origin else False)
            if m["operation"] != operation.value:
                raise ValueError("declared mutation differs from observed mutation")
            if m["before_sha256"] != (before.sha256 if before else None) or m["content_sha256"] != (after.sha256 if after else None):
                raise ValueError("mutation content digest")
            if m["mode"] != ((after or before).mode) or m["type"] != ((after or before).kind):
                raise ValueError("mutation mode/type")
            if operation not in policy.allowed_operations or (after is not None and after.mode not in policy.allowed_modes):
                return end(AdoptionAction.ISOLATE_TASK, "mutation held by conservative proof profile")
            if after is not None and SECRET.search(after.data):
                return end(AdoptionAction.ISOLATE_TASK, "secret material detected in changed result bytes")
        if observed_paths != changed:
            raise ValueError("unexpected/missing changed files")
    except (TypeError, ValueError, KeyError, AttributeError):
        return end(AdoptionAction.CONFLICT, "result bytes, paths or mutation digest mismatch")
    required = set(scope.get("required_checks", [])) | set(policy.required_verifications)
    if (type(verification) is not VerificationEvidence or verification.trustworthy is not True
            or (verification.result_digest, verification.source_digest, verification.expected_target_head, verification.scope_digest)
            != (manifest["result_digest"], manifest["source_digest"], target.head, manifest["scope_digest"])
            or not isinstance(verification.checks, Mapping) or any(type(k) is not str or type(v) is not bool for k,v in verification.checks.items())
            or not required <= verification.checks.keys()
            or any(verification.checks[x] is not True for x in required)
            or type(verification.evidence_refs) is not tuple or not verification.evidence_refs or any(type(x) is not str for x in verification.evidence_refs)
            or not set(verification.evidence_refs) <= set(manifest["evidence_refs"])):
        return end(AdoptionAction.HOLD_AUTHORITY, "bound independent verification contract unavailable or failed")
    facts.update(target_inventory_digest=inventory_digest(target.files), changed_paths=sorted(changed), verification_refs=list(verification.evidence_refs),
                 inspection_digest=digest({"result": manifest["result_digest"], "policy": policy.to_dict(), "verification": dict(verification.checks)}))
    return end(AdoptionAction.ADOPT, "actual result inspected against fresh valid non-default target")
