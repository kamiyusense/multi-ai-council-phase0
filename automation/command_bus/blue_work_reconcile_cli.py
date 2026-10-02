"""Replay a local fixture, emit a candidate, and stop. No send mode exists."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .blue_jules_result_event import EventLineage
from .blue_work_wake_prepare import CarrierSnapshot
from .blue_work_reconcile_prepare import ReconciliationPlan, _pairs, prepare_reconciled_wake


def replay_snapshot(inputs: dict, now: datetime) -> dict:
    try:
        inputs = dict(inputs)
        inputs["lineage"] = EventLineage(**inputs["lineage"])
        inputs["protocol"] = CarrierSnapshot(**inputs["protocol"])
        plan = prepare_reconciled_wake(**inputs, now=now)
    except (ValueError, TypeError, KeyError) as exc:
        plan = ReconciliationPlan("UNKNOWN", str(exc))
    return {
        "execution_mode": "PREPARE_ONLY", "external_send_attempted": False,
        "model_executed": False, "lineage_authentication": "NOT_WIRED",
        "live_transport": "NOT_WIRED", "plan": asdict(plan),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--now", required=True, help="explicit ISO timestamp for reproducible replay")
    parser.add_argument("--output", type=Path, help="create-only local artifact")
    args = parser.parse_args()
    try:
        inputs = json.loads(args.snapshot.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("--now must include timezone")
        result = replay_snapshot(inputs, now)
        encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output is not None:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        else:
            print(encoded, end="")
        return 2 if result["plan"]["status"] == "UNKNOWN" else 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "UNKNOWN", "reason": str(exc), "external_send_attempted": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
