"""Jules Tools CLI read-only transport (account-login route), STATIC contract + guarded runner.

Why: the REST status route authenticates with ``X-Goog-Api-Key`` and is not
approved for provider execution (user decision D1, 2026-10-08).  The official
Jules Tools CLI (``npm install -g @google/jules``, ``jules login`` in a
browser) authenticates with the user's Google account instead.  User decision
D2 allows reads of *existing* sessions over such a route without asking each
time; creating sessions, sending messages and starting model work are not
covered.

What this module guarantees, independent of the CLI's own behaviour:

* UTF-8 output is decoded explicitly on every platform; invalid bytes fail
  without replacement, output promotion, or a decode-error retry;

* only an explicit allowlist of read commands can run
  (``jules version``, ``jules remote list --session``,
  ``jules remote list --repo``); ``remote new``, ``login``/``logout``, the
  interactive TUI (no arguments), ``remote pull`` (it writes code locally) and
  anything else are refused before a process starts;
* the child process never sees an API key: every environment variable whose
  name contains ``API_KEY``, ``TOKEN``, ``SECRET`` or ``CREDENTIAL`` (plus
  ``GOOGLE_APPLICATION_CREDENTIALS``) is removed, so the CLI cannot silently
  fall back to a key;
* reads may be retried with a bounded backoff (they have no side effect); a
  command that is not allowlisted is never retried because it never ran;
* output is never interpreted beyond what is certain.  The CLI publishes no
  machine-readable format.  ``parse_session_listing`` is fixed against the
  table that ``jules remote list --session`` printed with CLI v0.1.42 on
  2026-10-08 (columns ``ID / Description / Repo / Last active / Status``,
  fields separated by two or more spaces).  Any other header is refused, a row
  that does not split into exactly five fields is skipped as unparseable, and
  only the exact status texts seen in that sample are mapped; everything else
  is ``UNKNOWN``.  ``find_session`` answers only whether the exact session id
  appears exactly once.

``build_cli_settlement_observation`` turns one parsed row into a create-only
``CLAUDE_AUTO_CLI_SETTLEMENT_OBSERVATION_V1`` record bound to the command,
the session, the CLI version/commit, the digest of the whole listing and the
dispatch correlation (workflow run, job, PR and the PR's Jules task id).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .claude_jules_dispatch import EVIDENCE_ROOT, canonical_json, sha256_of

CLI = "jules"
READ_ONLY_COMMANDS = (
    ("version",),
    ("remote", "list", "--session"),
    ("remote", "list", "--repo"),
)
FORBIDDEN_HINTS = ("new", "login", "logout", "pull", "--parallel")
_SECRET_NAME = re.compile(r"API_KEY|TOKEN|SECRET|CREDENTIAL|PASSWORD", re.I)
_EXTRA_SECRET_NAMES = {"GOOGLE_APPLICATION_CREDENTIALS"}
_SESSION_ID = re.compile(r"^[0-9]{1,32}$")
MAX_READ_ATTEMPTS = 4
BACKOFF_SECONDS = (0, 15, 60, 180)


@dataclass(frozen=True)
class CliRead:
    status: str                    # OK / REFUSED / UNAVAILABLE / FAILED
    argv: tuple[str, ...]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    attempts: int = 0
    reason: str = ""
    attempt_log: list[dict[str, Any]] = field(default_factory=list)


def command_allowed(args: Sequence[str]) -> tuple[bool, str]:
    """Allow only the exact read commands above; everything else is refused."""
    args = tuple(args)
    if not args:
        return False, "no arguments starts the interactive TUI, which can create sessions"
    if args in READ_ONLY_COMMANDS:
        return True, "read-only command"
    for hint in FORBIDDEN_HINTS:
        if hint in args:
            return False, f"'{hint}' is not a read-only command"
    return False, "not in the read-only allowlist"


def sanitized_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """The child environment without any API key, token, secret or credential variable."""
    source = dict(os.environ if env is None else env)
    return {k: v for k, v in source.items() if not _SECRET_NAME.search(k) and k not in _EXTRA_SECRET_NAMES}


def run_read(args: Sequence[str], *, runner: Callable[..., Any] = subprocess.run,
             sleep: Callable[[float], None] = time.sleep, env: dict[str, str] | None = None,
             timeout: float = 120, max_attempts: int = MAX_READ_ATTEMPTS) -> CliRead:
    """Run one allowlisted read, retrying transient failures with a bounded backoff."""
    argv = (CLI, *args)
    ok, reason = command_allowed(args)
    if not ok:
        return CliRead("REFUSED", argv, reason=reason)
    if not 1 <= max_attempts <= MAX_READ_ATTEMPTS:
        raise ValueError(f"max_attempts must be 1..{MAX_READ_ATTEMPTS}")
    child_env = sanitized_env(env)
    log: list[dict[str, Any]] = []
    last: CliRead | None = None
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            sleep(BACKOFF_SECONDS[attempt - 1])
        try:
            proc = runner(list(argv), capture_output=True, text=True, encoding="utf-8", errors="strict",
                          timeout=timeout, env=child_env)
        except FileNotFoundError:
            return CliRead("UNAVAILABLE", argv, attempts=attempt, reason="jules CLI is not installed",
                           attempt_log=log + [{"attempt": attempt, "result": "not installed"}])
        except UnicodeDecodeError:
            # Corrupt/mismatched encoding is not a transient network failure.
            # Do not substitute characters into session identities or retry.
            return CliRead("FAILED", argv, attempts=attempt, reason="invalid UTF-8 CLI output",
                           attempt_log=log + [{"attempt": attempt, "result": "invalid UTF-8"}])
        except subprocess.TimeoutExpired:
            log.append({"attempt": attempt, "result": "timeout"})
            last = CliRead("FAILED", argv, attempts=attempt, reason="timeout", attempt_log=list(log))
            continue
        log.append({"attempt": attempt, "result": f"exit {proc.returncode}"})
        if proc.returncode == 0:
            return CliRead("OK", argv, proc.returncode, proc.stdout, proc.stderr, attempt, "read ok", list(log))
        last = CliRead("FAILED", argv, proc.returncode, proc.stdout, proc.stderr, attempt,
                       f"exit {proc.returncode}", list(log))
    assert last is not None
    return last


def find_session(listing: str, session_id: str) -> dict[str, Any]:
    """Whether ``session_id`` appears exactly once as a whole token; nothing else is inferred."""
    if not _SESSION_ID.fullmatch(str(session_id or "")):
        raise ValueError("session id must be digits")
    hits = [line for line in listing.splitlines() if re.search(rf"(?<![0-9]){session_id}(?![0-9])", line)]
    if len(hits) == 1:
        found = "FOUND"
    elif not hits:
        found = "NOT_FOUND"
    else:
        found = "AMBIGUOUS"
    return {"session_id": session_id, "presence": found, "line_count": len(hits),
            "state": "UNKNOWN", "pr_url": "UNKNOWN",
            "note": "no documented machine-readable CLI output; state/PR need a recorded sample and a fixed parser"}


LISTING_HEADER = ("ID", "Description", "Repo", "Last active", "Status")
# exact status texts observed with CLI v0.1.42; the column may truncate long values
_STATUS = {"Completed": ("COMPLETED", "SETTLED"), "Failed": ("FAILED", "SETTLED"),
           "In Progress": ("IN_PROGRESS", "RUNNING")}
_AWAITING_PREFIX = "Awaiting User F"          # "Awaiting User Feedback", truncated by the column
CLI_SETTLEMENT_PROFILE = "CLAUDE_AUTO_CLI_SETTLEMENT_OBSERVATION_V1"
CLI_TRANSPORT = "jules-tools-cli"
_FIELD_SPLIT = re.compile(r" {2,}")
_OBS_KEYS = {"schema_version", "profile", "command_id", "session_id", "transport", "cli_version", "cli_commit",
             "cli_command", "listing_sha256", "row", "row_status", "provider_state", "settlement", "repo_prefix",
             "correlation", "observed_at", "observation_sha256"}


def classify_status(text: str) -> tuple[str, str]:
    """``(provider_state, settlement)`` for one status cell; unknown text is never settled."""
    if text in _STATUS:
        return _STATUS[text]
    if text.startswith("Awaiting User") and _AWAITING_PREFIX.startswith(text[:len(_AWAITING_PREFIX)]):
        return "AWAITING_USER_FEEDBACK", "RUNNING"
    return "UNKNOWN", "UNKNOWN"


def parse_session_listing(text: str) -> dict[str, Any]:
    """Rows of ``jules remote list --session``; refuses any header other than the recorded one."""
    lines = [line.rstrip() for line in text.splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines:
        raise ValueError("empty session listing")
    header = tuple(_FIELD_SPLIT.split(lines[0].strip()))
    if header != LISTING_HEADER:
        raise ValueError(f"unrecognised session listing header {header!r}")
    rows, unparseable = [], 0
    for line in lines[1:]:
        fields = _FIELD_SPLIT.split(line.strip())
        if len(fields) != len(LISTING_HEADER) or not _SESSION_ID.fullmatch(fields[0]):
            unparseable += 1
            continue
        state, settlement = classify_status(fields[4])
        rows.append({"session_id": fields[0], "description": fields[1], "repo": fields[2],
                     "last_active": fields[3], "status": fields[4], "provider_state": state,
                     "settlement": settlement, "row": line.strip()})
    return {"rows": rows, "unparseable_rows": unparseable,
            "listing_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def build_cli_settlement_observation(*, command_id: str, session_id: str, listing: str, cli_version: str,
                                     cli_commit: str, expected_repo: str, correlation: dict[str, Any],
                                     observed_at: str) -> dict[str, Any]:
    """One create-only settlement observation for ``session_id`` from a recorded listing (no guessing)."""
    if not _SESSION_ID.fullmatch(str(session_id or "")):
        raise ValueError("session id must be digits")
    if str(correlation.get("pr_task_id")) != session_id or str(correlation.get("dispatch_session_id")) != session_id:
        raise ValueError("correlation does not name this session")
    parsed = parse_session_listing(listing)
    hits = [r for r in parsed["rows"] if r["session_id"] == session_id]
    if len(hits) != 1:
        raise ValueError(f"session {session_id} appears {len(hits)} times in the listing")
    row = hits[0]
    prefix = row["repo"].rstrip("…")
    if not prefix or not expected_repo.startswith(prefix):
        raise ValueError("listed repository does not match the expected repository")
    record = {"schema_version": 1, "profile": CLI_SETTLEMENT_PROFILE, "command_id": command_id,
              "session_id": session_id, "transport": CLI_TRANSPORT, "cli_version": cli_version,
              "cli_commit": cli_commit, "cli_command": ["remote", "list", "--session"],
              "listing_sha256": parsed["listing_sha256"], "row": row["row"], "row_status": row["status"],
              "provider_state": row["provider_state"], "settlement": row["settlement"], "repo_prefix": prefix,
              "correlation": dict(correlation), "observed_at": observed_at}
    record["observation_sha256"] = sha256_of(record)
    return validate_cli_settlement_observation(record)


def validate_cli_settlement_observation(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _OBS_KEYS:
        raise ValueError("cli settlement observation keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != CLI_SETTLEMENT_PROFILE \
            or record["transport"] != CLI_TRANSPORT:
        raise ValueError("unsupported cli settlement observation")
    if record["observation_sha256"] != sha256_of({k: v for k, v in record.items() if k != "observation_sha256"}):
        raise ValueError("cli settlement observation digest mismatch")
    if classify_status(record["row_status"]) != (record["provider_state"], record["settlement"]):
        raise ValueError("cli settlement observation status inconsistent")
    if _FIELD_SPLIT.split(record["row"])[0] != record["session_id"]:
        raise ValueError("cli settlement observation row names another session")
    cli_settlement_path(record["command_id"])
    return record


def cli_settlement_path(command_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", command_id or ""):
        raise ValueError("unsafe command id")
    return f"{EVIDENCE_ROOT}/claude-auto-cli-settlements/{command_id}.json"


class CliSettlementStore:
    """Create-once store: one terminal CLI settlement per command; never overwritten, never resent."""

    def __init__(self, client: Any, *, data_branch: str):
        self.client, self.branch = client, data_branch

    def persist(self, record: dict[str, Any]) -> str:
        """CREATED / RECOVERED (identical) / NO_OP (already settled) / BLOCKED (conflict) / UNKNOWN (unclear)."""
        validate_cli_settlement_observation(record)
        if record["settlement"] != "SETTLED":
            return "BLOCKED"  # only a terminal observation is stored; RUNNING is re-read later
        path = cli_settlement_path(record["command_id"])
        existing = self.client.get(path, self.branch)
        if existing is not None:
            return self._compare(json.loads(existing.text), record)
        try:
            self.client.create(path, canonical_json(record), f"Claude AUTO CLI settlement {record['command_id']}",
                               self.branch)
        except Exception:
            pass  # readback decides; a create is never resent blindly
        readback = self.client.get(path, self.branch)
        if readback is None:
            return "UNKNOWN"
        stored = json.loads(readback.text)
        return "CREATED" if stored == record else self._compare(stored, record)

    @staticmethod
    def _compare(stored: Any, record: dict[str, Any]) -> str:
        if stored == record:
            return "RECOVERED"
        try:
            stored = validate_cli_settlement_observation(stored)
        except (KeyError, TypeError, ValueError):
            return "BLOCKED"
        if stored["session_id"] == record["session_id"] and stored["settlement"] == "SETTLED":
            return "NO_OP"
        return "BLOCKED"
