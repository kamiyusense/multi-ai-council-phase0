"""Real-world ports and entry point for the Step 7 LIVE publish half.

Importing this module performs no I/O. ``main`` is started only by the
workflow_dispatch workflow; ``--check`` validates the committed plan and
registry without any network access. Tokens and keys are read from the
environment, never printed, never written to a record, and never passed on a
command line.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import signal_step7_live_proof as live
from .github_backend import GitHubContent
from .jules_session_readonly import _exact_time, _safe_branch

API = "https://api.github.com"
JULES_API = "https://jules.googleapis.com/v1alpha/sessions/"
_LIMIT = 1024 * 1024
_ERROR = "provider readback unavailable"
_ARTIFACT_NAME = re.compile(r"^sf8-authority-evidence-([0-9]{1,24})$")
Http = Callable[[str, str, dict[str, str], bytes | None], tuple[int, dict[str, str], bytes]]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_http(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, dict[str, str], bytes]:
    """One request, no redirects, no retry, bounded response."""
    opener = build_opener(_NoRedirect())
    request = Request(url, data=body, method=method, headers=headers)
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read(_LIMIT + 1)
    except HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read(_LIMIT + 1) if exc.fp else b""


class RestApi:
    def __init__(self, token: str, repository: str = live.REPOSITORY, http: Http = urllib_http):
        if not isinstance(token, str) or not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("GitHub token unavailable")
        self._token, self.repository, self._http = token, repository, http

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28"}

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        status, _, raw = self._http(method, f"{API}/repos/{self.repository}/{path}", self._headers(), data)
        if len(raw) > _LIMIT:
            raise ValueError("response too large")
        try:
            return status, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return status, None

    def download(self, path: str) -> bytes | None:
        """Follow ONE redirect to a signed blob URL without forwarding the token."""
        status, headers, raw = self._http("GET", f"{API}/repos/{self.repository}/{path}", self._headers(), None)
        if status in (301, 302, 303, 307, 308) and headers.get("Location", "").startswith("https://"):
            status, _, raw = self._http("GET", headers["Location"], {}, None)
        return raw if status == 200 and len(raw) <= _LIMIT else None


class RestContentsClient:
    """GitHubContentsClient over the Contents API. Each write is one commit on ``branch``."""

    def __init__(self, api: RestApi):
        self.api = api

    @staticmethod
    def _safe(path: str, branch: str) -> None:
        if branch in {"main", "master"} or not branch or ".." in path or path.startswith("/"):
            raise ValueError("unsafe contents target")

    def get(self, path: str, ref: str) -> GitHubContent | None:
        status, body = self.api.request("GET", f"contents/{quote(path)}?ref={quote(ref, safe='')}")
        if status == 404:
            return None
        if status != 200 or not isinstance(body, dict) or body.get("type") != "file":
            raise RuntimeError("contents read failed")
        import base64
        return GitHubContent(path, base64.b64decode(body["content"]).decode("utf-8"), body["sha"])

    def list(self, prefix: str, ref: str) -> list[GitHubContent]:
        status, body = self.api.request("GET", f"contents/{quote(prefix.rstrip('/'))}?ref={quote(ref, safe='')}")
        if status == 404:
            return []
        if status != 200 or not isinstance(body, list):
            raise RuntimeError("contents list failed")
        out: list[GitHubContent] = []
        for item in body:
            if item.get("type") == "file":
                found = self.get(item["path"], ref)
                if found is not None:
                    out.append(found)
            elif item.get("type") == "dir":
                out.extend(self.list(item["path"], ref))
        return sorted(out, key=lambda c: c.path)

    def create(self, path: str, text: str, message: str, branch: str) -> GitHubContent:
        self._safe(path, branch)
        import base64
        status, body = self.api.request("PUT", f"contents/{quote(path)}", {
            "message": message, "branch": branch, "content": base64.b64encode(text.encode("utf-8")).decode("ascii")})
        if status not in (200, 201) or not isinstance(body, dict):
            raise RuntimeError("contents create failed")
        return GitHubContent(path, text, body["content"]["sha"])

    def update(self, path: str, text: str, sha: str, message: str, branch: str) -> GitHubContent:
        self._safe(path, branch)
        import base64
        status, body = self.api.request("PUT", f"contents/{quote(path)}", {
            "message": message, "branch": branch, "sha": sha,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii")})
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError("contents update failed")
        return GitHubContent(path, text, body["content"]["sha"])


class RestTargetReader:
    def __init__(self, api: RestApi):
        self.api = api

    def read_target(self, repository: str, pr_number: int) -> dict[str, Any] | None:
        status, pr = self.api.request("GET", f"pulls/{int(pr_number)}")
        if status != 200 or not isinstance(pr, dict):
            return None
        head = pr.get("head") or {}
        return {"number": pr.get("number"), "state": pr.get("state"), "merged": bool(pr.get("merged")),
                "draft": bool(pr.get("draft")), "head": {"ref": head.get("ref"), "sha": head.get("sha")},
                "repo": {"full_name": ((head.get("repo") or {}).get("full_name"))}}


CARRIER_WORKFLOW = "jules-chat-semiauto.yml"
CARRIER_BRANCH = "feature/chat-work-command-bus"
_LOG_COMMAND = re.compile(r"^\S*\s*COMMAND_ID:\s*(\S+)\s*$", re.M)
_LOG_SESSION = re.compile(r"^\S*\s*SESSION_ID:\s*([0-9]{1,24})\s*$", re.M)
_RUNS_SCANNED = 10


class RestCarrierSessionResolver:
    """Reads the Jules session id from the carrier run that executed THIS plan's command.

    The id is never typed by a person: a mistyped or stale id spent the whole GET budget of
    proof 2 and proof 3. Only GitHub is read (workflow runs, jobs and their logs); Jules is
    not touched. Exactly one distinct session id must be found for the command id.
    """

    def __init__(self, api: RestApi):
        self.api = api

    def resolve(self, command_id: str) -> str:
        return self.resolve_record(command_id)[0]

    def resolve_record(self, command_id: str) -> tuple[str, str]:
        """(session_id, created_at of the earliest carrier run that executed this command)."""
        if not isinstance(command_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", command_id):
            raise live.LiveProofError("CARRIER_COMMAND_ID_INVALID")
        status, body = self.api.request(
            "GET", f"actions/workflows/{CARRIER_WORKFLOW}/runs?branch={quote(CARRIER_BRANCH, safe='')}"
                   f"&event=push&status=success&per_page={_RUNS_SCANNED}")
        runs = (body or {}).get("workflow_runs") if status == 200 and isinstance(body, dict) else None
        if not isinstance(runs, list):
            raise live.LiveProofError("CARRIER_RUNS_UNREADABLE")
        found: set[str] = set()
        run_times: list[str] = []
        for run in runs[:_RUNS_SCANNED]:
            if not isinstance(run, dict) or run.get("conclusion") != "success" or not isinstance(run.get("id"), int):
                continue
            status, jobs = self.api.request("GET", f"actions/runs/{run['id']}/jobs")
            if status != 200 or not isinstance(jobs, dict):
                raise live.LiveProofError("CARRIER_JOBS_UNREADABLE")
            for job in jobs.get("jobs") or []:
                if not isinstance(job, dict) or job.get("conclusion") != "success" or not isinstance(job.get("id"), int):
                    continue
                raw = self.api.download(f"actions/jobs/{job['id']}/logs")
                if raw is None:
                    continue
                text = raw.decode("utf-8", errors="replace")
                if command_id not in set(_LOG_COMMAND.findall(text)):
                    continue
                found.update(_LOG_SESSION.findall(text))
                run_times.append(str(run.get("created_at")))
        if len(found) != 1:
            raise live.LiveProofError("CARRIER_SESSION_NOT_UNIQUE", str(len(found)))
        session_id = next(iter(found))
        if session_id in live.FORBIDDEN_SESSION_IDS:
            raise live.LiveProofError("CARRIER_SESSION_FORBIDDEN")
        try:
            created = min(live._time(t) for t in run_times)
        except Exception:
            raise live.LiveProofError("CARRIER_RUN_TIME_UNREADABLE") from None
        return session_id, live._iso(created)


CARRIER_RUN_NAME = "Phase 0 Chat to Jules semi-auto"
CARRIER_RUN_PATH = ".github/workflows/jules-chat-semiauto.yml"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class AutoNoop(Exception):
    """The workflow_run event is not this proof's carrier success: nothing to do, nothing spent."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def scan_carrier_run(api: "RestApi", run_id: int) -> tuple[set[str], set[str]]:
    """(command ids, session ids) printed by the successful jobs of ONE carrier run. GitHub reads only."""
    status, jobs = api.request("GET", f"actions/runs/{int(run_id)}/jobs")
    if status != 200 or not isinstance(jobs, dict):
        raise live.LiveProofError("CARRIER_JOBS_UNREADABLE")
    commands: set[str] = set()
    sessions: set[str] = set()
    for job in jobs.get("jobs") or []:
        if not isinstance(job, dict) or job.get("conclusion") != "success" or not isinstance(job.get("id"), int):
            continue
        raw = api.download(f"actions/jobs/{job['id']}/logs")
        if raw is None:
            continue
        text = raw.decode("utf-8", errors="replace")
        commands.update(_LOG_COMMAND.findall(text))
        sessions.update(_LOG_SESSION.findall(text))
    return commands, sessions


def verify_carrier_event_run(api: "RestApi", run_id: str) -> dict[str, Any]:
    """Re-read the triggering carrier run from the API; the event payload alone is never trusted.

    Any mismatch means this is not the Signal carrier success we may act on: NOOP before anything else.
    """
    if not re.fullmatch(r"[0-9]{1,18}", str(run_id)):
        raise AutoNoop("CARRIER_RUN_ID_INVALID")
    status, run = api.request("GET", f"actions/runs/{int(run_id)}")
    if status != 200 or not isinstance(run, dict):
        raise AutoNoop("CARRIER_RUN_UNREADABLE")
    owner = live.OWNER_ACTOR_ID
    checks = {
        "id": run.get("id") == int(run_id), "name": run.get("name") == CARRIER_RUN_NAME,
        "path": run.get("path") == CARRIER_RUN_PATH, "event": run.get("event") == "push",
        "branch": run.get("head_branch") == CARRIER_BRANCH, "status": run.get("status") == "completed",
        "conclusion": run.get("conclusion") == "success", "attempt": run.get("run_attempt") == 1,
        "repository": (run.get("repository") or {}).get("full_name") == live.REPOSITORY,
        "head_repository": (run.get("head_repository") or {}).get("full_name") == live.REPOSITORY,
        "actor": str((run.get("actor") or {}).get("id")) == owner,
        "triggering_actor": str((run.get("triggering_actor") or {}).get("id")) == owner,
        "head_sha": isinstance(run.get("head_sha"), str) and bool(_SHA40.fullmatch(run["head_sha"])),
    }
    bad = sorted(name for name, ok in checks.items() if not ok)
    if bad:
        raise AutoNoop("CARRIER_RUN_NOT_ELIGIBLE:" + ",".join(bad))
    try:
        live._time(run.get("created_at"))
    except Exception:
        raise AutoNoop("CARRIER_RUN_TIME_UNREADABLE") from None
    return run


class RestCompareReader:
    """GitHub compare of two exact SHAs (per_page=100). A failed or odd answer is None (fail closed)."""

    def __init__(self, api: "RestApi"):
        self.api = api

    def compare(self, base: str, head: str) -> dict[str, Any] | None:
        if not (_SHA40.fullmatch(str(base)) and _SHA40.fullmatch(str(head))):
            return None
        status, body = self.api.request("GET", f"compare/{base}...{head}?per_page=100")
        if status != 200 or not isinstance(body, dict):
            return None
        return {"status": body.get("status"), "ahead_by": body.get("ahead_by"),
                "behind_by": body.get("behind_by"), "files": body.get("files")}


ISSUER_WORKFLOW = "signal-sf8-authority-issuer.yml"


class RestAuthorityRunResolver:
    """Finds the one fresh owner-issued authority run instead of trusting a typed run id.

    Only GitHub is read. A candidate is a successful first-attempt workflow_dispatch of the
    issuer on main by the single owner, created after the plan's not_before, BEFORE the
    carrier run that created the Jules session, inside the authority max age, and not one of
    the reserved runs. Several candidates are ambiguous and stop the run before Jules; a
    typed id is only accepted if it is one of the candidates.
    """

    def __init__(self, api: RestApi):
        self.api = api

    def candidates(self, plan: dict[str, Any], carrier_created_at: str, now: str) -> list[str]:
        status, body = self.api.request(
            "GET", f"actions/workflows/{ISSUER_WORKFLOW}/runs?branch=main&event=workflow_dispatch"
                   f"&status=success&per_page={_RUNS_SCANNED}")
        runs = (body or {}).get("workflow_runs") if status == 200 and isinstance(body, dict) else None
        if not isinstance(runs, list):
            raise live.LiveProofError("AUTHORITY_RUNS_UNREADABLE")
        found: list[str] = []
        not_before, before, current = live._time(plan["not_before"]), live._time(carrier_created_at), live._time(now)
        for run in runs[:_RUNS_SCANNED]:
            if not isinstance(run, dict) or not isinstance(run.get("id"), int):
                continue
            run_id = str(run["id"])
            actor = str((run.get("actor") or {}).get("id"))
            trigger = str((run.get("triggering_actor") or {}).get("id"))
            if run.get("conclusion") != "success" or run.get("event") != "workflow_dispatch" \
                    or run.get("head_branch") != "main" or run.get("run_attempt") != 1 \
                    or actor != live.OWNER_ACTOR_ID or trigger != live.OWNER_ACTOR_ID \
                    or run_id in live.RESERVED_AUTHORITY_RUNS or run_id == live.PROVIDER_OIDC_RUN_ID:
                continue
            try:
                created = live._time(run.get("created_at"))
            except Exception:
                continue
            if created < not_before or created >= before \
                    or (current - created).total_seconds() > plan["authority_max_age_seconds"]:
                continue
            found.append(run_id)
        return found

    def resolve(self, plan: dict[str, Any], carrier_created_at: str, now: str, typed: str = "") -> str:
        found = self.candidates(plan, carrier_created_at, now)
        if typed:
            if typed not in found:
                raise live.LiveProofError("AUTHORITY_RUN_INPUT_MISMATCH")
            return typed
        if len(found) != 1:
            raise live.LiveProofError("AUTHORITY_RUN_NOT_UNIQUE", str(len(found)))
        return found[0]


class RestBranchReader:
    def __init__(self, api: RestApi):
        self.api = api

    def read_branch(self, repository: str, branch: str) -> dict[str, str] | None:
        status, body = self.api.request("GET", f"branches/{quote(branch, safe='')}")
        if status != 200 or not isinstance(body, dict):
            return None
        sha = (body.get("commit") or {}).get("sha")
        status, commit = self.api.request("GET", f"git/commits/{sha}")
        if status != 200 or not isinstance(commit, dict):
            return None
        return {"head": sha, "tree": (commit.get("tree") or {}).get("sha")}


class RestRunReader:
    def __init__(self, api: RestApi):
        self.api = api

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        status, run = self.api.request("GET", f"actions/runs/{int(run_id)}")
        return run if status == 200 and isinstance(run, dict) else None


class RestAuthorityEvidenceLoader:
    """Reads the sanitized evidence artifact of ONE finished issuer run."""

    def __init__(self, api: RestApi):
        self.api = api

    def load(self, run_id: str) -> dict[str, Any] | None:
        status, body = self.api.request("GET", f"actions/runs/{int(run_id)}/artifacts")
        if status != 200 or not isinstance(body, dict):
            return None
        wanted = [a for a in body.get("artifacts", [])
                  if (m := _ARTIFACT_NAME.match(str(a.get("name")))) and m.group(1) == str(run_id) and not a.get("expired")]
        if len(wanted) != 1:
            return None
        raw = self.api.download(f"actions/artifacts/{int(wanted[0]['id'])}/zip")
        if raw is None:
            return None
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if names != ["oidc-proof-evidence.json"]:
                return None
            document = json.loads(archive.read(names[0]))
        return document if isinstance(document, dict) else None


class JulesActiveSessionGetReader:
    """Exactly one bounded Jules GET Session (no activities). Sanitized dict out.

    No redirects, response limit, fixed error text, no exception chaining. The key is
    held privately and is never included in any returned value or message.
    """

    def __init__(self, key: str, http: Http = urllib_http):
        if not isinstance(key, str) or not key or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ValueError(_ERROR)
        self._key, self._http = key, http

    def read_active_session(self, session_id: str, *, expected_branch: str) -> dict[str, Any]:
        try:
            if not isinstance(session_id, str) or not re.fullmatch(r"[0-9]+", session_id) \
                    or not _safe_branch(expected_branch):
                raise ValueError(_ERROR)
            status, _, raw = self._http("GET", JULES_API + session_id, {"X-Goog-Api-Key": self._key}, None)
            if status != 200 or len(raw) > _LIMIT:
                raise ValueError(_ERROR)
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("name") != f"sessions/{session_id}":
                raise ValueError(_ERROR)
            context = data.get("sourceContext") or {}
            github = context.get("githubRepoContext") or {}
            _exact_time(data.get("createTime"))
            if "updateTime" in data:
                _exact_time(data["updateTime"])
            result = {"name": data["name"], "createTime": data["createTime"], "state": data.get("state"),
                      "sourceContext": {"source": context.get("source"),
                                        "githubRepoContext": {"startingBranch": github.get("startingBranch")}}}
            if "updateTime" in data:
                result["updateTime"] = data["updateTime"]
            return result
        except Exception:
            raise ValueError(_ERROR) from None


class SystemClock:
    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_inputs(plan_path: Path, registry_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    live.validate_plan(plan, registry)
    return plan, registry


_OUTPUT_VALUE = re.compile(r"^[A-Za-z0-9._-]{0,160}$")


def _write_outputs(path: str | None, values: dict[str, str]) -> None:
    """Append key=value lines for later jobs. Values are validated; nothing secret ever goes here."""
    if not path:
        return
    lines = []
    for key, value in values.items():
        if key == "status" or not _OUTPUT_VALUE.fullmatch(str(value)):
            continue
        lines.append(f"{key}={value}\n")
    with open(path, "a", encoding="utf-8") as handle:
        handle.writelines(lines)


def main(argv: list[str] | None = None, *, env: dict[str, str] | None = None, http: Http = urllib_http,
         clock: Any = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--result-out")
    parser.add_argument("--check", action="store_true", help="validate plan and registry only; no network")
    parser.add_argument("--bound-plan-from-data-branch", action="store_true",
                        help="read the bound plan from the data branch; its sha256 must equal PLAN_SHA256")
    parser.add_argument("--prepare-only", action="store_true",
                        help="resolve and verify everything read-only (no Jules key, no writes); write go/no-go outputs")
    parser.add_argument("--github-output", help="file to append go/session/authority outputs to (GITHUB_OUTPUT)")
    parser.add_argument("--bind-out", help="bind the template to a target snapshot and write the bound plan + carrier files here")
    parser.add_argument("--loop-number", type=int)
    parser.add_argument("--target-pr", type=int)
    parser.add_argument("--target-head")
    parser.add_argument("--target-tree")
    parser.add_argument("--now")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    try:
        plan, registry = load_inputs(Path(args.plan), Path(args.registry))
    except (live.LiveProofError, OSError, ValueError) as exc:
        print(json.dumps({"status": "STOPPED", "stage": "plan", "code": getattr(exc, "code", "PLAN_UNREADABLE")}))
        return 1
    if args.bind_out:
        # Offline: writes ONLY under --bind-out, never into the carrier directories.
        bound = live.bind_plan(plan, loop_number=args.loop_number, target_pr=args.target_pr,
                               target_head=args.target_head, target_tree=args.target_tree,
                               now=args.now or SystemClock().now())
        live.validate_plan(bound, registry, require_bound=True)
        out = Path(args.bind_out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "plan.bound.json").write_text(json.dumps(bound, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        for repo_path, document in live.carrier_files(bound).items():
            target = out / "carrier" / repo_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": "BOUND", "plan_sha256": live.plan_digest(bound)}))
        return 0
    if args.check:
        print(json.dumps({"status": "CHECKED", "lane_id": plan["lane_id"], "plan_sha256": live.plan_digest(plan)}))
        return 0
    clock_port = clock or SystemClock()
    try:
        api = RestApi(env.get("GITHUB_TOKEN", ""), http=http)
        store = RestContentsClient(api)
        carrier_run_id = env.get("CARRIER_RUN_ID", "")
        auto = bool(carrier_run_id)
        if auto:
            if env.get("GITHUB_EVENT_NAME") != "workflow_run" or not args.bound_plan_from_data_branch:
                raise AutoNoop("EVENT_NOT_WORKFLOW_RUN")
            verify_carrier_event_run_result = verify_carrier_event_run(api, carrier_run_id)
        if args.bound_plan_from_data_branch:
            found = store.get(live.BOUND_PLAN_PATH, plan["data_branch"])
            if found is None:
                if auto:
                    raise AutoNoop("NO_BOUND_PLAN")
                raise live.LiveProofError("BOUND_PLAN_MISSING")
            bound = json.loads(found.text)
            typed_digest = env.get("PLAN_SHA256", "")
            if typed_digest and live.plan_digest(bound) != typed_digest:
                raise live.LiveProofError("BOUND_PLAN_DIGEST_MISMATCH")
            live.validate_plan(bound, registry, require_bound=True)
            if {k: bound[k] for k in ("lane_id", "repository", "data_branch", "target_branch")} != \
                    {k: plan[k] for k in ("lane_id", "repository", "data_branch", "target_branch")}:
                raise live.LiveProofError("BOUND_PLAN_NOT_FROM_TEMPLATE")
            plan = bound
        # No Jules key in the read-only prepare job; otherwise the reader exists before any resolution.
        reader = None if args.prepare_only else JulesActiveSessionGetReader(env.get("JULES_API_KEY", ""), http=http)
        resolver = RestCarrierSessionResolver(api)
        command_id = plan["request"]["command_id"]
        if auto:
            commands, sessions = scan_carrier_run(api, int(carrier_run_id))
            if command_id not in commands:
                raise AutoNoop("CARRIER_COMMAND_NOT_THIS_PROOF")
            # From here on this IS the proof's carrier success: every mismatch is a hard stop, not a no-op.
            if len(sessions) != 1:
                raise live.LiveProofError("CARRIER_SESSION_NOT_UNIQUE", str(len(sessions)))
            resolved_session = next(iter(sessions))
            if resolved_session in live.FORBIDDEN_SESSION_IDS:
                raise live.LiveProofError("CARRIER_SESSION_FORBIDDEN")
            carrier_created_at = live._iso(live._time(verify_carrier_event_run_result["created_at"]))
            if store.get(live.TERMINAL_RECEIPT_PATH, plan["data_branch"]) is not None:
                raise AutoNoop("TERMINAL_RECEIPT_EXISTS")
            if store.get(live.ATTEMPT_MARKER_PATH, plan["data_branch"]) is not None:
                raise AutoNoop("ATTEMPT_MARKER_EXISTS")
        else:
            # The session id comes from the carrier run's own record, never from a typed value. An
            # optional typed value is only a cross-check; any disagreement stops before the Jules GET.
            resolved_session, carrier_created_at = resolver.resolve_record(command_id)
        typed_session = env.get("SESSION_ID", "") or env.get("EXPECT_SESSION_ID", "")
        if typed_session and typed_session != resolved_session:
            raise live.LiveProofError("SESSION_ID_INPUT_MISMATCH")
        # Same for the authority run: derived from GitHub's own run list (fresh, owner, before the
        # carrier run, unique). A typed id may only pick one of the valid candidates.
        resolved_authority = RestAuthorityRunResolver(api).resolve(
            plan, carrier_created_at, clock_port.now(), env.get("AUTHORITY_RUN_ID", ""))
        expected_authority = env.get("EXPECT_AUTHORITY_RUN_ID", "")
        if expected_authority and expected_authority != resolved_authority:
            raise live.LiveProofError("AUTHORITY_RUN_EXPECTATION_MISMATCH")
        executing_sha = env.get("GITHUB_SHA") or None
        evidence_path = None if args.prepare_only else Path(env["PROVIDER_OIDC_EVIDENCE_PATH"])
        ports = live.PublishPorts(
            clock=clock_port, target_reader=RestTargetReader(api), branch_reader=RestBranchReader(api),
            session_reader=reader, run_reader=RestRunReader(api),
            authority_evidence=RestAuthorityEvidenceLoader(api),
            provider_oidc_evidence=json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path else {},
            store=store, is_live=not args.prepare_only, compare_reader=RestCompareReader(api),
            executing_sha=executing_sha)
        # Read-only gate before the attempt marker, any write and any Jules call.
        live.preflight_publish(plan=plan, candidate_registry=registry, session_id=resolved_session,
                               authority_run_id=resolved_authority, ports=ports)
        if args.prepare_only:
            go = {"status": "READY", "go": "true", "session_id": resolved_session,
                  "authority_run_id": resolved_authority, "command_id": command_id}
            print(json.dumps(go, sort_keys=True))
            _write_outputs(args.github_output, go)
            if args.result_out:
                Path(args.result_out).write_text(json.dumps(go, sort_keys=True), encoding="utf-8")
            return 0
        result = live.run_publish_half(
            plan=plan, candidate_registry=registry, session_id=resolved_session,
            authority_run_id=resolved_authority, ports=ports)
    except AutoNoop as noop:  # not this proof's carrier success (or a duplicate event): nothing spent
        done = {"status": "NOOP", "stage": "event", "code": noop.code, "go": "false"}
        print(json.dumps(done, sort_keys=True))
        _write_outputs(args.github_output, {"go": "false"})
        if args.result_out:
            Path(args.result_out).write_text(json.dumps(done, sort_keys=True), encoding="utf-8")
        return 0
    except Exception as exc:  # setup failed before any provider read: nothing spent
        stopped = {"status": "STOPPED", "stage": "setup", "code": getattr(exc, "code", type(exc).__name__)}
        print(json.dumps(stopped))
        _write_outputs(args.github_output, {"go": "false"})
        if args.result_out:
            Path(args.result_out).write_text(json.dumps(stopped, sort_keys=True), encoding="utf-8")
        return 1
    document = {
        "status": result.status,
        "stage": result.stage,
        "code": result.code,
        "failure_detail": live.safe_failure_detail(result.reasons[0] if result.reasons else None),
        "counters": result.counters,
        "evidence_payload_sha256": (result.evidence or {}).get("evidence_payload_sha256"),
    }
    print(json.dumps(document, sort_keys=True))
    if args.result_out:
        Path(args.result_out).write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    return 0 if result.status == "COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
