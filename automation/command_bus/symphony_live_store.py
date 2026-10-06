"""Symphony-only durable command/claim/result records for one-turn LIVE work.

These records have a distinct schema and path from executor PREPARE_ONLY
records. Every append is create-only and followed by a remote readback. An
ambiguous create is read back once and is never resent.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .executor_backend import ExecutorContent, ExecutorContentsClient
from .symphony_controller import Command, Reservation, Snapshot, Target


PROTOCOL_VERSION = "SYMPHONY_LIVE_V1"
COMMAND_TYPE = "SYMPHONY_LIVE_COMMAND_V1"
CLAIM_TYPE = "SYMPHONY_LIVE_CLAIM_V1"
RESULT_TYPE = "SYMPHONY_LIVE_EXECUTION_RESULT_V1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_RESULT_STATUS = {"PASS", "FAIL", "BLOCKED", "UNKNOWN", "STALE"}
_PROOF_PATH = "evidence/symphony_live_one_round_v1.txt"
_PROOF_CONTENT = "SYMPHONY_LIVE_ONE_ROUND_V1_PASS"


def _has_complete_pass_evidence(verification: Any, *, head_before: str, head_after: str,
                                dispatch_count: int, model_start_count: int | None,
                                changed_paths: Any, proof_commit_sha: Any) -> bool:
    required = {
        "status": "PASS", "proof_path": _PROOF_PATH, "proof_content": _PROOF_CONTENT,
        "commit_parent": head_before, "normal_commit": True, "force_push_count": 0,
        "merge_count": 0, "default_branch_mutation_count": 0, "max_turns": 1,
        "remote_readback": "PASS",
    }
    return (
        isinstance(verification, dict)
        and all(verification.get(key) == value for key, value in required.items())
        and dispatch_count == 1 and model_start_count == 1
        and changed_paths == [_PROOF_PATH]
        and isinstance(proof_commit_sha, str)
        and re.fullmatch(r"[0-9a-f]{40}", proof_commit_sha) is not None
        and head_after == proof_commit_sha
    )


class TargetReader:
    def read_target(self, repository: str, pr_number: int) -> Target: ...
    def read_carrier_head(self, branch: str) -> str: ...
    def read_active_generation(self, loop_id: str) -> int: ...


def _path(kind: str, command_id: str) -> str:
    if kind not in {"commands", "claims", "results"} or not _ID.fullmatch(command_id):
        raise ValueError("invalid Symphony live record identity")
    return f"symphony_live/{kind}/{command_id}.json"


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except (ValueError, OverflowError):
        return False


def validate_live_command(record: dict[str, Any]) -> None:
    required = {
        "record_type", "protocol_version", "command_id", "logical_id", "correlation_id",
        "generation", "target_repository", "target_branch", "expected_target_head",
        "expected_target_tree", "expires_at", "allowed_paths", "exact_task", "verification",
        "live_provider_or_model_allowed", "max_concurrent_agents", "max_model_starts",
        "max_turns", "retry", "fallback", "status",
    }
    if not isinstance(record, dict) or not required <= record.keys():
        raise ValueError("incomplete Symphony LIVE command")
    if record["record_type"] != COMMAND_TYPE or record["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("wrong durable command protocol")
    if record["status"] != "READY" or record["live_provider_or_model_allowed"] is not True:
        raise ValueError("command is not LIVE-ready")
    if (any(type(record[key]) is not int for key in
            ("max_concurrent_agents", "max_model_starts", "max_turns", "retry"))
            or record["max_concurrent_agents"] != 1 or record["max_model_starts"] != 1
            or record["max_turns"] != 1 or record["retry"] != 0
            or record["fallback"] != "disabled"):
        raise ValueError("unsafe Symphony LIVE execution limits")
    for field in ("command_id", "logical_id", "correlation_id", "target_repository",
                  "target_branch", "expected_target_head", "exact_task"):
        if not isinstance(record[field], str) or not record[field]:
            raise ValueError(f"invalid LIVE command {field}")
    if not _ID.fullmatch(record["command_id"]) or not _ID.fullmatch(record["logical_id"]):
        raise ValueError("unsafe LIVE command identity")
    if type(record["generation"]) is not int or record["generation"] < 1:
        raise ValueError("invalid LIVE command generation")
    if record["expected_target_tree"] is not None and not isinstance(record["expected_target_tree"], str):
        raise ValueError("invalid LIVE command target tree")
    if not _aware_timestamp(record["expires_at"]):
        raise ValueError("invalid LIVE command expiry")
    if (not isinstance(record["allowed_paths"], list) or record["allowed_paths"] != [_PROOF_PATH]
            or any(not isinstance(path, str) or not path or path.startswith("/") or ".." in path.split("/")
                   for path in record["allowed_paths"])):
        raise ValueError("invalid LIVE command allowed paths")
    if (record["target_branch"] in {"main", "master"}
            or not isinstance(record["verification"], dict)
            or record["verification"].get("exact_content") != _PROOF_CONTENT
            or _PROOF_PATH not in record["exact_task"] or _PROOF_CONTENT not in record["exact_task"]):
        raise ValueError("invalid LIVE command verification contract")


def validate_live_claim(record: dict[str, Any]) -> None:
    required = {"record_type", "protocol_version", "claim_id", "command_id", "logical_id",
                "correlation_id", "generation", "target_repository", "target_branch",
                "head_before", "reservation_state", "reserved_at"}
    if not isinstance(record, dict) or not required <= record.keys():
        raise ValueError("incomplete Symphony LIVE claim")
    if record["record_type"] != CLAIM_TYPE or record["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("wrong Symphony LIVE claim type")
    for field in ("claim_id", "command_id", "logical_id", "correlation_id", "target_repository",
                  "target_branch", "head_before"):
        if not isinstance(record[field], str) or not record[field]:
            raise ValueError(f"invalid Symphony LIVE claim {field}")
    if type(record["generation"]) is not int or record["generation"] < 1:
        raise ValueError("invalid Symphony LIVE claim generation")
    if record["reservation_state"] != "CLAIMED" or not _aware_timestamp(record["reserved_at"]):
        raise ValueError("invalid Symphony LIVE claim state")


def validate_live_result(record: dict[str, Any]) -> None:
    required = {"record_type", "protocol_version", "result_id", "command_id", "logical_id",
                "correlation_id", "generation", "target_repository", "target_branch", "head_before",
                "head_after", "dispatch_count", "model_start_count", "model_start_count_known",
                "retry_count", "fallback_count", "fallback", "status", "terminal", "verification", "changed_paths",
                "proof_commit_sha", "controller_receipt"}
    if not isinstance(record, dict) or not required <= record.keys():
        raise ValueError("incomplete Symphony LIVE result")
    if record["record_type"] != RESULT_TYPE or record["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("wrong Symphony LIVE result type")
    for field in ("result_id", "command_id", "logical_id", "correlation_id", "target_repository",
                  "target_branch", "head_before", "head_after"):
        if not isinstance(record[field], str) or not record[field]:
            raise ValueError(f"invalid Symphony LIVE result {field}")
    if (record["result_id"] != f"live-result-{record['command_id']}"
            or type(record["generation"]) is not int or record["generation"] < 1):
        raise ValueError("Symphony LIVE result identity mismatch")
    if record["status"] not in _RESULT_STATUS or record["terminal"] is not True:
        raise ValueError("invalid Symphony LIVE terminal result")
    if (type(record["retry_count"]) is not int or record["retry_count"] != 0
            or type(record["fallback_count"]) is not int or record["fallback_count"] != 0
            or record["fallback"] != "disabled"):
        raise ValueError("unsafe Symphony LIVE result policy")
    if type(record["dispatch_count"]) is not int or record["dispatch_count"] not in {0, 1}:
        raise ValueError("invalid Symphony LIVE dispatch count")
    count = record["model_start_count"]
    if count is not None and (type(count) is not int or count not in {0, 1}):
        raise ValueError("invalid Symphony LIVE model start count")
    if type(record["model_start_count_known"]) is not bool or record["model_start_count_known"] is not (count is not None):
        raise ValueError("Symphony LIVE model start certainty mismatch")
    if not isinstance(record["changed_paths"], list) or any(not isinstance(p, str) for p in record["changed_paths"]):
        raise ValueError("invalid Symphony LIVE changed paths")
    if not isinstance(record["verification"], dict):
        raise ValueError("invalid Symphony LIVE verification evidence")
    if record["status"] == "PASS":
        verification = record["verification"]
        required_pass = {
            "status": "PASS", "proof_path": "evidence/symphony_live_one_round_v1.txt",
            "proof_content": "SYMPHONY_LIVE_ONE_ROUND_V1_PASS", "commit_parent": record["head_before"],
            "normal_commit": True, "force_push_count": 0, "merge_count": 0,
            "default_branch_mutation_count": 0, "max_turns": 1,
        }
        if any(verification.get(key) != value for key, value in required_pass.items()):
            raise ValueError("PASS result lacks complete exact proof verification")
        if (record["changed_paths"] != [required_pass["proof_path"]]
                or not isinstance(record["proof_commit_sha"], str)
                or not re.fullmatch(r"[0-9a-f]{40}", record["proof_commit_sha"])
                or record["head_after"] != record["proof_commit_sha"]
                or record["dispatch_count"] != 1
                or record["model_start_count"] != 1 or record["retry_count"] != 0
                or record["fallback"] != "disabled"):
            raise ValueError("PASS result proof counts or mutation do not match")
    if not isinstance(record["controller_receipt"], dict):
        raise ValueError("missing controller terminal receipt")


class GitHubSymphonyLiveTracker:
    """Tracker backed by isolated Symphony LIVE command/claim/result paths."""

    supports_live_model_execution = True

    def __init__(self, client: ExecutorContentsClient, target_reader: TargetReader, *,
                 loop_id: str, repository: str, target_pr: int, target_branch: str,
                 carrier_branch: str, write_branch: str, default_branch: str = "main"):
        if not isinstance(write_branch, str) or not write_branch or write_branch == default_branch:
            raise ValueError("Symphony LIVE records require a non-default write branch")
        if type(target_pr) is not int or target_pr < 1:
            raise ValueError("target PR must be a positive integer")
        if not all(isinstance(value, str) and value for value in
                   (loop_id, repository, target_branch, carrier_branch)):
            raise ValueError("invalid Symphony LIVE tracker identity")
        self.client = client
        self.target_reader = target_reader
        self.loop_id = loop_id
        self.repository = repository
        self.target_pr = target_pr
        self.target_branch = target_branch
        self.carrier_branch = carrier_branch
        self.write_branch = write_branch

    def _get(self, kind: str, command_id: str) -> dict[str, Any] | None:
        content = self.client.get(_path(kind, command_id), self.write_branch)
        if content is None:
            return None
        try:
            record = json.loads(content.text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("malformed Symphony LIVE record") from exc
        if not isinstance(record, dict) or record.get("command_id") != command_id:
            raise RuntimeError("Symphony LIVE record identity mismatch")
        {"commands": validate_live_command, "claims": validate_live_claim,
         "results": validate_live_result}[kind](record)
        return record

    def _list(self, kind: str) -> list[dict[str, Any]]:
        output = []
        for content in self.client.list(f"symphony_live/{kind}/", self.write_branch):
            try:
                record = json.loads(content.text)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("malformed Symphony LIVE record") from exc
            if not isinstance(record, dict) or content.path != _path(kind, record.get("command_id", "")):
                raise RuntimeError("Symphony LIVE record path mismatch")
            {"commands": validate_live_command, "claims": validate_live_claim,
             "results": validate_live_result}[kind](record)
            output.append(record)
        return sorted(output, key=lambda item: item["command_id"])

    def _append(self, kind: str, record: dict[str, Any]) -> str:
        path = _path(kind, record["command_id"])
        try:
            if self.client.get(path, self.write_branch) is not None:
                return "CONFLICT"
            self.client.create(path, _canonical(record),
                               f"append Symphony LIVE {kind[:-1]} {record['command_id']}", self.write_branch)
        except Exception:
            # Ambiguous write: only readback, never repeat the create.
            try:
                verified = self.client.get(path, self.write_branch)
                if verified is not None and json.loads(verified.text) == record:
                    return "ACCEPTED"
            except Exception:
                pass
            return "AMBIGUOUS"
        try:
            verified = self.client.get(path, self.write_branch)
            if verified is None:
                return "AMBIGUOUS"
            return "ACCEPTED" if json.loads(verified.text) == record else "AMBIGUOUS"
        except Exception:
            return "AMBIGUOUS"

    def create_command(self, record: dict[str, Any]) -> str:
        validate_live_command(record)
        if record["target_repository"] != self.repository or record["target_branch"] != self.target_branch:
            return "CONFLICT"
        existing = self._list("commands")
        if any(item["command_id"] == record["command_id"]
               or item["logical_id"] == record["logical_id"] for item in existing):
            return "CONFLICT"
        if record["generation"] != self.target_reader.read_active_generation(self.loop_id):
            return "CONFLICT"
        target = self.target_reader.read_target(self.repository, self.target_pr)
        if (target.branch != self.target_branch or target.head != record["expected_target_head"]
                or (record["expected_target_tree"] is not None and target.tree != record["expected_target_tree"])):
            return "CONFLICT"
        return self._append("commands", record)

    def reconcile(self) -> Snapshot:
        generation = self.target_reader.read_active_generation(self.loop_id)
        target = self.target_reader.read_target(self.repository, self.target_pr)
        carrier = self.target_reader.read_carrier_head(self.carrier_branch)
        if not isinstance(carrier, str) or not carrier:
            raise RuntimeError("carrier HEAD unavailable")
        commands = []
        for record in self._list("commands"):
            validate_live_command(record)
            commands.append(Command(
                command_id=record["command_id"], logical_id=record["logical_id"],
                correlation_id=record["correlation_id"], generation=record["generation"],
                expected_target_head=record["expected_target_head"], expires_at=record["expires_at"],
                expected_target_tree=record["expected_target_tree"], status=record["status"],
                payload={"task": record["exact_task"], "target_repository": record["target_repository"],
                         "target_branch": record["target_branch"],
                         "expected_target_tree": record["expected_target_tree"],
                         "allowed_paths": record["allowed_paths"],
                         "verification": record["verification"], "retry": record["retry"],
                         "fallback": record["fallback"], "concurrency": record["max_concurrent_agents"],
                         "max_turns": record["max_turns"], "max_model_starts": record["max_model_starts"]},
            ))
        raw_claims = self._list("claims")
        claims = tuple({
            "command_id": record["command_id"], "logical_id": record["logical_id"],
            "correlation_id": record["correlation_id"], "generation": record["generation"],
            "expected_target_head": record["head_before"], "reservation_id": record["claim_id"],
        } for record in raw_claims)
        results = tuple(self._list("results"))
        command_map = {item.command_id: item for item in commands}
        claim_map = {item["command_id"]: item for item in raw_claims}
        result_map = {item["command_id"]: item for item in results}
        if len(command_map) != len(commands) or len(claim_map) != len(claims) or len(result_map) != len(results):
            raise RuntimeError("duplicate Symphony LIVE record identity")
        for command_id, claim in claim_map.items():
            command = command_map.get(command_id)
            if (command is None or claim["logical_id"] != command.logical_id
                    or claim["correlation_id"] != command.correlation_id
                    or claim["generation"] != command.generation
                    or claim["head_before"] != command.expected_target_head):
                raise RuntimeError("Symphony LIVE claim/command mismatch")
        for command_id, result in result_map.items():
            command = command_map.get(command_id)
            claim = claim_map.get(command_id)
            if (command is None or claim is None or result["logical_id"] != command.logical_id
                    or result["correlation_id"] != command.correlation_id
                    or result["generation"] != command.generation
                    or result["head_before"] != claim["head_before"]):
                raise RuntimeError("Symphony LIVE result lineage mismatch")
        if target.repository != self.repository or target.branch != self.target_branch:
            raise RuntimeError("Symphony LIVE target identity mismatch")
        return Snapshot(f"{self.loop_id}-live-poll-{datetime.now(timezone.utc).timestamp():.6f}",
                        tuple(commands), claims, results, target, carrier, generation)

    def reserve(self, reservation: Reservation) -> str:
        command = self._get("commands", reservation.command_id)
        if command is None or command.get("record_type") != COMMAND_TYPE:
            return "CONFLICT"
        if (command.get("logical_id"), command.get("correlation_id"), command.get("generation"),
                command.get("expected_target_head")) != (reservation.logical_id, reservation.correlation_id,
                                                          reservation.generation, reservation.expected_target_head):
            return "CONFLICT"
        if self._get("claims", reservation.command_id) is not None or self._get("results", reservation.command_id) is not None:
            return "CONFLICT"
        target = self.target_reader.read_target(self.repository, self.target_pr)
        generation = self.target_reader.read_active_generation(self.loop_id)
        if (target.repository, target.branch, target.head, generation) != (
                self.repository, self.target_branch, reservation.expected_target_head, reservation.generation):
            return "CONFLICT"
        expected_tree = command.get("expected_target_tree")
        if expected_tree is not None and target.tree != expected_tree:
            return "CONFLICT"
        record = {
            "record_type": CLAIM_TYPE, "protocol_version": PROTOCOL_VERSION,
            "claim_id": reservation.reservation_id, "command_id": reservation.command_id,
            "logical_id": reservation.logical_id, "correlation_id": reservation.correlation_id,
            "generation": reservation.generation, "target_repository": self.repository,
            "target_branch": self.target_branch, "head_before": target.head,
            "reservation_state": "CLAIMED", "reserved_at": datetime.now(timezone.utc).isoformat(),
        }
        return self._append("claims", record)

    def read_reservation(self, command_id: str) -> Reservation | None:
        record = self._get("claims", command_id)
        if record is None or record.get("record_type") != CLAIM_TYPE:
            return None
        return Reservation(command_id, record["logical_id"], record["correlation_id"],
                           record["generation"], record["head_before"], record["claim_id"])

    def write_receipt(self, receipt: dict[str, Any]) -> str:
        command_id = receipt.get("command_id")
        command = self._get("commands", command_id)
        claim = self._get("claims", command_id)
        if command is None or claim is None or self._get("results", command_id) is not None:
            return "CONFLICT"
        if (receipt.get("logical_id") != command["logical_id"]
                or receipt.get("correlation_id") != command["correlation_id"]
                or receipt.get("generation") != command["generation"]
                or receipt.get("expected_target_head") != command["expected_target_head"]
                or claim.get("head_before") != command["expected_target_head"]):
            return "CONFLICT"
        target = self.target_reader.read_target(self.repository, self.target_pr)
        generation = self.target_reader.read_active_generation(self.loop_id)
        if (target.repository, target.branch, generation) != (self.repository, self.target_branch,
                                                               receipt.get("generation")):
            return "CONFLICT"
        label = receipt.get("terminal_status")
        status = {"DONE": "PASS", "FAILED": "FAIL", "BLOCKED": "BLOCKED",
                  "UNKNOWN": "UNKNOWN", "STALE": "STALE"}.get(label, "UNKNOWN")
        verification = receipt.get("verification")
        start_count = receipt.get("model_start_count")
        if start_count is not None and (type(start_count) is not int or start_count not in {0, 1}):
            return "CONFLICT"
        record = {
            "record_type": RESULT_TYPE, "protocol_version": PROTOCOL_VERSION,
            "result_id": f"live-result-{command_id}", "command_id": command_id,
            "logical_id": command["logical_id"], "correlation_id": command["correlation_id"],
            "generation": command["generation"], "target_repository": self.repository,
            "target_branch": self.target_branch, "head_before": claim["head_before"],
            "head_after": target.head, "dispatch_count": 1 if receipt.get("dispatch_attempted") else 0,
            "model_start_count": start_count, "model_start_count_known": start_count is not None,
            "retry_count": 0, "fallback_count": 0, "fallback": "disabled", "status": status,
            "terminal": True,
            "verification": verification if isinstance(verification, dict) else {"status": "UNKNOWN"},
            "changed_paths": receipt.get("changed_paths", []),
            "proof_commit_sha": receipt.get("proof_commit_sha"),
            "controller_receipt": receipt,
        }
        if status == "PASS" and not _has_complete_pass_evidence(
                verification, head_before=record["head_before"], head_after=record["head_after"],
                dispatch_count=record["dispatch_count"], model_start_count=start_count,
                changed_paths=record["changed_paths"], proof_commit_sha=record["proof_commit_sha"]):
            status = record["status"] = "UNKNOWN"
        if record["status"] not in _RESULT_STATUS:
            return "CONFLICT"
        try:
            validate_live_result(record)
        except ValueError:
            return "CONFLICT"
        written = self._append("results", record)
        if written == "ACCEPTED" and status != label:
            return "AMBIGUOUS"
        return written

    def read_receipt(self, command_id: str) -> dict[str, Any] | None:
        record = self._get("results", command_id)
        if record is None or record.get("record_type") != RESULT_TYPE or record.get("terminal") is not True:
            return None
        value = record.get("controller_receipt")
        if not isinstance(value, dict):
            return None
        result = dict(value)
        result["terminal_status"] = {
            "PASS": "DONE", "FAIL": "FAILED", "BLOCKED": "BLOCKED",
            "UNKNOWN": "UNKNOWN", "STALE": "STALE",
        }[record["status"]]
        return result
