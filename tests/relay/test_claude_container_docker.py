"""Path B (STATIC): docker argument builder for the gated Claude container. Nothing is started or executed."""

import contextlib
import io
import json
import unittest
from pathlib import Path

from relay import claude_container_docker as mod
from relay.claude_container_docker import build_docker_create_argv, build_docker_start_argv, container_name

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "fixtures" / "relay" / "claude_runtime_env_proven_751a694.json").read_text(encoding="utf-8"))
OBSERVED = [
    "--output-format", "stream-json", "--verbose", "--input-format", "stream-json",
    "--permission-prompt-tool", "stdio", "--disallowedTools", "AskUserQuestion", "--tools", "default",
    "--setting-sources=user,project,local", "--permission-mode", "default", "--include-partial-messages",
    "--session-id=3d01e114-c91d-423f-b792-13e2c2242c3f", "--replay-user-messages", "",
]
DISPATCH = "3D01E114-C91D-423F-B792-13E2C2242C3F"
ENTRYPOINT = "/home/yuuki/phase0-runs/path-b/claude_adapter_entrypoint.mjs"
SECCOMP = "/home/yuuki/work/multi-ai-council-phase0/automation/command_bus/docker/claude-runtime/claude-bwrap-seccomp-amd64.json"


def build(argv=None, **overrides):
    kwargs = dict(entrypoint_host_path=ENTRYPOINT, seccomp_host_path=SECCOMP)
    kwargs.update(overrides)
    return build_docker_create_argv(DISPATCH, OBSERVED if argv is None else argv, **kwargs)


class TestDockerArgv(unittest.TestCase):
    def test_runtime_env_is_the_proven_compose_env(self):
        self.assertEqual(mod.RUNTIME_ENV, FIXTURE["env"])
        self.assertEqual(mod.RUNTIME_IMAGE, FIXTURE["image"])
        self.assertEqual(mod.AUTH_VOLUME, "command_bus_" + FIXTURE["volume"].split(":")[0])
        for forbidden in ("HTTPS_PROXY", "HTTP_PROXY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            self.assertNotIn(forbidden, mod.RUNTIME_ENV)

    def test_exact_create_argv(self):
        argv = build()
        expected_head = [
            "docker", "create", "--interactive", "--name", "phase0-claude-acp-3d01e114-c91d-423f-b792-13e2c2242c3f",
            "--pull", "never", "--restart", "no", "--user", "1000:1000", "--network", "command_bus_internal",
            "--security-opt", f"seccomp={SECCOMP}",
            "--volume", "command_bus_claude-auth:/home/node/.claude",
            "--mount", f"type=bind,source={ENTRYPOINT},target=/opt/phase0/claude_adapter_entrypoint.mjs,readonly",
        ]
        self.assertEqual(argv[:len(expected_head)], expected_head)
        env_pairs = [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]
        self.assertEqual(env_pairs[:-2], [f"{k}={v}" for k, v in FIXTURE["env"].items()])
        self.assertEqual(env_pairs[-2:], ["PHASE0_LIVE_EXECUTION=1", "PHASE0_DISPATCH_ID=3d01e114-c91d-423f-b792-13e2c2242c3f"])
        self.assertEqual(argv[-len(OBSERVED) - 4:],
                         ["--entrypoint", "node", FIXTURE["image"], "/opt/phase0/claude_adapter_entrypoint.mjs", *OBSERVED])

    def test_never_adds_dangerous_options(self):
        argv = build()
        for bad in ("--privileged", "--rm", "--publish", "-p", "--env-file", "--cap-add", "--device", "--pid", "--ipc"):
            self.assertNotIn(bad, argv)
        self.assertEqual(argv[argv.index("--network") + 1], "command_bus_internal")  # never the egress network or host
        self.assertNotIn("command_bus_egress", " ".join(argv))
        self.assertNotIn("--dangerously-skip-permissions", argv)

    def test_auth_probe_is_allowed_and_forwarded_unchanged(self):
        argv = build(["auth", "status", "--json"])
        self.assertEqual(argv[-3:], ["auth", "status", "--json"])

    def test_refuses_unexpected_adapter_argv(self):
        for bad in (
            [*OBSERVED[:-1], "--dangerously-skip-permissions", ""],
            ["-p", "hello"],
            [],
            OBSERVED[:-1],  # trailing empty argument missing
            [*OBSERVED[:9], "all", *OBSERVED[10:]],  # --disallowedTools value changed
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build(bad)

    def test_refuses_bad_dispatch_id_and_paths(self):
        with self.assertRaises(ValueError):
            build_docker_create_argv("not-a-uuid", OBSERVED, entrypoint_host_path=ENTRYPOINT, seccomp_host_path=SECCOMP)
        for bad in ("relative/claude_adapter_entrypoint.mjs", "/tmp/a:b/claude_adapter_entrypoint.mjs",
                    "/tmp/a,b/claude_adapter_entrypoint.mjs", "/tmp/x y/claude_adapter_entrypoint.mjs",
                    "/tmp/../etc/claude_adapter_entrypoint.mjs", "/tmp/other.mjs"):
            with self.subTest(entrypoint=bad), self.assertRaises(ValueError):
                build(entrypoint_host_path=bad)
        for bad in ("seccomp.json", "/tmp/unconfined.json", "/tmp/a,b/" + mod.SECCOMP_IN_COMPOSE):
            with self.subTest(seccomp=bad), self.assertRaises(ValueError):
                build(seccomp_host_path=bad)

    def test_start_argv_attaches_the_named_container(self):
        self.assertEqual(build_docker_start_argv(DISPATCH),
                         ["docker", "start", "--attach", "--interactive", container_name(DISPATCH)])

    def test_module_cannot_run_anything(self):
        source = (ROOT / "src" / "relay" / "claude_container_docker.py").read_text(encoding="utf-8")
        for token in ("import subprocess", "os.system", "os.exec", "Popen", "socket", "urllib", "requests"):
            self.assertNotIn(token, source)

    def test_dry_run_cli_prints_only(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod._main(["--dry-run", "--dispatch-id", DISPATCH, "--entrypoint-host-path", ENTRYPOINT,
                              "--seccomp-host-path", SECCOMP, "--adapter-argv-json", json.dumps(OBSERVED)])
        self.assertEqual(code, 0, err.getvalue())
        printed = json.loads(out.getvalue())
        self.assertEqual(printed["executed"], False)
        self.assertEqual(printed["create"], build())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = mod._main(["--dry-run", "--dispatch-id", DISPATCH, "--entrypoint-host-path", ENTRYPOINT,
                              "--seccomp-host-path", SECCOMP, "--adapter-argv-json", '["-p","x"]'])
        self.assertEqual(code, 78)


if __name__ == "__main__":
    unittest.main()
