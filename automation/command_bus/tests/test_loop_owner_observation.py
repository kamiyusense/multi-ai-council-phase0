from __future__ import annotations

import copy
import unittest

from automation.command_bus.loop_owner_observation import (
    provider_observation_path,
    validate_provider_observation,
)


def observation():
    return {
        "schema_version": 1,
        "observation_id": "provider-observation-1",
        "loop_id": "loop-015",
        "owner_role": "SEMI_AUTO",
        "holder_id": "controller-1",
        "generation": 1,
        "fencing_token": 1,
        "expected_repo": "kamiyusense/multi-ai-council-phase0",
        "expected_pr": 4,
        "expected_target_head": "a" * 40,
        "state": "RUNNING",
        "evidence_ref": "evidence-owner-1",
        "observed_at": "2026-09-27T09:30:00+00:00",
        "expires_at": "2026-09-27T10:30:00+00:00",
        "verified": True,
    }


class ProviderObservationTests(unittest.TestCase):
    def test_valid_observation_and_path(self):
        item = observation()
        validate_provider_observation(item)
        self.assertEqual(
            provider_observation_path(item["loop_id"], item["generation"]),
            "automation/command_bus/loop_owner_observations/loop-015/000001.json",
        )

    def test_unknown_field_is_rejected(self):
        item = observation()
        item["unexpected"] = True
        with self.assertRaises(ValueError):
            validate_provider_observation(item)

    def test_bool_generation_and_fencing_mismatch_are_rejected(self):
        item = observation()
        item["generation"] = True
        with self.assertRaises(ValueError):
            validate_provider_observation(item)
        item = observation()
        item["fencing_token"] = 2
        with self.assertRaises(ValueError):
            validate_provider_observation(item)

    def test_unsafe_ids_and_invalid_sha_are_rejected(self):
        for field, value in (
            ("loop_id", "../bad"),
            ("observation_id", "../bad"),
            ("holder_id", "bad/holder"),
            ("expected_target_head", "z" * 40),
        ):
            item = observation()
            item[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_provider_observation(item)

    def test_expiry_must_follow_observed_at(self):
        item = observation()
        item["expires_at"] = item["observed_at"]
        with self.assertRaises(ValueError):
            validate_provider_observation(item)

    def test_verified_must_be_boolean_not_truthy_string(self):
        item = observation()
        item["verified"] = "true"
        with self.assertRaises(ValueError):
            validate_provider_observation(item)


if __name__ == "__main__":
    unittest.main()
