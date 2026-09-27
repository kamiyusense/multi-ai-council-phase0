import unittest
import os
from relay.acp_client import ACPClient

class TestACPClient(unittest.TestCase):
    def setUp(self):
        self.client = ACPClient()
        self.valid_fixture = "fixtures/relay/acp_initialize_account.json"
        self.invalid_fixture = "fixtures/relay/acp_initialize_unsupported.json"
        # Ensure fixtures exist
        os.makedirs("fixtures/relay", exist_ok=True)
        with open(self.valid_fixture, 'w') as f:
            f.write('{"protocol": "mock-v1", "auth": {"kind": "account", "account_id": "mock_account_123"}}')
        with open(self.invalid_fixture, 'w') as f:
            f.write('{"protocol": "mock-v2", "auth": {"kind": "api_key", "key": "sk-12345"}}')

    def test_prompt_before_open_fails(self):
        self.client.initialize(self.valid_fixture)
        with self.assertRaisesRegex(RuntimeError, "Cannot prompt from current state"):
            self.client.prompt("session_1", b"payload")

    def test_one_prompt_only(self):
        self.client.initialize(self.valid_fixture)
        self.client.open()
        self.client.prompt("session_1", b"payload")
        with self.assertRaisesRegex(RuntimeError, "One prompt only"):
            self.client.prompt("session_1", b"payload2")

    def test_cancel_idempotency_fail_on_second_cancel(self):
        self.client.initialize(self.valid_fixture)
        self.client.open()
        self.client.cancel("session_1")
        with self.assertRaisesRegex(RuntimeError, "Idempotency-fail on second cancel"):
            self.client.cancel("session_1")

    def test_prompt_after_cancel_rejected(self):
        self.client.initialize(self.valid_fixture)
        self.client.open()
        self.client.cancel("session_1")
        with self.assertRaisesRegex(RuntimeError, "Cannot prompt from current state"):
            self.client.prompt("session_1", b"payload")

    def test_close_after_cancel_allowed(self):
        self.client.initialize(self.valid_fixture)
        self.client.open()
        self.client.cancel("session_1")
        self.client.close()
        self.assertEqual(self.client.state, "CLOSED")

    def test_prompt_after_close_rejected(self):
        self.client.initialize(self.valid_fixture)
        self.client.open()
        self.client.close()
        with self.assertRaisesRegex(RuntimeError, "Cannot prompt from current state"):
            self.client.prompt("session_1", b"payload")

    def test_callbacks_never_auto_approve(self):
        self.client.initialize(self.valid_fixture)
        self.client.open()
        def mock_callback():
            return True
        with self.assertRaisesRegex(RuntimeError, "Callbacks never auto-approve"):
            self.client.prompt("session_1", b"payload", callbacks=[mock_callback])

    def test_initialize_rejects_unsupported(self):
        with self.assertRaisesRegex(ValueError, "Unsupported protocol or auth"):
            self.client.initialize(self.invalid_fixture)

    def test_initialize_accepts_account_fixture(self):
        self.client.initialize(self.valid_fixture)
        self.assertEqual(self.client.state, "INITIALIZED")

    def test_terminal_bytes_preserved_exactly(self):
        self.client.initialize(self.valid_fixture)
        self.client.open()
        payload = {"data": [1, 2, 3]}
        result = self.client.prompt("session_1", payload)
        self.assertEqual(result["terminal_bytes"], payload)
        self.assertIsNot(result["terminal_bytes"], payload) # check deepcopy

if __name__ == '__main__':
    unittest.main()
