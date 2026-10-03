"""Read-only Claude auth evidence interface (STATIC; nothing is queried here).

The official ``claude-agent-acp`` learns the identity from ``claude auth status --json`` and maps it
with ``fromCliStatus`` (``dist/auth-status.js``): a 3P backend or gateway decides first, then an API
key, then a subscription login. This module only turns an already-received ``auth status --json``
payload into a small evidence dict with the same precedence. It never runs the CLI, logs in/out,
refreshes tokens or reads credentials, and it copies no email/organization. Anything missing or
malformed is UNKNOWN; there is no official read-only quota surface for Claude in the pinned adapter,
so quota stays UNKNOWN.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["READ_ONLY_COMMAND", "summarize_claude_auth_evidence"]

# The one read-only probe the official adapter itself runs (never executed by Relay code).
READ_ONLY_COMMAND = ("auth", "status", "--json")
UNKNOWN = "UNKNOWN"


def summarize_claude_auth_evidence(cli_status: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {"auth_state": UNKNOWN, "plan_type": UNKNOWN, "quota": UNKNOWN, "side_effects": 0}
    if isinstance(cli_status, (str, bytes)):
        try:
            cli_status = json.loads(cli_status)
        except ValueError:
            return evidence
    if not isinstance(cli_status, dict) or not isinstance(cli_status.get("loggedIn"), bool):
        return evidence
    provider = cli_status.get("apiProvider")
    key_source = cli_status.get("apiKeySource")
    subscription = cli_status.get("subscriptionType")
    if provider == "gateway" or (isinstance(provider, str) and provider and provider != "firstParty"):
        evidence["auth_state"] = "EXTERNAL_ROUTE_VIOLATION"  # Phase 0 forbids gateway / 3P cloud routes
    elif key_source:
        evidence["auth_state"] = "API_KEY_ROUTE_VIOLATION"  # an API key outranks a stored subscription login
    elif subscription:
        evidence["auth_state"] = "CLAUDE_SUBSCRIPTION_ACCOUNT"
        evidence["plan_type"] = subscription if isinstance(subscription, str) else UNKNOWN
    elif not cli_status["loggedIn"]:
        evidence["auth_state"] = "NOT_AUTHENTICATED"
    return evidence
