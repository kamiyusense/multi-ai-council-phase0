import unittest
from automation.command_bus.validation_scope import ScopeKind,classify_command_bus_path,partition_command_bus_blobs,require_bounded_static_scope
def blob(path): return {"path":path,"type":"blob","sha":"a"*40,"mode":"100644"}
class ValidationScopeTests(unittest.TestCase):
    def test_static_code_tests_schema_and_readme_are_included(self):
        for path in ("automation/command_bus/reviewer.py","automation/command_bus/reviewer_wake_backend.py","automation/command_bus/tests/test_reviewer_transport.py","automation/command_bus/schema/command.schema.json","automation/command_bus/README.md"):
            with self.subTest(path=path): self.assertEqual(classify_command_bus_path(path),ScopeKind.STATIC)
    def test_append_only_runtime_ledgers_are_excluded_from_static_blob_fetch(self):
        for path in ("automation/command_bus/commands/loop/000001.json","automation/command_bus/events/loop/wake-001.json","automation/command_bus/evidence/run.json","automation/command_bus/receipts/loop/000001.json","automation/command_bus/state/loop.json","automation/command_bus/review_requests/loop/req.json","automation/command_bus/review_claims/loop/claim.json","automation/command_bus/review_responses/loop/resp.json","automation/command_bus/review_receipts/loop/receipt.json","automation/command_bus/review_wake_attempts/loop/req.json","automation/command_bus/execution_requests/loop/req.json","automation/command_bus/execution_claims/loop/claim.json","automation/command_bus/execution_results/loop/result.json","automation/command_bus/execution_receipts/loop/receipt.json","automation/command_bus/jules_launch_attempts/loop/command.json","automation/command_bus/auth_handoffs/handoff/requested.json","automation/command_bus/loop_owner_events/loop/000001.json","automation/command_bus/loop_owner_observations/loop/000001.json"):
            with self.subTest(path=path): self.assertEqual(classify_command_bus_path(path),ScopeKind.LEDGER)
    def test_unknown_new_nested_area_fails_closed(self):
        path="automation/command_bus/new_unclassified_area/file.json"; self.assertEqual(classify_command_bus_path(path),ScopeKind.UNKNOWN)
        with self.assertRaisesRegex(ValueError,"unknown command-bus blob scope"): require_bounded_static_scope([blob(path)])
    def test_partition_reports_bounded_static_and_unbounded_ledger_separately(self):
        entries=[blob("automation/command_bus/reviewer.py"),blob("automation/command_bus/tests/test_reviewer.py"),blob("automation/command_bus/schema/state.schema.json")]; entries.extend(blob(f"automation/command_bus/receipts/run-{i}/000001.json") for i in range(1000)); scope=require_bounded_static_scope(entries); self.assertEqual(scope.static_blob_count,3); self.assertEqual(scope.ledger_blob_count,1000); self.assertEqual(scope.unknown_blobs,())
    def test_non_blob_tree_entries_are_not_materialized_as_static_files(self):
        scope=require_bounded_static_scope([{"path":"automation/command_bus/tests","type":"tree","sha":"b"*40},blob("automation/command_bus/reviewer.py")]); self.assertEqual(scope.static_blob_count,1)
    def test_direct_unknown_artifact_fails_closed(self): self.assertEqual(classify_command_bus_path("automation/command_bus/runtime.db"),ScopeKind.UNKNOWN)
    def test_outside_command_bus_is_unknown(self): self.assertEqual(classify_command_bus_path("docs/HYBRID_WORK_CHAT_REVIEWER_RELAY_PROPOSAL.md"),ScopeKind.UNKNOWN)
if __name__=="__main__": unittest.main()
