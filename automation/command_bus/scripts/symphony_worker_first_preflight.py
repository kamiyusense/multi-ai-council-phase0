"""Read-only WSL preflight for a worker-first Official Symphony proof.

This diagnostic is not a model admission, GitHub publication capability or
activation. It does not mutate the repository, authenticate to GitHub, create a
thread or start a model. GitHub branch protection applies to the later operator
publication stage, not to this isolated, local, worker-only diagnostic.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

PROOF_BRANCH = re.compile(r"codex/symphony-worker-proof-[a-z0-9][a-z0-9-]{5,62}")
COMMIT = re.compile(r"[0-9a-f]{40}")


def _safe_dir(value: str | Path, *, private: bool = False) -> Path:
    p = Path(value)
    if not p.is_absolute() or not p.is_dir():
        raise ValueError("nonexistent or nonabsolute directory")
    if any(part.is_symlink() for part in (p, *p.parents)) or p.resolve() != p:
        raise ValueError("linked or noncanonical directory")
    if private:
        info = p.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("scratch parent must be owned and mode 0700")
    return p


def _separate(a: Path, b: Path) -> bool:
    return a != b and a not in b.parents and b not in a.parents


def _git(workspace: Path, *args: str) -> str:
    # Inherited GIT_DIR / GIT_WORK_TREE can otherwise redirect a read elsewhere.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(["git", "-C", str(workspace), *args], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=10, text=True, check=True)
    return result.stdout.strip()


def _native_linux_state(parent: Path) -> bool:
    # ext4 in WSL is ordinarily reported as ext2/ext3 by GNU stat.
    if os.name != "posix" or not Path("/proc/self/mountinfo").exists():
        return False
    result = subprocess.run(["stat", "-f", "-c", "%T", str(parent)],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, timeout=10, check=True)
    return result.stdout.strip() in {"ext2/ext3", "ext4"}


def _codex_readonly_probe(*, workspace: Path, sqlite_home: Path, executable: str):
    # Import only after all local-path and Git fences pass. Existing app-server
    # code handles the same-process account/config request without a model turn.
    from ..symphony_codex_app_server import JsonlCodexAppServer
    return JsonlCodexAppServer(executable=executable, timeout_seconds=60).probe_read_only(
        cwd=str(workspace), sqlite_home=sqlite_home)


def preflight(*, workspace: str | Path, expected_head: str,
              scratch_parent: str | Path, executable: str = "codex") -> dict[str, object]:
    """Diagnose local readiness only. All failures fail closed without LIVE.

    An empty private SQLite directory is made only in the approved scratch area
    and removed at exit. The existing CODEX_HOME and its Windows/WSL SQLite
    databases are never altered by this preflight.
    """
    status: dict[str, object] = {
        "mode": "WORKER_ONLY_READONLY_DIAGNOSTIC",
        "status": "BLOCKED", "reason": "LOCAL_READBACK_UNAVAILABLE",
        "model_turns": 0, "thread_starts": 0, "github_writes": 0,
        "worker_only_readonly_requires_branch_protection": False,
        "publication_rules_status": "NOT_EVALUATED", "production_installed": False,
        "live_authorized": False,
    }
    try:
        if type(expected_head) is not str or not COMMIT.fullmatch(expected_head):
            raise ValueError("expected exact commit required")
        if type(executable) is not str or Path(executable).name != "codex":
            raise ValueError("Codex executable required")
        workspace = _safe_dir(workspace)
        scratch = _safe_dir(scratch_parent, private=True)
        # Path overlap with worktree, auth home, or old shared DB is disallowed.
        auth = _safe_dir(os.environ.get("CODEX_HOME") or str(Path.home() / ".codex"))
        if not all((_separate(workspace, scratch), _separate(scratch, auth),
                    _separate(workspace, auth))):
            raise ValueError("workspace, scratch and auth home must be separate")
        if not _native_linux_state(scratch):
            raise ValueError("scratch is not verified native Linux ext storage")
        branch = _git(workspace, "symbolic-ref", "--quiet", "--short", "HEAD")
        if not PROOF_BRANCH.fullmatch(branch):
            raise ValueError("fresh nondefault worker-proof branch required")
        if _git(workspace, "rev-parse", "--verify", "HEAD") != expected_head:
            raise ValueError("worker-proof HEAD differs from operator pin")
        if _git(workspace, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ValueError("workspace is dirty; do not erase changes")
        # Fail closed if the parent environment selects a metered provider.
        from ..symphony_subscription_boundary import metered_worker_environment_present
        if metered_worker_environment_present(tuple(os.environ)):
            raise ValueError("metered environment selector present")
        status["local_branch_verified"] = True
        with tempfile.TemporaryDirectory(prefix="symphony-worker-proof-readonly-", dir=scratch) as temp:
            path = Path(temp)
            path.chmod(0o700)
            result = _codex_readonly_probe(workspace=workspace, sqlite_home=path,
                                           executable=executable)
        if (type(result) is not dict or result.get("status") != "DONE"
                or result.get("model_dispatch") != 0 or result.get("thread_starts") != 0
                or type(result.get("route")) is not dict
                or result["route"].get("subscription_route_compatible") is not True
                or result["route"].get("provenance") != "SAME_PROCESS_FRESH_READ_ONLY_NOT_ADMISSION"):
            raise ValueError("same-process subscription readback unavailable")
        status.update({"status": "PASS_READONLY_NOT_ADMISSION", "reason": "VERIFIED_LOCAL_PRECHECK",
                       "subscription_route_compatible": True})
    except (ValueError, PermissionError, OSError, subprocess.SubprocessError) as exc:
        # Never emit stderr, raw account data, local paths or token values.
        status["reason"] = (
            "LOCAL_CONSTRAINT_UNMET" if isinstance(exc, ValueError) else
            "LOCAL_PERMISSION_UNAVAILABLE" if isinstance(exc, PermissionError) else
            "LOCAL_READBACK_UNAVAILABLE"
        )
    except Exception:
        status["reason"] = "UNVERIFIED_READONLY_PROBE"
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--scratch-parent", required=True, type=Path)
    parser.add_argument("--codex", default="codex")
    args = parser.parse_args()
    result = preflight(workspace=args.workspace, expected_head=args.expected_head,
                       scratch_parent=args.scratch_parent, executable=args.codex)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS_READONLY_NOT_ADMISSION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
