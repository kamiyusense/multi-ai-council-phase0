"""Independent CI attestation input: read-only, pinned verifier workflow.

Hashes on worker-authored records establish integrity, not verifier identity.
This reader accepts records only from an independently fetched successful run,
with a pinned verifier workflow, successful required steps and a hash-matched
artifact archive. No candidate tests/providers or GraphQL writes run here.
Archive download is an injected GET-only capability, separate from model work.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass

from .symphony_result_manifest import DIGEST, SHA, digest, safe_path
from .symphony_result_verification import assemble_verification, DEFAULT_REQUIRED


class AttestationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CIContract:
    repository: str
    run_id: int
    candidate_commit: str
    workflow_path: str
    workflow_sha256: str
    artifact_name: str
    verifier_id: str
    required_steps: tuple[str, ...] = ("Independent syntax", "Independent tests", "Independent secret scan")


class CIArtifactVerificationReader:
    def __init__(self, http, contract: CIContract, *, archive_get, trusted_verifiers, worker_run_id):
        if (type(contract.run_id) is not int or contract.run_id <= 0
                or not SHA.fullmatch(contract.candidate_commit or "")
                or not DIGEST.fullmatch(contract.workflow_sha256 or "")
                or not contract.workflow_path.startswith(".github/workflows/")
                or not contract.workflow_path.endswith((".yml", ".yaml"))
                or not safe_path(contract.workflow_path)
                or ".." in contract.workflow_path or "?" in contract.workflow_path
                or not contract.required_steps):
            raise ValueError("independently configured exact CI contract required")
        self.http, self.contract, self.archive_get = http, contract, archive_get
        self.trusted_verifiers, self.worker_run_id = dict(trusted_verifiers), worker_run_id

    def _get(self, suffix):
        status, data = self.http.request("GET", "repos/" + self.contract.repository + "/" + suffix)
        if status != 200 or not isinstance(data, dict):
            raise AttestationUnavailable("CI GET unavailable")
        return data

    def _pages(self, suffix, key):
        items = []
        for page in range(1, 11):
            body = self._get(suffix + f"?per_page=100&page={page}")
            nodes = body.get(key)
            if not isinstance(nodes, list) or type(body.get("total_count")) is not int:
                raise AttestationUnavailable("CI listing incomplete")
            items.extend(nodes)
            if len(items) == body["total_count"]:
                return items
            if not nodes or len(items) > body["total_count"]:
                break
        raise AttestationUnavailable("CI listing incomplete/over limit")

    def read(self, manifest, *, required=DEFAULT_REQUIRED):
        c = self.contract
        run = self._get(f"actions/runs/{c.run_id}")
        if (run.get("id") != c.run_id or run.get("head_sha") != c.candidate_commit
                or run.get("repository", {}).get("full_name") != c.repository
                or run.get("path") != c.workflow_path or run.get("status") != "completed"
                or run.get("conclusion") != "success" or type(run.get("run_attempt")) is not int):
            raise AttestationUnavailable("CI identity/head/workflow/result not verified")
        workflow = self._get(f"contents/{c.workflow_path}?ref={c.candidate_commit}")
        try:
            raw = base64.b64decode(workflow["content"].replace("\n", ""), validate=True)
        except (KeyError, ValueError, TypeError) as exc:
            raise AttestationUnavailable("verifier workflow bytes unavailable") from exc
        if workflow.get("encoding") != "base64" or hashlib.sha256(raw).hexdigest() != c.workflow_sha256:
            raise AttestationUnavailable("verifier workflow differs from independent pin")
        jobs = self._pages(f"actions/runs/{c.run_id}/attempts/{run['run_attempt']}/jobs", "jobs")
        # All required checks must run together in a successful verifier job;
        # a skipped/failing check cannot borrow PASS from another job.
        qualified = [j for j in jobs if j.get("conclusion") == "success" and j.get("head_sha") == c.candidate_commit and all(
            sum(s.get("name") == name and s.get("status") == "completed" and s.get("conclusion") == "success"
                for s in j.get("steps", [])) == 1 for name in c.required_steps)]
        if len(qualified) != 1:
            raise AttestationUnavailable("required independent CI steps unavailable/ambiguous")
        artifacts = self._pages(f"actions/runs/{c.run_id}/artifacts", "artifacts")
        chosen = [a for a in artifacts if a.get("name") == c.artifact_name and a.get("expired") is False]
        if len(chosen) != 1:
            raise AttestationUnavailable("independent attestation artifact missing/ambiguous")
        artifact = chosen[0]
        if (type(artifact.get("id")) is not int or artifact.get("workflow_run", {}).get("head_sha") != c.candidate_commit
                or artifact.get("workflow_run", {}).get("id") != c.run_id):
            raise AttestationUnavailable("artifact run/head binding mismatch")
        archive = self.archive_get(c.repository, artifact["id"])
        if (type(archive) is not bytes or len(archive) > 16 * 1024 * 1024
                or artifact.get("digest") != "sha256:" + hashlib.sha256(archive).hexdigest()):
            raise AttestationUnavailable("artifact archive bytes not authenticated")
        try:
            with zipfile.ZipFile(io.BytesIO(archive)) as z:
                names = z.namelist()
                if names.count("attestation.json") != 1 or z.getinfo("attestation.json").file_size > 2 * 1024 * 1024:
                    raise ValueError("attestation member missing/too large/duplicate")
                attestation = json.loads(z.read("attestation.json"))
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise AttestationUnavailable("attestation archive invalid") from exc
        expected = {"protocol": "SYMPHONY_G62_CI_ATTESTATION_V1", "run_id": c.run_id,
            "run_attempt": run["run_attempt"], "job_id": qualified[0].get("id"), "candidate_commit": c.candidate_commit,
            "result_digest": manifest["result_digest"], "source_digest": manifest["source_digest"],
            "scope_digest": manifest["scope_digest"], "expected_target_head": manifest["expected_target_head"]}
        if (not isinstance(attestation, dict) or any(attestation.get(k) != v for k, v in expected.items())
                or digest({k: v for k, v in attestation.items() if k != "attestation_digest"}) != attestation.get("attestation_digest")):
            raise AttestationUnavailable("attestation result/source/scope/head binding mismatch")
        records = attestation.get("records")
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            raise AttestationUnavailable("attestation records malformed")
        if any(r.get("verifier_id") != c.verifier_id for r in records if r.get("verifier_kind") == "EXTERNAL_CI"):
            raise AttestationUnavailable("attestation external verifier identity mismatch")
        bundle = assemble_verification(manifest, records, trusted_verifiers=self.trusted_verifiers,
                                        worker_run_id=self.worker_run_id, required=required)
        if not bundle.evidence.trustworthy or not all(bundle.evidence.checks.get(k) is True for k in required):
            raise AttestationUnavailable("attestation checks are not independently PASS")
        return bundle
