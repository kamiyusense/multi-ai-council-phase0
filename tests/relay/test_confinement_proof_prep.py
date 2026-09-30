import os
import unittest


class TestConfinementProofPrep(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = os.path.join(os.path.dirname(__file__), "..", "..")
        cls.root = os.path.abspath(root)
        doc_path = os.path.join(cls.root, "docs", "RELAY_CONFINEMENT_PROOF_PREP.md")
        checkpoint_path = os.path.join(cls.root, "docs", "RELAY_STATIC_CHECKPOINT.md")
        if not os.path.isfile(doc_path):
            raise AssertionError("confinement proof prep document is missing")
        if not os.path.isfile(checkpoint_path):
            raise AssertionError("static checkpoint document is missing")
        with open(doc_path, "r", encoding="utf-8") as stream:
            cls.doc = stream.read()
        with open(checkpoint_path, "r", encoding="utf-8") as stream:
            cls.checkpoint = stream.read()
        cls.rows = cls._parse_table(cls.doc)

    @staticmethod
    def _parse_table(content: str) -> dict[str, dict[str, str]]:
        headers = [
            "provider_id",
            "workspace_boundary_state",
            "filesystem_confinement_state",
            "network_confinement_state",
            "child_process_state",
            "teardown_state",
            "restart_replay_state",
            "evidence_stage",
            "blocker_state",
        ]
        in_table = False
        parsed: dict[str, dict[str, str]] = {}
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("| provider_id |"):
                in_table = True
                continue
            if in_table and line.startswith("| ---"):
                continue
            if in_table and not line:
                break
            if in_table and line.startswith("|"):
                parts = [p.strip() for p in line.strip("|").split("|")]
                if len(parts) >= len(headers):
                    pid = parts[0]
                    parsed[pid] = dict(zip(headers, parts))
        return parsed

    def test_parse_exact_provider_order_openai_anthropic_google(self) -> None:
        keys = list(self.rows.keys())
        self.assertEqual(len(keys), 3, "should have exactly 3 providers")
        self.assertEqual(keys[0], "openai")
        self.assertEqual(keys[1], "anthropic")
        self.assertEqual(keys[2], "google")

    def test_assert_current_rows_remain_conservative_and_common_blocker_is_blocked_unknown(self) -> None:
        for provider, row in self.rows.items():
            self.assertEqual(row["workspace_boundary_state"], "STATIC_PREPARED")
            for field in [
                "filesystem_confinement_state",
                "network_confinement_state",
                "child_process_state",
                "teardown_state",
                "restart_replay_state"
            ]:
                self.assertEqual(row[field], "EVIDENCE_REQUIRED", f"{provider} {field} should be EVIDENCE_REQUIRED")
            self.assertEqual(row["evidence_stage"], "UNKNOWN")
            self.assertEqual(row["blocker_state"], "BLOCKED_UNKNOWN")

    def test_assert_static_workspace_container_declarations_explicitly_insufficient(self) -> None:
        self.assertIn("A disposable workspace design alone does not prove runtime confinement.", self.doc)
        self.assertIn("A path allowlist alone does not prove runtime confinement.", self.doc)
        self.assertIn("A container declaration alone does not prove runtime confinement.", self.doc)
        self.assertIn("A mock test alone does not prove runtime confinement.", self.doc)

    def test_assert_filesystem_network_child_process_teardown_UNKNOWN_fails_closed(self) -> None:
        self.assertIn("filesystem reachability", self.doc)
        self.assertIn("network reachability", self.doc)
        self.assertIn("child-process inheritance", self.doc)
        self.assertIn("teardown completion", self.doc)
        self.assertIn("restart/replay behavior", self.doc)
        self.assertIn("Fail closed / remain BLOCKED_UNKNOWN when any of these are unknown or ambiguous", self.doc)

    def test_assert_evidence_must_be_provider_and_proof_event_bound(self) -> None:
        self.assertIn("Evidence must be provider- and proof-event-bound; one provider cannot satisfy another.", self.doc)

    def test_assert_forbidden_path_network_proof_uses_no_real_secret_values(self) -> None:
        self.assertIn("No raw secrets/tokens/credential values belong in future evidence.", self.doc)
        self.assertIn("If proving a property would require accessing a real secret or sending a provider/model request, that proof method is forbidden", self.doc)
        self.assertIn("use synthetic markers or safe negative probes only", self.doc)

    def test_assert_all_conceptual_evidence_field_names_are_present(self) -> None:
        fields = [
            "provider_id",
            "proof_correlation_id",
            "observed_workspace_root",
            "filesystem_boundary_observation",
            "network_boundary_observation",
            "child_process_observation",
            "teardown_observation",
            "restart_observation",
            "forbidden_path_probe_result",
            "forbidden_network_probe_result",
            "evidence_source",
            "evidence_locator_or_hash",
            "captured_at",
            "verification_state"
        ]
        for field in fields:
            self.assertIn(f"`{field}`", self.doc)

    def test_assert_zero_live_evidence_acquired_and_common_confinement_remains_blocked_unknown(self) -> None:
        self.assertIn("Zero live confinement evidence is acquired by this batch.", self.doc)
        self.assertIn("`common_confinement` remains unresolved/BLOCKED_UNKNOWN.", self.doc)

    def test_assert_checkpoint_preserves_same_boundary(self) -> None:
        self.assertIn("This checkpoint is strictly PREPARED/static confinement-proof-prep status only.", self.checkpoint)
        self.assertIn("Zero live evidence was acquired", self.checkpoint)
        self.assertIn("common_confinement remains unresolved/BLOCKED_UNKNOWN.", self.checkpoint)
        self.assertIn("No real live blocker is resolved.", self.checkpoint)
