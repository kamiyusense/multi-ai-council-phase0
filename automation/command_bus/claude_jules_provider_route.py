"""Provider / billing route guard for long Claude AUTO campaigns (STATIC, no provider call).

The campaign may keep working for hours, retry reads and run correctives.  What
it must never do is keep running after the provider route stopped being the
subscription-only route the user approved: an API-key / metered / overage /
unknown billing route is a HARD STOP for every provider execution, and nothing
here infers SAFE from silence.

Two things are separated on purpose:

* ``classify_route`` turns a durable ``PROVIDER_ROUTE_DECLARATION_V1`` record
  (who declared which provider, auth method and billing route, with evidence
  and an expiry) into one route verdict.  A missing, malformed, expired or
  self-contradictory declaration is ``UNKNOWN_BILLING_ROUTE``.
* ``gate`` decides one operation kind against that verdict.  Local / static /
  GitHub-safe work never depends on the provider route, so a broken or unsafe
  route stops provider execution only; the rest of the campaign keeps going.

Operation kinds:

``LOCAL_STATIC``             local tests, fixtures, docs, GitHub readback and
                             non-default-branch writes: never a provider call.
``READ_ONLY_LIVE``           read of an existing provider object (e.g. one
                             Jules session GET); no new model turn.
``SUBSCRIPTION_MODEL_WORK``  new worker/model work inside the subscription.
``PAID_OR_UNKNOWN_PROVIDER`` API key / metered / external paid execution.

This module grants no authority; the dispatcher's authorization, owner fence
and budget still apply on top of an ``ALLOW``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .claude_jules_dispatch import sha256_of

ROUTE_PROFILE = "PROVIDER_ROUTE_DECLARATION_V1"

SUBSCRIPTION_CONFIRMED = "SUBSCRIPTION_CONFIRMED"
API_KEY_CONFIRMED = "API_KEY_CONFIRMED"
METERED_CONFIRMED = "METERED_CONFIRMED"
OVERAGE_CONFIRMED = "OVERAGE_CONFIRMED"
UNKNOWN_BILLING_ROUTE = "UNKNOWN_BILLING_ROUTE"
AUTH_BROKEN = "AUTH_BROKEN"
ROUTE_VERDICTS = (SUBSCRIPTION_CONFIRMED, API_KEY_CONFIRMED, METERED_CONFIRMED, OVERAGE_CONFIRMED,
                  UNKNOWN_BILLING_ROUTE, AUTH_BROKEN)

LOCAL_STATIC = "LOCAL_STATIC"
READ_ONLY_LIVE = "READ_ONLY_LIVE"
SUBSCRIPTION_MODEL_WORK = "SUBSCRIPTION_MODEL_WORK"
PAID_OR_UNKNOWN_PROVIDER = "PAID_OR_UNKNOWN_PROVIDER"
OPERATION_KINDS = (LOCAL_STATIC, READ_ONLY_LIVE, SUBSCRIPTION_MODEL_WORK, PAID_OR_UNKNOWN_PROVIDER)

ALLOW = "ALLOW"
STOP_PROVIDER = "STOP_PROVIDER"      # provider execution stops; independent safe work continues
HARD_STOP = "HARD_STOP"              # billing boundary: provider execution stops and a human must decide

# billing routes a declaration may name, mapped to the verdict they produce
_BILLING = {
    "subscription": SUBSCRIPTION_CONFIRMED,
    "api_key": API_KEY_CONFIRMED,
    "metered": METERED_CONFIRMED,
    "overage": OVERAGE_CONFIRMED,
    "unknown": UNKNOWN_BILLING_ROUTE,
}
_AUTH_STATES = {"ok", "broken"}
_KEYS = {"schema_version", "profile", "provider", "auth_method", "billing_route", "auth_state",
         "declared_by", "evidence_refs", "declared_at", "expires_at", "declaration_sha256"}
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class RouteVerdict:
    verdict: str
    reason: str
    provider: str | None = None


@dataclass(frozen=True)
class GateDecision:
    decision: str
    reason: str
    provider_execution_allowed: bool
    local_safe_work_allowed: bool
    requires_human: bool


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp needs a timezone")
    return parsed


def build_route_declaration(*, provider: str, auth_method: str, billing_route: str, auth_state: str,
                            declared_by: str, evidence_refs: list[str], declared_at: str,
                            expires_at: str) -> dict[str, Any]:
    record = {"schema_version": 1, "profile": ROUTE_PROFILE, "provider": provider, "auth_method": auth_method,
              "billing_route": billing_route, "auth_state": auth_state, "declared_by": declared_by,
              "evidence_refs": list(evidence_refs), "declared_at": declared_at, "expires_at": expires_at}
    record["declaration_sha256"] = sha256_of(record)
    return record


def classify_route(declaration: Any, *, provider: str, now: str) -> RouteVerdict:
    """One verdict for ``provider`` at ``now``; anything not positively proven is UNKNOWN_BILLING_ROUTE."""
    if declaration is None:
        return RouteVerdict(UNKNOWN_BILLING_ROUTE, "no provider route declaration")
    try:
        if not isinstance(declaration, dict) or set(declaration) != _KEYS:
            raise ValueError("declaration keys mismatch")
        if declaration["schema_version"] != 1 or declaration["profile"] != ROUTE_PROFILE:
            raise ValueError("unsupported declaration")
        if declaration["declaration_sha256"] != sha256_of(
                {k: v for k, v in declaration.items() if k != "declaration_sha256"}):
            raise ValueError("declaration digest mismatch")
        for key in ("provider", "auth_method", "declared_by"):
            if not isinstance(declaration[key], str) or not _ID.fullmatch(declaration[key]):
                raise ValueError(f"{key} invalid")
        if declaration["billing_route"] not in _BILLING or declaration["auth_state"] not in _AUTH_STATES:
            raise ValueError("billing_route or auth_state not recognised")
        refs = declaration["evidence_refs"]
        if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r.strip() for r in refs):
            raise ValueError("evidence_refs required")
        declared, expires, at = _time(declaration["declared_at"]), _time(declaration["expires_at"]), _time(now)
    except (KeyError, TypeError, ValueError) as exc:
        return RouteVerdict(UNKNOWN_BILLING_ROUTE, f"route declaration invalid: {exc}")
    if declaration["provider"] != provider:
        return RouteVerdict(UNKNOWN_BILLING_ROUTE, "route declaration names another provider")
    if not declared <= at < expires:
        return RouteVerdict(UNKNOWN_BILLING_ROUTE, "route declaration is not current", provider)
    verdict = _BILLING[declaration["billing_route"]]
    if verdict == SUBSCRIPTION_CONFIRMED and declaration["auth_method"] in {"api_key", "service_account_key"}:
        # An API key is the classic path to usage billing: never subscription unless declared otherwise.
        return RouteVerdict(API_KEY_CONFIRMED, "subscription declared but authentication is an API key", provider)
    if declaration["auth_state"] == "broken":
        if verdict == SUBSCRIPTION_CONFIRMED:
            return RouteVerdict(AUTH_BROKEN, "subscription route but authentication is broken", provider)
        return RouteVerdict(verdict, f"{declaration['billing_route']} route (authentication also broken)", provider)
    return RouteVerdict(verdict, f"declared {declaration['billing_route']} via {declaration['auth_method']}", provider)


def detect_route_drift(previous: RouteVerdict, current: RouteVerdict) -> bool:
    """True when the route changed in a way that must not be absorbed silently."""
    return previous.verdict != current.verdict or previous.provider != current.provider


def gate(operation: str, route: RouteVerdict) -> GateDecision:
    if operation not in OPERATION_KINDS:
        return GateDecision(HARD_STOP, f"unknown operation kind {operation!r}", False, True, True)
    if operation == LOCAL_STATIC:
        return GateDecision(ALLOW, "local/static/GitHub-safe work never depends on the provider route", False, True, False)
    if operation == PAID_OR_UNKNOWN_PROVIDER:
        return GateDecision(HARD_STOP, "paid or unknown provider execution is never automatic", False, True, True)
    if route.verdict == SUBSCRIPTION_CONFIRMED:
        return GateDecision(ALLOW, f"{operation} on a confirmed subscription route", True, True, False)
    if route.verdict == AUTH_BROKEN:
        return GateDecision(STOP_PROVIDER, "authentication broken: provider execution paused, safe work continues",
                            False, True, False)
    if route.verdict in {API_KEY_CONFIRMED, METERED_CONFIRMED, OVERAGE_CONFIRMED, UNKNOWN_BILLING_ROUTE}:
        return GateDecision(HARD_STOP, f"billing boundary: {route.verdict} ({route.reason})", False, True, True)
    return GateDecision(HARD_STOP, f"unrecognised route verdict {route.verdict!r}", False, True, True)
