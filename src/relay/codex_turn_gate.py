#!/usr/bin/env python3
"""Outer one-generation gate for the Codex App Server (stdio JSON-RPC).

Used as ``CODEX_PATH`` (documented codex-acp option): codex-acp runs
``<this file> app-server``; we start the real backend named by
``RELAY_GATE_BACKEND`` with the same argument and forward newline-delimited
JSON-RPC both ways, except that generation-starting requests are limited to
ONE per process. Any further one (e.g. codex-acp's fire-and-forget
title-generation turn) is answered with a JSON-RPC error and never reaches the
backend. Fail closed: unparsable client lines are not forwarded.

Same idea as the Claude Admission Gate: the host-side outer boundary, not
upstream behavior, decides how many upstream generations can happen.
Evidence: one JSON line per decision appended to ``RELAY_GATE_LOG``.
"""
import json
import os
import subprocess
import sys
import threading

# Requests that make the backend start a model generation.
GENERATION_METHODS = frozenset({
    "turn/start", "turn/steer", "review/start", "thread/compact/start", "thread/goal/set",
})
BLOCK_CODE = -32001


def _log(path, record):
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def run(argv, backend, log_path, stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    if argv != ["app-server"] or not backend:
        return 2
    out_lock = threading.Lock()

    def emit(line):
        with out_lock:
            stdout.write(line if line.endswith("\n") else line + "\n")
            stdout.flush()

    child = subprocess.Popen(
        [backend, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, bufsize=1, env=os.environ.copy(),
    )

    def pump():
        for line in child.stdout:
            emit(line)

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    allowed = 0
    try:
        for line in stdin:
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                _log(log_path, {"decision": "dropped_unparsable"})
                continue
            method = msg.get("method") if isinstance(msg, dict) else None
            if method in GENERATION_METHODS:
                if allowed >= 1:
                    _log(log_path, {"method": method, "decision": "blocked"})
                    if "id" in msg:
                        emit(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {
                            "code": BLOCK_CODE, "message": "relay gate: one generation per process"}}))
                    continue
                allowed += 1
                _log(log_path, {"method": method, "decision": "allowed"})
            child.stdin.write(line if line.endswith("\n") else line + "\n")
            child.stdin.flush()
    except BrokenPipeError:
        pass
    finally:
        try:
            child.stdin.close()
        except Exception:
            pass
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
        t.join(timeout=1)
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:], os.environ.get("RELAY_GATE_BACKEND"), os.environ.get("RELAY_GATE_LOG")))
