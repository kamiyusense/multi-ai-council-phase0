"""Step 7 bounded LIVE proof for the durable lane ``chatgpt-semi-auto`` (publish half).

STATIC module: importing or testing it performs no network I/O. The only live
effects happen when the workflow injects real ports; every port is injected.

Split of the proof:
- carrier half (existing, unchanged): one command file on the carrier branch makes
  the existing carrier workflow create ONE Jules session (POST 1) and read its
  create time back once (GET 1).
- publish half (this module): exactly ONE fresh Jules GET (GET 2), then the real
  authenticators, RuntimeTransitionPublisher, durable collector, lane-scoped
  registration check and the pre-adoption gate, all bound to the exact lane id.

Totals for the whole proof: POST 1, GET 2, authority dispatch 1 (done before this
half, by a human), retry 0, fallback disabled. Nothing here can raise a limit.

This module never writes the production registry, Issue #33, the default branch,
or merges anything. READY_FOR_HUMAN_APPROVAL never authorizes a registry write.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .control_tower_durable_collector import ControlTowerDurableCollector
from .control_tower_registration import assess_lane_registration_readiness
from .github_oidc_proof_policy_cli import SF8_AUTHORITY_PROFILE, SF8_PROFILE
from .jules_direct_readback_authenticator import JulesDirectReadbackAuthenticator
from .jules_provider_readback_candidate import (
    bind_jules_active_provider_readback,
    prepare_jules_provider_readback_candidate,
)
from .jules_provider_verification_source import prepare_jules_provider_verification_source
from .loop_owner_authority import AuthorityGrantGitHubBackend, DurableOwnerAuthority, grant_for_event
from .oidc_workflow_execution import (
    AuthorityIssuerPolicy,
    OidcBoundAuthorityAuthenticator,
    OidcBoundProviderAuthenticator,
    verify_oidc_workflow_execution,
)
from .recorded_live_evidence import authority_run_is_fresh, payload_digest
from .runtime_state_initializer import RuntimeStateInitializer
from .runtime_transition_coordinator import RuntimeTransitionPublisher
from .runtime_verifier_sources import SourceBoundAuthorityGrantVerifier, SourceBoundProviderVerifier
from .semiauto_stable_identity import prepare_adopted_current_semiauto_acquire
from .sf8_readiness import CheckResult, assess_pre_adoption_readiness

REPOSITORY = "kamiyusense/multi-ai-council-phase0"
LANE_ID = "chatgpt-semi-auto"
OWNER_ACTOR_ID = "20355232"
FORBIDDEN_SESSION_IDS = frozenset({
    "301196275118188780",  # old Session 132: GET budget exhausted
    "5943440322658150300",  # proof 2 session: GET budget exhausted and a publish already read it by mistake
    "11944164406087664763",  # proof 3 session: closed UNKNOWN, never read again
    "569271609782168660",  # proof 4 session: closed UNKNOWN (provider COMPLETED), never read again
})
RESERVED_AUTHORITY_RUNS = frozenset({"37031275812"})  # reserved for the adoption record
PROVIDER_OIDC_RUN_ID = "36981004299"  # finished SF-8 OIDC proof run: workflow-identity anchor
ALLOWED_PATH = "docs/evidence/signal-active-proof-5/PROOF.md"
ALLOWED_CONTENT = "signal active proof 5\n"
ACTIVE_RAW_STATES = frozenset({"QUEUED", "PLANNING", "IN_PROGRESS", "RUNNING"})
DATA_RECORD_DIR = "docs/evidence/signal-active-proof-5"
TERMINAL_RECEIPT_PATH = f"{DATA_RECORD_DIR}/live-terminal-receipt.json"
BOUND_PLAN_PATH = f"{DATA_RECORD_DIR}/plan.bound.json"
ATTEMPT_MARKER_PATH = f"{DATA_RECORD_DIR}/live-attempt-marker.json"
EVIDENCE_PATH = f"{DATA_RECORD_DIR}/live-proof-evidence.json"
# Whole-proof limits. The carrier half has already used its share when this half starts.
LIMITS = {"jules_post": 1, "jules_get": 2, "authority_dispatch": 1, "retry": 0}
CARRIER_SHARE = {"jules_post": 1, "jules_get": 1}
_DIGITS = re.compile(r"^[0-9]{1,24}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class LiveProofError(Exception):
    """A fail-closed stop. ``code`` is a stable machine-readable reason."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class Clock(Protocol):
    def now(self) -> str: ...


class TargetReader(Protocol):
    def read_target(self, repository: str, pr_number: int) -> dict[str, Any] | None: ...


class BranchReader(Protocol):
    def read_branch(self, repository: str, branch: str) -> dict[str, str] | None:
        """Return {"head": <sha>, "tree": <sha>} or None."""


class ActiveSessionReader(Protocol):
    def read_active_session(self, session_id: str, *, expected_branch: str) -> dict[str, Any]:
        """One bounded Jules GET (include_activities=false). Sanitized dict out."""


class AuthorityEvidenceLoader(Protocol):
    def load(self, run_id: str) -> dict[str, Any] | None: ...


@dataclass
class LiveCounters:
    """Counts what this half did. Totals add the carrier half's fixed share."""

    jules_get: int = 0
    jules_post: int = 0
    authority_dispatch: int = 0
    retry: int = 0
    events: list[str] = field(default_factory=list)

    def total(self, name: str) -> int:
        return getattr(self, name) + CARRIER_SHARE.get(name, 0)

    def spend(self, name: str) -> None:
        if name not in LIMITS or name == "retry":
            raise LiveProofError("BUDGET_UNKNOWN_COUNTER", name)
        if self.total(name) + 1 > LIMITS[name]:
            raise LiveProofError("BUDGET_EXCEEDED", name)
        setattr(self, name, getattr(self, name) + 1)
        self.events.append(name)

    def as_dict(self) -> dict[str, Any]:
        return {
            "this_half": {"jules_post": self.jules_post, "jules_get": self.jules_get,
                          "authority_dispatch": self.authority_dispatch, "retry": self.retry},
            "carrier_share": dict(CARRIER_SHARE),
            "whole_proof_total": {"jules_post": self.total("jules_post"), "jules_get": self.total("jules_get"),
                                  "authority_dispatch": self.total("authority_dispatch")},
            "limits": dict(LIMITS),
        }


_FRACTION = re.compile(r"\.[0-9]+(?=Z$|[+-][0-9]{2}:[0-9]{2}$)")


def _floor_provider_times(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Floor the Jules session createTime/updateTime to whole seconds.

    Jules returns sub-second timestamps, while the owner claim, the provider observation
    and the exact-equality check in the direct readback authenticator all use whole
    seconds. Without this the authenticator compares updateTime 00:55:08.43Z with the
    observed_at 00:55:08Z and refuses (proof 2 stopped here with the single GET spent).
    """
    result = dict(snapshot)
    for key in ("createTime", "updateTime"):
        value = result.get(key)
        if isinstance(value, str):
            result[key] = _FRACTION.sub("", value)
    return result


class BudgetedSessionReader:
    """Wraps the single real GET: spends budget BEFORE any I/O, and never repeats."""

    def __init__(self, inner: ActiveSessionReader, counters: LiveCounters):
        self.inner = inner
        self.counters = counters
        self.snapshot: dict[str, Any] | None = None

    def read_active_session(self, session_id: str, *, expected_branch: str) -> dict[str, Any]:
        if self.snapshot is not None:
            raise LiveProofError("SECOND_READ_REFUSED", "the single Jules GET was already spent")
        self.counters.spend("jules_get")
        try:
            snapshot = self.inner.read_active_session(session_id, expected_branch=expected_branch)
        except Exception as exc:  # timeout or transport error: result unknown, never retried
            raise LiveProofError("PROVIDER_READ_UNKNOWN", type(exc).__name__) from None
        if not isinstance(snapshot, dict):
            raise LiveProofError("PROVIDER_READ_UNKNOWN", "non-object response")
        snapshot = _floor_provider_times(snapshot)
        self.snapshot = copy.deepcopy(snapshot)
        return copy.deepcopy(snapshot)


class SnapshotSessionReader:
    """Authenticator-side reader that serves the single already-spent fresh GET."""

    def __init__(self, source: BudgetedSessionReader):
        self.source = source

    def read_session(self, session_id: str) -> dict[str, Any] | None:
        snap = self.source.snapshot
        if snap is None or snap.get("name") != f"sessions/{session_id}":
            return None
        return copy.deepcopy(snap)


class DictSourceReader:
    def __init__(self, value: dict[str, Any]):
        self.value = copy.deepcopy(value)

    def read(self, source_ref: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.value) if self.value.get("source_ref") == source_ref else None


class PrepareOnlyStatusBoundary:
    """Records the status plan; never writes Issue #33 or any display surface."""

    def __init__(self):
        self.plans: list[Any] = []

    def prepare(self, plan: Any) -> None:
        self.plans.append(plan)


@dataclass(frozen=True)
class LiveProofResult:
    status: str  # COMPLETE | STOPPED | UNKNOWN
    stage: str
    code: str
    counters: dict[str, Any]
    evidence: dict[str, Any] | None
    reasons: tuple[str, ...] = ()


def _digits(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGITS.fullmatch(value):
        raise LiveProofError("BAD_IDENTIFIER", field_name)
    return value


def _time(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _zulu(value: str) -> str:
    return _time(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------- plan (pre-POST)


UNBOUND_SHA = "0" * 40
PROVIDER_OIDC_EXPECTED_SHA = "93460dee54948dc6ac3888f4142ab78cd54ce759"
CARRIER_LANE_ID = "J-YELLOW"
CARRIER_LANE_DISPLAY = "💛"
PROOF_TASK_ID = "signal-active-proof-5"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def bind_plan(
    template: dict[str, Any], *, loop_number: int, target_pr: int, target_head: str, target_tree: str,
    now: str, request_minutes: int = 90, authority_max_age_seconds: int = 3600,
) -> dict[str, Any]:
    """Bind the committed template to the real target snapshot at LIVE start.

    Only the human-visible LIVE start uses this. The result is a plan whose request
    and claim are the exact carrier command/claim files; nothing here writes them.
    """
    from datetime import timedelta

    plan = copy.deepcopy(template)
    created = _time(now)
    command_id = f"relay-dev-loop-{int(loop_number)}-{PROOF_TASK_ID}"
    work_branch = f"jules-work/{command_id}"
    plan.update({
        "target_pr": target_pr, "work_branch": work_branch, "expected_target_head": target_head,
        "expected_target_tree": target_tree, "not_before": _iso(created),
        "authority_max_age_seconds": authority_max_age_seconds,
    })
    plan["durable_context"] = {**plan["durable_context"], "target_pr": target_pr,
                               "owner_expires_at": _iso(created + timedelta(hours=2))}
    plan["request"] = {
        **plan["request"], "command_id": command_id, "target_branch": plan["target_branch"],
        "work_branch": work_branch, "expected_target_head": target_head, "expected_target_tree": target_tree,
        "created_at": _iso(created), "expires_at": _iso(created + timedelta(minutes=request_minutes)),
    }
    plan["carrier_claim"] = {
        "schema_version": 3, "loop_number": int(loop_number), "loop_id": str(int(loop_number)),
        "lane_id": CARRIER_LANE_ID, "lane_display": CARRIER_LANE_DISPLAY, "task_id": PROOF_TASK_ID,
        "command_id": command_id, "target_branch": plan["target_branch"], "expected_target_head": target_head,
        "expected_target_tree": target_tree, "work_branch": work_branch, "state": "CLAIMED",
        "claimed_at": _iso(created),
        "duplicate_guard": "one file per loop number; create-only; if exists choose a new number",
        "retry": 0, "fallback": "disabled",
    }
    return plan


def carrier_files(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The two create-only carrier files, keyed by repository path (not written here)."""
    request, claim = plan["request"], plan["carrier_claim"]
    return {
        f"automation/command_bus/jules_api_requests/{request['command_id']}.json": request,
        f"automation/command_bus/loop_id_claims/{claim['loop_number']}.json": claim,
    }


def validate_plan(plan: Any, candidate_registry: Any, *, require_bound: bool = False) -> dict[str, Any]:
    """Static validation of the committed plan and its carrier request/claim.

    The exact lane id must be the adopted-candidate DURABLE lane. A fixture lane,
    a numeric/session-like id, or an id that equals any request identity is refused.
    """
    if not isinstance(plan, dict):
        raise LiveProofError("PLAN_NOT_OBJECT")
    expected_keys = {
        "schema_version", "plan_kind", "repository", "lane_id", "target_branch", "target_pr",
        "work_branch", "expected_target_head", "expected_target_tree", "data_branch",
        "allowed_path", "allowed_content", "authority_max_age_seconds", "not_before",
        "provider_oidc_run_id", "provider_oidc_expected_sha", "durable_context", "request", "carrier_claim",
        "limits", "retry", "fallback", "registry_write_allowed", "human_approval_required",
    }
    if set(plan) != expected_keys:
        raise LiveProofError("PLAN_KEYS_MISMATCH", ",".join(sorted(set(plan) ^ expected_keys)))
    if plan["schema_version"] != 1 or plan["plan_kind"] != "SIGNAL_STEP7_LIVE_PROOF_PLAN":
        raise LiveProofError("PLAN_KIND")
    if plan["repository"] != REPOSITORY:
        raise LiveProofError("WRONG_REPOSITORY")
    lane = plan["lane_id"]
    if lane != LANE_ID:
        raise LiveProofError("WRONG_LANE_ID", str(lane))
    if "fixture" in lane or lane.isdecimal():
        raise LiveProofError("FIXTURE_OR_NUMERIC_LANE")
    entries = [e for e in (candidate_registry or {}).get("loops", []) if e.get("loop_id") == lane] \
        if isinstance(candidate_registry, dict) else []
    if len(entries) != 1 or entries[0].get("identity_state") != "DURABLE":
        raise LiveProofError("LANE_NOT_DURABLE_IN_CANDIDATE_REGISTRY")
    for key in ("target_branch", "work_branch", "data_branch"):
        value = plan[key]
        if not isinstance(value, str) or value in {"main", "master"} or not value:
            raise LiveProofError("DEFAULT_OR_EMPTY_BRANCH", key)
    if len({plan["target_branch"], plan["work_branch"], plan["data_branch"]}) != 3:
        raise LiveProofError("BRANCHES_NOT_DISTINCT")
    for key in ("expected_target_head", "expected_target_tree", "provider_oidc_expected_sha"):
        if not isinstance(plan[key], str) or not _SHA.fullmatch(plan[key]):
            raise LiveProofError("BAD_SHA", key)
    if not isinstance(plan["target_pr"], int) or isinstance(plan["target_pr"], bool) or plan["target_pr"] <= 0:
        raise LiveProofError("BAD_TARGET_PR")
    if plan["allowed_path"] != ALLOWED_PATH or plan["allowed_content"] != ALLOWED_CONTENT:
        raise LiveProofError("ALLOWED_OUTPUT_MISMATCH")
    if require_bound and UNBOUND_SHA in (plan["expected_target_head"], plan["expected_target_tree"]):
        raise LiveProofError("PLAN_NOT_BOUND_TO_TARGET")
    if plan["provider_oidc_expected_sha"] != PROVIDER_OIDC_EXPECTED_SHA:
        raise LiveProofError("WRONG_PROVIDER_OIDC_SHA")
    if plan["limits"] != LIMITS or plan["retry"] != 0 or plan["fallback"] != "disabled":
        raise LiveProofError("LIMITS_MISMATCH")
    if plan["registry_write_allowed"] is not False or plan["human_approval_required"] is not True:
        raise LiveProofError("PLAN_WEAKENS_HUMAN_GATE")
    if plan["provider_oidc_run_id"] != PROVIDER_OIDC_RUN_ID:
        raise LiveProofError("WRONG_PROVIDER_OIDC_RUN")
    request, claim, context = plan["request"], plan["carrier_claim"], plan["durable_context"]
    if request.get("allowed_paths") != [ALLOWED_PATH]:
        raise LiveProofError("REQUEST_ALLOWED_PATHS")
    if ALLOWED_CONTENT.strip() not in str(request.get("prompt", "")):
        raise LiveProofError("REQUEST_PROMPT_MISSING_PROOF_CONTENT")
    for key, expected in (("target_branch", plan["target_branch"]), ("work_branch", plan["work_branch"]),
                          ("expected_target_head", plan["expected_target_head"]),
                          ("expected_target_tree", plan["expected_target_tree"]),
                          ("target_repo", REPOSITORY)):
        if request.get(key) != expected or (key in claim and claim[key] != expected):
            raise LiveProofError("REQUEST_PLAN_MISMATCH", key)
    if context.get("loop_id") != lane or context.get("target_pr") != plan["target_pr"]:
        raise LiveProofError("CONTEXT_PLAN_MISMATCH")
    if lane in {request.get("command_id"), context.get("correlation_id")}:
        raise LiveProofError("LANE_EQUALS_REQUEST_IDENTITY")
    return plan


# ------------------------------------------------------------ publish half (LIVE)


def _fail_unknown(code: str, stage: str, detail: str = "") -> LiveProofError:
    return LiveProofError(code, f"{stage}:{detail}" if detail else stage)


# --- main drift policy (decision: CONSERVATIVE-BOUND, not a weakening of the authority contract) ---
# The authority issuer proves the owner dispatched the issuer at exact main SHA X. Unrelated lanes merge to
# main all the time, so demanding X == current main would waste a LIVE proof on any harmless merge. Instead
# the authority SHA X is bound to BOTH the SHA that is actually executing this code (Y) and current main (Z):
# each of Y and Z must equal X or be strictly AHEAD of X (GitHub compare API) with NO change to a contract
# path in between. A contract path is anything that decides authority, publish or provider handling:
# every workflow, every non-test/non-data automation/command_bus file, and the SF-8 evidence. Any other
# difference, a truncated/unreadable compare, or a missing compare port stops BEFORE any Jules call.
CONTRACT_DRIFT_FREE_PREFIXES = (
    "automation/command_bus/tests/", "automation/command_bus/jules_api_requests/",
    "automation/command_bus/loop_id_claims/",
)
_COMPARE_FILE_CAP = 100  # the CLI asks GitHub for per_page=100: a full page may hide more files, so it fails closed


def is_contract_path(path: Any) -> bool:
    if not isinstance(path, str) or not path:
        return True  # unreadable name: fail closed
    if path.startswith(CONTRACT_DRIFT_FREE_PREFIXES):
        return False
    return path.startswith((".github/", "docs/evidence/signal-sf8/", "automation/command_bus/"))


def check_authority_sha_binding(authority_sha: Any, main_sha: Any, executing_sha: Any, compare_reader: Any) -> None:
    """Raise unless the authority run's SHA is exactly bound to the executing code and to main."""
    if not isinstance(authority_sha, str) or not _SHA.fullmatch(authority_sha) \
            or not isinstance(main_sha, str) or not _SHA.fullmatch(main_sha):
        raise LiveProofError("AUTHORITY_RUN_NOT_EXACT_MAIN")
    if executing_sha is not None and (not isinstance(executing_sha, str) or not _SHA.fullmatch(executing_sha)):
        raise LiveProofError("EXECUTING_SHA_INVALID")
    targets = [sha for sha in dict.fromkeys([main_sha, executing_sha]) if sha and sha != authority_sha]
    if not targets:
        return
    if compare_reader is None:
        raise LiveProofError("AUTHORITY_RUN_NOT_EXACT_MAIN")
    for target in targets:
        result = compare_reader.compare(authority_sha, target)
        if not isinstance(result, dict) or result.get("status") != "ahead" or result.get("behind_by") != 0:
            raise LiveProofError("MAIN_DRIFT_UNVERIFIED")
        files = result.get("files")
        if not isinstance(files, list) or len(files) >= _COMPARE_FILE_CAP or result.get("ahead_by", 0) < 1:
            raise LiveProofError("MAIN_DRIFT_UNVERIFIED")
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("filename"), str):
                raise LiveProofError("MAIN_DRIFT_CONTRACT_CHANGED")
            names = [item["filename"]] + ([item["previous_filename"]] if "previous_filename" in item else [])
            if any(is_contract_path(n) for n in names):
                raise LiveProofError("MAIN_DRIFT_CONTRACT_CHANGED")


def _check_target(plan: dict[str, Any], ports: "PublishPorts") -> dict[str, Any]:
    flat = ports.target_reader.read_target(REPOSITORY, plan["target_pr"])
    if not isinstance(flat, dict) or flat.get("state") != "open" or flat.get("merged") is not False:
        raise LiveProofError("TARGET_PR_NOT_OPEN")
    if flat.get("draft") is not True:
        raise LiveProofError("TARGET_PR_NOT_DRAFT")
    head = flat.get("head") or {}
    if head.get("ref") != plan["target_branch"] or head.get("sha") != plan["expected_target_head"]:
        raise LiveProofError("TARGET_HEAD_MISMATCH")
    for name in ("target_branch", "work_branch"):
        snap = ports.branch_reader.read_branch(REPOSITORY, plan[name])
        if not isinstance(snap, dict) or snap.get("head") != plan["expected_target_head"] \
                or snap.get("tree") != plan["expected_target_tree"]:
            raise LiveProofError("BRANCH_HEAD_OR_TREE_MISMATCH", name)
    return flat


def preflight_publish(*, plan: dict[str, Any], candidate_registry: dict[str, Any], session_id: str,
                      authority_run_id: str, ports: "PublishPorts") -> None:
    """Read-only gate that runs BEFORE the attempt marker, any write and any Jules call.

    Same target, branch and authority-SHA-binding checks as the publish half, so an unrelated
    change (target drift, contract drift on main, a stale or foreign authority run) stops the auto
    path with nothing recorded and nothing spent. It never touches Jules and never writes.
    """
    validate_plan(plan, candidate_registry, require_bound=True)
    claim, request = plan["carrier_claim"], plan["request"]
    if claim.get("lane_id") != CARRIER_LANE_ID or claim.get("task_id") != PROOF_TASK_ID \
            or claim.get("command_id") != request.get("command_id") \
            or not str(request.get("command_id", "")).endswith(f"-{PROOF_TASK_ID}") \
            or claim.get("retry") != 0 or claim.get("fallback") != "disabled":
        raise LiveProofError("CARRIER_IDENTITY_MISMATCH")
    if _digits(session_id, "session_id") in FORBIDDEN_SESSION_IDS:
        raise LiveProofError("OLD_SESSION_FORBIDDEN")
    authority_run_id = _digits(authority_run_id, "authority_run_id")
    if authority_run_id in RESERVED_AUTHORITY_RUNS or authority_run_id == PROVIDER_OIDC_RUN_ID:
        raise LiveProofError("AUTHORITY_RUN_RESERVED_OR_REUSED")
    store, branch = ports.store, plan["data_branch"]
    if store.get(TERMINAL_RECEIPT_PATH, branch) is not None:
        raise LiveProofError("TERMINAL_RECEIPT_EXISTS")
    if store.get(ATTEMPT_MARKER_PATH, branch) is not None:
        raise LiveProofError("ATTEMPT_MARKER_EXISTS")
    _check_target(plan, ports)
    main_snap = ports.branch_reader.read_branch(REPOSITORY, "main")
    run = ports.run_reader.read_run(authority_run_id)
    if not isinstance(run, dict) or not isinstance(main_snap, dict):
        raise LiveProofError("AUTHORITY_RUN_NOT_EXACT_MAIN")
    check_authority_sha_binding(run.get("head_sha"), main_snap.get("head"), ports.executing_sha,
                                ports.compare_reader)


@dataclass
class PublishPorts:
    clock: Clock
    target_reader: TargetReader
    branch_reader: BranchReader
    session_reader: ActiveSessionReader
    run_reader: Any  # ActionsRunReader: fresh REST read of a workflow run
    authority_evidence: AuthorityEvidenceLoader
    provider_oidc_evidence: dict[str, Any]
    store: Any  # GitHubContentsClient (non-default data branch)
    is_live: bool = False  # only the workflow's real ports may set this True
    compare_reader: Any = None  # GitHub compare port; None keeps the strict "authority SHA == main" rule
    executing_sha: str | None = None  # the exact SHA the running workflow code was checked out at


def run_publish_half(
    *, plan: dict[str, Any], candidate_registry: dict[str, Any], session_id: str,
    authority_run_id: str, ports: PublishPorts, counters: LiveCounters | None = None,
) -> LiveProofResult:
    counters = counters or LiveCounters()
    stage = "plan"
    try:
        validate_plan(plan, candidate_registry, require_bound=True)
        session_id = _digits(session_id, "session_id")
        authority_run_id = _digits(authority_run_id, "authority_run_id")
        if session_id in FORBIDDEN_SESSION_IDS:
            raise LiveProofError("OLD_SESSION_FORBIDDEN")
        if authority_run_id in RESERVED_AUTHORITY_RUNS or authority_run_id == PROVIDER_OIDC_RUN_ID:
            raise LiveProofError("AUTHORITY_RUN_RESERVED_OR_REUSED")
        branch, store = plan["data_branch"], ports.store

        stage = "duplicate_guard"
        if store.get(TERMINAL_RECEIPT_PATH, branch) is not None:
            raise LiveProofError("TERMINAL_RECEIPT_EXISTS")
        marker = {"schema_version": 1, "marker_kind": "SIGNAL_STEP7_LIVE_ATTEMPT",
                  "lane_id": LANE_ID, "session_id": session_id, "authority_run_id": authority_run_id,
                  "created_at": ports.clock.now()}
        try:
            store.create(ATTEMPT_MARKER_PATH, canonical_json(marker),
                         "record Step 7 live attempt marker", branch)
        except Exception:
            pass  # result unknown: judged only by readback below, never retried
        read = store.get(ATTEMPT_MARKER_PATH, branch)
        if read is None or json.loads(read.text) != marker:
            raise LiveProofError("ATTEMPT_MARKER_UNVERIFIED_OR_DUPLICATE")

        stage = "target"
        flat = _check_target(plan, ports)

        stage = "authority"
        main_snap = ports.branch_reader.read_branch(REPOSITORY, "main")
        evidence = ports.authority_evidence.load(authority_run_id)
        run = ports.run_reader.read_run(authority_run_id)
        if not isinstance(run, dict) or not isinstance(main_snap, dict):
            raise LiveProofError("AUTHORITY_RUN_NOT_EXACT_MAIN")
        check_authority_sha_binding(run.get("head_sha"), main_snap.get("head"), ports.executing_sha,
                                    ports.compare_reader)
        authority_exec = verify_oidc_workflow_execution(
            evidence=evidence, run_reader=ports.run_reader, profile=SF8_AUTHORITY_PROFILE,
            expected_run_id=authority_run_id, expected_sha=run["head_sha"])
        if authority_exec is None:
            raise LiveProofError("AUTHORITY_EXECUTION_UNVERIFIED")
        now = ports.clock.now()
        if _time(authority_exec.created_at) < _time(plan["not_before"]) or not authority_run_is_fresh(
                authority_exec.created_at, now=now, max_age_seconds=plan["authority_max_age_seconds"]):
            raise LiveProofError("AUTHORITY_RUN_STALE_OR_TOO_OLD")
        if authority_exec.event != "workflow_dispatch" or authority_exec.actor_id != OWNER_ACTOR_ID \
                or authority_exec.triggering_actor_id != OWNER_ACTOR_ID:
            raise LiveProofError("AUTHORITY_ACTOR_OR_EVENT_NOT_ALLOWED")
        provider_exec = verify_oidc_workflow_execution(
            evidence=ports.provider_oidc_evidence, run_reader=ports.run_reader, profile=SF8_PROFILE,
            expected_run_id=PROVIDER_OIDC_RUN_ID, expected_sha=plan["provider_oidc_expected_sha"])
        if provider_exec is None:
            raise LiveProofError("PROVIDER_OIDC_EXECUTION_UNVERIFIED")

        stage = "provider_get"
        reader = BudgetedSessionReader(ports.session_reader, counters)
        session_get = reader.read_active_session(session_id, expected_branch=plan["work_branch"])
        if session_get.get("name") != f"sessions/{session_id}":
            raise _fail_unknown("PROVIDER_SESSION_MISMATCH", stage)
        raw_state = session_get.get("state")
        if raw_state not in ACTIVE_RAW_STATES:
            raise _fail_unknown("PROVIDER_NOT_ACTIVE", stage, str(raw_state))
        github_ctx = (session_get.get("sourceContext") or {}).get("githubRepoContext") or {}
        if github_ctx.get("startingBranch") != plan["work_branch"] or \
                (session_get.get("sourceContext") or {}).get("source") != f"sources/github/{REPOSITORY}":
            raise _fail_unknown("PROVIDER_SOURCE_CONTEXT_MISMATCH", stage)

        stage = "prepare"
        rich_target = {"number": flat["number"], "state": flat["state"], "merged": flat["merged"],
                       "head": flat["head"], "repo": {"full_name": REPOSITORY}}
        prepared = prepare_adopted_current_semiauto_acquire(
            registry=candidate_registry, request=plan["request"], carrier_claim=plan["carrier_claim"],
            durable_context=plan["durable_context"], session_response=session_get,
            target_pr_readback=rich_target, now=_time(now))
        if prepared.owner_event["loop_id"] != LANE_ID:
            raise LiveProofError("PREPARED_LANE_MISMATCH")
        candidate = prepare_jules_provider_readback_candidate(bundle=prepared, session_readback=session_get)
        binding = bind_jules_active_provider_readback(bundle=prepared, candidate=candidate)
        normalized = prepare_jules_provider_verification_source(
            provider_observation_input=binding.provider_observation_input,
            evidence_document=binding.evidence_document, source_receipt=prepared.source_receipt,
            session_id=prepared.acceptance_session_id,
            proof_refs=[*candidate.proof_refs, *provider_exec.proof_refs])
        provider_source = {**normalized, "verification_state": "VERIFIED"}
        inner = JulesDirectReadbackAuthenticator(
            session_reader=SnapshotSessionReader(reader), target_reader=ports.target_reader, clock=ports.clock,
            expected_session_create_time=prepared.owner_event["claimed_at"])
        provider_verifier = SourceBoundProviderVerifier(
            DictSourceReader(provider_source), OidcBoundProviderAuthenticator(execution=provider_exec, inner=inner))

        stage = "durable_prepare"
        initialized = RuntimeStateInitializer(store, branch=branch).create(prepared.initial_state)
        if initialized.status not in {"ACCEPTED", "RECOVERED"}:
            raise _fail_unknown("PREPARED_STATE_UNVERIFIED", stage, initialized.status)
        receipt_ref = prepared.owner_event["source_receipt_ref"]
        if store.get(receipt_ref, branch) is None:
            try:
                store.create(receipt_ref, canonical_json(prepared.source_receipt),
                             "record Step 7 source receipt", branch)
            except Exception:
                pass
            if store.get(receipt_ref, branch) is None:
                raise _fail_unknown("RECEIPT_WRITE_UNVERIFIED", stage)

        stage = "authority_grant"
        authority_id = f"authority-{authority_run_id}"
        grant = grant_for_event(
            prepared.owner_event, authority_id=authority_id, issued_at=authority_exec.created_at,
            verification_ref=f"automation/command_bus/evidence/{LANE_ID}/{authority_id}.json")
        written = AuthorityGrantGitHubBackend(store, branch=branch).write(grant)
        if written.status != "ACCEPTED":
            raise _fail_unknown("GRANT_WRITE_UNVERIFIED", stage, str(written.status))
        authority_source = {
            "schema_version": 1, "verification_kind": "AUTHORITY_GRANT", "source_id": authority_id,
            "source_ref": grant["verification_ref"], "verification_state": "VERIFIED",
            "observed_at": _zulu(now), "expires_at": grant["expires_at"], "authority_id": authority_id,
            "loop_id": prepared.owner_event["loop_id"], "owner_role": prepared.owner_event["owner_role"],
            "holder_id": prepared.owner_event["holder_id"], "generation": prepared.owner_event["generation"],
            "fencing_token": prepared.owner_event["fencing_token"],
            "previous_generation": prepared.owner_event["previous_generation"],
            "event_type": prepared.owner_event["event_type"], "expected_repo": REPOSITORY,
            "expected_pr": prepared.owner_event["expected_pr"],
            "expected_target_head": prepared.owner_event["expected_target_head"],
            "command_id": prepared.owner_event["command_id"], "correlation_id": prepared.owner_event["correlation_id"],
            "proof_refs": list(authority_exec.proof_refs),
        }
        authority_verifier = SourceBoundAuthorityGrantVerifier(
            DictSourceReader(authority_source),
            OidcBoundAuthorityAuthenticator(
                execution=authority_exec,
                policy=AuthorityIssuerPolicy(allowed_actor_ids=frozenset({OWNER_ACTOR_ID})),
                provider_execution=provider_exec))

        stage = "publish"
        status_boundary = PrepareOnlyStatusBoundary()
        publisher = RuntimeTransitionPublisher(
            store, branch=branch, target_reader=_FlatTargetReader(ports.target_reader),
            owner_authority=DurableOwnerAuthority(store, branch=branch, verifier=authority_verifier, clock=ports.clock),
            provider_verifier=provider_verifier, status_boundary=status_boundary, clock=ports.clock)
        published = publisher.publish(binding.transition_request)
        if published.status != "READY":
            raise _fail_unknown(
                "PUBLISH_NOT_READY",
                stage,
                f"{published.status}:{published.stage}:{getattr(published, 'reason', '')}"[:200],
            )

        stage = "collect"
        collected = ControlTowerDurableCollector(
            store, ref=branch, target_reader=_FlatTargetReader(ports.target_reader), clock=ports.clock,
        ).collect_transition(LANE_ID)
        if collected.status != "COLLECTED" or collected.transition is None \
                or collected.transition.projection is None \
                or collected.transition.projection.loop_id != LANE_ID:
            raise _fail_unknown("COLLECT_NOT_EXACT_LANE", stage, str(collected.status))

        stage = "registration"
        lane_registration = assess_lane_registration_readiness(candidate_registry, LANE_ID, collected.transition)
        if lane_registration.status != "READY":
            raise _fail_unknown("LANE_REGISTRATION_NOT_READY", stage, str(lane_registration.status))

        stage = "gate"
        scope = "LIVE" if ports.is_live else "STATIC"
        checks = {
            "owner_authority_authentication": CheckResult("PASS", scope, f"github-actions:run/{authority_run_id}"),
            "provider_authentication": CheckResult("PASS", scope, f"jules-session:{session_id}"),
            "prepared_persistence": CheckResult("PASS", scope, ATTEMPT_MARKER_PATH),
            "canonical_receipt": CheckResult("PASS", scope, receipt_ref),
            "publisher_accepted": CheckResult("PASS", scope, "publisher:READY"),
            "collector_readback": CheckResult("PASS", scope, "collector:COLLECTED"),
            "negative_stale_mismatch_tests": CheckResult("PASS", "STATIC", "test:test_signal_step7_live_proof"),
            "recovery_test": CheckResult("PASS", "STATIC", "test:test_signal_step7_live_proof"),
        }
        gate = assess_pre_adoption_readiness(checks)
        document = _evidence_document(
            plan=plan, prepared=prepared, session_get=session_get, raw_state=raw_state,
            authority_exec=authority_exec, provider_exec=provider_exec, counters=counters,
            gate=gate, lane_registration=lane_registration.status, now=now, scope=scope, session_id=session_id)
        stage = "evidence"
        _write_once(store, EVIDENCE_PATH, document, branch)
        _write_once(store, TERMINAL_RECEIPT_PATH, _terminal_receipt("COMPLETE", "NONE", document, counters), branch)
        return LiveProofResult("COMPLETE", "evidence", "NONE", counters.as_dict(), document)
    except LiveProofError as exc:
        return _stopped(stage, exc, counters, plan, ports)
    except Exception as exc:  # unexpected: fail closed, never retried
        return _stopped(stage, LiveProofError("UNEXPECTED", type(exc).__name__), counters, plan, ports)


class _FlatTargetReader:
    """Publisher/collector want a flat target; the rich readback has the same facts."""

    def __init__(self, inner: TargetReader):
        self.inner = inner

    def read_target(self, repository: str, pr_number: int) -> dict[str, Any] | None:
        rich = self.inner.read_target(repository, pr_number)
        if not isinstance(rich, dict):
            return None
        return {"repo": repository, "pr": pr_number, "head": (rich.get("head") or {}).get("sha"),
                "state": rich.get("state"), "merged": rich.get("merged")}


def _write_once(store: Any, path: str, document: dict[str, Any], branch: str) -> None:
    text = canonical_json(document)
    try:
        store.create(path, text, f"record Step 7 live {path.rsplit('/', 1)[-1]}", branch)
    except Exception:
        pass
    read = store.get(path, branch)
    if read is None or json.loads(read.text) != document:
        raise LiveProofError("RECORD_WRITE_UNVERIFIED", path)


def _evidence_document(
    *, plan: dict[str, Any], prepared: Any, session_get: dict[str, Any], raw_state: str,
    authority_exec: Any, provider_exec: Any, counters: LiveCounters, gate: Any,
    lane_registration: str, now: str, scope: str, session_id: str,
) -> dict[str, Any]:
    event = prepared.owner_event
    document = {
        "schema_version": 1, "evidence_kind": "SIGNAL_STEP7_LIVE_PROOF_EVIDENCE", "scope": scope,
        "repository": REPOSITORY, "lane_id": LANE_ID, "session_id": session_id,
        "create_time": session_get.get("createTime"), "update_time": session_get.get("updateTime"),
        "observed_at": now, "provider_raw_state": raw_state, "canonical_runtime_state": "RUNNING",
        "starting_branch": plan["work_branch"], "work_branch": plan["work_branch"],
        "target_branch": plan["target_branch"], "target_head": plan["expected_target_head"],
        "target_tree": plan["expected_target_tree"], "target_pr": plan["target_pr"],
        "provider_source_context": session_get.get("sourceContext"),
        "allowed_path": plan["allowed_path"], "allowed_content": plan["allowed_content"],
        "owner_generation": event["generation"], "fencing_token": event["fencing_token"],
        "authority_run_id": authority_exec.run_id, "authority_evidence_sha256": authority_exec.evidence_sha256,
        "provider_oidc_run_id": provider_exec.run_id,
        "source_receipt_ref": event["source_receipt_ref"], "evidence_refs": list(event["evidence_refs"]),
        "counters": counters.as_dict(), "retry": 0, "fallback": "disabled",
        "lane_registration": lane_registration,
        "pre_adoption_gate": {
            "status": gate.status, "reasons": list(gate.reasons),
            "human_approval_required": gate.human_approval_required,
            "registry_write_allowed": gate.registry_write_allowed,
        },
        "production_registry_written": False, "issue33_written": False, "merged": False,
    }
    document["evidence_payload_sha256"] = payload_digest(document, "evidence_payload_sha256")
    return document


_SENSITIVE_FAILURE_MARKERS = (
    "authorization", "bearer", "token", "secret", "api_key", "api-key",
    "x-goog-api-key", "ghp_", "github_pat_",
)


def safe_failure_detail(value: Any) -> str | None:
    """Bounded diagnostic text for durable receipts/artifacts; never preserve likely secrets."""
    if value is None:
        return None
    text = " ".join(str(value).split())[:200]
    if not text:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _SENSITIVE_FAILURE_MARKERS):
        return "REDACTED"
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in text):
        return "REDACTED"
    return text


def _terminal_receipt(status: str, code: str, document: dict[str, Any] | None,
                      counters: LiveCounters, *, failure_stage: str | None = None,
                      failure_detail: str | None = None) -> dict[str, Any]:
    receipt = {
        "schema_version": 1, "receipt_kind": "SIGNAL_STEP7_LIVE_TERMINAL_RECEIPT", "lane_id": LANE_ID,
        "status": status, "code": code, "counters": counters.as_dict(),
        "evidence_payload_sha256": (document or {}).get("evidence_payload_sha256"),
        "failure_stage": failure_stage,
        "failure_detail": safe_failure_detail(failure_detail),
        "additional_jules_get_allowed": False, "additional_jules_post_allowed": False,
        "rerun_allowed": False,
    }
    receipt["receipt_payload_sha256"] = payload_digest(receipt, "receipt_payload_sha256")
    return receipt


def _stopped(stage: str, exc: LiveProofError, counters: LiveCounters, plan: Any, ports: PublishPorts) -> LiveProofResult:
    """Stop without retry. A terminal receipt blocks reruns, except when the stop was
    caused by an existing terminal receipt/attempt marker (never overwritten)."""
    unknown = stage in {"provider_get", "prepare", "durable_prepare", "authority_grant", "publish", "collect",
                        "registration", "evidence"} or exc.code.endswith("UNKNOWN")
    status = "UNKNOWN" if unknown else "STOPPED"
    if exc.code not in {"TERMINAL_RECEIPT_EXISTS", "ATTEMPT_MARKER_UNVERIFIED_OR_DUPLICATE"} \
            and stage not in {"plan"} and isinstance(plan, dict) and plan.get("data_branch"):
        try:
            _write_once(
                ports.store,
                TERMINAL_RECEIPT_PATH,
                _terminal_receipt(
                    status,
                    exc.code,
                    None,
                    counters,
                    failure_stage=stage,
                    failure_detail=str(exc),
                ),
                plan["data_branch"],
            )
        except Exception:
            pass  # terminal receipt unverified: the stop result below is the only record
    return LiveProofResult(status, stage, exc.code, counters.as_dict(), None, (str(exc),))


def assess_output_readback(
    output: dict[str, Any], *, evidence: dict[str, Any], previous: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Fail-closed reasons for the later GitHub readback of the Jules output PR (empty = acceptable).

    Used after the proof, never to spend provider budget: it only reads GitHub data. The
    output must change exactly the one allowed file with the exact allowed content, stay
    unmerged, hang off the isolated work branch at the expected target head, and not drift
    from an earlier readback of the same pull request.
    """
    reasons: list[str] = []
    try:
        if output.get("changed_files") != [evidence["allowed_path"]]:
            reasons.append("unexpected changed paths")
        if output.get("changed_file_content") != evidence["allowed_content"]:
            reasons.append("proof content is not the exact allowed content")
        if output.get("merged") is not False:
            reasons.append("output pull request is merged")
        if output.get("base_branch") != evidence["work_branch"]:
            reasons.append("output base is not the isolated work branch")
        if output.get("base_sha") != evidence["target_head"]:
            reasons.append("output base is not the expected target head")
        if output.get("head_branch") != f"{evidence['work_branch']}-{evidence['session_id']}":
            reasons.append("output branch is not the Jules branch of this session")
        if output.get("head_sha") in (None, evidence["target_head"]):
            reasons.append("output head equals base or is missing")
        if previous is not None:
            for key in ("pull_request", "head_sha", "changed_files", "changed_file_content", "merged"):
                if previous.get(key) != output.get(key):
                    reasons.append(f"output drifted: {key}")
    except (KeyError, TypeError, AttributeError):
        reasons.append("output or evidence malformed")
    return tuple(reasons)


def plan_digest(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(plan).encode("utf-8")).hexdigest()
