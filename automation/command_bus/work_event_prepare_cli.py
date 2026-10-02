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
from .github_readonly import result_files, compare_ancestry, read_all
from .cloud_work_lanes import LANES, lane_identity
from .jules_result_lineage import validate_formal_command
from .blue_work_reconcile_prepare import _records, _sha
from .work_bridge_prepare import prepare_bridge
from .jules_session_readonly import _reject_constant
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
        snapshot = collect_lane_snapshot(reader, lane=lane, result_number=pr["number"]) if lane != 'auto' else None
        if snapshot is not None and snapshot.result_pr.get("head", {}).get("sha") != pr.get("head", {}).get("sha"):
            result.update(status="STALE", reason="event result HEAD advanced")
            return result
        global_snapshot = collect_global_jules_snapshot(reader)
        source = read_result_source(reader, global_snapshot, base)
        validate_formal_command(source['request'], source['claim'], now=now, historical=True)
        actual_lane = next(l for l in LANES if lane_identity(l)['jules_lane'] == source['claim']['lane_id'])
        if lane != 'auto' and lane != actual_lane:
            raise ValueError('event lane differs from formal claim')
        if snapshot is None:
            snapshot = collect_lane_snapshot(reader, lane=actual_lane, result_number=pr['number'])
        current = snapshot.result_pr
        if current.get('head', {}).get('sha') != pr.get('head', {}).get('sha'):
            return dict(result, status='STOP', reason='event result HEAD advanced')
        if (current.get('state') != 'open' or current.get('merged') is not False
                or any(current.get(side, {}).get('repo', {}).get('full_name') != EXPECTED_REPOSITORY for side in ('head', 'base'))
                or current.get('base', {}).get('ref') != source['request']['work_branch']
                or current.get('base', {}).get('sha') != source['request']['expected_target_head']):
            raise ValueError('result fork/base/source mismatch')
        head = current['head']['sha']
        if not _sha(head):
            raise ValueError('result HEAD missing')
        changed = result_files(reader, current)
        if not changed or any(x['filename'] not in source['request']['allowed_paths']
                or x.get('status') not in {'added', 'modified'} or x.get('symlink') is not False for x in changed):
            return dict(result, status='STOP', reason='result changed-file scope/mode unsafe')
        commit = reader.get(ROOT + '/git/commits/' + head).data
        comparison = compare_ancestry(reader, source['request']['expected_target_head'], head)
        if (commit.get('sha') != head or not _sha(commit.get('tree', {}).get('sha'))
                or comparison.get('status') != 'ahead'
                or comparison.get('base_commit', {}).get('sha') != source['request']['expected_target_head']
                or comparison.get('base_commit', {}).get('commit', {}).get('tree', {}).get('sha') != source['request']['expected_target_tree']
                or comparison.get('merge_base_commit', {}).get('sha') != source['request']['expected_target_head']
                or not comparison.get('commits') or comparison['commits'][-1].get('sha') != head):
            raise ValueError('result ancestry/tree unavailable')
        jobs = read_all(reader, ROOT + f"/actions/runs/{source['dispatch_run']['id']}/jobs?per_page=100", array_key='jobs')
        dispatch = source['dispatch_run']
        if (dispatch.get('status') != 'completed' or dispatch.get('conclusion') != 'success'
                or dispatch.get('head_sha') != source['command_commit'].get('sha')
                or len(source['command_commit'].get('files', [])) != 1
                or source['command_commit']['files'][0].get('status') != 'added'
                or source['command_commit']['files'][0].get('filename') != f"automation/command_bus/jules_api_requests/{source['request']['command_id']}.json"
                or not jobs or any(not _positive(j.get('id')) or j.get('run_id') != dispatch['id'] or j.get('head_sha') != dispatch['head_sha']
                    or j.get('status') != 'completed' or j.get('conclusion') != 'success' for j in jobs)):
            raise ValueError('dispatch job/publication identity unavailable')
        seen, terminals = _records(snapshot.reviews, snapshot.comments, True, lane=actual_lane)
        identity = f'{actual_lane}-jules-result-pr{current["number"]}-{head}'
        # Final read fences include carrier records, generation and target PR.
        final = collect_lane_snapshot(reader, lane=actual_lane, result_number=pr['number'])
        ref = reader.get(ROOT + '/git/ref/heads/' + global_snapshot.carrier_branch).data
        if final != snapshot or ref.get('object', {}).get('sha') != global_snapshot.carrier_head:
            raise ValueError('durable state changed during event preparation; no retry')
        result["readback"] = {"carrier_pr": snapshot.carrier_pr["number"],
                              "worker_generation": snapshot.protocol.worker_generation,
                              "reviews": len(snapshot.reviews), "comments": len(snapshot.comments),
                              "jules_carrier_head": global_snapshot.carrier_head,
                              "source_command_id": source["request"].get("command_id"),
                              'lane': actual_lane, 'result_pr': current['number'], 'result_head': head,
                              'result_tree': commit['tree']['sha'], 'complete_changed_files': len(changed),
                              'dispatch_run': dispatch['id'], 'dispatch_jobs': [j['id'] for j in jobs]}
        if identity in seen:
            return dict(result, status='NO_OP', reason='durable command or terminal already exists; never repost')
        result.update(status="BLOCKED", reason="authenticated provider captures and dispatch log source NOT_WIRED; no posting candidate or authority")
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        # Never print raw network exception bodies, request headers or content.
        result.update(status="UNKNOWN", reason="GitHub readback unavailable or inconsistent; source authentication NOT_WIRED; retry=0")
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--snapshot", type=Path)
    inputs.add_argument("--bridge-snapshot", type=Path)
    inputs.add_argument("--github-event", type=Path)
    parser.add_argument("--lane", default="auto", choices=("auto", "blue", "yellow", "green", "red"))
    parser.add_argument("--now", help="explicit aware ISO timestamp; otherwise UTC clock")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("create-only artifact already exists; no readback performed")
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("aware clock required")
        path = args.snapshot or args.bridge_snapshot or args.github_event
        value = json.loads(path.read_text(), object_pairs_hook=_pairs, parse_constant=_reject_constant)
        if args.snapshot:
            result = prepare_static_cycle(value, now=now)
        elif args.bridge_snapshot:
            result = prepare_bridge(value, now=now)
        else:
            result = prepare_github_event(value, GitHubGetReader(os.environ.get("GITHUB_TOKEN", "")), lane=args.lane, now=now)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        return 0  # UNKNOWN is a saved blocked artifact, not successful lineage.
    except (ValueError, OSError, TypeError):
        print("UNKNOWN: input/output/read capability unavailable; no retry or send")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
