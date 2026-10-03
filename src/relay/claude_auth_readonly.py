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

__all__ = [
    "AUTH_STATUS_UPDATE_METHOD", "READ_ONLY_COMMAND", "summarize_claude_auth_evidence", "summarize_claude_auth_status_update",
]

# The one read-only probe the official adapter itself runs (never executed by Relay code).
READ_ONLY_COMMAND = ("auth", "status", "--json")
# Official adapter -> client notification (``params: {authStatus: {kind, label, detail?, account?}}``).
# The adapter has already applied its own precedence (3P/gateway > API key > subscription > none);
# Relay only translates its ``kind`` and never recomputes the precedence.
AUTH_STATUS_UPDATE_METHOD = "_auth/status_update"
UNKNOWN = "UNKNOWN"
_KIND_TO_STATE = {
    "account": "CLAUDE_SUBSCRIPTION_ACCOUNT",
    "api_key": "API_KEY_ROUTE_VIOLATION",
    "gateway": "EXTERNAL_ROUTE_VIOLATION",
    "external": "EXTERNAL_ROUTE_VIOLATION",
    "none": "NOT_AUTHENTICATED",
}


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
    elif not cli_status["loggedIn"] and not key_source:
        # Mirror the official adapter: outside a 3P backend, a known logged-out
        # verdict wins before any stale subscription fields are considered.
        evidence["auth_state"] = "NOT_AUTHENTICATED"
    elif key_source:
        evidence["auth_state"] = "API_KEY_ROUTE_VIOLATION"  # an API key outranks a stored subscription login
    elif subscription:
        evidence["auth_state"] = "CLAUDE_SUBSCRIPTION_ACCOUNT"
        evidence["plan_type"] = subscription if isinstance(subscription, str) else UNKNOWN
    return evidence


def summarize_claude_auth_status_update(auth_status: Any) -> dict[str, Any]:
    """Sanitized classification of an official ``_auth/status_update`` ``authStatus`` object.

    Only ``kind`` is read. ``label``/``detail``/``account`` (plan, email, organization) are never copied,
    so the evidence carries the classification only (plan stays UNKNOWN). Missing/unknown ``kind`` -> UNKNOWN.
    """
    evidence: dict[str, Any] = {
        "auth_state": UNKNOWN, "plan_type": UNKNOWN, "quota": UNKNOWN, "side_effects": 0,
        "source": "acp_auth_status_update",
    }
    kind = auth_status.get("kind") if isinstance(auth_status, dict) else None
    if isinstance(kind, str) and kind in _KIND_TO_STATE:
        evidence["auth_state"] = _KIND_TO_STATE[kind]
    return evidence
