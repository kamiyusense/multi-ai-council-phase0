import unittest

from providers.policy import antigravity_binary_name, antigravity_launch_args


class TestAntigravityStaticLaunchShape(unittest.TestCase):
    """M4: launch shape of Google's ``agy_acp_server`` from the registry manifest (data only, never launched)."""

    def test_linux_needs_empty_uid_arg_others_none(self):
        self.assertEqual(antigravity_launch_args("linux", "x86_64"), ("--uid=",))
        self.assertEqual(antigravity_launch_args("Linux", "aarch64"), ("--uid=",))
        self.assertEqual(antigravity_launch_args("windows", "x86_64"), ())
        self.assertEqual(antigravity_launch_args("darwin", "aarch64"), ())

    def test_unsupported_platform_fails_closed(self):
        for platform, arch in (("freebsd", "x86_64"), ("windows", "riscv64")):
            with self.subTest(platform=platform, arch=arch):
                with self.assertRaises(ValueError):
                    antigravity_launch_args(platform, arch)

    def test_binary_and_args_agree_with_manifest_cmd(self):
        self.assertEqual(antigravity_binary_name("linux", "x86_64"), "agy_acp_server.par")
        self.assertEqual(antigravity_binary_name("windows", "aarch64"), "agy_acp_server.exe")


if __name__ == "__main__":
    unittest.main()
