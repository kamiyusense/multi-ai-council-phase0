"""Deterministic in-memory GitHub/Jules world for Claude x Jules loop tests.

No network, no provider, no subprocess.  The fake GitHub mirrors the Contents
API (create-only conflicts, per-branch commits) and a tiny git object graph
(non-force fast-forward only).  FakeJules mimics the observed real behaviour:
the carrier workflow accepts one command, Jules starts from
``jules-work/<command_id>``, pushes ``jules-work/<command_id>-<session>`` and
opens a PR whose body ends with the ``jules.google.com/task/<session>`` footer.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.loop_owner_backend import owner_event_path

REPO = "kamiyusense/multi-ai-council-phase0"
TARGET = "claude/autoloop-mock-target"
CARRIER = "feature/chat-work-command-bus"
DATA = "claude/autoloop-mock-data"
LOOP = "claude-auto-loop-001"
HOLDER = "claude-auto-controller-1"
NOW = "2026-10-01T13:00:00+00:00"


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


class FakeGitHub:
    """Contents API + git refs over one shared fake repository."""

    def __init__(self) -> None:
        self.files: dict[tuple[str, str], GitHubContent] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        self.branches: dict[str, str] = {}
        self.writes: list[tuple[str, str, str]] = []
        self.create_hook: Callable[[str, str], str | None] | None = None
        self.ff_hook: Callable[[str], str | None] | None = None
        self.counter = 0
        root = self.commit(None, {"README.md": "root\n"}, "root")
        for branch in (TARGET, CARRIER, DATA):
            self.branches[branch] = root

    # -- git graph -----------------------------------------------------------
    def commit(self, parent: str | None, files: dict[str, str], message: str) -> str:
        self.counter += 1
        tree = _sha(json.dumps(sorted(files.items())))
        sha = _sha(f"{parent}:{tree}:{message}:{self.counter}")
        self.commits[sha] = {"parent": parent, "tree": tree, "files": dict(files)}
        return sha

    def child(self, parent: str, changes: dict[str, str | None], message: str) -> str:
        files = dict(self.commits[parent]["files"])
        for path, text in changes.items():
            if text is None:
                files.pop(path, None)
            else:
                files[path] = text
        return self.commit(parent, files, message)

    def ancestors(self, sha: str) -> list[str]:
        chain = []
        while sha is not None:
            chain.append(sha)
            sha = self.commits[sha]["parent"]
        return chain

    def get_branch_head(self, branch: str) -> str | None:
        return self.branches.get(branch)

    def get_commit_tree(self, sha: str) -> str | None:
        return self.commits.get(sha, {}).get("tree")

    def create_branch(self, branch: str, sha: str) -> None:
        if branch in self.branches:
            raise RuntimeError("ref exists")
        self.branches[branch] = sha
        self.writes.append(("ref", branch, sha))

    def compare(self, base: str, head: str) -> dict[str, Any] | None:
        if base not in self.commits or head not in self.commits:
            return None
        head_chain, base_chain = self.ancestors(head), self.ancestors(base)
        merge_base = next(sha for sha in head_chain if sha in set(base_chain))
        before, after = self.commits[base]["files"], self.commits[head]["files"]
        files = []
        for path in sorted(set(before) | set(after)):
            if path not in before:
                files.append({"path": path, "status": "added"})
            elif path not in after:
                files.append({"path": path, "status": "removed"})
            elif before[path] != after[path]:
                files.append({"path": path, "status": "modified"})
        return {"base_sha": base, "head_sha": head, "merge_base": merge_base,
                "ahead_by": head_chain.index(merge_base), "behind_by": base_chain.index(merge_base),
                "files": files}

    def fast_forward_branch(self, branch: str, expected_old: str, new_sha: str) -> dict[str, Any]:
        if self.ff_hook is not None and (verdict := self.ff_hook(branch)) is not None:
            if verdict == "raise-after-write":
                self._ff(branch, expected_old, new_sha)
            raise RuntimeError("ambiguous fast-forward")
        return self._ff(branch, expected_old, new_sha)

    def _ff(self, branch: str, expected_old: str, new_sha: str) -> dict[str, Any]:
        if self.branches.get(branch) != expected_old or expected_old not in self.ancestors(new_sha):
            raise RuntimeError("not a fast-forward")
        self.branches[branch] = new_sha
        self.writes.append(("ff", branch, new_sha))
        return {"status": "WRITTEN"}

    # -- contents API ----------------------------------------------------------
    def get(self, path: str, ref: str) -> GitHubContent | None:
        return self.files.get((ref, path))

    def list(self, prefix: str, ref: str) -> list[GitHubContent]:
        return [c for (branch, path), c in sorted(self.files.items()) if branch == ref and path.startswith(prefix)]

    def create(self, path: str, text: str, message: str, branch: str) -> GitHubContent:
        hook = self.create_hook(path, branch) if self.create_hook else None
        if hook == "raise-before-write":
            raise RuntimeError("transport failure before write")
        if (branch, path) in self.files:
            raise RuntimeError("create-only conflict")
        content = GitHubContent(path=path, text=text, sha=_sha(text))
        self.files[(branch, path)] = content
        self.branches[branch] = self.child(self.branches[branch], {path: text}, message)
        self.writes.append(("create", branch, path))
        if hook == "raise-after-write":
            raise RuntimeError("response lost after write")
        return content

    def update(self, path: str, text: str, sha: str, message: str, branch: str) -> GitHubContent:
        raise AssertionError("Claude AUTO records are create-only")

    def json(self, branch: str, path: str) -> Any:
        return json.loads(self.files[(branch, path)].text)


def owner_event(*, generation: int = 1, role: str = "AUTO", holder: str = HOLDER,
                event_type: str = "ACQUIRE", expires_at: str = "2026-10-01T23:00:00+00:00",
                previous: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "schema_version": 1, "event_id": f"owner-{generation}", "event_type": event_type,
        "loop_id": LOOP, "owner_role": role, "holder_id": holder, "generation": generation,
        "fencing_token": generation, "previous_generation": generation - 1 if generation > 1 else None,
        "claimed_at": "2026-10-01T12:00:00+00:00", "expires_at": expires_at,
        "expected_repo": REPO, "expected_pr": 999, "expected_target_head": "a" * 40,
        "command_id": f"owner-cmd-{generation}", "correlation_id": f"owner-corr-{generation}",
        "source_receipt_id": f"owner-receipt-{generation}",
        "source_receipt_ref": f"automation/command_bus/receipts/{LOOP}/{generation:06d}.json",
        "evidence_refs": [f"automation/command_bus/evidence/{LOOP}/owner-{generation}.json"],
    }
    if event_type == "HANDOFF" and previous is not None:
        event["previous_owner_role"], event["previous_holder_id"] = previous["owner_role"], previous["holder_id"]
    return event


def seed_owner(github: FakeGitHub, *events: dict[str, Any]) -> None:
    for event in events:
        path = owner_event_path(event["loop_id"], event["generation"])
        github.files[(DATA, path)] = GitHubContent(path=path, text=json.dumps(event), sha=_sha(path))


def policy(**overrides: Any) -> dict[str, Any]:
    value = {
        "schema_version": 1, "profile": "CLAUDE_AUTO_JULES_POLICY_V1", "controller_id": "claude-auto",
        "holder_id": HOLDER, "target_repo": REPO, "default_branch": "main", "carrier_branch": CARRIER,
        "data_branch": DATA, "allowed_target_branches": [TARGET], "allowed_lane_ids": ["J-BLUE"],
        "expected_pr": 999, "max_rounds": 6,
        "live_dispatch_authorization": {
            "approved_by": "mock-human", "approval_ref": "mock-approval", "scope": "mock-only",
            "max_dispatches": 6, "expires_at": "2026-10-02T00:00:00+00:00",
        },
    }
    value.update(overrides)
    return value


def task_spec(task_id: str = "alpha-helper", path: str = "automation/command_bus/alpha.py",
              test_path: str = "automation/command_bus/tests/test_alpha.py") -> dict[str, Any]:
    return {
        "schema_version": 1, "task_id": task_id, "size": "MEDIUM", "task_class": "static helper",
        "goal": "Add one pure helper.", "non_goals": "No I/O.",
        "read_first": ["automation/command_bus/claude_loop.py"],
        "allowed_paths": [{"path": path, "allowed_ops": ["ADD", "MODIFY"]},
                          {"path": test_path, "allowed_ops": ["ADD", "MODIFY"]}],
        "do_not_touch": ["no workflow changes"], "reuse": ["Reuse claude_loop helpers."],
        "semantics": ["helper returns exact value"], "negative_cases": ["bool-as-int rejected"],
        "acceptance": ["helper behaviour asserted directly"],
        "validation_commands": ["python -m unittest discover -s automation/command_bus/tests -t ."],
        "publication": "Publish the normal isolated Jules PR only if all checks pass.",
        "stop_conditions": ["allowlist expansion needed"],
        "acceptance_checks": ["helper_exact_value", "bool_as_int_rejected"],
    }


def roadmap(*specs: dict[str, Any]) -> dict[str, Any]:
    tasks, previous = [], []
    for spec in specs or (task_spec(),):
        tasks.append({"task_spec": spec, "depends_on": list(previous)})
        previous = [spec["task_id"]]
    return {"schema_version": 1, "profile": "CLAUDE_AUTO_JULES_ROADMAP_V1", "roadmap_id": "mock", "tasks": tasks}


GOOD_TEST = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(helper(1), 2)\n"
VACUOUS_TEST = "import unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertTrue(True)\n"


class FakeJules:
    """Simulates the carrier workflow + Jules for one appended command."""

    def __init__(self, github: FakeGitHub):
        self.github = github
        self.sessions = 0
        self.prs: dict[int, dict[str, Any]] = {}
        self.observations: dict[str, dict[str, Any]] = {}
        self.next_pr = 300

    def pending_commands(self) -> list[str]:
        prefix = "automation/command_bus/jules_api_requests/"
        done = set(self.observations)
        return [c.path[len(prefix):-5] for c in self.github.list(prefix, CARRIER) if c.path[len(prefix):-5] not in done]

    def run(self, command_id: str, *, changes: dict[str, str | None] | None = None,
            body_session: str | None = None) -> dict[str, Any]:
        request = self.github.json(CARRIER, f"automation/command_bus/jules_api_requests/{command_id}.json")
        work = request["work_branch"]
        assert self.github.branches[work] == request["expected_target_head"]
        self.sessions += 1
        session = str(9_000_000 + self.sessions)
        self.observations[command_id] = {"command_id": command_id, "workflow_run_id": f"run-{self.sessions}",
                                         "conclusion": "success", "session_id": session}
        paths = request["allowed_paths"]
        default = {paths[0]: f"def helper(x):\n    return x + 1  # {command_id}\n"}
        if len(paths) > 1:
            default[paths[1]] = GOOD_TEST
        head = self.github.child(request["expected_target_head"], changes if changes is not None else default, f"jules {command_id}")
        branch = f"{work}-{session}"
        self.github.branches[branch] = head
        number = self.next_pr
        self.next_pr += 1
        footer = body_session or session
        self.prs[number] = {"number": number, "state": "open", "merged": False, "base_ref": work, "head_sha": head,
                            "head_ref": branch,
                            "body": f"Done.\n\n---\n*PR created automatically by Jules for task [{footer}](https://jules.google.com/task/{footer}) started by @kamiyusense*"}
        return self.payload(number, "opened")

    def push_followup(self, number: int, changes: dict[str, str | None]) -> dict[str, Any]:
        pr = self.prs[number]
        pr["head_sha"] = self.github.child(pr["head_sha"], changes, "jules follow-up")
        self.github.branches[pr["head_ref"]] = pr["head_sha"]
        return self.payload(number, "synchronize")

    def payload(self, number: int, action: str) -> dict[str, Any]:
        pr = self.prs[number]
        repo = {"full_name": REPO}
        return {"action": action, "repository": repo, "pull_request": {
            "number": number, "state": pr["state"], "merged": pr["merged"], "body": pr["body"],
            "base": {"ref": pr["base_ref"], "repo": repo},
            "head": {"ref": pr["head_ref"], "sha": pr["head_sha"], "repo": repo}}}


class FakeFacts:
    """Claude-side evidence: own test run, own review, own small repair."""

    def __init__(self, github: FakeGitHub, jules: FakeJules):
        self.github, self.jules = github, jules
        self.test_failures: set[str] = set()
        self.review_failures: dict[str, list[dict[str, Any]]] = {}
        self.repair_text: str | None = None
        self.calls: list[str] = []

    def dispatch_observation(self, command_id: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.jules.observations.get(command_id))

    def fresh_pr(self, number: int) -> dict[str, Any] | None:
        pr = self.jules.prs.get(number)
        return None if pr is None else {k: pr[k] for k in ("number", "state", "merged", "base_ref", "head_sha", "head_ref", "body")}

    def compare(self, base: str, head: str) -> dict[str, Any] | None:
        return self.github.compare(base, head)

    def commit_tree(self, sha: str) -> str | None:
        return self.github.get_commit_tree(sha)

    def run_tests(self, head: str) -> dict[str, Any]:
        self.calls.append(f"tests:{head}")
        failed = head in self.test_failures
        return {"head_sha": head, "tree_sha": self.github.get_commit_tree(head), "tests_run": 42,
                "exit_code": 1 if failed else 0, "failures": 1 if failed else 0, "errors": 0}

    def test_sources(self, head: str, paths: list[str]) -> dict[str, str]:
        files = self.github.commits[head]["files"]
        return {p: files[p] for p in paths if p in files}

    def review(self, intent: dict[str, Any], spec: dict[str, Any], head: str):
        self.calls.append(f"review:{head}")
        failures = self.review_failures.get(head, [])
        observations = {name: {"result": "PASS", "evidence": f"asserted directly at {head[:8]}"}
                        for name in list(spec["acceptance_checks"]) + ["negative_cases_exercised", "regression_suite_reviewed"]}
        return observations, copy.deepcopy(failures)

    def small_repair(self, intent: dict[str, Any], inspection: dict[str, Any]) -> str | None:
        path = intent["carrier_request"]["allowed_paths"][1]
        head = self.github.child(inspection["candidate_head"], {path: self.repair_text or GOOD_TEST}, "claude small repair")
        self.github.branches[f"claude-auto-repair/{intent['carrier_request']['command_id']}"] = head
        return head
