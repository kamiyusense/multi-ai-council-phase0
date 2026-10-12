"""G6.2 production prepare-only seam. There is no write-capable HTTP path.

A reviewed result can become a deterministic plan. OFF is the sole accepted
mode; sending objects/ref updates remains unavailable. Official Symphony is
not called here. The existing STATIC bridge is used only by mock fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass

from .symphony_git_adoption import construct_candidate, make_adoption_id
from .symphony_github_git_transport import prepare_candidate_requests, prepare_update_refs
from .symphony_result_adoption import AdoptionAction, decide_verified_result_adoption
from .symphony_result_manifest import ProofMutationPolicy, digest, inventory_digest, seal_manifest


@dataclass(frozen=True)
class Preparation:
    status: str
    reason: str
    plan: dict | None = None


class PrepareOnlyGitHubTransport:
    """An OFF adapter around independently configured readers; never executes.

    Readiness is not authorization. Neither a caller-selected mode nor a
    mutable static_only flag can enable publication: no sender is held here.
    """
    static_only = False
    mode = "OFF"

    def __init__(self, *, repository: str, repository_id: str, target_branch: str,
                 default_branch: str, target_reader, validity_reader, mode="OFF"):
        if mode != "OFF":
            raise PermissionError("production publication OFF; LIVE not authorized or wired")
        self.repository, self.repository_id = repository, repository_id
        self.target_branch, self.default_branch = target_branch, default_branch
        self.target_reader, self.validity_reader = target_reader, validity_reader
        # Validate literal branch/node/OID contract now, without network/write.
        prepare_update_refs(repository_id=repository_id, branch=target_branch, default_branch=default_branch,
                            before_oid="1" * 40, after_oid="2" * 40, client_mutation_id="prepare-only")

    def prepare(self, *, manifest, attempt, source, verification, now: str) -> Preparation:
        if (seal_manifest(manifest) != manifest or manifest["repository"] != self.repository
                or manifest["target_branch"] != self.target_branch):
            return Preparation("CONFLICT", "result/configuration digest mismatch")
        target = self.target_reader.read()
        if (target.repository != self.repository or target.branch != self.target_branch
                or target.default_branch != self.default_branch):
            return Preparation("HOLD_AUTHORITY", "fresh target binding unavailable")
        check = decide_verified_result_adoption(manifest=manifest, attempt=attempt, target=target,
            source=source, validity=self.validity_reader(target), verification=verification, policy=ProofMutationPolicy())
        if check.decision.action is not AdoptionAction.ADOPT:
            return Preparation(check.decision.action.value, check.decision.reason)
        candidate = construct_candidate(parent=target.head, files=source.files, created_at=now,
                                        adoption_id=make_adoption_id(manifest))
        objects = prepare_candidate_requests(candidate)
        ref = prepare_update_refs(repository_id=self.repository_id, branch=self.target_branch,
            default_branch=self.default_branch, before_oid=target.head, after_oid=candidate.commit,
            client_mutation_id="sym-g62-" + candidate.commit[:16])
        # Re-read after all preparation, so an observed head/task drift invalidates
        # the plan. Atomic beforeOid remains required at any future send boundary.
        fresh = self.target_reader.read()
        final = decide_verified_result_adoption(manifest=manifest, attempt=attempt, target=fresh,
            source=source, validity=self.validity_reader(fresh), verification=verification, policy=ProofMutationPolicy())
        if final.decision.action is not AdoptionAction.ADOPT:
            return Preparation(final.decision.action.value, final.decision.reason)
        body = {"protocol": "SYMPHONY_G62_PREPARED_PLAN_V1", "mode": "OFF", "repository": self.repository,
            "target_branch": self.target_branch, "expected_target_head": target.head,
            "candidate_commit": candidate.commit, "candidate_tree": candidate.tree,
            "result_digest": manifest["result_digest"], "source_digest": inventory_digest(source.files),
            "scope_digest": manifest["scope_digest"], "inspection": final.evidence,
            "object_requests": objects, "single_ref_request": ref,
            "authorized_to_send": False, "real_writes": 0}
        return Preparation("PREPARED_OFF", "verified plan only; external publication unavailable",
                           {**body, "plan_digest": digest(body)})

    def put_candidate(self, *args, **kwargs):
        raise PermissionError("production publication OFF")

    def compare_and_swap(self, *args, **kwargs):
        raise PermissionError("production publication OFF")

    def execute(self, *args, **kwargs):
        raise PermissionError("production publication OFF")
