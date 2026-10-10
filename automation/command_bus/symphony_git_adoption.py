"""G6 STATIC adoption/recovery seam with create-only records and fake Git CAS.

This batch exposes no live Git transport. ``static_only`` is required on the
transport; an existing GitHub/CLI ref helper cannot be wired in accidentally.
Worker scheduling, continuation and lifecycle ledgers remain untouched.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Callable, Mapping, Protocol

from .executor_backend import ExecutorContentsClient
from .symphony_result_adoption import AdoptionAction, decide_verified_result_adoption
from .symphony_result_manifest import (CanonicalTarget, FileEntry, SourceResult, TaskValidity,
    VerificationEvidence, ProofMutationPolicy, SHA, DIGEST, ID, canonical, digest,
    safe_branch, safe_path, inventory_digest, seal_manifest)

PROTOCOL = "SYMPHONY_G6_ADOPTION_V1"
KINDS = {"result", "decision", "intent", "objects", "ref_intent", "receipt", "target_lock"}


class AdoptionConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class GitCandidate:
    parent: str
    tree: str
    commit: str
    commit_bytes: bytes
    files: Mapping[str, FileEntry]
    objects: Mapping[str, tuple[str, bytes]]


def _git_oid(kind: str, data: bytes) -> str:
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def construct_candidate(*, parent: str, files: Mapping[str, FileEntry], created_at: str,
                        adoption_id: str) -> GitCandidate:
    """Pure Git blob/tree/commit construction; creates no objects or refs."""
    if not SHA.fullmatch(parent) or not ID.fullmatch(adoption_id):
        raise ValueError("invalid candidate identity")
    clock = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if clock.tzinfo is None:
        raise ValueError("candidate timestamp requires timezone")
    directories: dict = {}; objects = {}
    for path, entry in sorted(files.items()):
        if not safe_path(path) or type(entry) is not FileEntry or type(entry.data) is not bytes:
            raise ValueError("unsafe candidate file")
        parts = path.split("/"); directory = directories
        for p in parts[:-1]:
            child = directory.setdefault(p, {})
            if not isinstance(child, dict):
                raise ValueError("file/directory collision")
            directory = child
        if parts[-1] in directory:
            raise ValueError("file/directory collision")
        if entry.mode == "160000" and entry.kind == "gitlink":
            oid = entry.data.decode("ascii")
            if not SHA.fullmatch(oid):
                raise ValueError("invalid gitlink")
        elif (entry.mode in {"100644", "100755"} and entry.kind == "blob") or (entry.mode == "120000" and entry.kind == "symlink"):
            oid = _git_oid("blob", entry.data); objects[oid] = ("blob", entry.data)
        else:
            raise ValueError("unsupported candidate Git mode/type")
        directory[parts[-1]] = (entry.mode, oid)
    def tree(directory):
        raw = b""
        # Git sorts directory names as if suffixed by '/', not plain strings.
        for name, item in sorted(directory.items(), key=lambda p: (p[0] + ("/" if isinstance(p[1], dict) else "")).encode()):
            mode, oid = ("40000", tree(item)) if isinstance(item, dict) else item
            raw += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(oid)
        oid = _git_oid("tree", raw); objects[oid] = ("tree", raw); return oid
    tree_oid = tree(directories)
    identity = f"Symphony G6 STATIC <static@invalid> {int(clock.timestamp())} +0000"
    raw = f"tree {tree_oid}\nparent {parent}\nauthor {identity}\ncommitter {identity}\n\nG6 adoption {adoption_id}\n".encode()
    commit = _git_oid("commit", raw); objects[commit] = ("commit", raw)
    return GitCandidate(parent, tree_oid, commit, raw, dict(files), objects)


class StaticGitTransport(Protocol):
    static_only: bool
    atomic_expected_head: bool
    def read_target(self) -> CanonicalTarget: ...
    def put_candidate(self, candidate: GitCandidate) -> None: ...
    def read_candidate(self, commit: str) -> GitCandidate | None: ...
    def compare_and_swap(self, *, branch: str, expected_head: str, candidate_head: str) -> None: ...


@dataclass(frozen=True)
class AdoptionResult:
    status: str
    reason: str
    adoption_id: str | None = None
    receipt: dict | None = None
    decision_evidence: dict | None = None

    def to_dict(self) -> dict:
        return {"protocol": PROTOCOL, "status": self.status, "reason": self.reason,
                "adoption_id": self.adoption_id, "receipt": self.receipt,
                "unknown_class": "RECOVERABLE_UNKNOWN" if self.status == "UNKNOWN" else None,
                "decision_evidence": self.decision_evidence}


def make_adoption_id(manifest: dict) -> str:
    for key in ("campaign_id", "attempt_id"):
        if not ID.fullmatch(manifest[key]):
            raise ValueError("invalid adoption identity")
    if type(manifest["task_id"]) is not str or not manifest["task_id"] or any(ord(c) < 32 for c in manifest["task_id"]):
        raise ValueError("invalid task identity")
    if not DIGEST.fullmatch(manifest["result_digest"]):
        raise ValueError("invalid result digest")
    return "adopt-" + digest({k: manifest[k] for k in ("repository", "target_branch", "campaign_id",
        "attempt_id", "generation", "task_id", "worker_run_id", "expected_target_head", "result_digest")})[:32]


class AppendOnlyAdoptionStore:
    """Reuse ExecutorContentsClient's create/read contract; never update/delete.

    A create exception gets exact readback, not another create. Every entry has
    a self-digest and the decision/intent/ref/receipt chain binds predecessors.
    The caller must supply a credential-free fake client in this STATIC batch.
    """
    def __init__(self, client: ExecutorContentsClient, *, write_branch: str, default_branch: str = "main"):
        if not safe_branch(write_branch, default_branch):
            raise ValueError("adoption ledger requires a canonical non-default branch")
        self.client, self.branch = client, write_branch

    def path(self, campaign: str, adoption: str, kind: str) -> str:
        if not ID.fullmatch(campaign) or not ID.fullmatch(adoption) or (kind not in KINDS and re.fullmatch(r"inspection-[0-9a-f]{64}", kind) is None):
            raise ValueError("invalid adoption ledger identity")
        return f"symphony_adoptions/{campaign}/{adoption}/{kind}.json"

    def _get(self, path: str) -> dict | None:
        content = self.client.get(path, self.branch)
        if content is None:
            return None
        try:
            record = json.loads(content.text)
            if (content.path != path or set(record) != {"protocol", "path", "payload", "record_digest"}
                    or record["protocol"] != PROTOCOL or record["path"] != path
                    or digest({k: v for k, v in record.items() if k != "record_digest"}) != record["record_digest"]):
                raise ValueError("ledger digest/path mismatch")
            return record["payload"]
        except (TypeError, ValueError, KeyError) as exc:
            raise AdoptionConflict("adoption record integrity mismatch") from exc

    def get(self, campaign: str, adoption: str, kind: str) -> dict | None:
        return self._get(self.path(campaign, adoption, kind))

    def _put(self, path: str, payload: dict) -> str:
        record = {"protocol": PROTOCOL, "path": path, "payload": payload}
        text = canonical({**record, "record_digest": digest(record)})
        try:
            old = self._get(path)
            if old is not None:
                return "NOOP_DUPLICATE" if old == payload else "CONFLICT"
            self.client.create(path, text, "append Symphony G6 observation", self.branch)
        except AdoptionConflict:
            return "CONFLICT"
        except Exception:
            # Unknown create: GET only. No retry, including receipt/dispatch fences.
            pass
        try:
            found = self._get(path)
            return "ACCEPTED" if found == payload else ("CONFLICT" if found is not None else "UNKNOWN")
        except AdoptionConflict:
            return "CONFLICT"
        except Exception:
            return "UNKNOWN"

    def put(self, campaign: str, adoption: str, kind: str, payload: dict) -> str:
        return self._put(self.path(campaign, adoption, kind), payload)

    def _lock_path(self, intent):
        slot = digest({k: intent[k] for k in ("repository", "target_branch", "expected_target_head")})
        return f"symphony_adoption_locks/{slot}.json"

    def lock_target(self, intent: dict) -> str:
        return self._put(self._lock_path(intent), {"adoption_id": intent["adoption_id"], "intent_digest": digest(intent)})

    def verify_lock(self, intent: dict) -> bool:
        return self._get(self._lock_path(intent)) == {"adoption_id": intent["adoption_id"], "intent_digest": digest(intent)}


class StaticAdoptionBridge:
    def __init__(self, *, store: AppendOnlyAdoptionStore, transport: StaticGitTransport,
                 repository: str, target_branch: str, default_branch: str,
                 policy: ProofMutationPolicy = ProofMutationPolicy()):
        if getattr(transport, "static_only", None) is not True or getattr(transport, "atomic_expected_head", None) is not True:
            raise ValueError("STATIC atomic expected-head transport required; LIVE not wired")
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
                or not safe_branch(target_branch, default_branch) or target_branch == store.branch):
            raise ValueError("non-default result target must differ from ledger branch")
        self.store, self.transport = store, transport
        self.repository, self.target_branch, self.default_branch = repository, target_branch, default_branch
        self.policy = policy

    def _bound_target(self, target):
        return (type(target) is CanonicalTarget and target.repository == self.repository
                and target.branch == self.target_branch and target.default_branch == self.default_branch
                and target.trustworthy is True and target.complete is True and type(target.head) is str and SHA.fullmatch(target.head or ""))

    def _candidate_verified(self, intent: dict) -> bool:
        candidate = self.transport.read_candidate(intent["candidate_commit"])
        if type(candidate) is not GitCandidate:
            return False
        rebuilt = construct_candidate(parent=intent["expected_target_head"], files=candidate.files,
            created_at=intent["created_at"], adoption_id=intent["adoption_id"])
        return (candidate.parent == rebuilt.parent and candidate.tree == rebuilt.tree == intent["candidate_tree"]
                and candidate.commit == rebuilt.commit == intent["candidate_commit"]
                and candidate.commit_bytes == rebuilt.commit_bytes
                and dict(candidate.objects) == dict(rebuilt.objects)
                and inventory_digest(candidate.files) == intent["source_digest"])

    def _validate_chain(self, manifest, adoption, intent, decision):
        if (not intent or not decision or decision.get("action") != "ADOPT"
                or intent.get("protocol") != PROTOCOL or intent.get("status") != "INTENT"
                or intent.get("adoption_id") != adoption or intent.get("decision_digest") != digest(decision)
                or intent.get("manifest_digest") != digest(manifest)):
            raise AdoptionConflict("adoption intent/result/decision chain mismatch")
        for key in ("campaign_id", "attempt_id", "task_id", "worker_run_id", "generation", "attempt_number", "runner_generation", "result_digest",
                    "expected_target_head", "repository", "target_branch", "source_digest"):
            if intent.get(key) != manifest[key]:
                raise AdoptionConflict("adoption intent binding mismatch")
        if intent["repository"] != self.repository or intent["target_branch"] != self.target_branch:
            raise AdoptionConflict("configured target differs from durable intent")
        if decision.get("result_digest") != manifest["result_digest"]:
            raise AdoptionConflict("decision result mismatch")

    def _receipt_valid(self, receipt, intent, marker):
        if not marker or marker != {"intent_digest": digest(intent), "candidate_commit": intent["candidate_commit"]}:
            return False
        fields = {"protocol": PROTOCOL, "status": "ADOPTED", "adoption_id": intent["adoption_id"],
                  "intent_digest": digest(intent), "ref_intent_digest": digest(marker),
                  "campaign_id": intent["campaign_id"], "attempt_id": intent["attempt_id"], "task_id": intent["task_id"],
                  "generation": intent["generation"], "attempt_number": intent["attempt_number"], "runner_generation": intent["runner_generation"], "result_digest": intent["result_digest"],
                  "repository": intent["repository"], "target_branch": intent["target_branch"],
                  "head_before": intent["expected_target_head"], "head_after": intent["candidate_commit"],
                  "tree_after": intent["candidate_tree"], "source_digest": intent["source_digest"],
                  "remote_tree_blob_ref_verified": True, "ref_write_retry_count": 0}
        return type(receipt) is dict and set(receipt) == set(fields) | {"observed_at"} and all(receipt[k] == v and type(receipt[k]) is type(v) for k,v in fields.items())

    def _finish(self, campaign, adoption, intent, marker, now):
        if not self._candidate_verified(intent):
            return AdoptionResult("UNKNOWN", "candidate tree/blob/commit readback unavailable or mismatched", adoption)
        receipt = {"protocol": PROTOCOL, "status": "ADOPTED", "adoption_id": adoption,
            "intent_digest": digest(intent), "ref_intent_digest": digest(marker), "campaign_id": campaign,
            "attempt_id": intent["attempt_id"], "task_id": intent["task_id"], "generation": intent["generation"], "attempt_number": intent["attempt_number"], "runner_generation": intent["runner_generation"],
            "result_digest": intent["result_digest"], "repository": intent["repository"], "target_branch": intent["target_branch"],
            "head_before": intent["expected_target_head"], "head_after": intent["candidate_commit"],
            "tree_after": intent["candidate_tree"], "source_digest": intent["source_digest"],
            "remote_tree_blob_ref_verified": True, "ref_write_retry_count": 0, "observed_at": now}
        written = self.store.put(campaign, adoption, "receipt", receipt)
        if written not in {"ACCEPTED", "NOOP_DUPLICATE"}:
            return AdoptionResult(written, "ref read back; receipt remains unresolved, never resend ref update", adoption)
        stored = self.store.get(campaign, adoption, "receipt")
        if not self._receipt_valid(stored, intent, marker):
            return AdoptionResult("CONFLICT", "terminal adoption receipt mismatch", adoption)
        return AdoptionResult("ADOPTED", "remote ref/tree/blobs verified; durable receipt read back", adoption, stored)

    def process(self, *, manifest: dict | None, attempt_reader: Callable,
                source_reader: Callable[[], SourceResult], validity_reader: Callable[[CanonicalTarget], TaskValidity],
                verification_reader: Callable[[], VerificationEvidence], now: str,
                crash_hook: Callable[[str], None] = lambda point: None) -> AdoptionResult:
        """Recover using records/GETs; no automatic model or ref-update resend.

        A fence written before CAS cannot prove whether CAS was attempted. If
        recovery sees that fence but the old/unknown head, return UNKNOWN. This
        is deliberately different from idempotent content-addressed objects.
        """
        if manifest is None:
            return AdoptionResult("HOLD_AUTHORITY", "worker TERMINAL alone is not actual result evidence")
        try:
            if seal_manifest(manifest) != manifest or manifest["repository"] != self.repository or manifest["target_branch"] != self.target_branch:
                return AdoptionResult("CONFLICT", "result digest/configured target mismatch")
            adoption = make_adoption_id(manifest); campaign = manifest["campaign_id"]
            saved_result = self.store.get(campaign, adoption, "result")
            intent = self.store.get(campaign, adoption, "intent")
            decision = self.store.get(campaign, adoption, "decision")
            marker = self.store.get(campaign, adoption, "ref_intent")
            receipt = self.store.get(campaign, adoption, "receipt")
            if saved_result is not None and saved_result != manifest:
                raise AdoptionConflict("result digest reused with different bytes")
            if intent is not None or marker is not None or receipt is not None:
                if saved_result is None:
                    raise AdoptionConflict("adoption result record missing")
                self._validate_chain(manifest, adoption, intent, decision)
            if receipt is not None:
                if not self.store.verify_lock(intent) or not self._receipt_valid(receipt, intent, marker) or not self._candidate_verified(intent):
                    raise AdoptionConflict("receipt/candidate chain mismatch")
                # Historical verified receipt stays terminal if target advances later.
                return AdoptionResult("NOOP_DUPLICATE", "verified terminal receipt already exists; Git writes 0", adoption, receipt)
            target = self.transport.read_target()
            if not self._bound_target(target):
                return AdoptionResult("HOLD_AUTHORITY", "fresh canonical authority unavailable", adoption)
            if marker is not None:
                if marker != {"intent_digest": digest(intent), "candidate_commit": intent["candidate_commit"]}:
                    raise AdoptionConflict("ref intent binding mismatch")
                if not self.store.verify_lock(intent):
                    raise AdoptionConflict("adoption target lock missing/mismatched")
                if target.head == intent["candidate_commit"]:
                    return self._finish(campaign, adoption, intent, marker, now)
                return AdoptionResult("UNKNOWN", "ref update may have happened; readback inconclusive, resend forbidden", adoption)
            # Snapshot copies prevent mutation of inventories after their inspection.
            target = replace(target, files=dict(target.files))
            source = source_reader(); source = replace(source, files=dict(source.files))
            attempt = attempt_reader(); validity = validity_reader(target); verification = verification_reader()
            inspection = decide_verified_result_adoption(manifest=manifest, attempt=attempt,
                target=target, source=source, validity=validity, verification=verification, policy=self.policy)
            audited = self.store.put(campaign, adoption, "inspection-" + digest(inspection.evidence), inspection.evidence)
            if audited not in {"ACCEPTED", "NOOP_DUPLICATE"}:
                return AdoptionResult(audited, "inspection evidence durability unavailable", adoption, decision_evidence=inspection.evidence)
            if inspection.decision.action is not AdoptionAction.ADOPT:
                return AdoptionResult(inspection.decision.action.value, inspection.decision.reason, adoption, decision_evidence=inspection.evidence)
            for kind, payload in [("result", manifest), ("decision", inspection.evidence)]:
                state = self.store.put(campaign, adoption, kind, payload)
                if state not in {"ACCEPTED", "NOOP_DUPLICATE"}:
                    return AdoptionResult(state, "durable result/inspection unresolved", adoption)
            created = intent["created_at"] if intent else now
            candidate = construct_candidate(parent=target.head, files=source.files, created_at=created, adoption_id=adoption)
            proposed = {"protocol": PROTOCOL, "status": "INTENT", "adoption_id": adoption,
                **{k: manifest[k] for k in ("campaign_id", "attempt_id", "task_id", "worker_run_id", "generation", "attempt_number", "runner_generation",
                    "result_digest", "expected_target_head", "repository", "target_branch", "source_digest")},
                "created_at": created, "manifest_digest": digest(manifest), "decision_digest": digest(inspection.evidence),
                "candidate_commit": candidate.commit, "candidate_tree": candidate.tree}
            if intent is not None and intent != proposed:
                raise AdoptionConflict("restored candidate/inspection differs from intent")
            state = self.store.put(campaign, adoption, "intent", proposed)
            if state not in {"ACCEPTED", "NOOP_DUPLICATE"}:
                return AdoptionResult(state, "durable adoption intent unresolved", adoption)
            intent = proposed
            state = self.store.lock_target(intent)
            if state not in {"ACCEPTED", "NOOP_DUPLICATE"}:
                return AdoptionResult(state, "another adoption owns this exact target HEAD", adoption)
            crash_hook("AFTER_INTENT")
            try:
                self.transport.put_candidate(candidate)
            except Exception:
                pass  # content addressed object readback, not an uncertain ref retry
            if not self._candidate_verified(intent):
                return AdoptionResult("UNKNOWN", "candidate objects not verified; ref write 0", adoption)
            crash_hook("AFTER_OBJECTS")
            state = self.store.put(campaign, adoption, "objects", {"intent_digest": digest(intent), "candidate_commit": candidate.commit, "tree": candidate.tree})
            if state not in {"ACCEPTED", "NOOP_DUPLICATE"}:
                return AdoptionResult(state, "durable candidate marker unresolved", adoption)
            fresh = self.transport.read_target()
            if not self._bound_target(fresh):
                return AdoptionResult("HOLD_AUTHORITY", "pre-ref canonical authority unavailable", adoption)
            fresh_source = source_reader(); fresh_source = replace(fresh_source, files=dict(fresh_source.files))
            check = decide_verified_result_adoption(manifest=manifest, attempt=attempt_reader(), target=fresh,
                source=fresh_source, validity=validity_reader(fresh), verification=verification_reader(), policy=self.policy)
            audited = self.store.put(campaign, adoption, "inspection-" + digest(check.evidence), check.evidence)
            if audited not in {"ACCEPTED", "NOOP_DUPLICATE"}:
                return AdoptionResult(audited, "pre-ref inspection evidence durability unavailable", adoption, decision_evidence=check.evidence)
            if check.decision.action is not AdoptionAction.ADOPT:
                return AdoptionResult(check.decision.action.value, check.decision.reason, adoption, decision_evidence=check.evidence)
            marker = {"intent_digest": digest(intent), "candidate_commit": candidate.commit}
            state = self.store.put(campaign, adoption, "ref_intent", marker)
            if state not in {"ACCEPTED", "NOOP_DUPLICATE"}:
                return AdoptionResult(state, "pre-ref fence unresolved; no blind ref write", adoption)
            crash_hook("AFTER_REF_INTENT")
            try:
                self.transport.compare_and_swap(branch=self.target_branch, expected_head=target.head, candidate_head=candidate.commit)
            except Exception:
                pass  # exactly one call, then GET readback even if response is lost
            crash_hook("AFTER_REF")
            after = self.transport.read_target()
            if not self._bound_target(after) or after.head != candidate.commit:
                return AdoptionResult("UNKNOWN", "ref update unproven; readback only on restart", adoption)
            return self._finish(campaign, adoption, intent, marker, now)
        except AdoptionConflict as exc:
            return AdoptionResult("CONFLICT", str(exc), locals().get("adoption"))
        except Exception:
            if locals().get("marker") is not None:
                return AdoptionResult("UNKNOWN", "ref outcome unresolved; GET readback only, never resend", locals().get("adoption"))
            return AdoptionResult("HOLD_AUTHORITY", "result/adoption authority read unavailable; no default adoption", locals().get("adoption"))

    def apply_receipt_to_campaign(self, kernel, *, manifest: dict) -> AdoptionResult:
        """Opt-in post-receipt seam; caller checkpoints with existing campaign store.

        This never invokes the upstream scheduler. An absent/mismatched receipt
        cannot turn G5's worker UNKNOWN into a successful campaign result.
        """
        from .symphony_autonomous_runtime import TaskOutcome
        try:
            adoption = make_adoption_id(manifest); campaign = manifest["campaign_id"]
            if seal_manifest(manifest) != manifest or kernel.state.campaign_id != campaign or kernel.state.generation != manifest["generation"]:
                raise AdoptionConflict("campaign/result identity mismatch")
            stored = self.store.get(campaign, adoption, "result")
            intent = self.store.get(campaign, adoption, "intent"); decision = self.store.get(campaign, adoption, "decision")
            receipt = self.store.get(campaign, adoption, "receipt"); marker = self.store.get(campaign, adoption, "ref_intent")
            if receipt is None:
                return AdoptionResult("HOLD_AUTHORITY", "durable Git adoption receipt missing", adoption)
            if stored != manifest:
                raise AdoptionConflict("campaign result differs from inspected result")
            self._validate_chain(manifest, adoption, intent, decision)
            if not self.store.verify_lock(intent) or not self._receipt_valid(receipt, intent, marker) or not self._candidate_verified(intent):
                raise AdoptionConflict("unverified campaign adoption receipt")
            task = kernel.state.tasks[manifest["task_id"]]
            if task.expected_target_head != manifest["expected_target_head"] or task.attempts != manifest["attempt_number"]:
                raise AdoptionConflict("campaign task lineage mismatch")
            result_id = "sym-g6-adoption:" + adoption
            if result_id in kernel.state.processed_result_ids:
                return AdoptionResult("NOOP_DUPLICATE", "campaign already checkpointed this adoption", adoption, receipt)
            kernel.record_result(result_id=result_id, task_id=task.task_id, outcome=TaskOutcome.DONE,
                                 allow_blocked_recovery=True, recovery_attempt_id=manifest["attempt_id"])
            kernel.state.result_attempt_ids[result_id] = manifest["attempt_id"]
            return AdoptionResult("ADOPTED", "verified receipt permits campaign checkpoint; caller must save it", adoption, receipt)
        except AdoptionConflict as exc:
            return AdoptionResult("CONFLICT", str(exc))
        except Exception:
            return AdoptionResult("HOLD_AUTHORITY", "campaign receipt/authority unavailable")


    def apply_decision_to_campaign(self, kernel, *, manifest: dict, result: AdoptionResult) -> AdoptionResult:
        """Only task-local replan/isolation; never selection, dispatch or DONE.

        Successful completion has exactly one entry point: the independently
        verified adoption receipt above. The caller saves a normal campaign
        checkpoint before continuing its own planning, using the existing store.
        """
        from .symphony_autonomous_runtime import TaskOutcome, TaskStatus
        try:
            adoption = make_adoption_id(manifest)
            if (seal_manifest(manifest) != manifest or result.adoption_id != adoption
                    or kernel.state.campaign_id != manifest["campaign_id"]
                    or kernel.state.generation != manifest["generation"]):
                raise AdoptionConflict("task decision/result identity mismatch")
            task = kernel.state.tasks[manifest["task_id"]]
            if task.expected_target_head != manifest["expected_target_head"] or task.attempts != manifest["attempt_number"]:
                raise AdoptionConflict("task decision attempt lineage mismatch")
            if result.status not in {"STALE_REPLAN", "ISOLATE_TASK", "HOLD_AUTHORITY", "CONFLICT", "UNKNOWN"}:
                return AdoptionResult("HOLD_AUTHORITY", "campaign completion requires verified adoption receipt", adoption)
            if result.decision_evidence is not None:
                saved = self.store.get(manifest["campaign_id"], adoption, "inspection-" + digest(result.decision_evidence))
                if saved != result.decision_evidence or saved.get("action") != result.status:
                    raise AdoptionConflict("task decision lacks matching durable inspection")
            if task.status in {TaskStatus.COMPLETE, TaskStatus.SUPERSEDED}:
                return AdoptionResult("NOOP_DUPLICATE", "historical decision cannot alter completed task", adoption)
            if result.status == "STALE_REPLAN":
                if result.decision_evidence is None:
                    raise AdoptionConflict("stale replan requires durable canonical inspection")
                rid = "sym-g6-replan:" + adoption + ":" + digest(result.decision_evidence)[:16]
                if rid in kernel.state.processed_result_ids:
                    return AdoptionResult("NOOP_DUPLICATE", "task replan already checkpointed", adoption)
                kernel.record_result(result_id=rid, task_id=task.task_id, outcome=TaskOutcome.STALE)
            else:
                kernel.isolate_unresolved_attempt(task.task_id, manifest["attempt_id"], "G6 " + result.status)
            return AdoptionResult(result.status, "task-local checkpoint permitted; independent work remains available", adoption)
        except AdoptionConflict as exc:
            return AdoptionResult("CONFLICT", str(exc))
        except Exception:
            return AdoptionResult("HOLD_AUTHORITY", "task decision checkpoint authority unavailable")
