import hashlib
import unittest

from automation.command_bus.connector_reconstruction import (
    git_blob_sha,
    materialization_relpath,
    require_unique_static_entries,
    validate_static_entry,
    verify_connector_blob,
)


def sha(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def entry(path, content=b"x", mode="100644"):
    return {
        "path": path,
        "type": "blob",
        "sha": sha(content),
        "mode": mode,
        "size": len(content),
    }


class ConnectorReconstructionTests(unittest.TestCase):
    def test_git_blob_sha_matches_git_object_format(self):
        content = b"hello\n"
        self.assertEqual(git_blob_sha(content), sha(content))

    def test_connector_blob_requires_tree_sha_size_and_recomputed_sha(self):
        content = b"payload"
        e = entry("automation/command_bus/example.py", content)
        verified = verify_connector_blob(e, fetched_sha=e["sha"], content=content)
        self.assertEqual(verified.path, e["path"])
        with self.assertRaisesRegex(ValueError, "connector blob sha"):
            verify_connector_blob(e, fetched_sha="0" * 40, content=content)
        with self.assertRaisesRegex(ValueError, "size"):
            verify_connector_blob(e, fetched_sha=e["sha"], content=content + b"x")
        bad = dict(e)
        bad["sha"] = "1" * 40
        with self.assertRaisesRegex(ValueError, "recomputed git blob"):
            verify_connector_blob(bad, fetched_sha=bad["sha"], content=content)

    def test_zero_byte_blob_is_supported(self):
        content = b""
        e = entry("automation/command_bus/tests/__init__.py", content)
        verified = verify_connector_blob(e, fetched_sha=e["sha"], content=content)
        self.assertEqual(verified.size, 0)

    def test_path_traversal_and_outside_root_fail_closed(self):
        for path in (
            "../escape.py",
            "automation/command_bus/../escape.py",
            "automation/command_bus/tests/../../escape.py",
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    validate_static_entry(entry(path))

    def test_symlink_or_unknown_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "mode"):
            validate_static_entry(entry(
                "automation/command_bus/link",
                mode="120000",
            ))

    def test_materialization_path_is_relative_to_command_bus_root(self):
        self.assertEqual(
            materialization_relpath("automation/command_bus/tests/test_x.py"),
            "tests/test_x.py",
        )

    def test_duplicate_static_paths_fail_closed(self):
        e = entry("automation/command_bus/example.py")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            require_unique_static_entries([e, dict(e)])

    def test_unique_entries_are_sorted(self):
        a = entry("automation/command_bus/b.py", b"b")
        b = entry("automation/command_bus/a.py", b"a")
        result = require_unique_static_entries([a, b])
        self.assertEqual(
            [item.path for item in result],
            [
                "automation/command_bus/a.py",
                "automation/command_bus/b.py",
            ],
        )


if __name__ == "__main__":
    unittest.main()
