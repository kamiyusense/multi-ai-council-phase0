"""Fail-closed, single-dispatch polling controller for static Phase 0 runs.

This module borrows the tracker polling and reconciliation shape from OpenAI
Symphony while reusing Phase 0's durable command/claim/receipt boundary. It is
an interface plus deterministic controller core: production GitHub transport
and live model runners are deliberately not included.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .executor import consume_executor_result, claim_executor, submit_executor_result
from .executor_backend import GitHubExecutorBackend


DEFAULT_POLL_INTERVAL_MS = 30_000
MAX_CONCURRENT_AGENTS = 1
MAX_TURNS = 1
RETRY = 0
FALLBACK_ENABLED = False


@dataclass(frozen=True)
class Command:
    command_id: str
    logical_id: str
    correlation_id: str
    generation: int
    expected_target_head: str
    expires_at: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "READY"
    expected_target_tree: str | None = None


@dataclass(frozen=True)
class Target:
    repository: str
    branch: str
    head: str
    tree: str


@dataclass(frozen=True)
class Snapshot:
    cycle_id: str
    commands: tuple[Command, ...]
    claims: tuple[dict[str, Any], ...]
    receipts: tuple[dict[str, Any], ...]
    target: Target
    carrier_head: str
    active_generation: int


@dataclass(frozen=True)
class Reservation:
    command_id: str
    logical_id: str
    correlation_id: str
    generation: int
    expected_target_head: str
    reservation_id: str


@dataclass(frozen=True)
class CycleResult:
    cycle_id: str
    selected: bool = False
    command_id: str | None = None
    dispatch_attempted: bool = False
    model_started: bool | None = False
    provider_started: bool | None = False
    terminal_status: str = "NOOP"
    readback: str = "NOT_REQUIRED"
    reason: str | None = None


class Tracker(Protocol):
    """Durable GitHub adapter contract; write methods must not auto-retry."""

    def reconcile(self) -> Snapshot: ...
    def reserve(self, reservation: Reservation) -> str: ...
    def read_reservation(self, command_id: str) -> Reservation | None: ...
    def write_receipt(self, receipt: dict[str, Any]) -> str: ...
    def read_receipt(self, command_id: str) -> dict[str, Any] | None: ...


class GitHubTargetReader(Protocol):
    """Connected GitHub read path for target PR, carrier ref and generation."""

    def read_target(self, repository: str, pr_number: int) -> Target: ...
    def read_carrier_head(self, branch: str) -> str: ...
    def read_active_generation(self, loop_id: str) -> int: ...


class GitHubExecutorTracker:
    """Thin adapter over Phase 0's existing executor records and readback gate.

    Requests opt in with ``symphony_profile=SYMPHONY_INSPIRED_STATIC_V1`` and
    carry ``logical_command_id`` plus ``generation``. Existing PREPARE_ONLY,
    retry=0, fallback=disabled, and GitHubExecutorBackend validation remains
    authoritative. This adapter supplies no GitHub credentials or HTTP client.
    """

    PROFILE = "SYMPHONY_INSPIRED_STATIC_V1"
    supports_live_model_execution = False

    def __init__(self, backend: GitHubExecutorBackend, target_reader: GitHubTargetReader,
                 *, loop_id: str, carrier_branch: str, repository: str, target_pr: int,
                 default_branch: str = "main", executor_instance_id: str = "symphony-static"):
        if not backend.branch or backend.branch == default_branch:
            raise ValueError("durable executor writes require a non-default branch")
        if not isinstance(target_pr, int) or isinstance(target_pr, bool) or target_pr < 1:
            raise ValueError("target PR must be a positive integer")
        self.backend = backend
        self.target_reader = target_reader
        self.loop_id = loop_id
        self.carrier_branch = carrier_branch
        self.repository = repository
        self.target_pr = target_pr
        self.executor_instance_id = executor_instance_id
        self._generation = 0

    def _recovered(self):
        recovered = self.backend.recover(self.loop_id)
        if recovered.status != "RECOVERED":
            raise RuntimeError("GitHub executor state unavailable")
        return recovered.record["ledger"], recovered.record["state"]

    def reconcile(self) -> Snapshot:
        ledger, state = self._recovered()
        self._generation = self.target_reader.read_active_generation(self.loop_id)
        if isinstance(self._generation, bool) or not isinstance(self._generation, int) or self._generation < 1:
            raise RuntimeError("active generation unavailable")
        requests = [r for r in ledger.requests if r.get("symphony_profile") == self.PROFILE]
        commands = tuple(Command(
            command_id=r["request_id"],
            logical_id=r.get("logical_command_id", ""),
            correlation_id=r["correlation_id"],
            generation=r.get("generation", -1),
            expected_target_head=r["expected_target_head"],
            expires_at=r["expires_at"],
            payload={"objective": r["objective"], "input_refs": list(r["input_refs"])},
            status=("READY" if state.get("state") == "RUNNING" and not state.get("stop_requested")
                    and r.get("status") == "OPEN" else "BLOCKED"),
            expected_target_tree=r.get("expected_target_tree"),
        ) for r in requests)
        request_map = {r["request_id"]: r for r in requests}
        claims = tuple({
            "command_id": c["request_id"],
            "logical_id": request_map.get(c["request_id"], {}).get("logical_command_id"),
            "correlation_id": request_map.get(c["request_id"], {}).get("correlation_id"),
            "generation": c["executor_generation"],
            "expected_target_head": request_map.get(c["request_id"], {}).get("expected_target_head"),
            "reservation_id": c["claim_id"],
        } for c in ledger.claims if c.get("request_id") in request_map)
        receipts = tuple(r["controller_receipt"] for r in ledger.receipts
                         if r.get("request_id") in request_map and isinstance(r.get("controller_receipt"), dict))
        if any((r["expected_repo"], r["expected_pr"]) != (self.repository, self.target_pr) for r in requests):
            raise RuntimeError("executor request target identity mismatch")
        target = self.target_reader.read_target(self.repository, self.target_pr)
        carrier_head = self.target_reader.read_carrier_head(self.carrier_branch)
        if not isinstance(carrier_head, str) or not carrier_head:
            raise RuntimeError("carrier HEAD unavailable")
        return Snapshot(f"{self.loop_id}-poll-{datetime.now(timezone.utc).timestamp():.6f}",
                        commands, claims, receipts, target, carrier_head, self._generation)

    def reserve(self, reservation: Reservation) -> str:
        ledger, state = self._recovered()
        request = next((r for r in ledger.requests if r.get("request_id") == reservation.command_id
                        and r.get("symphony_profile") == self.PROFILE), None)
        if request is None or request.get("logical_command_id") != reservation.logical_id:
            return "CONFLICT"
        target = self.target_reader.read_target(request["expected_repo"], request["expected_pr"])
        generation = self.target_reader.read_active_generation(self.loop_id)
        if target.head != reservation.expected_target_head or generation != reservation.generation:
            return "CONFLICT"
        expected_tree = request.get("expected_target_tree")
        if expected_tree not in {None, "UNKNOWN"} and target.tree != expected_tree:
            return "CONFLICT"
        claim = claim_executor(
            ledger, reservation.command_id, claim_id=reservation.reservation_id,
            executor_instance_id=self.executor_instance_id,
            executor_generation=reservation.generation,
            capability=request["capability"], claimed_at=datetime.now(timezone.utc),
            expires_at=request["expires_at"], state=state,
        )
        if claim.status != "CLAIMED":
            return "CONFLICT"
        persisted = self.backend.append("claim", self.loop_id, claim.record)
        return "ACCEPTED" if persisted.status == "ACCEPTED" else "AMBIGUOUS"

    def read_reservation(self, command_id: str) -> Reservation | None:
        ledger, _ = self._recovered()
        command = next((r for r in ledger.requests if r.get("request_id") == command_id
                        and r.get("symphony_profile") == self.PROFILE), None)
        claim = next((c for c in ledger.claims if c.get("request_id") == command_id), None)
        if command is None or claim is None:
            return None
        return Reservation(command_id, command["logical_command_id"], command["correlation_id"],
                           command["generation"], command["expected_target_head"], claim["claim_id"])

    def write_receipt(self, receipt: dict[str, Any]) -> str:
        ledger, state = self._recovered()
        request = next((r for r in ledger.requests if r.get("request_id") == receipt.get("command_id")
                        and r.get("symphony_profile") == self.PROFILE), None)
        if request is None:
            return "CONFLICT"
        target = self.target_reader.read_target(request["expected_repo"], request["expected_pr"])
        generation = self.target_reader.read_active_generation(self.loop_id)
        if target.head != receipt.get("expected_target_head") or generation != receipt.get("generation"):
            return "CONFLICT"
        expected_tree = request.get("expected_target_tree")
        if expected_tree not in {None, "UNKNOWN"} and target.tree != expected_tree:
            return "CONFLICT"
        result_state = "PREPARED" if receipt.get("terminal_status") == "DONE" else (
            "BLOCKED" if receipt.get("terminal_status") == "BLOCKED" else "UNKNOWN")
        result = submit_executor_result(
            ledger, request["request_id"], result_id=f"symphony-result-{request['request_id']}",
            executor_instance_id=self.executor_instance_id,
            executor_generation=receipt["generation"], result_state=result_state,
            evidence_refs=[f"controller-cycle://{receipt['cycle_id']}"],
            loop_id=self.loop_id, round=request["round"],
            correlation_id=request["correlation_id"],
            expected_target_head=request["expected_target_head"], state=state,
            artifact_refs=[], expected_target_tree=request.get("expected_target_tree"),
        )
        if result.status != "ACCEPTED":
            return "CONFLICT"
        result.record["terminal_status"] = receipt["terminal_status"]
        result.record["controller_receipt"] = receipt
        result_write = self.backend.append("result", self.loop_id, result.record)
        if result_write.status != "ACCEPTED":
            return "AMBIGUOUS"
        consumed = consume_executor_result(
            ledger, request["request_id"], loop_id=self.loop_id, round=request["round"],
            correlation_id=request["correlation_id"], expected_target_head=request["expected_target_head"],
            state=state,
        )
        if consumed.status != "VALID":
            return "CONFLICT"
        durable_receipt = ledger.receipts[-1]
        durable_receipt["terminal_status"] = receipt["terminal_status"]
        durable_receipt["controller_receipt"] = receipt
        written = self.backend.append("receipt", self.loop_id, durable_receipt)
        return "ACCEPTED" if written.status == "ACCEPTED" else "AMBIGUOUS"

    def read_receipt(self, command_id: str) -> dict[str, Any] | None:
        ledger, _ = self._recovered()
        record = next((r for r in ledger.receipts if r.get("request_id") == command_id), None)
        value = record.get("controller_receipt") if record else None
        return value if isinstance(value, dict) else None


class AgentRunner(Protocol):
    """Runner boundary. Implementations must classify ambiguity as UNKNOWN."""

    live_enabled: bool

    def prepare(self, command: Command) -> Any: ...
    def dispatch(self, prepared: Any) -> Any: ...
    def classify_result(self, result: Any) -> str: ...


class StaticFakeAgentRunner:
    """Built-in fixture runner. It has no process, provider, or network path."""

    live_enabled = False

    def __init__(self, *, fail_at: str | None = None, result: str = "DONE"):
        self.fail_at = fail_at
        self.result = result
        self.prepare_calls = 0
        self.dispatch_calls = 0
        self.classify_calls = 0

    def prepare(self, command: Command) -> Command:
        self.prepare_calls += 1
        if self.fail_at == "prepare":
            raise RuntimeError("fixture prepare failure")
        return command

    def dispatch(self, prepared: Command) -> str:
        self.dispatch_calls += 1
        if self.fail_at == "dispatch":
            raise RuntimeError("fixture ambiguous dispatch")
        return self.result

    def classify_result(self, result: Any) -> str:
        self.classify_calls += 1
        if self.fail_at == "classify":
            raise RuntimeError("fixture classification failure")
        return result


def _time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _terminal(snapshot: Snapshot, command: Command) -> bool:
    return any(
        receipt.get("command_id") == command.command_id
        or receipt.get("logical_id") == command.logical_id
        for receipt in snapshot.receipts
    )


def _reserved(snapshot: Snapshot, command: Command) -> bool:
    return any(
        claim.get("command_id") == command.command_id
        or claim.get("logical_id") == command.logical_id
        for claim in snapshot.claims
    )


def eligible(snapshot: Snapshot, *, now: datetime) -> list[Command]:
    """Return valid unclaimed work; carrier HEAD is intentionally ignored."""
    try:
        current = now.astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return []
    candidates = []
    commands = [item for item in snapshot.commands if isinstance(item, Command)]
    command_counts: dict[str, int] = {}
    logical_counts: dict[str, int] = {}
    for item in commands:
        command_counts[item.command_id] = command_counts.get(item.command_id, 0) + 1
        logical_counts[item.logical_id] = logical_counts.get(item.logical_id, 0) + 1
    for command in commands:
        if (not command.command_id or not command.logical_id or not command.correlation_id
                or command.status != "READY" or command_counts[command.command_id] != 1
                or logical_counts[command.logical_id] != 1):
            continue
        if (isinstance(command.generation, bool) or not isinstance(command.generation, int)
                or command.generation < 1 or not isinstance(command.expected_target_head, str)
                or not command.expected_target_head):
            continue
        try:
            expiry = _time(command.expires_at)
        except (TypeError, ValueError, OverflowError):
            continue
        if expiry <= current or command.generation != snapshot.active_generation:
            continue
        if command.expected_target_head != snapshot.target.head:
            continue
        if command.expected_target_tree not in {None, "UNKNOWN"} and command.expected_target_tree != snapshot.target.tree:
            continue
        if _terminal(snapshot, command) or _reserved(snapshot, command):
            continue
        candidates.append(command)
    return sorted(candidates, key=lambda item: (item.command_id, item.logical_id))


def _persist_terminal(tracker: Tracker, snapshot: Snapshot, command: Command, *,
                      cycle_id: str, status: str, dispatch_attempted: bool,
                      model_started: bool | None = False,
                      verification: dict[str, Any] | None = None,
                      changed_paths: list[str] | None = None,
                      proof_commit_sha: str | None = None) -> tuple[str, str | None]:
    receipt = {
        "schema_version": 1,
        "receipt_id": f"receipt-{command.command_id}",
        "command_id": command.command_id,
        "logical_id": command.logical_id,
        "correlation_id": command.correlation_id,
        "generation": command.generation,
        "expected_target_head": command.expected_target_head,
        "expected_target_tree": command.expected_target_tree,
        "observed_target_head": snapshot.target.head,
        "observed_target_tree": snapshot.target.tree,
        "target_repository": snapshot.target.repository,
        "target_branch": snapshot.target.branch,
        "target_tree": snapshot.target.tree,
        "carrier_head": snapshot.carrier_head,
        "cycle_id": cycle_id,
        "selected": True,
        "dispatch_attempted": dispatch_attempted,
        "model_started": model_started,
        "model_start_count": 1 if model_started is True else (0 if model_started is False else None),
        "provider_started": model_started,
        "verification": verification or {"status": "UNKNOWN"},
        "changed_paths": changed_paths or [],
        "proof_commit_sha": proof_commit_sha,
        "terminal_status": status,
        "retry_count": 0,
        "fallback_used": False,
    }
    try:
        written = tracker.write_receipt(receipt)
    except Exception:
        written = "AMBIGUOUS"
    if written == "ACCEPTED":
        return "VERIFIED", None
    try:
        readback = tracker.read_receipt(command.command_id)
    except Exception:
        readback = None
    if readback == receipt:
        return "VERIFIED", None
    return "UNKNOWN", "terminal receipt write not verified"


class SymphonyInspiredController:
    """One-cycle polling controller with durable claim-before-dispatch."""

    def __init__(self, tracker: Tracker, runner: AgentRunner, *, poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS):
        if isinstance(poll_interval_ms, bool) or not isinstance(poll_interval_ms, int) or poll_interval_ms <= 0:
            raise ValueError("poll_interval_ms must be a positive integer")
        # The live boundary is intentionally an exact concrete type check. A
        # third-party object cannot opt in merely by setting live_enabled=True.
        from .symphony_codex_app_server import CodexAppServerAgentRunner
        if type(runner) not in {StaticFakeAgentRunner, CodexAppServerAgentRunner}:
            raise ValueError("only the built-in static fake runner or CodexAppServerAgentRunner is admitted")
        if type(runner) is CodexAppServerAgentRunner:
            if runner.live_enabled is not True:
                raise ValueError("CodexAppServerAgentRunner LIVE flag must be explicitly enabled")
            if getattr(tracker, "supports_live_model_execution", False) is not True:
                raise ValueError("tracker cannot truthfully persist LIVE model execution")
        self.tracker = tracker
        self.runner = runner
        self.poll_interval_ms = poll_interval_ms
        self._stop = threading.Event()
        self._cycle_lock = threading.Lock()

    def stop(self) -> None:
        """Request graceful stop; an active cycle is allowed to finish."""
        self._stop.set()

    def cycle(self, *, now: datetime | None = None) -> CycleResult:
        if not self._cycle_lock.acquire(blocking=False):
            return CycleResult("BUSY", terminal_status="NOOP", reason="concurrency limit is one")
        try:
            return self._cycle(now=now)
        finally:
            self._cycle_lock.release()

    def _cycle(self, *, now: datetime | None = None) -> CycleResult:
        at = now or datetime.now(timezone.utc)
        try:
            snapshot = self.tracker.reconcile()
        except Exception as exc:
            return CycleResult("UNKNOWN", terminal_status="UNKNOWN", reason=f"reconcile failed: {type(exc).__name__}")
        cycle_id = snapshot.cycle_id
        candidates = eligible(snapshot, now=at)
        if not candidates:
            return CycleResult(cycle_id)
        command = candidates[0]
        reservation_id = f"claim-{command.command_id}-g{command.generation}"
        reservation = Reservation(command.command_id, command.logical_id, command.correlation_id,
                                  command.generation, command.expected_target_head, reservation_id)
        try:
            write_state = self.tracker.reserve(reservation)
        except Exception:
            write_state = "AMBIGUOUS"
        if write_state != "ACCEPTED":
            # Ambiguous/conflicting reservation: read only, then stop. An exact
            # record match cannot prove which concurrent controller owns it.
            try:
                self.tracker.read_reservation(command.command_id)
            except Exception:
                pass
            return CycleResult(cycle_id, True, command.command_id, terminal_status="UNKNOWN",
                               readback="READ_ONLY", reason="reservation write not verified")
        try:
            current = self.tracker.reconcile()
        except Exception:
            return CycleResult(cycle_id, True, command.command_id, terminal_status="UNKNOWN",
                               readback="UNKNOWN", reason="post-claim reconciliation unavailable")
        if (current.target.head != command.expected_target_head
                or (command.expected_target_tree not in {None, "UNKNOWN"}
                    and current.target.tree != command.expected_target_tree)
                or current.active_generation != command.generation
                or _terminal(current, command)):
            readback, error = _persist_terminal(
                self.tracker, current, command, cycle_id=cycle_id,
                status="BLOCKED", dispatch_attempted=False,
            )
            return CycleResult(cycle_id, True, command.command_id, terminal_status=("STALE" if not error else "UNKNOWN"),
                               readback=readback, reason="claim-time guard changed")
        verified_claim = next((item for item in current.claims
                               if item.get("command_id") == command.command_id), None)
        if verified_claim is None or verified_claim != reservation.__dict__:
            return CycleResult(cycle_id, True, command.command_id, terminal_status="UNKNOWN",
                               readback="UNKNOWN", reason="reservation readback mismatch")
        attempted = False
        model_started: bool | None = False
        verification: dict[str, Any] | None = None
        changed_paths: list[str] = []
        proof_commit_sha: str | None = None
        try:
            prepared = self.runner.prepare(command)
            attempted = True
            raw = self.runner.dispatch(prepared)
            observed = getattr(raw, "model_started", False)
            model_started = observed if observed is True or observed is False or observed is None else None
            evidence = getattr(raw, "verification", None)
            verification = evidence if isinstance(evidence, dict) else None
            paths = getattr(raw, "changed_paths", ())
            changed_paths = list(paths) if isinstance(paths, (list, tuple)) else []
            commit_sha = getattr(raw, "proof_commit_sha", None)
            proof_commit_sha = commit_sha if isinstance(commit_sha, str) else None
            classification = self.runner.classify_result(raw)
        except Exception as exc:
            # A runner exception may have happened after an external start.
            # The durable reservation fences restart and no retry is attempted.
            readback, receipt_error = _persist_terminal(
                self.tracker, current, command, cycle_id=cycle_id,
                status="UNKNOWN", dispatch_attempted=attempted,
                model_started=model_started,
                verification=verification, changed_paths=changed_paths,
                proof_commit_sha=proof_commit_sha,
            )
            reason = f"runner ambiguous: {type(exc).__name__}"
            if receipt_error:
                reason += "; " + receipt_error
            return CycleResult(cycle_id, True, command.command_id, attempted, model_started,
                               model_started is True,
                               "UNKNOWN", readback, reason)
        if classification not in {"DONE", "BLOCKED", "FAILED", "UNKNOWN"}:
            classification = "UNKNOWN"
        readback, error = _persist_terminal(
            self.tracker, current, command, cycle_id=cycle_id,
            status=classification, dispatch_attempted=True, model_started=model_started,
            verification=verification, changed_paths=changed_paths,
            proof_commit_sha=proof_commit_sha,
        )
        if error:
            return CycleResult(cycle_id, True, command.command_id, True, model_started,
                               model_started is True,
                               "UNKNOWN", readback, error)
        return CycleResult(cycle_id, True, command.command_id, True, model_started,
                           model_started is True, classification, readback)

    def run_forever(self) -> None:
        """Poll on the configured cadence until stop() requests shutdown."""
        while not self._stop.is_set():
            started = time.monotonic()
            self.cycle()
            remaining = max(0.0, self.poll_interval_ms / 1000 - (time.monotonic() - started))
            self._stop.wait(remaining)
