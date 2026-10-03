#!/usr/bin/env python3
"""Tripwire standing in for the Claude Code CLI (``CLAUDE_CODE_EXECUTABLE``) in STATIC tests.

It is NOT a fake Claude: it does nothing except record that the official adapter tried to run
the CLI (argv -> ``RELAY_TRIPWIRE_LOG``) and exit non-zero with no output. It reads no credentials
and makes no network call, so the adapter can never reach a real account or model through it.

Optional SYNTHETIC auth-status answer: if ``RELAY_TRIPWIRE_AUTH_STATUS_JSON`` is set, the exact
probe ``auth status --json`` prints that (test-supplied, synthetic) text and exits 0, so the
official adapter's own ``_auth/status_update`` push can be observed. Nothing else is ever answered.
"""
import json
import os
import sys

log = os.environ.get("RELAY_TRIPWIRE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sys.argv[1:]) + "\n")
synthetic = os.environ.get("RELAY_TRIPWIRE_AUTH_STATUS_JSON")
if synthetic is not None and sys.argv[1:] == ["auth", "status", "--json"]:
    sys.stdout.write(synthetic)
    sys.exit(0)
sys.exit(2)
