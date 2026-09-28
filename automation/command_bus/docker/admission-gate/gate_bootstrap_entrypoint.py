"""One-shot, no-network production Gate-state bootstrap entrypoint.

This module is invoked only by an explicit human-gated Compose profile. It does
not accept paths, identity values, credentials, provider requests, or retries.
"""

from __future__ import annotations

import os
import sys

from claude_admission_gate import initialize_production_store_once


STATE_DIR = "/var/lib/phase0/claude-gate"
CONTROL_DIR = "/var/lib/phase0"
RECEIPT_PATH = "/var/lib/phase0/claude-gate-bootstrap-receipt.json"
CONFIRMATION_ARGUMENT = "--confirm-one-time-production-bootstrap"


def run_once() -> dict:
    """Create the state and external receipt once; never derive expected ID."""
    if not os.path.ismount(CONTROL_DIR) or not os.path.ismount(STATE_DIR):
        raise RuntimeError("external control bind and gate-state volume mounts must both be present")
    return initialize_production_store_once(
        state_dir=STATE_DIR,
        receipt_path=RECEIPT_PATH,
        explicit_bootstrap=True,
        retry=0,
        fallback="disabled",
        expected_store_id=None,
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv != [CONFIRMATION_ARGUMENT]:
        print("BLOCKED: explicit one-time confirmation is required; no bootstrap attempted", file=sys.stderr)
        return 64
    try:
        receipt = run_once()
    except Exception:
        print("BLOCKED: one-time bootstrap failed or was interrupted; no retry; inspect external receipt", file=sys.stderr)
        return 78
    if (receipt.get("status") != "COMPLETE" or receipt.get("retry") != 0
            or receipt.get("fallback") != "disabled" or receipt.get("bootstrap_once") is not True):
        print("BLOCKED: bootstrap receipt is incomplete or unverifiable; no retry", file=sys.stderr)
        return 78
    print("COMPLETE: external bootstrap receipt written; retain it and independently provide its store ID to normal Gate startup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
