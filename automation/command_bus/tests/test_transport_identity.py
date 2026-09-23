import unittest

from automation.command_bus.transport_identity import (
    BrowserCapability, BrowserSessionId, RuntimeCapability,
    require_runtime_available, static_default_capabilities,
)


class TransportIdentityTests(unittest.TestCase):
    def test_all_session_identities_are_distinct(self):
        values=[item.value for item in BrowserSessionId]
        self.assertEqual(len(values), len(set(values)))
        self.assertIn("WORK_CLOUD_BROWSER_JULES_UI", values)
        self.assertIn("DESKTOP_BUILTIN_BROWSER_JULES_UI", values)
        self.assertIn("CHROME_EXISTING_SESSION_JULES_UI", values)

    def test_static_defaults_do_not_infer_availability(self):
        capabilities=static_default_capabilities()
        self.assertTrue(capabilities)
        self.assertTrue(all(item.state is RuntimeCapability.UNKNOWN for item in capabilities))

    def test_unknown_is_not_available(self):
        cap=BrowserCapability(BrowserSessionId.DESKTOP_BUILTIN_BROWSER_JULES_UI,RuntimeCapability.UNKNOWN)
        with self.assertRaisesRegex(ValueError,"UNKNOWN"):
            require_runtime_available(cap)

    def test_available_requires_durable_evidence(self):
        cap=BrowserCapability(BrowserSessionId.WORK_CLOUD_BROWSER_JULES_UI,RuntimeCapability.AVAILABLE)
        with self.assertRaisesRegex(ValueError,"evidence"):
            require_runtime_available(cap)
        require_runtime_available(BrowserCapability(
            BrowserSessionId.WORK_CLOUD_BROWSER_JULES_UI,
            RuntimeCapability.AVAILABLE,
            "automation/command_bus/evidence/example.json",
        ))


if __name__ == "__main__":
    unittest.main()
