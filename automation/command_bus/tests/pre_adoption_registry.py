"""Test helper: the registry as it was before the approved DURABLE adoption, with a built-in guard.

Many static contract tests were written when every lane was PLACEHOLDER. They test properties of the
registry shape, global registration and migration preparation, not the adoption itself. This helper
gives them the same registry they always saw (the one adopted lane back at PLACEHOLDER) and nothing
else: it keeps every assertion in those tests intact.

It is also a guard. It refuses (``AssertionError``) unless every DURABLE lane in the registry it is given
is covered by a valid ``DURABLE_ADOPTION_APPROVAL_V1`` record committed in the repository, and the
registry equals exactly the proposal that approval was bound to. A DURABLE lane without such a record
fails every test that loads the registry through here.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from automation.command_bus import durable_adoption_approval as dap
from automation.command_bus import durable_adoption_approval_cli as cli
from automation.command_bus.lane_identity_adoption import registry_digest

REPO = Path(__file__).resolve().parents[3]
APPROVAL_PATH = REPO / "docs/evidence/signal-step7-proof5/durable-adoption-approval.json"


def approved_lanes() -> tuple[str, ...]:
    """Lanes with a committed, valid approval (validated as of the moment it was issued)."""
    if not APPROVAL_PATH.exists():
        return ()
    approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    return (cli.verify_file(APPROVAL_PATH, REPO, approval["approved_at"]),)


def pre_adoption(raw: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(raw)
    durable = [e["loop_id"] for e in out["loops"] if e["identity_state"] == "DURABLE"]
    if not durable:
        return out
    assert tuple(durable) == approved_lanes(), f"DURABLE lane(s) {durable} have no valid adoption approval"
    approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    assert registry_digest(raw) == approval["proposed_registry_sha256"], "registry differs from the approved proposal"
    for entry in out["loops"]:
        if entry["loop_id"] in durable:
            entry["identity_state"] = "PLACEHOLDER"
    return out
