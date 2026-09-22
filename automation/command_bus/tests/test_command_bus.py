from datetime import datetime, timedelta, timezone
import unittest

from automation.command_bus.event_processor import EventProcessor
from automation.command_bus.ledger import InMemoryLedger
from automation.command_bus.state_machine import StateMachine
from automation.command_bus.validator import validate_command, validate_receipt, validate_state

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
REPO = "kamiyusense/multi-ai-council-phase0"
HEAD = "62f341b04f9d6e19dd003b42304bb896e4db45ef"

def state(expires=None, round=0, status="RUNNING"):
    return {"schema_version":1,"loop_id":"relay-dev-001","state":status,"round":round,"max_rounds":6,"expires_at":(expires or NOW+timedelta(hours=1)).isoformat(),"stop_requested":False,"last_command_id":None,"last_receipt_id":None,"expected_target":"work","retry_policy":0}

def command(n, action="ECHO_AND_RECEIPT", head=HEAD):
    return {"schema_version":1,"command_id":f"{n:06d}","loop_id":"relay-dev-001","round":n,"correlation_id":f"relay-dev-001-round-{n}","target":"work","action":action,"expected_repo":REPO,"expected_pr":4,"expected_head":head,"retry":0,"fallback":"disabled","requires_live_model":False,"requires_github_write":False}

class CommandBusTests(unittest.TestCase):
    def test_schema_validation(self):
        validate_state(state()); validate_command(command(1))
        with self.assertRaises(ValueError): validate_command({**command(1), "retry": 1})
        with self.assertRaises(ValueError): validate_receipt({"schema_version":1})

    def test_mock_six_round_halts_at_ceiling(self):
        ledger=InMemoryLedger(state())
        results=[]
        for n in range(1,7):
            ledger.add_command(command(n)); results.append(EventProcessor(ledger,repo=REPO,pr=4,observed_head=HEAD).process(f"{n:06d}",now=NOW))
            ledger.state["state"]="RUNNING"
        self.assertTrue(all(r.status == "PROCESSED" for r in results))
        ledger.add_command(command(7)); result=EventProcessor(ledger,repo=REPO,pr=4,observed_head=HEAD).process("000007",now=NOW)
        self.assertEqual(result.status,"BLOCKED"); self.assertIn("max_rounds",result.reason)

    def test_stop_hard_stop(self):
        ledger=InMemoryLedger(state()); stop=command(1,"STOP"); ledger.add_command(stop)
        result=EventProcessor(ledger,repo=REPO,pr=4,observed_head=HEAD).process("000001",now=NOW)
        self.assertEqual(result.receipt["state"],"CANCELLED"); self.assertEqual(ledger.state["state"],"HALTED")

    def test_expiry_hard_stop(self):
        ledger=InMemoryLedger(state(expires=NOW-timedelta(seconds=1))); ledger.add_command(command(1))
        self.assertEqual(EventProcessor(ledger,repo=REPO,pr=4,observed_head=HEAD).process("000001",now=NOW).reason,"expired")

    def test_duplicate_and_terminal_receipt_no_replay(self):
        ledger=InMemoryLedger(state()); ledger.add_command(command(1)); p=EventProcessor(ledger,repo=REPO,pr=4,observed_head=HEAD)
        self.assertEqual(p.process("000001",now=NOW).status,"PROCESSED"); self.assertEqual(p.process("000001",now=NOW).status,"NO-OP")
        with self.assertRaises(ValueError): ledger.add_command(command(1))

    def test_receipt_only_event_noop(self):
        ledger=InMemoryLedger(state()); self.assertEqual(EventProcessor(ledger,repo=REPO,pr=4,observed_head=HEAD).process(now=NOW).status,"NO-OP")

    def test_target_head_and_correlation_blocks(self):
        for altered in ({"expected_head":"bad"},{"expected_pr":5},{"correlation_id":"wrong"}):
            ledger=InMemoryLedger(state()); ledger.add_command({**command(1),**altered})
            result=EventProcessor(ledger,repo=REPO,pr=4,observed_head=HEAD).process("000001",now=NOW)
            self.assertEqual(result.status,"BLOCKED")

    def test_stale_executor_and_safety_defaults_block(self):
        ledger=InMemoryLedger(state()); ledger.add_command(command(1,head="af9c5517ed8678bdff3af60fd298dd586d5a6786"))
        result=EventProcessor(ledger,repo=REPO,pr=4,observed_head=HEAD).process("000001",now=NOW)
        self.assertEqual(result.status,"BLOCKED"); self.assertEqual(result.receipt["retry_count"],0); self.assertFalse(result.receipt["fallback_used"])

    def test_state_machine_stop_and_expiry(self):
        sm=StateMachine(state()); self.assertIsNone(sm.blocked_reason(NOW)); sm.request_stop(); self.assertIsNotNone(sm.blocked_reason(NOW))

if __name__ == "__main__": unittest.main()
