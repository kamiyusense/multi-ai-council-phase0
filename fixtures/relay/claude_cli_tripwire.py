#!/usr/bin/env python3
"""Tripwire standing in for the Claude Code CLI (``CLAUDE_CODE_EXECUTABLE``) in STATIC tests.

It is NOT a fake Claude: it does nothing except record that the official adapter tried to run
the CLI (argv -> ``RELAY_TRIPWIRE_LOG``) and exit non-zero with no output. It reads no credentials
and makes no network call, so the adapter can never reach a real account or model through it.
"""
import json
import os
import sys

log = os.environ.get("RELAY_TRIPWIRE_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sys.argv[1:]) + "\n")
sys.exit(2)
