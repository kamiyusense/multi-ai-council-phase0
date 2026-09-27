"""Serve-only entrypoint for the containerized Phase 0 Admission Gate."""

from __future__ import annotations

import os
import sys

from claude_admission_gate import (
    CONTAINER_GATE_BIND_IP,
    CONTAINER_GATE_PORT,
    DispatchStore,
    make_server,
)


STATE_DIR = "/var/lib/phase0/claude-gate"
DATABASE_PATH = f"{STATE_DIR}/dispatches.sqlite3"
UPSTREAM_URL = "https://api.anthropic.com"


def create_open_existing_server(env: dict[str, str]):
    """Open one already-provisioned store; this function never bootstraps it."""
    expected = {
        "PHASE0_GATE_MODE": "OPEN_EXISTING_ONLY",
        "PHASE0_GATE_BIND": CONTAINER_GATE_BIND_IP,
        "PHASE0_GATE_PORT": str(CONTAINER_GATE_PORT),
        "PHASE0_GATE_STATE_DIR": STATE_DIR,
        "PHASE0_GATE_UPSTREAM_URL": UPSTREAM_URL,
    }
    for name, value in expected.items():
        if env.get(name) != value:
            raise ValueError("required fixed Gate setting is missing or mismatched")
    expected_store_id = env.get("PHASE0_GATE_EXPECTED_STORE_ID", "")
    store = DispatchStore.open_production(
        DATABASE_PATH,
        state_dir=STATE_DIR,
        expected_store_id=expected_store_id,
    )
    return make_server(
        store=store,
        upstream_url=UPSTREAM_URL,
        bind_host=CONTAINER_GATE_BIND_IP,
        container_mode=True,
    )


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    if argv != ["serve"]:
        print("BLOCKED: only the OPEN_EXISTING_ONLY serve mode is supported", file=sys.stderr)
        return 64
    try:
        server = create_open_existing_server(env)
    except Exception:
        print("BLOCKED: existing Gate store or fixed topology is unavailable; no bootstrap or retry", file=sys.stderr)
        return 78
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
