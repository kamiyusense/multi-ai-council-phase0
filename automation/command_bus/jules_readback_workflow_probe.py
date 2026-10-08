"""Count the provider calls of the REAL ``jules-session-readback.yml`` step (STATIC, read-only).

A settlement read is meant to cost exactly one Jules ``GET /sessions/<id>``.
Whether it does is decided by the workflow file on the branch whose push
triggers it (the carrier), not by what a request file or a design note says.
This probe takes that workflow text, extracts its ``Read Jules session once``
step and runs it in bash with ``curl`` replaced by a local recording stub, so
the number of calls is measured on the production step itself.

Nothing here reaches the network: the stub answers every call, proxies point at
a closed local port, and a step that names another HTTP client is refused
before it runs.  The API key given to the step is a sentinel, and the probe
fails if that sentinel shows up in any output.

``one_get_preflight`` is the gate for a one-GET settlement trial: it returns
``ONE_GET_CONFIRMED`` only when ``include_activities: false`` gives one session
GET and zero activities GETs, invalid values are refused with zero calls, a
failing GET is not retried, and the step prints exactly one readback line that
``claude_jules_settlement.readback_lines`` accepts.  Otherwise ``NOT_ONE_GET``
with the reasons.  It never adds a status request; adding one stays a
separately approved LIVE action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .claude_jules_settlement import ReadbackMismatch, readback_lines

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ".github/workflows/jules-session-readback.yml"
STEP_NAME = "Read Jules session once"
KEY_SENTINEL = "probe-sentinel-key-0f3a9c"
PROBE_SESSION_ID = "123"
# Values a request may carry that are not JSON booleans.  Each must be refused
# before any provider call.
INVALID_INCLUDE_ACTIVITIES = ("false", "true", None, 0, 1, "", [], {})
_OMIT = object()
_FOREIGN_CLIENTS = re.compile(r"\bwget\b|/curl\b|\bnc\b|urllib|http\.client|\brequests\b|python[0-9.]* -c")

SESSION_BODY = {
    "name": f"sessions/{PROBE_SESSION_ID}", "state": "COMPLETED", "createTime": "2026-10-01T10:00:00Z",
    "updateTime": "2026-10-01T10:00:05Z",
    "sourceContext": {"source": "sources/github/kamiyusense/multi-ai-council-phase0",
                      "githubRepoContext": {"startingBranch": "x"}},
    "outputs": [],
}

_CURL_STUB = """#!{python}
import json, os, sys
args = sys.argv[1:]
url = args[-1] if args else ""
with open(os.environ["PROBE_CALLS"], "a", encoding="utf-8") as log:
    log.write(json.dumps({{"url": url, "args": args}}) + "\\n")
spec = json.load(open(os.environ["PROBE_SPEC"], encoding="utf-8"))
if url.startswith("https://jules.googleapis.com/v1alpha/sessions/") and "/activities" in url:
    kind = "activities"
elif url.startswith("https://jules.googleapis.com/v1alpha/sessions/"):
    kind = "session"
else:
    sys.stderr.write("probe: unexpected url\\n")
    sys.exit(7)
reply = spec[kind]
if "--output" in args:
    with open(args[args.index("--output") + 1], "w", encoding="utf-8") as out:
        body = reply["body"]
        out.write(body if isinstance(body, str) else json.dumps(body))
sys.stdout.write(str(reply["code"]))
sys.exit(0 if reply["code"] < 400 else 22)
"""


def blob_sha(text: str) -> str:
    """The git blob id of ``text``, so a verdict names the exact workflow content it judged."""
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def extract_read_step(workflow_text: str) -> str:
    marker = f"      - name: {STEP_NAME}\n"
    if workflow_text.count(marker) != 1:
        raise ValueError(f"expected exactly one '{STEP_NAME}' step")
    start = workflow_text.index(marker)
    run = workflow_text.index("        run: |\n", start) + len("        run: |\n")
    block = []
    for line in workflow_text[run:].splitlines():
        if line.strip() and not line.startswith("          "):
            break
        block.append(line[10:] if line.startswith("          ") else "")
    step = "\n".join(block) + "\n"
    if _FOREIGN_CLIENTS.search(step):
        raise ValueError("step uses an HTTP client the probe cannot intercept")
    return step


def run_read_step(workflow_text: str, *, include_activities: Any = _OMIT, session_code: int = 200,
                  activities_code: int = 200, session_body: Any = None, activities_body: Any = None,
                  timeout: float = 60) -> dict[str, Any]:
    """Run the workflow's real step once against the stub and report what it did."""
    step = extract_read_step(workflow_text)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        python = sys.executable or "python3"
        for name, content in (("curl", _CURL_STUB.format(python=python)),
                              ("python", f'#!/bin/sh\nexec "{python}" "$@"\n')):
            tool = bin_dir / name
            tool.write_text(content, encoding="utf-8")
            tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
        spec = tmp_path / "spec.json"
        spec.write_text(json.dumps({
            "session": {"body": SESSION_BODY if session_body is None else session_body, "code": session_code},
            "activities": {"body": {"activities": []} if activities_body is None else activities_body,
                           "code": activities_code}}), encoding="utf-8")
        request = {"session_id": PROBE_SESSION_ID}
        if include_activities is not _OMIT:
            request["include_activities"] = include_activities
        status = tmp_path / "status.json"
        status.write_text(json.dumps(request), encoding="utf-8")
        calls = tmp_path / "calls.jsonl"
        calls.touch()
        summary = tmp_path / "summary.md"
        runner_temp = tmp_path / "rt"
        runner_temp.mkdir()
        script = tmp_path / "step.sh"
        script.write_text("set -euo pipefail\n" + step, encoding="utf-8")
        closed = "http://127.0.0.1:9"
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONPATH": str(ROOT),
               "PROBE_SPEC": str(spec), "PROBE_CALLS": str(calls), "STATUS_PATH": str(status),
               "GITHUB_STEP_SUMMARY": str(summary), "RUNNER_TEMP": str(runner_temp),
               "JULES_API_KEY": KEY_SENTINEL, "HTTPS_PROXY": closed, "HTTP_PROXY": closed, "ALL_PROXY": closed,
               "https_proxy": closed, "http_proxy": closed, "all_proxy": closed, "NO_PROXY": "", "no_proxy": ""}
        proc = subprocess.run(["bash", str(script)], cwd=ROOT, env=env, capture_output=True, text=True,
                              timeout=timeout)
        recorded = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines() if line]
        summary_text = summary.read_text(encoding="utf-8") if summary.exists() else ""
        evidence_file = runner_temp / "jules-session-readback-evidence.json"
        evidence_text = evidence_file.read_text(encoding="utf-8") if evidence_file.exists() else ""
    session_url = f"https://jules.googleapis.com/v1alpha/sessions/{PROBE_SESSION_ID}"
    leaked = any(KEY_SENTINEL in text for text in (proc.stdout, proc.stderr, summary_text, evidence_text))
    return {
        "returncode": proc.returncode,
        "session_gets": sum(1 for c in recorded if c["url"] == session_url),
        "activities_gets": sum(1 for c in recorded if c["url"].startswith(session_url + "/activities")),
        "calls": len(recorded),
        "all_calls_retry_0": all("--retry" in c["args"] and c["args"][c["args"].index("--retry") + 1] == "0"
                                 for c in recorded),
        "stdout": proc.stdout,
        "summary": summary_text,
        "evidence": json.loads(evidence_text) if evidence_text else None,
        "key_leaked": leaked,
    }


def _readback_line_count(stdout: str) -> int | None:
    try:
        return len(readback_lines(stdout))
    except ReadbackMismatch:
        return None


def one_get_preflight(workflow_text: str) -> dict[str, Any]:
    """``ONE_GET_CONFIRMED`` only when ``include_activities: false`` is exactly one provider GET."""
    reasons: list[str] = []
    observed: dict[str, Any] = {}

    false_run = run_read_step(workflow_text, include_activities=False, activities_code=503)
    observed["false"] = {k: false_run[k] for k in ("returncode", "session_gets", "activities_gets", "calls")}
    if (false_run["returncode"], false_run["session_gets"], false_run["activities_gets"], false_run["calls"]) \
            != (0, 1, 0, 1):
        reasons.append("include_activities=false is not exactly one session GET and zero activities GETs")
    if _readback_line_count(false_run["stdout"]) != 1:
        reasons.append("include_activities=false does not print exactly one valid readback line")

    for label, kwargs in (("omitted", {}), ("true", {"include_activities": True})):
        run = run_read_step(workflow_text, **kwargs)
        observed[label] = {k: run[k] for k in ("returncode", "session_gets", "activities_gets", "calls")}

    invalid = []
    for value in INVALID_INCLUDE_ACTIVITIES:
        run = run_read_step(workflow_text, include_activities=value)
        invalid.append({"value": value, "returncode": run["returncode"], "calls": run["calls"]})
        if run["returncode"] == 0 or run["calls"] != 0:
            reasons.append(f"invalid include_activities {json.dumps(value)} was not refused before any call")
    observed["invalid"] = invalid

    failing = run_read_step(workflow_text, include_activities=False, session_code=500)
    observed["session_failure"] = {k: failing[k] for k in ("returncode", "session_gets", "activities_gets", "calls")}
    if failing["returncode"] == 0 or failing["calls"] != 1:
        reasons.append("a failing session GET is not a single call that fails the step")

    runs = [false_run, failing]
    if not all(run["all_calls_retry_0"] for run in runs):
        reasons.append("a provider call is made without --retry 0")
    if any(run["key_leaked"] for run in runs):
        reasons.append("the API key appears in the step output")

    return {"status": "NOT_ONE_GET" if reasons else "ONE_GET_CONFIRMED", "workflow_blob": blob_sha(workflow_text),
            "reasons": reasons, "observed": observed}


def _git_show(ref: str, path: str) -> str:
    return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only one-GET preflight of jules-session-readback.yml.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--ref", help="git ref whose workflow is judged, e.g. origin/feature/chat-work-command-bus")
    source.add_argument("--file", help="workflow file to judge")
    args = parser.parse_args(argv)
    text = _git_show(args.ref, WORKFLOW_PATH) if args.ref else Path(args.file).read_text(encoding="utf-8")
    verdict = one_get_preflight(text)
    verdict["source"] = f"{args.ref}:{WORKFLOW_PATH}" if args.ref else args.file
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if verdict["status"] == "ONE_GET_CONFIRMED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
