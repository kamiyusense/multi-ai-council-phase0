"""Durable, fenced Claude AUTO -> Jules dispatch over the existing carrier route.

The dispatcher reuses the current Jules semi-auto carrier contract unchanged:
schema-v3 Loop claim, isolated ``jules-work/<command_id>`` branch, one
append-only ``JULES_CHAT_SEMIAUTO_V2`` command file (whose push triggers the
existing single-submit workflow), plus the existing
``CLAUDE_AUTO_ORIGIN_BINDING_V1`` companion record.

Everything that will be written is computed once into an immutable *dispatch
intent* record.  Each step is create-only with independent readback; an
existing identical record is recovered, a different one blocks, and an
ambiguous write is read back, never resent.  A new Claude session can resume a
half-finished dispatch from the intent alone.

Live use is fail-closed: unless the policy carries an explicit human
authorization, ``dispatch`` performs no write at all.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from .claude_jules_campaign import MAX_CAMPAIGN_ROUNDS

from .claude_jules_origin_binding import validate_binding_record
from .claude_jules_origin_binding_store import ClaudeJulesOriginBindingStore
from .github_backend import GitHubContentsClient
from .jules_carrier_current import jules_api_request as carrier_request_validator
from .jules_carrier_current import loop_id_claim as carrier_claim_validator

POLICY_PROFILE = "CLAUDE_AUTO_JULES_POLICY_V1"
INTENT_PROFILE = "CLAUDE_AUTO_DISPATCH_INTENT_V1"
RECEIPT_PROFILE = "CLAUDE_AUTO_DISPATCH_RECEIPT_V1"
EVIDENCE_ROOT = "automation/command_bus/evidence"
CLAIMS_DIR = "automation/command_bus/loop_id_claims"
COMMANDS_DIR = "automation/command_bus/jules_api_requests"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_POLICY_KEYS = {
    "schema_version", "profile", "controller_id", "holder_id", "target_repo",
    "default_branch", "carrier_branch", "data_branch", "allowed_target_branches",
    "allowed_lane_ids", "expected_pr", "max_rounds", "live_dispatch_authorization",
}
_AUTH_KEYS = {"approved_by", "approval_ref", "scope", "max_dispatches", "expires_at"}


@dataclass(frozen=True)
class DispatchResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None


class GitRefClient(Protocol):
    """Minimal git ref transport implemented by the connected GitHub controller."""

    def get_branch_head(self, branch: str) -> str | None: ...
    def get_commit_tree(self, sha: str) -> str | None: ...
    def create_branch(self, branch: str, sha: str) -> Any: ...


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _time(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate the Claude AUTO controller policy (grants are explicit lists)."""
    if not isinstance(policy, dict) or set(policy) != _POLICY_KEYS:
        raise ValueError("policy keys mismatch")
    if policy["schema_version"] != 1 or policy["profile"] != POLICY_PROFILE:
        raise ValueError("unsupported policy profile")
    if policy["controller_id"] != "claude-auto":
        raise ValueError("policy controller must be claude-auto")
    for key in ("holder_id", "target_repo", "default_branch", "carrier_branch", "data_branch"):
        if not isinstance(policy[key], str) or not policy[key]:
            raise ValueError(f"policy {key} required")
    if policy["data_branch"] == policy["default_branch"] or policy["carrier_branch"] == policy["default_branch"]:
        raise ValueError("policy branches must be non-default")
    for key in ("allowed_target_branches", "allowed_lane_ids"):
        if not isinstance(policy[key], list) or len(set(policy[key])) != len(policy[key]):
            raise ValueError(f"policy {key} must be a unique list")
    if policy["default_branch"] in policy["allowed_target_branches"] or policy["carrier_branch"] in policy["allowed_target_branches"]:
        raise ValueError("default/carrier branch can never be a Claude AUTO target")
    for lane in policy["allowed_lane_ids"]:
        carrier_claim_validator.lane_display_for(lane)
    if isinstance(policy["expected_pr"], bool) or not isinstance(policy["expected_pr"], int) or policy["expected_pr"] < 1:
        raise ValueError("policy expected_pr must be positive")
    if isinstance(policy["max_rounds"], bool) or not isinstance(policy["max_rounds"], int) or not 1 <= policy["max_rounds"] <= MAX_CAMPAIGN_ROUNDS:
        raise ValueError("policy max_rounds must be 1..1000")
    auth = policy["live_dispatch_authorization"]
    if auth is not None:
        if not isinstance(auth, dict) or set(auth) != _AUTH_KEYS:
            raise ValueError("live dispatch authorization malformed")
        for key in ("approved_by", "approval_ref", "scope"):
            if not isinstance(auth[key], str) or not auth[key]:
                raise ValueError(f"authorization {key} required")
        if isinstance(auth["max_dispatches"], bool) or not isinstance(auth["max_dispatches"], int) or not 1 <= auth["max_dispatches"] <= 10:
            raise ValueError("authorization max_dispatches must be 1..10 (Loop A total LIVE budget)")
        _time(auth["expires_at"], "authorization expires_at")
    return policy


def live_authorization_problem(policy: dict[str, Any], *, now: str, dispatches_used: int) -> str | None:
    auth = policy["live_dispatch_authorization"]
    if auth is None:
        return "no explicit human live-dispatch authorization in policy"
    if _time(now, "now") >= _time(auth["expires_at"], "authorization expires_at"):
        return "live-dispatch authorization expired"
    if dispatches_used >= auth["max_dispatches"]:
        return "live-dispatch authorization budget exhausted"
    return None


def check_dispatch_authority(
    owner_latest: dict[str, Any] | None, *, policy: dict[str, Any], origin_loop_id: str,
    generation: int | None, now: str,
) -> DispatchResult:
    """Fence a dispatch with the existing durable Loop-owner chain.

    ``owner_latest`` must be the latest event returned by
    ``LoopOwnerGitHubBackend.read_chain`` (which already validated the whole
    append-only chain).  Only a live AUTO lease held by this controller at the
    exact generation may issue commands; SEMI_AUTO ownership is never taken.
    ``generation=None`` checks only that this holder currently owns a live
    lease (used before inspection/adoption writes).
    """
    try:
        if not isinstance(owner_latest, dict):
            return DispatchResult("UNKNOWN", "durable owner chain unavailable")
        if owner_latest.get("loop_id") != origin_loop_id:
            return DispatchResult("BLOCKED", "owner chain belongs to another loop")
        if owner_latest.get("expected_repo") != policy["target_repo"]:
            return DispatchResult("BLOCKED", "owner chain targets another repository")
        if owner_latest.get("owner_role") == "SEMI_AUTO":
            return DispatchResult("BLOCKED", "loop is owned by SEMI_AUTO; do not take over")
        if owner_latest.get("event_type") in {"RELEASE", "TERMINAL"}:
            return DispatchResult("BLOCKED", "owner lease released or terminal")
        if owner_latest.get("owner_role") != "AUTO" or owner_latest.get("holder_id") != policy["holder_id"]:
            return DispatchResult("BLOCKED", "loop is not owned by this Claude AUTO holder")
        current = owner_latest.get("generation")
        if generation is None:
            generation = current  # controller-level check: any live lease held by this holder
        if current != generation or owner_latest.get("fencing_token") != generation:
            return DispatchResult("BLOCKED", f"stale owner generation {generation}; current {current}")
        if owner_latest.get("expected_pr") != policy["expected_pr"]:
            return DispatchResult("BLOCKED", "owner chain targets another PR")
        if _time(owner_latest["claimed_at"], "claimed_at") > _time(now, "now"):
            return DispatchResult("BLOCKED", "owner claim is from the future")
        if _time(now, "now") >= _time(owner_latest["expires_at"], "expires_at"):
            return DispatchResult("BLOCKED", "owner lease expired")
        return DispatchResult("PASS", "current AUTO owner generation verified")
    except (KeyError, TypeError, ValueError) as exc:
        return DispatchResult("UNKNOWN", f"owner fencing unverifiable: {exc}")


def intent_id(origin_loop_id: str, origin_round: int, origin_generation: int, attempt: int) -> str:
    value = f"{origin_loop_id}-r{origin_round}-g{origin_generation}-a{attempt}"
    if not _SAFE_ID.fullmatch(value):
        raise ValueError("unsafe dispatch intent id")
    return value


def intent_path(identifier: str) -> str:
    if not isinstance(identifier, str) or not _SAFE_ID.fullmatch(identifier):
        raise ValueError("unsafe dispatch intent id")
    return f"{EVIDENCE_ROOT}/claude-auto-dispatch-intents/{identifier}.json"


def dispatch_receipt_path(command_id: str) -> str:
    if not isinstance(command_id, str) or not carrier_request_validator.COMMAND_ID_RE.fullmatch(command_id):
        raise ValueError("unsafe command_id")
    return f"{EVIDENCE_ROOT}/claude-auto-dispatch-receipts/{command_id}.json"


def claim_path(loop_id: str) -> str:
    return f"{CLAIMS_DIR}/{carrier_claim_validator.claim_filename(loop_id)}"


def command_path(command_id: str) -> str:
    if not isinstance(command_id, str) or not carrier_request_validator.COMMAND_ID_RE.fullmatch(command_id):
        raise ValueError("unsafe command_id")
    return f"{COMMANDS_DIR}/{command_id}.json"


def build_dispatch_intent(
    *, origin_loop_id: str, origin_round: int, origin_correlation_id: str,
    origin_generation: int, attempt: int, task_id: str, task_spec_sha256: str,
    carrier_request: dict[str, Any], carrier_claim: dict[str, Any],
    origin_binding: dict[str, Any], prepared_at: str,
) -> dict[str, Any]:
    record = {
        "schema_version": 1,
        "profile": INTENT_PROFILE,
        "intent_id": intent_id(origin_loop_id, origin_round, origin_generation, attempt),
        "origin_loop_id": origin_loop_id,
        "origin_round": origin_round,
        "origin_correlation_id": origin_correlation_id,
        "origin_generation": origin_generation,
        "attempt": attempt,
        "task_id": task_id,
        "task_spec_sha256": task_spec_sha256,
        "carrier_request": carrier_request,
        "carrier_claim": carrier_claim,
        "origin_binding": origin_binding,
        "prepared_at": prepared_at,
        "retry": 0,
        "fallback": "disabled",
    }
    record["intent_sha256"] = sha256_of(record)
    return validate_dispatch_intent(record)


def validate_dispatch_intent(record: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "schema_version", "profile", "intent_id", "origin_loop_id", "origin_round",
        "origin_correlation_id", "origin_generation", "attempt", "task_id",
        "task_spec_sha256", "carrier_request", "carrier_claim", "origin_binding",
        "prepared_at", "retry", "fallback", "intent_sha256",
    }
    if not isinstance(record, dict) or set(record) != keys:
        raise ValueError("dispatch intent keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != INTENT_PROFILE:
        raise ValueError("unsupported dispatch intent")
    if record["retry"] != 0 or record["fallback"] != "disabled":
        raise ValueError("dispatch intent retry/fallback mismatch")
    if record["intent_sha256"] != sha256_of({k: v for k, v in record.items() if k != "intent_sha256"}):
        raise ValueError("dispatch intent digest mismatch")
    for key in ("origin_round", "origin_generation", "attempt"):
        if isinstance(record[key], bool) or not isinstance(record[key], int) or record[key] < 1:
            raise ValueError(f"invalid {key}")
    if record["origin_round"] > MAX_CAMPAIGN_ROUNDS:
        raise ValueError("dispatch intent round exceeds finite campaign cap")
    if record["intent_id"] != intent_id(record["origin_loop_id"], record["origin_round"],
                                        record["origin_generation"], record["attempt"]):
        raise ValueError("dispatch intent id mismatch")
    request, claim = record["carrier_request"], record["carrier_claim"]
    carrier_request_validator.validate_request(request, now=_time(request["created_at"], "created_at"))
    carrier_claim_validator.verify_command_claim(request, claim)
    binding = validate_binding_record(record["origin_binding"])
    expected_origin = (record["origin_loop_id"], record["origin_round"],
                       record["origin_correlation_id"], record["origin_generation"])
    if (binding["origin_loop_id"], binding["origin_round"], binding["origin_correlation_id"],
            binding["origin_generation"]) != expected_origin:
        raise ValueError("dispatch intent origin/binding mismatch")
    if binding["command_id"] != request["command_id"] or binding["claim_loop_id"] != claim["loop_id"]:
        raise ValueError("dispatch intent binding/carrier mismatch")
    if claim["task_id"] != record["task_id"]:
        raise ValueError("dispatch intent task mismatch")
    if not re.fullmatch(r"[0-9a-f]{64}", record["task_spec_sha256"] or ""):
        raise ValueError("invalid task_spec_sha256")
    return record


def used_loop_numbers(client: GitHubContentsClient, carrier_branch: str) -> set[int]:
    """Read every globally used Loop number (claims and numbered commands)."""
    used: set[int] = set()
    for content in client.list(CLAIMS_DIR + "/", carrier_branch):
        name = content.path.rsplit("/", 1)[-1]
        match = re.fullmatch(r"([0-9]{3,6})\.json", name)
        if match is None:
            raise ValueError(f"unexpected claim ledger file: {content.path}")
        used.add(int(match.group(1)))
    for content in client.list(COMMANDS_DIR + "/", carrier_branch):
        parsed = carrier_claim_validator.extract_numbered_loop(content.path.rsplit("/", 1)[-1][:-5])
        if parsed is not None:
            used.add(int(parsed[0]))
    return used


def next_unused_loop_number(client: GitHubContentsClient, carrier_branch: str) -> int:
    used = used_loop_numbers(client, carrier_branch)
    return (max(used) + 1) if used else 1


class ClaudeJulesDispatcher:
    """Execute one dispatch intent through the existing carrier contract."""

    def __init__(self, *, client: GitHubContentsClient, refs: GitRefClient, policy: dict[str, Any],
                 owner_reader: Any, carrier_guard: Any = None):
        self.client, self.refs = client, refs
        # Optional no-write check that the shared carrier is quiet (see CarrierQuietGuard).
        self.carrier_guard = carrier_guard
        self.policy = validate_policy(policy)
        self.owner_reader = owner_reader
        self.binding_store = ClaudeJulesOriginBindingStore(client, self.policy["data_branch"])
        from .claude_jules_live_budget import LiveBudgetLedger  # local import: the ledger reuses this module
        self.budget = LiveBudgetLedger(client, data_branch=self.policy["data_branch"])

    # -- public -----------------------------------------------------------
    def dispatch(self, intent: dict[str, Any], *, now: str, dispatches_used: int) -> DispatchResult:
        try:
            intent = validate_dispatch_intent(intent)
        except (KeyError, TypeError, ValueError) as exc:
            return DispatchResult("BLOCKED", f"invalid dispatch intent: {exc}")
        request, claim = intent["carrier_request"], intent["carrier_claim"]
        if (terminal := self._existing_receipt(request["command_id"])) is not None:
            return terminal
        if _time(now, "now") >= _time(request["expires_at"], "expires_at"):
            if self.client.get(intent_path(intent["intent_id"]), self.policy["data_branch"]) is None:
                return DispatchResult("BLOCKED", "carrier request expired before dispatch; nothing written")
            return self._receipt(intent, "BLOCKED", "carrier request expired before dispatch")
        if (pre := self.preflight(intent, now=now, dispatches_used=dispatches_used)).status != "PASS":
            if pre.status == "BLOCKED" and pre.reason.startswith("STALE"):
                if self.client.get(intent_path(intent["intent_id"]), self.policy["data_branch"]) is not None:
                    return self._receipt(intent, "BLOCKED", pre.reason)
            return pre

        steps = (
            ("intent", lambda: self._create_once(intent_path(intent["intent_id"]), intent,
                                                 self.policy["data_branch"], "claude-auto dispatch intent")),
            ("carrier", lambda: self._carrier_quiet(claim_path(claim["loop_id"]), request["command_id"])),
            ("claim", lambda: self._create_once(claim_path(claim["loop_id"]), claim,
                                                self.policy["carrier_branch"], "claim Loop for Claude AUTO", pretty=True)),
            ("work-branch", lambda: self._work_branch(request)),
            ("binding", lambda: self._binding(intent)),
        )
        for name, step in steps:
            outcome = step()
            if outcome.status == "COLLISION":
                return self._receipt(intent, "BLOCKED", f"{name}: {outcome.reason}; choose a new Loop number")
            if outcome.status not in {"CREATED", "RECOVERED", "PASS"}:
                return DispatchResult(outcome.status, f"{name}: {outcome.reason}")

        # Irreversible trigger: re-fence and re-read the target immediately before.
        if (fence := self._fence(intent, now)).status != "PASS":
            return fence
        if (stale := self._target_problem(request)):
            return self._receipt(intent, "BLOCKED", stale) if stale.startswith("STALE") else DispatchResult("UNKNOWN", stale)
        if (quiet := self._carrier_quiet(command_path(request["command_id"]), request["command_id"])).status != "PASS":
            return quiet
        # Consume one slot of the fixed total LIVE budget before the irreversible write.
        slot = self.budget.acquire(command_id=request["command_id"], intent_sha256=intent["intent_sha256"],
                                   origin_loop_id=intent["origin_loop_id"], acquired_at=now)
        if slot.status in {"EXHAUSTED", "COLLISION"}:
            return self._receipt(intent, "BLOCKED", f"live budget: {slot.reason}")
        if slot.status not in {"ACQUIRED", "RECOVERED"}:
            return DispatchResult("UNKNOWN", f"live budget: {slot.reason}")
        outcome = self._create_once(command_path(request["command_id"]), request,
                                    self.policy["carrier_branch"], "append Claude AUTO Jules command", pretty=True)
        if outcome.status == "COLLISION":
            return self._receipt(intent, "BLOCKED", f"command: {outcome.reason}")
        if outcome.status not in {"CREATED", "RECOVERED"}:
            return DispatchResult(outcome.status, f"command: {outcome.reason}; do not resend")
        return self._receipt(intent, "DISPATCHED", "command appended once; await workflow/Jules session readback")

    def preflight(self, intent: dict[str, Any], *, now: str, dispatches_used: int) -> DispatchResult:
        """All no-write gates: grants, live authorization, owner fence, fresh target."""
        if (problem := self._static_problem(intent)):
            return DispatchResult("BLOCKED", problem)
        if (problem := live_authorization_problem(self.policy, now=now, dispatches_used=dispatches_used)):
            return DispatchResult("PREPARED_NOT_AUTHORIZED", f"{problem}; nothing written", intent)
        try:
            slots = self.budget.slots()
        except (OSError, RuntimeError) as exc:
            return DispatchResult("UNKNOWN", f"live budget read failed: {exc}")
        except Exception as exc:
            return DispatchResult("UNKNOWN", f"live budget ledger unverifiable: {exc}")
        command_id = intent["carrier_request"]["command_id"]
        if len(slots) >= self.budget.cap and not any(s["command_id"] == command_id for s in slots):
            return DispatchResult("PREPARED_NOT_AUTHORIZED",
                                  f"LIVE budget exhausted ({len(slots)}/{self.budget.cap}); nothing written", intent)
        if (fence := self._fence(intent, now)).status != "PASS":
            return fence
        if (stale := self._target_problem(intent["carrier_request"])):
            return DispatchResult("BLOCKED" if stale.startswith("STALE") else "UNKNOWN", stale)
        if (quiet := self._carrier_quiet(None, intent["carrier_request"]["command_id"])).status != "PASS":
            return quiet
        return DispatchResult("PASS", "no-write preflight passed")

    def _carrier_quiet(self, path: str | None, command_id: str) -> DispatchResult:
        """PASS when no guard is set, the record already exists (resume), or the carrier is quiet."""
        if self.carrier_guard is None:
            return DispatchResult("PASS", "no carrier guard")
        if path is not None:
            try:
                if self.client.get(path, self.policy["carrier_branch"]) is not None:
                    return DispatchResult("PASS", "carrier record already written; readback decides")
            except Exception as exc:
                return DispatchResult("UNKNOWN", f"carrier pre-read failed: {exc}")
        try:
            verdict = self.carrier_guard(command_id)
        except Exception as exc:
            return DispatchResult("UNKNOWN", f"carrier guard failed: {exc}")
        if verdict.status not in {"PASS", "WAIT", "BLOCKED"}:
            return DispatchResult("UNKNOWN", verdict.reason)
        return verdict

    # -- steps ------------------------------------------------------------
    def _static_problem(self, intent: dict[str, Any]) -> str | None:
        request, claim = intent["carrier_request"], intent["carrier_claim"]
        if request["target_repo"] != self.policy["target_repo"]:
            return "target repository is not the policy repository"
        if request["target_branch"] not in self.policy["allowed_target_branches"]:
            return "target branch is not granted to Claude AUTO"
        if claim["lane_id"] not in self.policy["allowed_lane_ids"]:
            return f"lane {claim['lane_id']} is not granted to Claude AUTO"
        if intent["origin_round"] > self.policy["max_rounds"]:
            return "max_rounds reached"
        return None

    def controller_fence(self, origin_loop_id: str, now: str) -> DispatchResult:
        return self._fence({"origin_loop_id": origin_loop_id, "origin_generation": None}, now)

    def _fence(self, intent: dict[str, Any], now: str) -> DispatchResult:
        try:
            read = self.owner_reader.read_chain(intent["origin_loop_id"])
        except Exception as exc:  # transport failure is never a pass
            return DispatchResult("UNKNOWN", f"owner chain read failed: {exc}")
        if getattr(read, "status", None) != "READ":
            return DispatchResult("UNKNOWN", f"owner chain unavailable: {getattr(read, 'reason', '')}")
        return check_dispatch_authority(read.record, policy=self.policy, origin_loop_id=intent["origin_loop_id"],
                                        generation=intent["origin_generation"], now=now)

    def _target_problem(self, request: dict[str, Any]) -> str | None:
        try:
            head = self.refs.get_branch_head(request["target_branch"])
            tree = self.refs.get_commit_tree(head) if head else None
        except Exception as exc:
            return f"target readback failed: {exc}"
        if head is None or tree is None:
            return "target head/tree unavailable"
        if head != request["expected_target_head"]:
            return "STALE_TARGET: target head changed"
        if tree != request["expected_target_tree"]:
            return "STALE_TARGET: target tree changed"
        return None

    def _create_once(self, path: str, record: dict[str, Any], branch: str, message: str,
                     *, pretty: bool = False) -> DispatchResult:
        try:
            existing = self.client.get(path, branch)
        except Exception as exc:
            return DispatchResult("UNKNOWN", f"pre-read failed: {exc}")
        if existing is not None:
            return self._compare(existing.text, record, "RECOVERED")
        try:
            self.client.create(path, pretty_json(record) if pretty else canonical_json(record), message, branch)
        except Exception:
            pass  # ambiguous create: resolved only by readback, never resent
        try:
            readback = self.client.get(path, branch)
        except Exception as exc:
            return DispatchResult("UNKNOWN", f"readback failed: {exc}; do not resend")
        if readback is None:
            return DispatchResult("UNKNOWN", "create not proven by readback; do not resend")
        # A different record at our path means a concurrent writer won the create.
        return self._compare(readback.text, record, "CREATED")

    @staticmethod
    def _compare(text: str, record: dict[str, Any], status: str) -> DispatchResult:
        try:
            if json.loads(text) == record:
                return DispatchResult(status, "exact record verified by readback", record)
        except json.JSONDecodeError:
            pass
        return DispatchResult("COLLISION", "a different record already exists")

    def _work_branch(self, request: dict[str, Any]) -> DispatchResult:
        branch, head = request["work_branch"], request["expected_target_head"]
        try:
            current = self.refs.get_branch_head(branch)
        except Exception as exc:
            return DispatchResult("UNKNOWN", f"work branch pre-read failed: {exc}")
        if current is not None:
            return DispatchResult("RECOVERED", "work branch exists at snapshot") if current == head \
                else DispatchResult("COLLISION", "work branch exists at another commit")
        try:
            self.refs.create_branch(branch, head)
        except Exception:
            pass  # ambiguous: readback decides
        try:
            current = self.refs.get_branch_head(branch)
        except Exception as exc:
            return DispatchResult("UNKNOWN", f"work branch readback failed: {exc}")
        if current != head:
            return DispatchResult("UNKNOWN", "work branch creation not proven by readback")
        return DispatchResult("CREATED", "isolated work branch created at snapshot")

    def _binding(self, intent: dict[str, Any]) -> DispatchResult:
        saved = self.binding_store.persist(intent["origin_binding"], intent["carrier_request"], intent["carrier_claim"])
        if saved.status == "ACCEPTED":
            return DispatchResult("CREATED", saved.reason)
        if saved.status == "RECOVERED":
            return DispatchResult("RECOVERED", saved.reason)
        if saved.status == "BLOCKED":
            return DispatchResult("COLLISION", saved.reason)
        return DispatchResult("UNKNOWN", saved.reason)

    def _existing_receipt(self, command_id: str) -> DispatchResult | None:
        try:
            existing = self.client.get(dispatch_receipt_path(command_id), self.policy["data_branch"])
        except Exception as exc:
            return DispatchResult("UNKNOWN", f"receipt pre-read failed: {exc}")
        if existing is None:
            return None
        try:
            record = json.loads(existing.text)
        except json.JSONDecodeError:
            return DispatchResult("UNKNOWN", "existing dispatch receipt is unreadable")
        if not isinstance(record, dict):
            return DispatchResult("UNKNOWN", "existing dispatch receipt is malformed")
        return DispatchResult("NO-OP", f"terminal dispatch receipt already exists ({record.get('state')})", record)

    def _receipt(self, intent: dict[str, Any], state: str, reason: str) -> DispatchResult:
        request = intent["carrier_request"]
        receipt = {
            "schema_version": 1,
            "profile": RECEIPT_PROFILE,
            "command_id": request["command_id"],
            "intent_id": intent["intent_id"],
            "intent_sha256": intent["intent_sha256"],
            "origin_loop_id": intent["origin_loop_id"],
            "origin_round": intent["origin_round"],
            "origin_generation": intent["origin_generation"],
            "loop_id": intent["carrier_claim"]["loop_id"],
            "lane_id": intent["carrier_claim"]["lane_id"],
            "target_branch": request["target_branch"],
            "work_branch": request["work_branch"],
            "expected_target_head": request["expected_target_head"],
            "expected_target_tree": request["expected_target_tree"],
            "state": state,
            "reason": reason,
            "retry_count": 0,
            "fallback_used": False,
        }
        outcome = self._create_once(dispatch_receipt_path(request["command_id"]), receipt,
                                    self.policy["data_branch"], f"Claude AUTO dispatch receipt {state}")
        if outcome.status == "CREATED":
            return DispatchResult(state, reason, receipt)
        if outcome.status == "RECOVERED":
            return DispatchResult("NO-OP", "identical dispatch receipt already recorded", receipt)
        return DispatchResult("UNKNOWN", f"dispatch receipt unresolved: {outcome.reason}", receipt)
