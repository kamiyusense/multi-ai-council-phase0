"""Entry point of the DURABLE adoption approval issuer (one human dispatch, GitHub read-only).

``--issue`` is started only by ``signal-durable-adoption-approval-issuer.yml``. It re-reads its own run
from GitHub (workflow, path, event, main, attempt 1, owner actor and triggering actor), refuses a second
approval, re-reads the proof 5 terminal receipt and evidence from the data branch, re-reads the Jules
output PR from GitHub (no Jules call), and writes ONE sanitized approval record to a local file that the
workflow uploads as an artifact. It never writes to GitHub, never touches the registry or Issue #33, and
uses no secret other than the read-only GITHUB_TOKEN. Retry 0, fallback disabled.

``--verify FILE`` checks an approval record offline against the committed evidence. No network.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from . import durable_adoption_approval as dap
from . import signal_step7_live_proof as live
from .signal_step7_live_proof_cli import Http, RestApi, RestContentsClient, SystemClock, urllib_http

WORKFLOW_NAME = "Signal DURABLE adoption approval issuer"
WORKFLOW_FILE = "signal-durable-adoption-approval-issuer.yml"
WORKFLOW_PATH = f".github/workflows/{WORKFLOW_FILE}"
OUTPUT_PR = 286
DATA_BRANCH = "signal/chatgpt-semi-auto-active-proof-5-data"
RECEIPT_PATH = live.TERMINAL_RECEIPT_PATH
EVIDENCE_PATH = f"{live.DATA_RECORD_DIR}/live-proof-evidence.json"
EVID_DIR = "docs/evidence/signal-step7-proof5"
REGISTRY_PATH = "automation/command_bus/config/control_tower_registry.json"
CANDIDATE_REGISTRY_PATH = "docs/evidence/signal-sf8/registry-candidate-chatgpt-semi-auto-durable.json"
_SHA40 = re.compile(r"[0-9a-f]{40}")


class Stop(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _with_lane_state(registry: dict[str, Any], state: str) -> dict[str, Any]:
    import copy
    out = copy.deepcopy(registry)
    for entry in out["loops"]:
        if entry["loop_id"] == dap.LANE_ID:
            entry["identity_state"] = state
    return out


def registries_from_production(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """(current, proposed) derived from the production file: valid before and after the flip."""
    production = _load(root / REGISTRY_PATH)
    current = _with_lane_state(production, "PLACEHOLDER")
    proposed = _with_lane_state(production, "DURABLE")
    candidate = _load(root / CANDIDATE_REGISTRY_PATH)
    if dap.registry_digest(proposed) != dap.registry_digest(candidate):
        raise Stop("PROPOSED_REGISTRY_IS_NOT_THE_COMMITTED_CANDIDATE")
    return current, proposed


def registries_from_candidate(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """(current, proposed) of the historical approval, taken from the committed candidate, not the live file.

    The approval is the record of one decision, bound to exactly these two registries (the proposed one is the
    committed candidate, the current one is that candidate with the lane still PLACEHOLDER). Later changes to
    the production file must neither invalidate nor re-validate it, so it is checked against these digests only.
    """
    proposed = _load(root / CANDIDATE_REGISTRY_PATH)
    return _with_lane_state(proposed, "PLACEHOLDER"), proposed


PRODUCTION_GUARD_FAILURES = (
    "ADOPTED_LANE_MISSING_OR_NOT_DURABLE", "ADOPTED_LANE_CHANGED", "SECOND_DURABLE_LANE",
    "ACTIVE_LANE_NOT_PLACEHOLDER", "FROZEN_LANE_ENABLED",
)


def production_registry_guard(production: dict[str, Any], root: Path) -> list[str]:
    """Failure codes (empty = ok) for the production registry versus the approved DURABLE adoption.

    The adopted row must equal the approved entry in every field except ``display_name``; it must be the only
    DURABLE row; every other enabled row must be PLACEHOLDER; a FROZEN row must be disabled. A new
    PLACEHOLDER row never counts as adoption: only the committed approval bound to the candidate does.
    """
    approved = {e["loop_id"]: e for e in _load(root / CANDIDATE_REGISTRY_PATH)["loops"]}[dap.LANE_ID]
    rows = production.get("loops", [])
    failures: list[str] = []
    adopted = [e for e in rows if e.get("loop_id") == dap.LANE_ID]
    if len(adopted) != 1 or adopted[0].get("identity_state") != "DURABLE":
        failures.append("ADOPTED_LANE_MISSING_OR_NOT_DURABLE")
    elif {k: v for k, v in adopted[0].items() if k != "display_name"} != {k: v for k, v in approved.items() if k != "display_name"}:
        failures.append("ADOPTED_LANE_CHANGED")
    if [e.get("loop_id") for e in rows if e.get("identity_state") == "DURABLE"] != [dap.LANE_ID]:
        failures.append("SECOND_DURABLE_LANE")
    if any(e.get("loop_id") != dap.LANE_ID and e.get("enabled") and e.get("identity_state") != "PLACEHOLDER" for e in rows):
        failures.append("ACTIVE_LANE_NOT_PLACEHOLDER")
    if any(e.get("identity_state") == "FROZEN" and e.get("enabled") for e in rows):
        failures.append("FROZEN_LANE_ENABLED")
    return failures


def verify_own_run(api: RestApi, env: dict[str, str]) -> dict[str, Any]:
    run_id = env.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[0-9]{1,18}", run_id):
        raise Stop("RUN_ID_INVALID")
    if env.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or env.get("GITHUB_REF") != "refs/heads/main" \
            or env.get("GITHUB_RUN_ATTEMPT") != "1" or env.get("GITHUB_REPOSITORY") != live.REPOSITORY:
        raise Stop("NOT_A_FIRST_ATTEMPT_MAIN_DISPATCH")
    status, run = api.request("GET", f"actions/runs/{int(run_id)}")
    if status != 200 or not isinstance(run, dict):
        raise Stop("OWN_RUN_UNREADABLE")
    owner = live.OWNER_ACTOR_ID
    checks = {
        "id": run.get("id") == int(run_id), "name": run.get("name") == WORKFLOW_NAME,
        "path": run.get("path") == WORKFLOW_PATH, "event": run.get("event") == "workflow_dispatch",
        "branch": run.get("head_branch") == "main", "attempt": run.get("run_attempt") == 1,
        "repository": (run.get("repository") or {}).get("full_name") == live.REPOSITORY,
        "head_repository": (run.get("head_repository") or {}).get("full_name") == live.REPOSITORY,
        "actor": str((run.get("actor") or {}).get("id")) == owner,
        "triggering_actor": str((run.get("triggering_actor") or {}).get("id")) == owner,
        "head_sha": isinstance(run.get("head_sha"), str) and bool(_SHA40.fullmatch(run["head_sha"]))
        and run["head_sha"] == env.get("GITHUB_SHA"),
    }
    bad = sorted(name for name, ok in checks.items() if not ok)
    if bad:
        raise Stop("OWN_RUN_NOT_ELIGIBLE:" + ",".join(bad))
    return run


def refuse_second_approval(api: RestApi, run_id: str) -> None:
    status, body = api.request("GET", f"actions/workflows/{WORKFLOW_FILE}/runs?per_page=30")
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("workflow_runs"), list):
        raise Stop("RUN_HISTORY_UNREADABLE")
    others = [r.get("id") for r in body["workflow_runs"] if str(r.get("id")) != run_id]
    if others or body.get("total_count") != 1:
        raise Stop("ANOTHER_APPROVAL_RUN_EXISTS")


def read_proof(api: RestApi, root: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    store = RestContentsClient(api)
    receipt_file = store.get(RECEIPT_PATH, DATA_BRANCH)
    evidence_file = store.get(EVIDENCE_PATH, DATA_BRANCH)
    if receipt_file is None or evidence_file is None:
        raise Stop("PROOF_RECORDS_MISSING")
    receipt, evidence = json.loads(receipt_file.text), json.loads(evidence_file.text)
    if receipt != _load(root / EVID_DIR / "live-terminal-receipt.json") \
            or evidence != _load(root / EVID_DIR / "live-proof-evidence.json"):
        raise Stop("COMMITTED_EVIDENCE_DIFFERS_FROM_DATA_BRANCH")
    from urllib.parse import quote
    status, commits = api.request(
        "GET", f"commits?sha={quote(DATA_BRANCH, safe='')}&path={quote(RECEIPT_PATH)}&per_page=1")
    if status != 200 or not isinstance(commits, list) or len(commits) != 1:
        raise Stop("PROOF_COMPLETION_TIME_UNREADABLE")
    stamp = ((commits[0].get("commit") or {}).get("committer") or {}).get("date")
    if not isinstance(stamp, str):
        raise Stop("PROOF_COMPLETION_TIME_UNREADABLE")
    return receipt, evidence, stamp


def read_output(api: RestApi, evidence: dict[str, Any], root: Path) -> dict[str, Any]:
    status, pr = api.request("GET", f"pulls/{OUTPUT_PR}")
    if status != 200 or not isinstance(pr, dict):
        raise Stop("OUTPUT_PR_UNREADABLE")
    status, files = api.request("GET", f"pulls/{OUTPUT_PR}/files?per_page=100")
    if status != 200 or not isinstance(files, list):
        raise Stop("OUTPUT_FILES_UNREADABLE")
    head_sha = (pr.get("head") or {}).get("sha")
    content_file = RestContentsClient(api).get(live.ALLOWED_PATH, head_sha) if isinstance(head_sha, str) else None
    if content_file is None:
        raise Stop("OUTPUT_CONTENT_UNREADABLE")
    output = {
        "pull_request": OUTPUT_PR, "head_sha": head_sha,
        "head_branch": (pr.get("head") or {}).get("ref"), "base_branch": (pr.get("base") or {}).get("ref"),
        "base_sha": (pr.get("base") or {}).get("sha"),
        "changed_files": [f.get("filename") for f in files], "changed_file_content": content_file.text,
        "merged": bool(pr.get("merged")),
    }
    if output != _load(root / EVID_DIR / "jules-output-github-readback.json")["output"]:
        raise Stop("OUTPUT_DIFFERS_FROM_RECORDED_READBACK")
    return output


def issue(api: RestApi, env: dict[str, str], root: Path, now: str) -> dict[str, Any]:
    run = verify_own_run(api, env)
    run_id = str(run["id"])
    refuse_second_approval(api, run_id)
    receipt, evidence, completed_at = read_proof(api, root)
    output = read_output(api, evidence, root)
    current, proposed = registries_from_production(root)
    if dap.durable_lanes(current):
        raise Stop("CURRENT_REGISTRY_ALREADY_HAS_DURABLE_LANES")
    approval = dap.build_approval(
        run_id=run_id, actor_id=live.OWNER_ACTOR_ID, run_attempt=1, now=now, receipt=receipt, evidence=evidence,
        readback_output=output, current_registry=current, proposed_registry=proposed)
    try:
        dap.validate_durable_adoption_approval(
            approval, receipt=receipt, evidence=evidence, readback_output=output, current_registry=current,
            proposed_registry=proposed, proof_completed_at=_to_zulu(completed_at),
            allowed_approver_ids=frozenset({live.OWNER_ACTOR_ID}), now=now)
    except dap.ApprovalError as exc:
        raise Stop(exc.code) from None
    return approval


def _to_zulu(stamp: str) -> str:
    return live._iso(live._time(stamp)).replace("+00:00", "Z")


def verify_file(path: Path, root: Path, now: str) -> str:
    approval = _load(path)
    receipt = _load(root / EVID_DIR / "live-terminal-receipt.json")
    evidence = _load(root / EVID_DIR / "live-proof-evidence.json")
    output = _load(root / EVID_DIR / "jules-output-github-readback.json")["output"]
    completed = _load(root / EVID_DIR / "adoption-candidate.json")["proof"]["proof_completed_at"]
    current, proposed = registries_from_candidate(root)
    return dap.validate_durable_adoption_approval(
        approval, receipt=receipt, evidence=evidence, readback_output=output, current_registry=current,
        proposed_registry=proposed, proof_completed_at=completed,
        allowed_approver_ids=frozenset({live.OWNER_ACTOR_ID}), now=now)


def main(argv: list[str] | None = None, *, env: dict[str, str] | None = None, http: Http = urllib_http,
         clock: Any = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--issue", action="store_true")
    group.add_argument("--verify", metavar="FILE")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    root = root or Path(__file__).resolve().parents[2]
    now = (clock or SystemClock()).now().replace("+00:00", "Z")
    try:
        if args.verify:
            lane = verify_file(Path(args.verify), root, now)
            print(json.dumps({"status": "VERIFIED", "lane_id": lane}))
            return 0
        if not args.output:
            raise Stop("OUTPUT_PATH_REQUIRED")
        api = RestApi(env.get("GITHUB_TOKEN", ""), http=http)
        approval = issue(api, env, root, now)
        out = Path(args.output)
        if out.exists():
            raise Stop("OUTPUT_ALREADY_EXISTS")
        out.write_text(json.dumps(approval, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ISSUED", "approval_id": approval["approval_id"]}))
        return 0
    except Stop as exc:
        print(json.dumps({"status": "STOPPED", "code": exc.code}))
    except dap.ApprovalError as exc:
        print(json.dumps({"status": "STOPPED", "code": exc.code}))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(json.dumps({"status": "STOPPED", "code": type(exc).__name__}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
