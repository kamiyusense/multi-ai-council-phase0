"""Standard library command-line bridge over signal_companion_core for SF-12 Windows Companion.

Subcommands:
1. state --snapshot FILE --now ISO8601Z [--max-age 600]
   Prints one JSON line {"color": ..., "reason_code": ...} to stdout.
2. notify --snapshot FILE --seen FILE [--first-run]
   Prints one JSON line {"notifications": [...], "seen_state": {...}} to stdout.

Fail-passive: missing/unreadable snapshot passed as None, malformed as text.
Missing/unreadable seen file treated as empty dict {}.
Bad arguments exit 2 via argparse.
Zero side-effects except printing to stdout: no file writes, no network, no subprocess.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from .signal_companion_core import notification_plan, tray_state


def _parse_iso8601z(val: str) -> datetime:
    if not isinstance(val, str) or not val.endswith("Z"):
        raise argparse.ArgumentTypeError("Timestamp must be ISO 8601 format ending with 'Z'")
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise argparse.ArgumentTypeError("Timestamp must include timezone Z")
        return dt
    except Exception as e:
        raise argparse.ArgumentTypeError(f"Invalid ISO 8601 timestamp: {val}") from e


def _read_snapshot_file(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return None


def _read_seen_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
            return json.loads(text)
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Signal Companion CLI Bridge")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    state_parser = subparsers.add_parser("state")
    state_parser.add_argument("--snapshot", required=True, help="Path to snapshot JSON file")
    state_parser.add_argument(
        "--now",
        required=True,
        type=_parse_iso8601z,
        help="Current time in ISO 8601 UTC Z format",
    )
    state_parser.add_argument("--max-age", type=int, default=600, help="Max snapshot age in seconds")

    notify_parser = subparsers.add_parser("notify")
    notify_parser.add_argument("--snapshot", required=True, help="Path to snapshot JSON file")
    notify_parser.add_argument("--seen", required=True, help="Path to seen state JSON file")
    notify_parser.add_argument(
        "--first-run",
        action="store_true",
        default=False,
        help="First run flag",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "state":
        snapshot_raw = _read_snapshot_file(args.snapshot)
        state = tray_state(snapshot_raw, args.now, max_age_seconds=args.max_age)
        out = {
            "color": state.color,
            "reason_code": state.reason_code,
        }
        print(json.dumps(out))
        return 0

    if args.subcommand == "notify":
        snapshot_raw = _read_snapshot_file(args.snapshot)
        seen_raw = _read_seen_file(args.seen)
        notifications, new_seen = notification_plan(
            snapshot_raw, seen_raw, first_run=args.first_run
        )
        notif_dicts = [
            n.to_dict() if hasattr(n, "to_dict") else dict(n)
            for n in notifications
        ]
        out = {
            "notifications": notif_dicts,
            "seen_state": new_seen,
        }
        print(json.dumps(out))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
