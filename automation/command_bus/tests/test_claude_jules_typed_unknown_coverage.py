"""Runtime coverage guard: every non-success boundary the controller can emit gets a typed classification.

The controller source is parsed (no execution) for each ``StepResult(<action>, <status>, <reason>)`` whose status is a
boundary.  Each literal reason must classify, and anything that names an unproven write, an identity contradiction or a
"do not resend" boundary must never be retry-safe.  A new reason that slips past the classifier fails here first.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

from automation.command_bus.claude_jules_campaign import (
    HARD_UNKNOWN, RECOVERABLE_UNKNOWN, TASK_BLOCKED, TRANSIENT_UNKNOWN, classify_boundary,
)

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "claude_jules_autoloop.py"
BOUNDARY = {"UNKNOWN", "BLOCKED", "TASK_BLOCKED", "NO_RESULT_TIMEOUT"}
NEVER_RETRY = ("not proven", "do not resend", "mismatch", "contradiction", "collision", "unresolved", "altered")


def emitted_boundaries() -> list[tuple[int, str, str]]:
    rows = []
    for node in ast.walk(ast.parse(SOURCE.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "StepResult" and len(node.args) >= 3):
            continue
        status, reason = node.args[1], node.args[2]
        if not (isinstance(status, ast.Constant) and status.value in BOUNDARY):
            continue
        if isinstance(reason, ast.Constant):
            text = reason.value
        elif isinstance(reason, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "<detail>" for v in reason.values)
        else:
            continue  # computed reason: covered by the behavioural tests of its producer
        rows.append((node.lineno, status.value, text))
    return rows


class TypedUnknownCoverageTests(unittest.TestCase):
    def test_source_still_emits_a_meaningful_set_of_boundaries(self):
        self.assertGreaterEqual(len(emitted_boundaries()), 30)

    def test_every_emitted_boundary_is_classified(self):
        for line, status, text in emitted_boundaries():
            with self.subTest(line=line, reason=text):
                kind = classify_boundary(status, text)
                self.assertIsNotNone(kind)
                self.assertIn(kind.kind, {HARD_UNKNOWN, TRANSIENT_UNKNOWN, RECOVERABLE_UNKNOWN, TASK_BLOCKED})

    def test_unproven_writes_and_contradictions_are_never_retry_safe(self):
        checked = 0
        for line, status, text in emitted_boundaries():
            if any(marker in text.lower() for marker in NEVER_RETRY):
                checked += 1
                with self.subTest(line=line, reason=text):
                    self.assertFalse(classify_boundary(status, text).retry_safe)
        self.assertGreaterEqual(checked, 10)

    def test_retry_safe_boundaries_are_only_reads(self):
        for line, status, text in emitted_boundaries():
            kind = classify_boundary(status, text)
            if kind.retry_safe:
                with self.subTest(line=line, reason=text):
                    self.assertTrue(any(word in text.lower() for word in ("unavailable", "unverifiable", "read", "failed")),
                                    "a retry-safe boundary must describe a read/evidence gap")
                    self.assertNotIn("create", text.lower())
                    self.assertNotIn("write", text.lower())

    def test_detail_cannot_turn_a_hard_boundary_into_a_retryable_one(self):
        # An exception text is untrusted: appending read-like words must not soften a write ambiguity.
        hard = classify_boundary("UNKNOWN", "controller operation unresolved: temporary read failed; do not resend")
        self.assertFalse(hard.retry_safe)
        self.assertEqual(hard.kind, HARD_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
