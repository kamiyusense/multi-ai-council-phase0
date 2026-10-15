"""Provider / billing route guard for long Claude AUTO campaigns (STATIC, no provider call).

The campaign may keep working for hours, retry reads and run correctives.  What
it must never do is run provider work on a route the user has not accepted:
an API-key REST route, a metered / overage route, or a route nobody can name.
Authentication and billing are separate facts and are judged separately:

* ``auth_class``    how the call authenticates: ``ACCOUNT_OAUTH`` (Google
  account login, e.g. Jules Tools CLI), ``REST_API_KEY`` (``X-Goog-Api-Key``),
  or ``UNKNOWN``.  An API key is not proof of metered billing, and an account
  login is not proof of subscription-only billing.
* ``billing_class`` what the evidence says about cost: ``SUBSCRIPTION_CONFIRMED``,
  ``METERED_CONFIRMED``, ``OVERAGE_CONFIRMED`` or ``BILLING_UNKNOWN``.

``classify_route`` reads a digest-bound ``PROVIDER_ROUTE_DECLARATION_V1``
record into one ``RouteVerdict`` with both classes and a summary ``verdict``:
``ACCOUNT_OAUTH_CONFIRMED`` / ``REST_API_KEY`` / ``METERED_CONFIRMED`` /
``OVERAGE_CONFIRMED`` / ``AUTH_BROKEN`` / ``UNKNOWN_ROUTE``.  A missing,
tampered, malformed, expired, not-yet-valid or foreign record is
``UNKNOWN_ROUTE``; nothing is inferred from silence.

``gate`` decides one operation kind.  Only provider execution is ever stopped:
``LOCAL_STATIC`` work (tests, fixtures, docs, GitHub readback, non-default
branch writes, analysis) is always allowed, so a blocked route never stops the
campaign's independent safe work.

=========================  ==================================================
route                      provider operations
=========================  ==================================================
ACCOUNT_OAUTH_CONFIRMED    READ_ONLY_LIVE allowed (user decision D2, 2026-10-08:
                           existing-session reads without an API key);
                           SUBSCRIPTION_MODEL_WORK only with
                           ``billing_class == SUBSCRIPTION_CONFIRMED``
REST_API_KEY               HARD_STOP (user decision D1, 2026-10-08), except
                           SUBSCRIPTION_MODEL_WORK on the carrier transport
                           under an owner-declared record that is at most
                           4 hours long and declares subscription billing
                           (owner decisions 2026-10-11 and 2026-10-15)
METERED / OVERAGE          HARD_STOP
AUTH_BROKEN                STOP_PROVIDER (re-login is a human action)
UNKNOWN_ROUTE              STOP_PROVIDER, human must declare the route
=========================  ==================================================

``PAID_OR_UNKNOWN_PROVIDER`` is never automatic.  This module grants no
authority: dispatch authorization, owner fence and budget still apply.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from .claude_jules_dispatch import sha256_of

ROUTE_PROFILE = "PROVIDER_ROUTE_DECLARATION_V1"

# summary verdicts
ACCOUNT_OAUTH_CONFIRMED = "ACCOUNT_OAUTH_CONFIRMED"
REST_API_KEY = "REST_API_KEY"
METERED_CONFIRMED = "METERED_CONFIRMED"
OVERAGE_CONFIRMED = "OVERAGE_CONFIRMED"
AUTH_BROKEN = "AUTH_BROKEN"
UNKNOWN_ROUTE = "UNKNOWN_ROUTE"
ROUTE_VERDICTS = (ACCOUNT_OAUTH_CONFIRMED, REST_API_KEY, METERED_CONFIRMED, OVERAGE_CONFIRMED, AUTH_BROKEN,
                  UNKNOWN_ROUTE)

# auth / billing classes
ACCOUNT_OAUTH = "ACCOUNT_OAUTH"
UNKNOWN_AUTH = "UNKNOWN"
SUBSCRIPTION_CONFIRMED = "SUBSCRIPTION_CONFIRMED"
BILLING_UNKNOWN = "BILLING_UNKNOWN"

# operation kinds
LOCAL_STATIC = "LOCAL_STATIC"
READ_ONLY_LIVE = "READ_ONLY_LIVE"
SUBSCRIPTION_MODEL_WORK = "SUBSCRIPTION_MODEL_WORK"
PAID_OR_UNKNOWN_PROVIDER = "PAID_OR_UNKNOWN_PROVIDER"
OPERATION_KINDS = (LOCAL_STATIC, READ_ONLY_LIVE, SUBSCRIPTION_MODEL_WORK, PAID_OR_UNKNOWN_PROVIDER)

# decisions
ALLOW = "ALLOW"
STOP_PROVIDER = "STOP_PROVIDER"      # provider execution paused; independent safe work continues
HARD_STOP = "HARD_STOP"              # billing boundary: provider execution stops until a human decides

_AUTH_METHODS = {"account_oauth": ACCOUNT_OAUTH, "api_key": REST_API_KEY, "unknown": UNKNOWN_AUTH}
_BILLING = {"subscription": SUBSCRIPTION_CONFIRMED, "metered": METERED_CONFIRMED, "overage": OVERAGE_CONFIRMED,
            "unknown": BILLING_UNKNOWN}
_AUTH_STATES = {"ok", "broken"}
_KEYS = {"schema_version", "profile", "provider", "transport", "auth_method", "billing_route", "auth_state",
         "declared_by", "evidence_refs", "declared_at", "expires_at", "declaration_sha256"}
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# The one narrow exception to the REST API-key hard stop (owner decision 2026-10-15, after the owner's 2026-10-11
# decision that the Jules API-key route is accepted): only the owner may declare it, only for the carrier transport,
# only with subscription billing, and only for a record that lives at most four hours. Nothing else widens.
OWNER_DECLARER = "owner"
OWNER_API_KEY_TRANSPORT = "carrier-rest-api-key"
OWNER_API_KEY_MAX_WINDOW = timedelta(hours=4)


@dataclass(frozen=True)
class RouteVerdict:
    verdict: str
    reason: str
    provider: str | None = None
    transport: str | None = None
    auth_class: str = UNKNOWN_AUTH
    billing_class: str = BILLING_UNKNOWN
    owner_time_boxed: bool = False  # set only by classify_route for the narrow owner exception above


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


def build_route_declaration(*, provider: str, transport: str, auth_method: str, billing_route: str,
                            auth_state: str, declared_by: str, evidence_refs: list[str], declared_at: str,
                            expires_at: str) -> dict[str, Any]:
    record = {"schema_version": 1, "profile": ROUTE_PROFILE, "provider": provider, "transport": transport,
              "auth_method": auth_method, "billing_route": billing_route, "auth_state": auth_state,
              "declared_by": declared_by, "evidence_refs": list(evidence_refs), "declared_at": declared_at,
              "expires_at": expires_at}
    record["declaration_sha256"] = sha256_of(record)
    return record


def classify_route(declaration: Any, *, provider: str, transport: str, now: str) -> RouteVerdict:
    """One verdict for ``provider`` over ``transport`` at ``now``; unproven is UNKNOWN_ROUTE."""
    if declaration is None:
        return RouteVerdict(UNKNOWN_ROUTE, "no provider route declaration", provider, transport)
    try:
        if not isinstance(declaration, dict) or set(declaration) != _KEYS:
            raise ValueError("declaration keys mismatch")
        if declaration["schema_version"] != 1 or declaration["profile"] != ROUTE_PROFILE:
            raise ValueError("unsupported declaration")
        if declaration["declaration_sha256"] != sha256_of(
                {k: v for k, v in declaration.items() if k != "declaration_sha256"}):
            raise ValueError("declaration digest mismatch")
        for key in ("provider", "transport", "declared_by"):
            if not isinstance(declaration[key], str) or not _ID.fullmatch(declaration[key]):
                raise ValueError(f"{key} invalid")
        if declaration["auth_method"] not in _AUTH_METHODS or declaration["billing_route"] not in _BILLING \
                or declaration["auth_state"] not in _AUTH_STATES:
            raise ValueError("auth_method, billing_route or auth_state not recognised")
        refs = declaration["evidence_refs"]
        if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r.strip() for r in refs):
            raise ValueError("evidence_refs required")
        declared, expires, at = _time(declaration["declared_at"]), _time(declaration["expires_at"]), _time(now)
    except (KeyError, TypeError, ValueError) as exc:
        return RouteVerdict(UNKNOWN_ROUTE, f"route declaration invalid: {exc}", provider, transport)
    if declaration["provider"] != provider or declaration["transport"] != transport:
        return RouteVerdict(UNKNOWN_ROUTE, "route declaration names another provider or transport", provider,
                            transport)
    if not declared <= at < expires:
        return RouteVerdict(UNKNOWN_ROUTE, "route declaration is not current", provider, transport)
    auth, billing = _AUTH_METHODS[declaration["auth_method"]], _BILLING[declaration["billing_route"]]
    common = dict(provider=provider, transport=transport, auth_class=auth, billing_class=billing)
    if billing in {METERED_CONFIRMED, OVERAGE_CONFIRMED}:
        return RouteVerdict(billing, f"{declaration['billing_route']} billing declared", **common)
    if auth == REST_API_KEY:
        owner_window = (billing == SUBSCRIPTION_CONFIRMED and declaration["declared_by"] == OWNER_DECLARER
                        and transport == OWNER_API_KEY_TRANSPORT and declaration["auth_state"] == "ok"
                        and expires - declared <= OWNER_API_KEY_MAX_WINDOW)
        return RouteVerdict(REST_API_KEY, "REST API-key authentication", **common, owner_time_boxed=owner_window)
    if declaration["auth_state"] == "broken":
        return RouteVerdict(AUTH_BROKEN, "authentication broken", **common)
    if auth == ACCOUNT_OAUTH:
        return RouteVerdict(ACCOUNT_OAUTH_CONFIRMED, f"account login; billing {billing}", **common)
    return RouteVerdict(UNKNOWN_ROUTE, "authentication method unknown", **common)


def detect_route_drift(previous: RouteVerdict, current: RouteVerdict) -> bool:
    """True when anything about the route changed; a change is never absorbed silently."""
    return (previous.verdict, previous.provider, previous.transport, previous.auth_class, previous.billing_class) \
        != (current.verdict, current.provider, current.transport, current.auth_class, current.billing_class)


def gate(operation: str, route: RouteVerdict) -> GateDecision:
    def stop(decision: str, reason: str, human: bool) -> GateDecision:
        return GateDecision(decision, reason, False, True, human)

    if operation not in OPERATION_KINDS:
        return stop(HARD_STOP, f"unknown operation kind {operation!r}", True)
    if operation == LOCAL_STATIC:
        return GateDecision(ALLOW, "local/static/GitHub-safe work never depends on the provider route",
                            False, True, False)
    if operation == PAID_OR_UNKNOWN_PROVIDER:
        return stop(HARD_STOP, "paid or unknown provider execution is never automatic", True)
    verdict = route.verdict
    if verdict in {METERED_CONFIRMED, OVERAGE_CONFIRMED}:
        return stop(HARD_STOP, f"billing boundary: {verdict}", True)
    if verdict == REST_API_KEY:
        if operation == SUBSCRIPTION_MODEL_WORK and route.owner_time_boxed and route.billing_class == SUBSCRIPTION_CONFIRMED:
            return GateDecision(ALLOW, "owner-declared, time-boxed (<= 4 h) API-key carrier route with subscription "
                                "billing (owner decisions 2026-10-11 and 2026-10-15)", True, True, False)
        return stop(HARD_STOP, "REST API-key route is not approved for provider execution (D1)", True)
    if verdict == AUTH_BROKEN:
        return stop(STOP_PROVIDER, "authentication broken: provider paused, re-login needed; safe work continues",
                    True)
    if verdict == UNKNOWN_ROUTE:
        return stop(STOP_PROVIDER, f"provider route unknown ({route.reason}); safe work continues", True)
    if verdict == ACCOUNT_OAUTH_CONFIRMED:
        if operation == READ_ONLY_LIVE:
            return GateDecision(ALLOW, "existing-session read over an account login (D2)", True, True, False)
        if route.billing_class == SUBSCRIPTION_CONFIRMED:
            return GateDecision(ALLOW, "model work on an account route with subscription billing evidence",
                                True, True, False)
        return stop(STOP_PROVIDER, "account login without subscription billing evidence: no new model work", True)
    return stop(HARD_STOP, f"unrecognised route verdict {verdict!r}", True)


def route_resolver(declaration: Any, *, provider: str, transport: str) -> Callable[[str], RouteVerdict]:
    """A ``now -> RouteVerdict`` callable for the dispatcher; re-classified at every check."""
    return lambda now: classify_route(declaration, provider=provider, transport=transport, now=now)
