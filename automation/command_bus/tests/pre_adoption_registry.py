"""Test helper: the registry as it was before the approved DURABLE adoption, with a built-in guard.

Many static contract tests were written when every lane was PLACEHOLDER. They test properties of the
registry shape, global registration and migration preparation, not the adoption itself. This helper
gives them the same registry they always saw (the one adopted lane back at PLACEHOLDER) and nothing
else: it keeps every assertion in those tests intact.

It is also a guard. It refuses (``AssertionError``) unless every DURABLE lane in the registry it is given
is covered by a valid ``DURABLE_ADOPTION_APPROVAL_V1`` record committed in the repository, and the
adopted row equals the approved entry except display_name, is the only DURABLE row, and the other enabled lanes are PLACEHOLDER. A DURABLE lane without such a record
fails every test that loads the registry through here.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from automation.command_bus import durable_adoption_approval as dap
from automation.command_bus import durable_adoption_approval_cli as cli

REPO = Path(__file__).resolve().parents[3]
APPROVAL_PATH = REPO / "docs/evidence/signal-step7-proof5/durable-adoption-approval.json"


def approved_lanes() -> tuple[str, ...]:
    """Lanes with a committed, valid approval (validated as of the moment it was issued)."""
    if not APPROVAL_PATH.exists():
        return ()
    approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    return (cli.verify_file(APPROVAL_PATH, REPO, approval["approved_at"]),)


def pre_adoption(raw: dict[str, Any]) -> dict[str, Any]:
    """The historical all-PLACEHOLDER registry, returned only if ``raw`` passes the production guard.

    Many static contract tests describe the four-lane registry that existed before the approved adoption. They
    keep seeing exactly that registry (the committed adoption candidate with the adopted lane back at PLACEHOLDER),
    so every assertion in them stays intact. ``raw`` is the production file and is only guarded here: a DURABLE lane
    without a valid committed approval, a changed adopted row, a second DURABLE lane or an enabled non-PLACEHOLDER
    lane fails every test that loads the registry through this function.
    """
    durable = [e["loop_id"] for e in raw["loops"] if e["identity_state"] == "DURABLE"]
    if not durable:
        return copy.deepcopy(raw)
    assert tuple(durable) == approved_lanes(), f"DURABLE lane(s) {durable} have no valid adoption approval"
    guard = cli.production_registry_guard(raw, REPO)
    assert not guard, f"production registry violates the approved adoption: {guard}"
    return cli.registries_from_candidate(REPO)[0]


def adopted_snapshot() -> dict[str, Any]:
    """The registry exactly as approved for the adoption (adopted lane DURABLE, three old PLACEHOLDER rows).

    Behavioural tests that were written against that four-lane registry (lane ids, counts, notifications) read it
    from the committed candidate instead of the live production file, which later gained new rows. Production
    itself is covered by its own tests (``test_registry_five_lanes``) and by ``production_registry_guard``.
    """
    return copy.deepcopy(cli.registries_from_candidate(REPO)[1])
