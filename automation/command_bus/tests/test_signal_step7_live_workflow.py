"""STATIC checks of the Step 7 live-publish workflow candidate, CLI ports and carrier files.

No network, no Jules, no GitHub write. The workflow is only text-checked here.
"""
from __future__ import annotations

import base64
import io
import json
import re
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from automation.command_bus import signal_step7_live_proof as live
from automation.command_bus import signal_step7_live_proof_cli as cli
from automation.command_bus.jules_api_request import validate_request
from automation.command_bus.loop_id_claim import verify_command_claim

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = (ROOT / ".github/workflows/signal-step7-live-publish.yml").read_text(encoding="utf-8")
TEST_WORKFLOW = (ROOT / ".github/workflows/loop-status-signal-test.yml").read_text(encoding="utf-8")
TEMPLATE_PATH = ROOT / "docs/evidence/signal-sf8/step7-live-plan-template.json"
REGISTRY_PATH = ROOT / "docs/evidence/signal-sf8/registry-candidate-chatgpt-semi-auto-durable.json"
TEMPLATE = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
HEAD, TREE = "a" * 40, "b" * 40
NOW = "2026-10-03T00:00:00+00:00"


def code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


class WorkflowStaticTests(unittest.TestCase):
    def test_only_workflow_dispatch_can_start_it(self):
        body = "\n".join(code_lines(WORKFLOW))
        on_block = re.search(r"^on:\n((?:[ ]{2,}.*\n)+)", body + "\n", re.M).group(1)
        self.assertEqual(re.findall(r"^  ([a-z_]+):", on_block, re.M), ["workflow_dispatch"])
        for forbidden in ("push:", "pull_request", "schedule:", "workflow_run", "workflow_call", "issue_comment",
                          "repository_dispatch", "pull_request_target"):
            self.assertNotIn(forbidden, body)

    def test_job_guard_is_main_attempt_one_dispatch_and_the_single_owner(self):
        condition = re.search(r"^    if: (.+)$", WORKFLOW, re.M).group(1)
        for part in ("github.repository == 'kamiyusense/multi-ai-council-phase0'",
                     "github.ref == 'refs/heads/main'", "github.run_attempt == 1",
                     "github.event_name == 'workflow_dispatch'",
                     "contains(fromJSON('[\"20355232\"]'), github.actor_id)"):
            self.assertIn(part, condition)
        self.assertNotIn("triggering_actor_id", WORKFLOW, "undocumented context must never be used")

    def test_permissions_are_minimal_and_have_no_id_token(self):
        block = re.search(r"^permissions:\n((?:  .+\n)+)", WORKFLOW, re.M).group(1)
        self.assertEqual(sorted(line.strip() for line in block.splitlines()),
                         ["actions: read", "contents: write", "pull-requests: read"])
        self.assertNotIn("id-token", WORKFLOW)

    def test_actions_are_pinned_and_credentials_not_persisted(self):
        uses = re.findall(r"uses:\s*(\S+)", WORKFLOW)
        self.assertTrue(uses)
        for ref in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$")
        self.assertIn("persist-credentials: false", WORKFLOW)

    def test_the_jules_key_is_only_in_the_one_publish_step(self):
        self.assertEqual(WORKFLOW.count("secrets.JULES_API_KEY"), 1)
        self.assertEqual(WORKFLOW.count("JULES_API_KEY:"), 1)
        publish = WORKFLOW.split("- name: Publish once with one fresh Jules read", 1)[1].split("- name:", 1)[0]
        self.assertIn("JULES_API_KEY: ${{ secrets.JULES_API_KEY }}", publish)
        validate = WORKFLOW.split("- name: Validate inputs", 1)[1].split("- name:", 1)[0]
        self.assertNotIn("secrets.", validate)
        for line in code_lines(WORKFLOW):
            if "echo" in line or "printf" in line:
                self.assertNotIn("secrets.", line)
                self.assertNotIn("KEY", line)
                self.assertNotIn("TOKEN", line)

    def test_workflow_cannot_post_merge_message_or_retry(self):
        body = "\n".join(code_lines(WORKFLOW))
        for forbidden in ("curl", "--retry", "-X POST", "jules.googleapis.com", "sendMessage", "approvePlan",
                          "merge", "force", "rebase", "continue-on-error", "workflow_dispatch(", "gh api",
                          "control_tower_registry.json", "issues/33"):
            self.assertNotIn(forbidden, body)

    def test_inputs_are_validated_before_any_secret_step(self):
        validate = WORKFLOW.split("- name: Validate inputs", 1)[1].split("- name:", 1)[0]
        for needle in ("^[0-9]{1,24}$", "301196275118188780", "5943440322658150300", "^[0-9a-f]{64}$", "--check"):
            self.assertIn(needle, validate)
        self.assertLess(WORKFLOW.index("- name: Validate inputs"), WORKFLOW.index("- name: Publish once"))

    def test_session_id_input_is_optional_and_only_a_cross_check(self):
        block = WORKFLOW.split("      session_id:", 1)[1].split("      authority_run_id:", 1)[0]
        self.assertIn("required: false", block)
        self.assertIn("default: ''", block)

    def test_artifact_is_the_sanitized_result_only(self):
        upload = WORKFLOW.split("uses: actions/upload-artifact", 1)[1]
        self.assertIn("path: ${{ runner.temp }}/step7-live-result.json", upload)
        self.assertEqual(len(re.findall(r"upload-artifact", WORKFLOW)), 1)

    def test_no_other_workflow_references_or_chains_this_one(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            if path.name in {"signal-step7-live-publish.yml", "loop-status-signal-test.yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("signal-step7-live-publish", text)
            self.assertNotIn("Step 7 live publish", text)

    def test_the_test_workflow_runs_for_the_new_files(self):
        for path in (".github/workflows/signal-step7-live-publish.yml",
                     "automation/command_bus/signal_step7_live_proof.py",
                     "automation/command_bus/signal_step7_live_proof_cli.py",
                     "automation/command_bus/tests/test_signal_step7_live_proof.py",
                     "automation/command_bus/tests/test_signal_step7_live_workflow.py",
                     "docs/evidence/signal-sf8/**"):
            self.assertIn(f"- {path}", TEST_WORKFLOW)


class CarrierFilesTests(unittest.TestCase):
    def bound(self, **changes):
        args = dict(loop_number=133, target_pr=7, target_head=HEAD, target_tree=TREE, now=NOW)
        args.update(changes)
        return live.bind_plan(TEMPLATE, **args)

    def test_template_is_valid_but_not_bound_so_it_cannot_run(self):
        live.validate_plan(TEMPLATE, REGISTRY)
        with self.assertRaises(live.LiveProofError) as ctx:
            live.validate_plan(TEMPLATE, REGISTRY, require_bound=True)
        self.assertEqual(ctx.exception.code, "PLAN_NOT_BOUND_TO_TARGET")

    def test_bound_plan_passes_the_unchanged_carrier_validators(self):
        plan = self.bound()
        live.validate_plan(plan, REGISTRY, require_bound=True)
        now = datetime(2026, 10, 3, 0, 5, tzinfo=timezone.utc)
        request = validate_request(plan["request"], now=now)
        claim = verify_command_claim(plan["request"], plan["carrier_claim"], require_dispatchable_current=True)
        self.assertEqual(request["allowed_paths"], [live.ALLOWED_PATH])
        self.assertEqual(claim["loop_id"], "133")
        self.assertEqual(plan["request"]["work_branch"], f"jules-work/{plan['request']['command_id']}")
        self.assertNotEqual(plan["request"]["work_branch"], plan["target_branch"])
        self.assertEqual((plan["request"]["retry"], plan["request"]["fallback"]), (0, "disabled"))
        self.assertFalse(plan["request"]["merge_allowed"])
        self.assertFalse(plan["request"]["force_push_allowed"])
        self.assertIn("signal active proof 3", plan["request"]["prompt"])
        self.assertNotIn(live.LANE_ID, (plan["request"]["command_id"], plan["durable_context"]["correlation_id"]))

    def test_command_file_names_match_the_carrier_path_filters(self):
        files = live.carrier_files(self.bound())
        paths = sorted(files)
        self.assertEqual(len(paths), 2)
        self.assertTrue(re.fullmatch(r"automation/command_bus/jules_api_requests/[a-z0-9][a-z0-9._-]{0,63}\.json", paths[0]))
        self.assertEqual(paths[1], "automation/command_bus/loop_id_claims/133.json")

    def test_binding_never_changes_the_human_gate_or_lane(self):
        plan = self.bound()
        self.assertEqual(plan["lane_id"], "chatgpt-semi-auto")
        self.assertFalse(plan["registry_write_allowed"])
        self.assertTrue(plan["human_approval_required"])
        self.assertEqual(plan["limits"], live.LIMITS)

    def test_binder_cli_writes_only_under_the_requested_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = cli.main(["--plan", str(TEMPLATE_PATH), "--registry", str(REGISTRY_PATH), "--bind-out", tmp,
                             "--loop-number", "133", "--target-pr", "7", "--target-head", HEAD,
                             "--target-tree", TREE, "--now", NOW], env={})
            self.assertEqual(code, 0)
            written = sorted(str(p.relative_to(tmp)) for p in Path(tmp).rglob("*.json"))
            self.assertEqual(len(written), 3, written)
            bound = json.loads((Path(tmp) / "plan.bound.json").read_text(encoding="utf-8"))
            live.validate_plan(bound, REGISTRY, require_bound=True)
        self.assertFalse((ROOT / "automation/command_bus/loop_id_claims/133.json").exists())

    def test_template_fixture_head_is_refused_at_run_time_even_if_a_caller_forgets_to_bind(self):
        from automation.command_bus.tests.test_signal_step7_live_proof import make_ports

        result = live.run_publish_half(plan=TEMPLATE, candidate_registry=REGISTRY, session_id="123",
                                       authority_run_id="456", ports=make_ports())
        self.assertEqual(result.code, "PLAN_NOT_BOUND_TO_TARGET")


class Http:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        return self.responses.pop(0)


def jr(value, status=200, headers=None):
    return status, headers or {}, json.dumps(value).encode()


class CliPortTests(unittest.TestCase):
    def test_jules_reader_makes_one_get_and_never_leaks_the_key(self):
        http = Http([jr({"name": "sessions/42", "createTime": "2026-10-03T00:00:00Z", "updateTime": "2026-10-03T00:01:00Z",
                         "state": "IN_PROGRESS", "extra": "dropped", "outputs": [{"x": 1}],
                         "sourceContext": {"source": "sources/github/kamiyusense/multi-ai-council-phase0",
                                           "githubRepoContext": {"startingBranch": "jules-work/x"}}})])
        reader = cli.JulesActiveSessionGetReader("secret-key-123", http=http)
        result = reader.read_active_session("42", expected_branch="jules-work/x")
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(http.calls[0][0], "GET")
        self.assertNotIn("include_activities=true", http.calls[0][1])
        self.assertEqual(http.calls[0][2], {"X-Goog-Api-Key": "secret-key-123"})
        self.assertEqual(set(result), {"name", "createTime", "updateTime", "state", "sourceContext"})
        self.assertNotIn("secret-key-123", json.dumps(result))

    def test_jules_reader_failures_have_fixed_text_and_no_key(self):
        for response in (jr({}, 500), jr({"name": "sessions/9", "createTime": "2026-10-03T00:00:00Z"}),
                         (200, {}, b"not json"), (200, {}, b"x" * (cli._LIMIT + 1))):
            with self.subTest(response=response[0]):
                reader = cli.JulesActiveSessionGetReader("secret-key-123", http=Http([response]))
                with self.assertRaises(ValueError) as ctx:
                    reader.read_active_session("42", expected_branch="jules-work/x")
                self.assertEqual(str(ctx.exception), cli._ERROR)
                self.assertNotIn("secret-key-123", repr(ctx.exception))
        reader = cli.JulesActiveSessionGetReader("k", http=Http([]))
        for bad in ("../1", "abc", ""):
            with self.assertRaises(ValueError):
                reader.read_active_session(bad, expected_branch="jules-work/x")
        with self.assertRaises(ValueError):
            reader.read_active_session("1", expected_branch="main")

    def test_missing_keys_stop_before_any_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            bound = live.bind_plan(TEMPLATE, loop_number=133, target_pr=7, target_head=HEAD, target_tree=TREE, now=NOW)
            plan_path = Path(tmp) / "plan.json"
            plan_path.write_text(json.dumps(bound), encoding="utf-8")
            http = Http([])
            for env in ({}, {"GITHUB_TOKEN": "t"}, {"JULES_API_KEY": "k"}):
                code = cli.main(["--plan", str(plan_path), "--registry", str(REGISTRY_PATH)], env=env, http=http)
                self.assertEqual(code, 1)
            self.assertEqual(http.calls, [])

    def test_check_mode_needs_no_environment(self):
        self.assertEqual(cli.main(["--plan", str(TEMPLATE_PATH), "--registry", str(REGISTRY_PATH), "--check"], env={}), 0)

    def test_contents_client_refuses_default_branch_and_encodes_content(self):
        http = Http([jr({"content": {"sha": "s1"}}, 201)])
        client = cli.RestContentsClient(cli.RestApi("t", http=http))
        with self.assertRaises(ValueError):
            client.create("a/b.json", "x", "m", "main")
        with self.assertRaises(ValueError):
            client.update("a/b.json", "x", "sha", "m", "master")
        created = client.create("a/b.json", "hello", "m", "signal/data")
        self.assertEqual(created.sha, "s1")
        method, url, headers, body = http.calls[0]
        self.assertEqual(method, "PUT")
        payload = json.loads(body)
        self.assertEqual(payload["branch"], "signal/data")
        self.assertEqual(base64.b64decode(payload["content"]), b"hello")
        self.assertEqual(len(http.calls), 1, "no retry")

    def test_contents_get_missing_is_none_and_errors_raise(self):
        client = cli.RestContentsClient(cli.RestApi("t", http=Http([jr({}, 404)])))
        self.assertIsNone(client.get("a.json", "signal/data"))
        client = cli.RestContentsClient(cli.RestApi("t", http=Http([jr({}, 500)])))
        with self.assertRaises(RuntimeError):
            client.get("a.json", "signal/data")

    def test_artifact_download_drops_the_token_when_following_the_redirect(self):
        http = Http([(302, {"Location": "https://blob.example/x"}, b""), (200, {}, b"zip")])
        api = cli.RestApi("tok-1", http=http)
        self.assertEqual(api.download("actions/artifacts/1/zip"), b"zip")
        self.assertIn("Authorization", http.calls[0][2])
        self.assertEqual(http.calls[1][2], {})
        self.assertEqual(len(http.calls), 2)

    def evidence_zip(self, names=("oidc-proof-evidence.json",), payload=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            for name in names:
                archive.writestr(name, json.dumps(payload or {"schema_version": 2}))
        return buf.getvalue()

    def test_authority_evidence_loader_accepts_exactly_one_matching_artifact(self):
        listing = {"artifacts": [{"id": 5, "name": "sf8-authority-evidence-99", "expired": False}]}
        http = Http([jr(listing), (302, {"Location": "https://blob.example/z"}, b""), (200, {}, self.evidence_zip())])
        loader = cli.RestAuthorityEvidenceLoader(cli.RestApi("t", http=http))
        self.assertEqual(loader.load("99"), {"schema_version": 2})
        for bad in (
            {"artifacts": []},
            {"artifacts": [{"id": 5, "name": "sf8-authority-evidence-98", "expired": False}]},
            {"artifacts": [{"id": 5, "name": "sf8-authority-evidence-99", "expired": True}]},
            {"artifacts": [{"id": 5, "name": "sf8-authority-evidence-99", "expired": False},
                           {"id": 6, "name": "sf8-authority-evidence-99", "expired": False}]},
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(cli.RestAuthorityEvidenceLoader(cli.RestApi("t", http=Http([jr(bad)]))).load("99"))
        http = Http([jr(listing), (302, {"Location": "https://blob.example/z"}, b""),
                     (200, {}, self.evidence_zip(names=("oidc-proof-evidence.json", "extra.txt")))])
        self.assertIsNone(cli.RestAuthorityEvidenceLoader(cli.RestApi("t", http=http)).load("99"))

    def test_run_and_target_readers_pass_through_exactly_what_github_returned(self):
        run = {"id": 1, "path": "p"}
        self.assertEqual(cli.RestRunReader(cli.RestApi("t", http=Http([jr(run)]))).read_run("1"), run)
        self.assertIsNone(cli.RestRunReader(cli.RestApi("t", http=Http([jr({}, 404)]))).read_run("1"))
        pr = {"number": 7, "state": "open", "merged": False, "draft": True,
              "head": {"ref": "b", "sha": HEAD, "repo": {"full_name": live.REPOSITORY}}}
        target = cli.RestTargetReader(cli.RestApi("t", http=Http([jr(pr)]))).read_target(live.REPOSITORY, 7)
        self.assertEqual(target["draft"], True)
        self.assertEqual(target["head"], {"ref": "b", "sha": HEAD})


def carrier_log(command_id, session_id):
    """Same line shapes as the real carrier job log (timestamp prefix, env block of the summary step)."""
    stamp = "2026-10-03T04:20:54.9554643Z"
    return "\n".join([
        f"{stamp} \x1b[36;1m  echo \"- command_id: \\`${{COMMAND_ID:-UNKNOWN}}\\`\"\x1b[0m",
        f"{stamp} env:",
        f"{stamp}   COMMAND_ID: {command_id}",
        f"{stamp}   SESSION_ID: {session_id}",
        f"{stamp}   LOOP_ID: 133", ""])


class FakeWorld:
    """In-memory GitHub + Jules REST surface for an end-to-end run of cli.main (no real network)."""

    def __init__(self, *, session_state="IN_PROGRESS", session_status=200):
        from urllib.parse import unquote
        self.unquote = unquote
        self.files: dict[tuple[str, str], tuple[str, str]] = {}
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.session_state, self.session_status = session_state, session_status
        self.session_id = "424242424242424242"
        self.authority_run = "7700000002"
        self.carrier_logs: dict[int, str] = {}

    def seed(self, branch, path, text):
        self.files[(branch, path)] = (text, f"sha-{len(self.files)}")

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers)))
        if url.startswith(cli.JULES_API):
            sid = url.rsplit("/", 1)[1]
            return (self.session_status, {}, json.dumps({
                "name": f"sessions/{sid}", "createTime": "2026-10-03T00:05:00Z", "updateTime": "2026-10-03T00:08:00Z",
                "state": self.session_state,
                "sourceContext": {"source": f"sources/github/{live.REPOSITORY}",
                                  "githubRepoContext": {"startingBranch": self.work_branch}}}).encode())
        if url.startswith("https://blob.example/log/"):
            return 200, {}, self.carrier_logs[int(url.rsplit("/", 1)[1])].encode()
        if url == "https://blob.example/zip":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as archive:
                archive.writestr("oidc-proof-evidence.json", json.dumps(self.authority_evidence))
            return 200, {}, buf.getvalue()
        path = url.split(f"/repos/{live.REPOSITORY}/", 1)[1]
        if path.startswith("pulls/"):
            return 200, {}, json.dumps({"number": 7, "state": "open", "merged": False, "draft": True,
                                        "head": {"ref": self.target_branch, "sha": HEAD,
                                                 "repo": {"full_name": live.REPOSITORY}}}).encode()
        if path.startswith("branches/"):
            name = self.unquote(path.split("/", 1)[1])
            sha = "c" * 40 if name == "main" else HEAD
            if name not in {"main", self.target_branch, self.work_branch}:
                return 404, {}, b"{}"
            return 200, {}, json.dumps({"commit": {"sha": sha}}).encode()
        if path.startswith("git/commits/"):
            return 200, {}, json.dumps({"tree": {"sha": "e" * 40 if path.endswith("c" * 40) else TREE}}).encode()
        if path.startswith(f"actions/workflows/{cli.CARRIER_WORKFLOW}/runs"):
            return 200, {}, json.dumps({"workflow_runs": [
                {"id": 9000 + n, "conclusion": "success"} for n in sorted(self.carrier_logs)]}).encode()
        if path.startswith("actions/runs/90") and path.endswith("/jobs"):
            n = int(path.split("/")[2]) - 9000
            return 200, {}, json.dumps({"jobs": [{"id": 100 + n, "conclusion": "success"}]}).encode()
        if path.startswith("actions/jobs/1") and path.endswith("/logs"):
            return 302, {"Location": f"https://blob.example/log/{int(path.split('/')[2]) - 100}"}, b""
        if path == f"actions/runs/{self.authority_run}":
            return 200, {}, json.dumps(self.authority_run_json).encode()
        if path == f"actions/runs/{live.PROVIDER_OIDC_RUN_ID}":
            return 200, {}, json.dumps(self.provider_run_json).encode()
        if path == f"actions/runs/{self.authority_run}/artifacts":
            return 200, {}, json.dumps({"artifacts": [{"id": 77, "name": f"sf8-authority-evidence-{self.authority_run}",
                                                       "expired": False}]}).encode()
        if path == "actions/artifacts/77/zip":
            return 302, {"Location": "https://blob.example/zip"}, b""
        if path.startswith("contents/"):
            route, _, query = path.partition("?ref=")
            file_path, branch = self.unquote(route[len("contents/"):]), self.unquote(query)
            if method == "GET":
                found = self.files.get((branch, file_path))
                if found is None:
                    prefix = file_path.rstrip("/") + "/"
                    children = {}
                    for (b, name) in self.files:
                        if b == branch and name.startswith(prefix):
                            head = name[len(prefix):].split("/", 1)
                            kind = "file" if len(head) == 1 else "dir"
                            children[prefix + head[0]] = kind
                    if not children:
                        return 404, {}, b"{}"
                    return 200, {}, json.dumps([{"type": kind, "path": path_}
                                                for path_, kind in sorted(children.items())]).encode()
                return 200, {}, json.dumps({"type": "file", "sha": found[1], "content":
                                            base64.b64encode(found[0].encode()).decode()}).encode()
            payload = json.loads(body)
            key = (payload["branch"], self.unquote(route[len("contents/"):]))
            if key in self.files and "sha" not in payload:
                return 422, {}, b"{}"
            text = base64.b64decode(payload["content"]).decode()
            self.files[key] = (text, f"sha-{len(self.files)}-{len(text)}")
            return 201, {}, json.dumps({"content": {"sha": self.files[key][1]}}).encode()
        return 404, {}, b"{}"


class FixedClock:
    def now(self):
        return "2026-10-03T00:10:00+00:00"


class EndToEndCliTests(unittest.TestCase):
    def world(self, **kwargs):
        from automation.command_bus.github_oidc_proof_policy_cli import SF8_AUTHORITY_PROFILE, SF8_PROFILE
        from automation.command_bus.tests.test_oidc_workflow_execution import evidence_for, run_for

        world = FakeWorld(**kwargs)
        bound = live.bind_plan(TEMPLATE, loop_number=133, target_pr=7, target_head=HEAD, target_tree=TREE, now=NOW)
        world.target_branch, world.work_branch = bound["target_branch"], bound["work_branch"]
        world.bound = bound
        world.carrier_logs[1] = carrier_log(bound["request"]["command_id"], world.session_id)
        world.seed(bound["data_branch"], live.BOUND_PLAN_PATH, json.dumps(bound))
        main_sha = "c" * 40
        world.authority_run_json = run_for(SF8_AUTHORITY_PROFILE, run_id=world.authority_run, sha=main_sha,
                                           created_at="2026-10-03T00:02:00Z")
        world.authority_evidence = evidence_for(SF8_AUTHORITY_PROFILE, run_id=world.authority_run, sha=main_sha)
        world.provider_run_json = run_for(SF8_PROFILE, run_id=live.PROVIDER_OIDC_RUN_ID,
                                          sha=live.PROVIDER_OIDC_EXPECTED_SHA)
        world.provider_evidence = evidence_for(SF8_PROFILE, run_id=live.PROVIDER_OIDC_RUN_ID,
                                               sha=live.PROVIDER_OIDC_EXPECTED_SHA)
        return world

    def run_main(self, world, tmp, **env_changes):
        evidence_path = Path(tmp) / "provider-oidc.json"
        evidence_path.write_text(json.dumps(world.provider_evidence), encoding="utf-8")
        env = {"GITHUB_TOKEN": "gh-token-xyz", "JULES_API_KEY": "jules-key-xyz", "SESSION_ID": world.session_id,
               "AUTHORITY_RUN_ID": world.authority_run, "PLAN_SHA256": live.plan_digest(world.bound),
               "PROVIDER_OIDC_EVIDENCE_PATH": str(evidence_path)}
        env.update(env_changes)
        out = Path(tmp) / "result.json"
        code = cli.main(["--plan", str(TEMPLATE_PATH), "--registry", str(REGISTRY_PATH),
                         "--bound-plan-from-data-branch", "--result-out", str(out)], env=env, http=world, clock=FixedClock())
        return code, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)

    def test_dispatch_to_evidence_over_fake_rest_spends_one_get_and_writes_only_the_data_branch(self):
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            code, result = self.run_main(world, tmp)
        self.assertEqual((code, result["status"]), (0, "COMPLETE"), result)
        self.assertIsNone(result["failure_detail"])
        jules = [c for c in world.calls if c[1].startswith(cli.JULES_API)]
        self.assertEqual(len(jules), 1)
        self.assertEqual([c for c in world.calls if c[0] == "POST"], [])
        self.assertEqual(result["counters"]["whole_proof_total"], {"jules_post": 1, "jules_get": 2, "authority_dispatch": 0})
        branches = {branch for branch, _ in world.files}
        self.assertEqual(branches, {world.bound["data_branch"]})
        self.assertIn((world.bound["data_branch"], live.TERMINAL_RECEIPT_PATH), world.files)
        evidence = json.loads(world.files[(world.bound["data_branch"], live.EVIDENCE_PATH)][0])
        self.assertEqual((evidence["lane_id"], evidence["scope"]), ("chatgpt-semi-auto", "LIVE"))
        self.assertEqual(evidence["pre_adoption_gate"]["status"], "READY_FOR_HUMAN_APPROVAL")
        self.assertFalse(evidence["pre_adoption_gate"]["registry_write_allowed"])
        blob_calls = [c for c in world.calls if c[1].startswith("https://blob.example")]
        self.assertTrue(blob_calls and all("Authorization" not in c[2] for c in blob_calls))
        everything = json.dumps(result) + json.dumps({f"{k[0]}:{k[1]}": v[0] for k, v in world.files.items()})
        for secret in ("gh-token-xyz", "jules-key-xyz"):
            self.assertNotIn(secret, everything)

    def test_a_second_dispatch_is_refused_by_the_terminal_receipt_without_a_jules_read(self):
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            self.run_main(world, tmp)
            first_reads = len([c for c in world.calls if c[1].startswith(cli.JULES_API)])
            code, result = self.run_main(world, tmp)
        self.assertEqual((code, result["code"]), (1, "TERMINAL_RECEIPT_EXISTS"))
        self.assertEqual(len([c for c in world.calls if c[1].startswith(cli.JULES_API)]), first_reads)

    def test_digest_mismatch_or_missing_bound_plan_stops_before_any_provider_call(self):
        for changes in ({"PLAN_SHA256": "0" * 64},):
            world = self.world()
            with tempfile.TemporaryDirectory() as tmp:
                code, result = self.run_main(world, tmp, **changes)
            self.assertEqual(code, 1)
            self.assertEqual([c for c in world.calls if c[1].startswith(cli.JULES_API)], [])
        world = self.world()
        del world.files[(world.bound["data_branch"], live.BOUND_PLAN_PATH)]
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = self.run_main(world, tmp)
        self.assertEqual(code, 1)
        self.assertEqual([c for c in world.calls if c[1].startswith(cli.JULES_API)], [])

    def test_sub_second_provider_times_are_floored_and_still_publish(self):
        # Proof 2 stopped with PUBLISH_NOT_READY because Jules returns sub-second times
        # while the owner claim / observation / authenticator compare whole seconds.
        for create, update in (("2026-10-03T00:05:00Z", "2026-10-03T00:08:00.123456789Z"),
                               ("2026-10-03T00:05:00.9Z", "2026-10-03T00:09:59.500000Z"),
                               ("2026-10-03T00:05:00.250Z", "2026-10-03T00:05:00.250Z")):
            with self.subTest(create=create, update=update):
                world = self.world()
                original = world.__class__.__call__

                def call(method, url, headers, body, original=original, world=world, create=create, update=update):
                    status, hdrs, raw = original(world, method, url, headers, body)
                    if url.startswith(cli.JULES_API):
                        data = json.loads(raw)
                        data["createTime"], data["updateTime"] = create, update
                        raw = json.dumps(data).encode()
                    return status, hdrs, raw

                world.__class__ = type("SubSecondWorld", (world.__class__,), {"__call__": lambda self, m, u, h, b: call(m, u, h, b)})
                with tempfile.TemporaryDirectory() as tmp:
                    code, result = self.run_main(world, tmp)
                self.assertEqual((code, result["status"]), (0, "COMPLETE"), result)
                self.assertEqual(len([c for c in world.calls if c[1].startswith(cli.JULES_API)]), 1)

    def jules_calls(self, world):
        return [c for c in world.calls if c[1].startswith(cli.JULES_API)]

    def test_session_id_is_read_from_the_carrier_run_when_nothing_is_typed(self):
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            code, result = self.run_main(world, tmp, SESSION_ID="")
        self.assertEqual((code, result["status"]), (0, "COMPLETE"), result)
        called = self.jules_calls(world)
        self.assertEqual([c[1].rsplit("/", 1)[1] for c in called], [world.session_id])

    def test_a_typed_session_id_that_differs_from_the_carrier_record_stops_before_any_jules_call(self):
        world = self.world()
        with tempfile.TemporaryDirectory() as tmp:
            code, result = self.run_main(world, tmp, SESSION_ID="5943440322658150300")
        self.assertEqual((code, result["code"]), (1, "SESSION_ID_INPUT_MISMATCH"))
        self.assertEqual(self.jules_calls(world), [])
        self.assertNotIn((world.bound["data_branch"], live.ATTEMPT_MARKER_PATH), world.files)
        self.assertNotIn((world.bound["data_branch"], live.TERMINAL_RECEIPT_PATH), world.files)

    def test_no_or_ambiguous_carrier_record_stops_before_any_jules_call(self):
        command_id = self.world().bound["request"]["command_id"]
        cases = {"none": {}, "other_command": {1: carrier_log("relay-dev-loop-1-other", "111")},
                 "two_sessions": {1: carrier_log(command_id, "111"), 2: carrier_log(command_id, "222")}}
        for name, logs in cases.items():
            with self.subTest(name):
                world = self.world()
                world.carrier_logs = dict(logs)
                with tempfile.TemporaryDirectory() as tmp:
                    code, result = self.run_main(world, tmp, SESSION_ID="")
                self.assertEqual((code, result["code"]), (1, "CARRIER_SESSION_NOT_UNIQUE"))
                self.assertEqual(self.jules_calls(world), [])

    def test_old_sessions_are_forbidden_even_if_the_carrier_record_names_them(self):
        for old in ("301196275118188780", "5943440322658150300"):
            with self.subTest(old):
                world = self.world()
                world.carrier_logs[1] = carrier_log(world.bound["request"]["command_id"], old)
                with tempfile.TemporaryDirectory() as tmp:
                    code, result = self.run_main(world, tmp, SESSION_ID="")
                self.assertEqual((code, result["code"]), (1, "CARRIER_SESSION_FORBIDDEN"))
                self.assertEqual(self.jules_calls(world), [])

    def test_a_completed_provider_state_never_publishes(self):
        world = self.world(session_state="COMPLETED")
        with tempfile.TemporaryDirectory() as tmp:
            code, result = self.run_main(world, tmp)
        self.assertEqual((code, result["status"], result["code"]), (1, "UNKNOWN", "PROVIDER_NOT_ACTIVE"))
        self.assertEqual(result["stage"], "provider_get")
        self.assertEqual(result["failure_detail"], "PROVIDER_NOT_ACTIVE: provider_get:COMPLETED")
        self.assertEqual(len([c for c in world.calls if c[1].startswith(cli.JULES_API)]), 1)
        self.assertNotIn((world.bound["data_branch"], live.EVIDENCE_PATH), world.files)

    def test_a_provider_http_error_is_unknown_and_not_retried(self):
        world = self.world(session_status=503)
        with tempfile.TemporaryDirectory() as tmp:
            code, result = self.run_main(world, tmp)
        self.assertEqual((code, result["code"]), (1, "PROVIDER_READ_UNKNOWN"))
        self.assertEqual(len([c for c in world.calls if c[1].startswith(cli.JULES_API)]), 1)


if __name__ == "__main__":
    unittest.main()
