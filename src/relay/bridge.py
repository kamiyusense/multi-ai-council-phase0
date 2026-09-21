from src.phase0_core.adapter import CoreProviderAdapter

class RelayProviderAdapterBridge(CoreProviderAdapter):
    def __init__(self, simulate_timeout=False, simulate_failure=False, simulate_malformed=False, simulate_no_cli=False):
        self.simulate_timeout = simulate_timeout
        self.simulate_failure = simulate_failure
        self.simulate_malformed = simulate_malformed
        self.simulate_no_cli = simulate_no_cli

    def prepare(self, case_context):
        return {"case_id": case_context.get("case_id"), "payload": case_context.get("payload")}

    def preflight(self, prepared_context):
        if self.simulate_no_cli:
            raise Exception("CLI unavailable")
        return {"ok": True}

    def dispatch(self, prepared_context):
        if self.simulate_failure:
            raise Exception("Mock failure on dispatch")
        return {"process_id": "mock_id"}

    def collect(self, process_handle):
        if self.simulate_timeout:
            raise TimeoutError("Timeout")
        if self.simulate_malformed:
            return {"stdout": "malformed", "rawResponse": "{}"}
        return {"stdout": "mock", "rawResponse": '{"answer_state": "ANSWER"}'}

    def abort(self, process_handle):
        return {"aborted": True}

    def classify(self, raw_result):
        if "malformed" in raw_result.get("stdout", ""):
            return {"execution_state": "INVALID_OUTPUT"}
        return {"execution_state": "COMPLETE", "participation_state": "PARTICIPANT"}
