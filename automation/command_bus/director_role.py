"""Director role: one director at a time, takeover in config order (docs/RELAY_TOWER_DIRECTION_V4.md section 5, S6).

The director is a role, not a fixed AI.  The role lives in an append-only event chain (the durable record), so any
AI can resume from it:

* ``ACQUIRE``  - a vacant role is taken (generation + 1).
* ``RENEW``    - the holder extends its lease (same generation).
* ``HANDOVER`` - the next AI in ``fallback_order`` takes an expired role (generation + 1); a Japanese handover note
  is required.
* ``RELEASE``  - the holder gives the role up.

Every event carries a fencing token that only grows, so a director that lost the role cannot act with an old
token.  The AI at ``fallback_order[0]`` is the primary; any other holder is a stand-in and may only do static work
and status reports, within a daily cap.  Nobody acting as director merges, changes production settings, or (as a
stand-in) changes code: Merge stays with the owner's chat approval.  Antigravity is never a candidate.

The existing owner chain (``loop_owner.py``) is not reused directly: its roles are fixed to SEMI_AUTO / AUTO and
each event is bound to a PR head and receipts.  The same ideas are kept: append-only chain, generation fencing,
lease expiry and an explicit handover.

Pure functions only: nothing here reads or writes GitHub or starts a provider.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .approval_comment import check_ai_write, load_policy

__all__ = ["DirectorConfig", "DirectorState", "DirectorError", "load_config", "project", "acquire", "renew",
           "release", "takeover", "check_action", "handover_report_ja"]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "director_role.json"
EVENTS = {"ACQUIRE", "RENEW", "HANDOVER", "RELEASE"}
ACTIONS = {"STATIC_WORK", "STATUS_REPORT", "CODE_CHANGE_PR", "MERGE", "PROD_SETTING_CHANGE"}
_NEVER = {"MERGE", "PROD_SETTING_CHANGE"}
_NEVER_CANDIDATE = {"antigravity"}
_CONFIG_KEYS = {"schema_version", "fallback_order", "lease_minutes", "standin_daily_cap", "standin_actions",
                "primary_actions"}
_EVENT_KEYS = {"event", "holder", "generation", "fencing_token", "at", "expires_at", "previous_holder", "note_ja"}


class DirectorError(ValueError):
    """Malformed config or chain, or a refused step (fail closed)."""


@dataclass(frozen=True)
class DirectorConfig:
    fallback_order: tuple[str, ...]
    lease_minutes: int
    standin_daily_cap: int
    standin_actions: frozenset[str]
    primary_actions: frozenset[str]


@dataclass(frozen=True)
class DirectorState:
    status: str                 # VACANT, ACTIVE or EXPIRED
    holder: str | None
    generation: int
    fencing_token: int
    expires_at: datetime | None


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> DirectorConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != _CONFIG_KEYS or raw["schema_version"] != 1:
        raise DirectorError("CONFIG_SHAPE")
    order = raw["fallback_order"]
    agents = set(load_policy().agents)
    if not isinstance(order, list) or not order or len(set(order)) != len(order) \
            or not set(order) <= agents - _NEVER_CANDIDATE:
        raise DirectorError("FALLBACK_ORDER")
    for key in ("lease_minutes", "standin_daily_cap"):
        if not isinstance(raw[key], int) or isinstance(raw[key], bool) or not 0 < raw[key] <= 10_000:
            raise DirectorError("CONFIG_NUMBERS")
    standin, primary = raw["standin_actions"], raw["primary_actions"]
    if not isinstance(standin, list) or not set(standin) <= {"STATIC_WORK", "STATUS_REPORT"}:
        raise DirectorError("STANDIN_ACTIONS")
    if not isinstance(primary, list) or not set(primary) <= ACTIONS - _NEVER:
        raise DirectorError("PRIMARY_ACTIONS")
    return DirectorConfig(tuple(order), raw["lease_minutes"], raw["standin_daily_cap"], frozenset(standin),
                          frozenset(primary))


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise DirectorError("TIME")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DirectorError("TIME") from exc
    if parsed.tzinfo is None:
        raise DirectorError("TIME")
    return parsed


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def project(chain: Sequence[Mapping[str, Any]], now: datetime, config: DirectorConfig) -> DirectorState:
    """Validate the whole chain and return the role as of ``now``.  Any break in the chain raises."""
    holder: str | None = None
    generation = fencing = 0
    expires: datetime | None = None
    last_at: datetime | None = None
    for event in chain:
        if not isinstance(event, Mapping) or set(event) != _EVENT_KEYS or event["event"] not in EVENTS:
            raise DirectorError("EVENT_SHAPE")
        at, kind, who = _time(event["at"]), event["event"], event["holder"]
        if last_at is not None and at < last_at:
            raise DirectorError("EVENT_ORDER")
        if who not in config.fallback_order:
            raise DirectorError("HOLDER_NOT_A_CANDIDATE")
        if not isinstance(event["fencing_token"], int) or event["fencing_token"] != fencing + 1:
            raise DirectorError("FENCING_TOKEN")
        live = holder is not None and expires is not None and at < expires
        if kind == "ACQUIRE":
            ok = holder is None and event["generation"] == generation + 1 and event["previous_holder"] is None
        elif kind == "RENEW":
            ok = who == holder and live and event["generation"] == generation
        elif kind == "HANDOVER":
            ok = (holder is not None and not live and who != holder and event["previous_holder"] == holder
                  and event["generation"] == generation + 1 and isinstance(event["note_ja"], str)
                  and event["note_ja"].strip() != "")
        else:  # RELEASE
            ok = who == holder and event["generation"] == generation
        if not ok:
            raise DirectorError(f"BAD_{kind}")
        generation, fencing, last_at = event["generation"], event["fencing_token"], at
        if kind == "RELEASE":
            holder, expires = None, None
        else:
            holder = who
            expires = _time(event["expires_at"])
            if expires <= at:
                raise DirectorError("LEASE")
    if holder is None:
        return DirectorState("VACANT", None, generation, fencing, None)
    status = "ACTIVE" if expires is not None and now < expires else "EXPIRED"
    return DirectorState(status, holder, generation, fencing, expires)


def _event(kind: str, holder: str, state: DirectorState, now: datetime, config: DirectorConfig, *,
           generation: int, previous: str | None = None, note: str | None = None) -> dict[str, Any]:
    return {"event": kind, "holder": holder, "generation": generation, "fencing_token": state.fencing_token + 1,
            "at": _iso(now), "expires_at": _iso(now + timedelta(minutes=config.lease_minutes)),
            "previous_holder": previous, "note_ja": note}


def acquire(chain: Sequence[Mapping[str, Any]], who: str, now: datetime, config: DirectorConfig,
            unavailable: Iterable[str] = ()) -> dict[str, Any]:
    """Take a vacant role.  ``who`` must be the first available AI in ``fallback_order``."""
    state = project(chain, now, config)
    if state.status != "VACANT":
        raise DirectorError("NOT_VACANT")
    _check_turn(who, config, set(unavailable))
    return _event("ACQUIRE", who, state, now, config, generation=state.generation + 1)


def renew(chain: Sequence[Mapping[str, Any]], who: str, now: datetime, config: DirectorConfig) -> dict[str, Any]:
    state = project(chain, now, config)
    if state.status != "ACTIVE" or state.holder != who:
        raise DirectorError("NOT_THE_ACTIVE_HOLDER")
    return _event("RENEW", who, state, now, config, generation=state.generation)


def release(chain: Sequence[Mapping[str, Any]], who: str, now: datetime, config: DirectorConfig) -> dict[str, Any]:
    state = project(chain, now, config)
    if state.holder != who:
        raise DirectorError("NOT_THE_HOLDER")
    event = _event("RELEASE", who, state, now, config, generation=state.generation)
    event["expires_at"] = event["at"]
    return event


def takeover(chain: Sequence[Mapping[str, Any]], who: str, now: datetime, config: DirectorConfig, *, note_ja: str,
             unavailable: Iterable[str] = ()) -> dict[str, Any]:
    """Take an expired role from its holder.  Lease expiry is required; the expired holder counts as unavailable."""
    state = project(chain, now, config)
    if state.status != "EXPIRED" or state.holder is None:
        raise DirectorError("LEASE_NOT_EXPIRED")
    if not isinstance(note_ja, str) or not note_ja.strip():
        raise DirectorError("HANDOVER_NOTE_REQUIRED")
    _check_turn(who, config, set(unavailable) | {state.holder})
    return _event("HANDOVER", who, state, now, config, generation=state.generation + 1, previous=state.holder,
                  note=note_ja.strip())


def _check_turn(who: str, config: DirectorConfig, unavailable: set[str]) -> None:
    if who not in config.fallback_order:
        raise DirectorError("NOT_A_CANDIDATE")
    ahead = config.fallback_order[:config.fallback_order.index(who)]
    if any(ai not in unavailable for ai in ahead):
        raise DirectorError("NOT_YOUR_TURN")
    if who in unavailable:
        raise DirectorError("UNAVAILABLE")


def check_action(state: DirectorState, who: str, fencing_token: int, action: str, *, standin_used_today: int,
                 config: DirectorConfig) -> tuple[bool, str]:
    """May ``who`` (holding ``fencing_token``) do ``action`` now?  Returns (ok, reason)."""
    if action not in ACTIONS:
        return False, "UNKNOWN_ACTION"
    if action in _NEVER:
        return False, "OWNER_ONLY"
    if state.status != "ACTIVE" or state.holder != who:
        return False, "NOT_THE_ACTIVE_DIRECTOR"
    if fencing_token != state.fencing_token:
        return False, "STALE_FENCING_TOKEN"
    if who == config.fallback_order[0]:
        return (True, "PRIMARY") if action in config.primary_actions else (False, "NOT_ALLOWED")
    if action not in config.standin_actions:
        return False, "STANDIN_STATIC_ONLY"
    if standin_used_today >= config.standin_daily_cap:
        return False, "STANDIN_DAILY_CAP"
    return True, "STANDIN"


def handover_report_ja(event: Mapping[str, Any], config: DirectorConfig) -> str:
    """The Japanese report for the owner after a takeover (signed, checked by the AI write rule)."""
    if event.get("event") != "HANDOVER":
        raise DirectorError("NOT_A_HANDOVER")
    holder = event["holder"]
    scope = ("いつもの担当に戻った。" if holder == config.fallback_order[0] else
             f"代理の {holder} は、調べものと状況報告だけをする（コード変更・マージ・本番設定の変更はしない・"
             f"1日 {config.standin_daily_cap} 回まで）。")
    text = (f"司令塔役の交代：{event['previous_holder']} → {holder}（第{event['generation']}世代）\n"
            f"理由：{event['previous_holder']} の担当時間が切れたため。\n"
            f"引き継ぎメモ：{event['note_ja']}\n"
            f"{scope}\n\n"
            f"AI-Agent: {holder}")
    return check_ai_write(text, load_policy())
