"""STATIC simulator for long mock campaigns (tests only; never imported by production code).

The production Loop A gate caps real Jules dispatches at 10 (human
authorization ``max_dispatches`` <= 10 and the slot ledger's fixed cap).  A
20-30 round scheduler test needs more *simulated* dispatches.  Instead of
loosening the production cap, this context manager swaps exactly those two
gates for a simulation gate while it is active:

* the authorization must say ``scope == "static-simulation-only"`` and
  ``approved_by == "static-simulator"`` (a real authorization is refused), and
* the simulated cap is explicit and still finite.

Everything else (owner fence, intent/receipt identity, carrier guard, budget
slot contiguity, campaign budget) is the production code path.  Leaving the
context restores the production gate; ``test_production_cap_is_back_after_the_simulator``
proves it.
"""
from __future__ import annotations

import contextlib
from typing import Any, Iterator
from unittest import mock

from automation.command_bus import claude_jules_dispatch, claude_jules_live_budget

SIMULATION_SCOPE = "static-simulation-only"
SIMULATION_APPROVER = "static-simulator"


@contextlib.contextmanager
def static_dispatch_simulator(cap: int) -> Iterator[None]:
    if type(cap) is not int or not 1 <= cap <= 100:
        raise ValueError("simulated cap must be a finite 1..100")
    real = claude_jules_dispatch.live_authorization_problem

    def simulated(policy: dict[str, Any], *, now: str, dispatches_used: int) -> str | None:
        auth = policy["live_dispatch_authorization"]
        if auth is None or auth.get("scope") != SIMULATION_SCOPE or auth.get("approved_by") != SIMULATION_APPROVER:
            return "static simulator refuses a non-simulation authorization"
        if dispatches_used >= cap:
            return "live-dispatch authorization budget exhausted"
        expired = real(dict(policy, live_dispatch_authorization=dict(auth, max_dispatches=10)), now=now,
                       dispatches_used=0)
        return expired  # keeps the expiry check of the production gate

    with mock.patch.object(claude_jules_dispatch, "live_authorization_problem", simulated), \
            mock.patch.object(claude_jules_live_budget, "LOOP_A_LIVE_BUDGET", cap), \
            mock.patch.object(claude_jules_live_budget.LiveBudgetLedger.__init__, "__kwdefaults__", {"cap": cap}):
        yield


def simulation_authorization(base: dict[str, Any]) -> dict[str, Any]:
    return dict(base, approved_by=SIMULATION_APPROVER, approval_ref="static-simulation", scope=SIMULATION_SCOPE,
                max_dispatches=10)
