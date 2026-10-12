"""Offline G5.1 OTP/AST validation of an already patched exact upstream pin.

Does not start the application, tracker loop, AppServer or providers. Requires
existing local dev dependencies. No package installation, patch mutation or Git
publication is performed. The fixture signing key is public, STATIC-only data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

PIN = "be10a1b79df723d6d7612b5651c8522704dafb2e"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    command_bus = Path(__file__).resolve().parents[1]
    patch = command_bus / "symphony_g5_observer.patch"
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=upstream, text=True).strip() == PIN
    subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=upstream, check=True)
    with tempfile.TemporaryDirectory(prefix="g51-pin-") as temporary:
        baseline = Path(temporary)
        for name in ("orchestrator.ex", "agent_runner.ex"):
            content = subprocess.check_output(["git", "show", f"{PIN}:elixir/lib/symphony_elixir/{name}"], cwd=upstream)
            (baseline / name).write_bytes(content)
            target = baseline / "elixir/lib/symphony_elixir" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=baseline, check=True)
        env = dict(os.environ)
        for name in ("GITHUB_TOKEN", "GH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
                     "AZURE_OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE",
                     "SYMPHONY_G5_OBSERVER_KEY_HEX", "SYMPHONY_G5_OBSERVER_EVENTS"):
            env.pop(name, None)
        env.update(MIX_ENV="dev", G51_BASELINE_DIR=str(baseline),
                   G51_SIGNED_FIXTURE_OUTPUT=str(output / "otp-signed-events.jsonl"))
        test = command_bus / "tests/fixtures/symphony_g51/worker_lifecycle_test.exs"
        # Paths are passed as data (JSON/Elixir string literals), not through a shell.
        expression = ('ExUnit.start(autorun: false, trace: true); Code.require_file("test/support/test_support.exs"); '
                      f'Code.require_file({json.dumps(str(test))}); result = ExUnit.run(); '
                      'if result.failures > 0, do: System.halt(1)')
        checks = [
            ("elixir-format", ["mix", "format", "--check-formatted", "lib/symphony_elixir/agent_runner.ex",
                              "lib/symphony_elixir/orchestrator.ex", "lib/symphony_elixir/g5_observer.ex"]),
            ("elixir-compile", ["mix", "compile", "--warnings-as-errors"]),
            ("elixir-specs", ["mix", "specs.check"]),
            ("elixir-fixtures", ["mix", "run", "--no-start", "-e", expression]),
        ]
        results = []
        for name, command in checks:
            completed = subprocess.run(command, cwd=upstream / "elixir", env=env, capture_output=True)
            content = completed.stdout + completed.stderr
            (output / (name + ".txt")).write_bytes(content)
            results.append(dict(check=name, exit_code=completed.returncode,
                                sha256=hashlib.sha256(content).hexdigest()))
            print(f"{name}: {'PASS' if completed.returncode == 0 else 'FAIL'}")
            if completed.returncode:
                break
        passed = len(results) == len(checks) and all(result["exit_code"] == 0 for result in results)
        report = dict(protocol="SYMPHONY_G51_OFFLINE_VALIDATION_V1", upstream_pin=PIN,
                      outcome="PASS" if passed else "FAIL", checks=results,
                      clean_pin_patch_check="PASS", applied_patch_reverse_check="PASS",
                      patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
                      application_started=False, live_launch_count=0, model_dispatch_count=0,
                      upstream_behavior_changes=False if passed else "UNKNOWN")
        if passed:
            report["signed_fixture_sha256"] = hashlib.sha256((output / "otp-signed-events.jsonl").read_bytes()).hexdigest()
        (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
