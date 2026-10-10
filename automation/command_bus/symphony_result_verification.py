"""G6.1 independent result verification: syntax / tests / secret-scan contract.

Produces the G6 ``VerificationEvidence`` the inspector already requires. Each
check is a sealed record bound to result_digest, source_digest,
expected_target_head and scope_digest. A record is accepted only from a
trusted verifier that is not the worker, and only from a verifier *kind*
allowed for that check:

| check               | allowed kinds                                   |
|---------------------|-------------------------------------------------|
| syntax              | G61_BUILTIN_SYNTAX (parse only), EXTERNAL_CI    |
| tests               | EXTERNAL_CI (worker code is never run here)     |
| secret_scan         | EXTERNAL_CI (a full scanner, e.g. CI job)       |
| secret_pattern_scan | G61_BUILTIN_SECRET_PATTERNS                     |

The built-in syntax check only parses bytes (``ast.parse``/``json``/``tomllib``;
nothing is executed). The built-in pattern scan is a supplementary detector and can
never satisfy ``secret_scan`` on its own. Conflicting duplicates, unknown
verifiers, binding mismatches or missing checks produce an untrusted/failed
evidence object, so the inspector holds; nothing defaults to PASS.
"""
from __future__ import annotations

import ast
import json
import re
import tomllib
from dataclasses import dataclass
from typing import Iterable, Mapping

from .symphony_result_manifest import (DIGEST, ID, SHA, SourceResult, VerificationEvidence, canonical,
                                       digest)

PROTOCOL = "SYMPHONY_G61_VERIFICATION_V1"
CHECK_KINDS = {
    "syntax": frozenset({"G61_BUILTIN_SYNTAX", "EXTERNAL_CI"}),
    "tests": frozenset({"EXTERNAL_CI"}),
    "secret_scan": frozenset({"EXTERNAL_CI"}),
    "secret_pattern_scan": frozenset({"G61_BUILTIN_SECRET_PATTERNS"}),
}
DEFAULT_REQUIRED = ("syntax", "tests", "secret_scan", "secret_pattern_scan")
RECORD_KEYS = {"protocol", "check", "verifier_id", "verifier_kind", "result_digest", "source_digest",
               "expected_target_head", "scope_digest", "status", "details_digest", "observed_at", "record_digest"}
MAX_PARSE_BYTES = 2 * 1024 * 1024
SECRET_PATTERNS = {
    "github_token": rb"gh[pousr]_[A-Za-z0-9_]{20,}",
    "github_pat": rb"github_pat_[A-Za-z0-9_]{20,}",
    "openai_style_key": rb"sk-[A-Za-z0-9_-]{20,}",
    "aws_access_key": rb"(?:AKIA|ASIA)[0-9A-Z]{16}",
    "slack_token": rb"xox[abprs]-[A-Za-z0-9-]{10,}",
    "google_api_key": rb"AIza[0-9A-Za-z_-]{35}",
    "private_key": rb"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----",
}
_SECRET = re.compile(b"|".join(b"(?:" + p + b")" for p in SECRET_PATTERNS.values()))


def check_ref(check: str) -> str:
    return "sym-g61-check:" + check


def manifest_check_refs(required: Iterable[str] = DEFAULT_REQUIRED) -> list[str]:
    """Refs the result manifest predeclares; records bind back via digests."""
    return [check_ref(c) for c in required]


def _changed_entries(manifest: dict, source: SourceResult):
    for m in manifest["mutations"]:
        entry = source.files.get(m["path"])
        if entry is not None:
            yield m["path"], entry


def builtin_syntax(manifest: dict, source: SourceResult, *, verifier_id: str, observed_at: str) -> tuple[dict, dict]:
    """Parse-only syntax check of changed text files."""
    failures = []
    for path, entry in _changed_entries(manifest, source):
        if entry.kind != "blob":
            continue
        try:
            if len(entry.data) > MAX_PARSE_BYTES:
                raise ValueError("too large to parse")
            text = entry.data.decode("utf-8")
            if path.endswith(".py"):
                ast.parse(text, filename=path)
            elif path.endswith(".json"):
                json.loads(text)
            elif path.endswith(".toml"):
                tomllib.loads(text)
        except (SyntaxError, ValueError, UnicodeDecodeError, RecursionError, MemoryError) as exc:
            failures.append({"path": path, "error": type(exc).__name__})
    details = {"checked": sorted(p for p, _ in _changed_entries(manifest, source)), "failures": failures}
    return _record(manifest, "syntax", verifier_id, "G61_BUILTIN_SYNTAX", "FAIL" if failures else "PASS", details, observed_at), details


def builtin_secret_patterns(manifest: dict, source: SourceResult, *, verifier_id: str, observed_at: str) -> tuple[dict, dict]:
    """Supplementary known-pattern scan over changed bytes and the manifest."""
    hits = sorted({path for path, entry in _changed_entries(manifest, source) if _SECRET.search(entry.data)}
                  | ({"<manifest>"} if _SECRET.search(canonical(manifest).encode()) else set()))
    details = {"patterns": sorted(SECRET_PATTERNS), "hit_paths": hits}  # paths only, never matched bytes
    return _record(manifest, "secret_pattern_scan", verifier_id, "G61_BUILTIN_SECRET_PATTERNS",
                   "FAIL" if hits else "PASS", details, observed_at), details


def _record(manifest, check, verifier_id, kind, status, details, observed_at) -> dict:
    if status not in {"PASS", "FAIL"} or check not in CHECK_KINDS or not ID.fullmatch(verifier_id or ""):
        raise ValueError("invalid verification record")
    body = {"protocol": PROTOCOL, "check": check, "verifier_id": verifier_id, "verifier_kind": kind,
        "result_digest": manifest["result_digest"], "source_digest": manifest["source_digest"],
        "expected_target_head": manifest["expected_target_head"], "scope_digest": manifest["scope_digest"],
        "status": status, "details_digest": digest(dict(details)), "observed_at": observed_at}
    return {**body, "record_digest": digest(body)}


def external_record(manifest: dict, *, check: str, verifier_id: str, status: str, details: Mapping, observed_at: str) -> dict:
    """Shape an attestation from an external runner (e.g. a CI job on the
    candidate). The runner, not the worker, decides status."""
    return _record(manifest, check, verifier_id, "EXTERNAL_CI", status, details, observed_at)


@dataclass(frozen=True)
class VerificationBundle:
    evidence: VerificationEvidence
    records_digest: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"protocol": PROTOCOL, "trustworthy": self.evidence.trustworthy, "checks": dict(self.evidence.checks),
                "evidence_refs": list(self.evidence.evidence_refs), "records_digest": self.records_digest,
                "reasons": list(self.reasons)}


def assemble_verification(manifest: dict, records: Iterable[dict], *, trusted_verifiers: Mapping[str, str],
                          worker_run_id: str, required: Iterable[str] = DEFAULT_REQUIRED) -> VerificationBundle:
    """``trusted_verifiers`` maps verifier_id -> verifier_kind (configured, not
    taken from the record). Returns trustworthy=False whenever any doubt exists."""
    required = tuple(required)
    records = list(records)
    reasons: list[str] = []
    checks: dict[str, bool] = {}
    seen: dict[str, str] = {}
    binding = {k: manifest[k] for k in ("result_digest", "source_digest", "expected_target_head", "scope_digest")}
    for record in records:
        try:
            if type(record) is not dict or set(record) != RECORD_KEYS or record["protocol"] != PROTOCOL:
                raise ValueError("record schema")
            if digest({k: v for k, v in record.items() if k != "record_digest"}) != record["record_digest"]:
                raise ValueError("record digest")
            if {k: record[k] for k in binding} != binding:
                raise ValueError("record bound to another result/head/scope")
            check, vid, kind = record["check"], record["verifier_id"], record["verifier_kind"]
            if vid == worker_run_id or trusted_verifiers.get(vid) != kind or kind not in CHECK_KINDS.get(check, ()):
                raise ValueError("verifier not trusted for check")
            if not DIGEST.fullmatch(record["details_digest"]):
                raise ValueError("details digest")
            if check in seen and seen[check] != record["status"]:
                raise ValueError("conflicting duplicate check")
            seen[check] = record["status"]
            checks[check] = checks.get(check, True) and record["status"] == "PASS"
        except (KeyError, TypeError, ValueError) as exc:
            reasons.append(str(exc))
    missing = [c for c in required if c not in checks]
    if missing:
        reasons.append("missing checks: " + ",".join(missing))
    trustworthy = not reasons and SHA.fullmatch(manifest["expected_target_head"]) is not None
    refs = tuple(check_ref(c) for c in required)
    evidence = VerificationEvidence(binding["result_digest"], binding["source_digest"], binding["expected_target_head"],
                                    binding["scope_digest"], checks, refs, trustworthy)
    return VerificationBundle(evidence, digest(sorted((r.get("record_digest", "") if type(r) is dict else "") for r in records)),
                              tuple(reasons))
