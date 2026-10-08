"""Jules Tools CLI read-only transport (account-login route), STATIC contract + guarded runner.

Why: the REST status route authenticates with ``X-Goog-Api-Key`` and is not
approved for provider execution (user decision D1, 2026-10-08).  The official
Jules Tools CLI (``npm install -g @google/jules``, ``jules login`` in a
browser) authenticates with the user's Google account instead.  User decision
D2 allows reads of *existing* sessions over such a route without asking each
time; creating sessions, sending messages and starting model work are not
covered.

What this module guarantees, independent of the CLI's own behaviour:

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
  machine-readable format, so ``find_session`` only answers whether the exact
  session id appears exactly once in the listing.  Session state, PR and
  completion are ``UNKNOWN`` until a real output sample has been recorded and
  a parser has been fixed against it.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

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
            proc = runner(list(argv), capture_output=True, text=True, timeout=timeout, env=child_env)
        except FileNotFoundError:
            return CliRead("UNAVAILABLE", argv, attempts=attempt, reason="jules CLI is not installed",
                           attempt_log=log + [{"attempt": attempt, "result": "not installed"}])
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
