"""Offline formal cycle replay or GitHub GET-only event preflight; no send mode."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

from .blue_jules_result_event import EXPECTED_REPOSITORY
from .blue_work_reconcile_prepare import _pairs, _positive
from .cloud_work_snapshot import collect_lane_snapshot
from .github_jules_source import collect_global_jules_snapshot, read_result_source
from .github_readonly import GitHubGetReader, ROOT
from .work_closed_loop_prepare import prepare_static_cycle


def prepare_github_event(event: dict, reader, *, lane: str, now: datetime) -> dict:
    result = {"execution_mode": "PREPARE_ONLY", "external_send_attempted": False,
              "model_executed": False, "source_authentication": "NOT_WIRED", "live_transport": "NOT_WIRED"}
    try:
        if not isinstance(event, dict) or event.get("repository", {}).get("full_name") != EXPECTED_REPOSITORY:
            raise ValueError("event repository unavailable/mismatch")
        if event.get("action") not in {"opened", "synchronize", "reopened"}:
            result.update(status="NO_OP", reason="unsupported event action")
            return result
        pr = event.get("pull_request")
        if not isinstance(pr, dict) or not _positive(pr.get("number")):
            raise ValueError("event PR identity unavailable")
        base = pr.get("base", {}).get("ref")
        if not isinstance(base, str):
            raise ValueError("event base unavailable")
        if not base.startswith("jules-work/"):
            result.update(status="NO_OP", reason="unrelated result base; no GitHub request made")
            return result
        if event["action"] == "reopened":
            # BWJ-1 currently accepts only opened/synchronize. Do not broaden
            # it silently; durable reconciliation can be replayed explicitly.
            result.update(status="NO_OP", reason="reopened is not an accepted BWJ-1 wake event")
            return result
        snapshot = collect_lane_snapshot(reader, lane=lane, result_number=pr["number"])
        if snapshot.result_pr.get("head", {}).get("sha") != pr.get("head", {}).get("sha"):
            result.update(status="STALE", reason="event result HEAD advanced")
            return result
        global_snapshot = collect_global_jules_snapshot(reader)
        source = read_result_source(reader, global_snapshot, base)
        result["readback"] = {"carrier_pr": snapshot.carrier_pr["number"],
                              "worker_generation": snapshot.protocol.worker_generation,
                              "reviews": len(snapshot.reviews), "comments": len(snapshot.comments),
                              "jules_carrier_head": global_snapshot.carrier_head,
                              "source_command_id": source["request"].get("command_id")}
        result.update(status="UNKNOWN", reason="authenticated existing Jules Session GET and dispatch job-log readback NOT_WIRED; no wake candidate")
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        # Never print raw network exception bodies, request headers or content.
        result.update(status="UNKNOWN", reason="GitHub readback unavailable or inconsistent; retry=0")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--snapshot", type=Path)
    inputs.add_argument("--github-event", type=Path)
    parser.add_argument("--lane", default="blue", choices=("blue", "yellow", "green", "red"))
    parser.add_argument("--now", help="explicit aware ISO timestamp; otherwise UTC clock")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("aware clock required")
        path = args.snapshot or args.github_event
        value = json.loads(path.read_text(), object_pairs_hook=_pairs)
        result = prepare_static_cycle(value, now=now) if args.snapshot else prepare_github_event(
            value, GitHubGetReader(os.environ.get("GITHUB_TOKEN", "")), lane=args.lane, now=now)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return 0  # UNKNOWN is a saved blocked artifact, not successful lineage.
    except (ValueError, OSError, TypeError):
        print("UNKNOWN: input/output/read capability unavailable; no retry or send")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
