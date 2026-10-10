"""Durable LIVE budget fixtures: the real 9/10 slot ledger (copied from the data branch
``claude/claude-jules-autoloop-data`` at ``7e778853f8d7eebb3fc355d3d3d1fa5cd3b67a9c``) in an in-memory create-only
store with fault injection.  No git, no network."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from automation.command_bus import claude_jules_durable_budget as db

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "durable_budget"
PREFIX = "automation/command_bus/evidence/claude-auto-live-budget/"
DATA_BRANCH = "claude/claude-jules-autoloop-data"


def declaration(**over):
    decl = {"profile": db.DECLARATION_PROFILE, "budget_id": "jules-live-loop-a", "repository":
            "kamiyusense/multi-ai-council-phase0", "data_branch": DATA_BRANCH, "ledger_prefix": PREFIX, "cap": 10,
            "approved_by": "test-human", "approval_ref": "test approval"}
    decl.update(over)
    return decl


def declaration_v2(**over):
    """A production-style budget: its own id and ledger namespace (never the 9/10 proof ledger)."""
    decl = {"profile": db.DECLARATION_PROFILE_V2, "budget_id": "jules-prod-test", "campaign_id": "prod-test",
            "repository": "kamiyusense/multi-ai-council-phase0", "data_branch": DATA_BRANCH,
            "ledger_prefix": PROD_PREFIX, "cap": 50, "slot_create": True, "approved_by": "test-human",
            "approval_ref": "test approval"}
    decl.update(over)
    return decl


PROD_PREFIX = "automation/command_bus/evidence/claude-jules-production-budget/jules-prod-test/"


@dataclass
class Content:
    path: str
    text: str
    sha: str = ""


class LedgerStore:
    """Create-only files on one branch.  ``create`` fails if the path exists (the loser of a race).

    Faults: ``lose_response`` (written, then the caller sees an exception), ``fail_before`` (nothing written),
    ``fail_reads`` (every read raises), ``hide_after_write`` (the write lands but is not visible to the next get).
    """

    def __init__(self, *, real_slots: int = 9):
        self.files: dict[str, str] = {}
        for i in range(1, real_slots + 1):
            self.files[f"{PREFIX}slot-{i:02d}.json"] = (FIXTURES / f"slot-{i:02d}.json").read_text(encoding="utf-8")
        self.creates: list[str] = []
        self.lose_response = self.fail_before = self.fail_reads = self.hide_after_write = False
        self.before_create = None           # callable run inside create, before the existence check (races)
        self.hidden: set[str] = set()

    def list(self, prefix, branch):
        assert branch == DATA_BRANCH
        if self.fail_reads:
            raise RuntimeError("ledger read 502")
        return [Content(p, t) for p, t in sorted(self.files.items()) if p.startswith(prefix) and p not in self.hidden]

    def get(self, path, branch):
        if self.fail_reads:
            raise RuntimeError("ledger read 502")
        if path in self.hidden or path not in self.files:
            return None
        return Content(path, self.files[path])

    def create(self, path, text, message, branch):
        assert branch == DATA_BRANCH
        self.creates.append(path)
        if self.before_create:
            hook, self.before_create = self.before_create, None
            hook()
        if self.fail_before:
            raise RuntimeError("connection reset before the push")
        if path in self.files:
            raise RuntimeError("create-only conflict: path already exists")
        self.files[path] = text
        if self.hide_after_write:
            self.hidden.add(path)
        if self.lose_response:
            raise TimeoutError("push response lost")
        return Content(path, text)


def budget(store=None, *, create_enabled=True, **decl):
    return db.DurableBudget(store or LedgerStore(), declaration(**decl),
                            repository="kamiyusense/multi-ai-council-phase0", create_enabled=create_enabled)
