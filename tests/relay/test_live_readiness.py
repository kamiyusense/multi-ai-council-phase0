import ast
from pathlib import Path
from typing import Any
import copy

import pytest

from providers.live_readiness import evaluate_live_readiness, COMMON_PROOFS, PROVIDER_PROOFS


def test_evaluate_live_readiness_valid_openai():
    preflight = {
        "provider_id": "openai",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["openai"])}

    result = evaluate_live_readiness("openai", preflight, proofs)
    assert result["state"] == "READY_FOR_HUMAN_APPROVAL"
    assert result["live_ready"] is False
    assert result["dispatch_allowed"] is False
    assert result["human_approval_required"] is True
    assert result["retry_count"] == 0
    assert result["fallback_state"] == "disabled"


def test_evaluate_live_readiness_valid_anthropic():
    preflight = {
        "provider_id": "anthropic",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["anthropic"])}

    result = evaluate_live_readiness("anthropic", preflight, proofs)
    assert result["state"] == "READY_FOR_HUMAN_APPROVAL"


def test_evaluate_live_readiness_valid_google():
    preflight = {
        "provider_id": "google",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["google"])}

    result = evaluate_live_readiness("google", preflight, proofs)
    assert result["state"] == "READY_FOR_HUMAN_APPROVAL"


def test_evaluate_live_readiness_missing_common_proof():
    preflight = {
        "provider_id": "openai",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["openai"])}
    del proofs["finite_timeout"]

    result = evaluate_live_readiness("openai", preflight, proofs)
    assert result["state"] == "BLOCKED_UNKNOWN"


def test_evaluate_live_readiness_missing_provider_proof():
    preflight = {
        "provider_id": "anthropic",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["anthropic"])}
    del proofs["sdk_retry_zero"]

    result = evaluate_live_readiness("anthropic", preflight, proofs)
    assert result["state"] == "BLOCKED_UNKNOWN"


def test_evaluate_live_readiness_malformed_proof():
    preflight = {
        "provider_id": "google",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["google"])}
    proofs["intended_account_route"] = "CONFIRMED" # type: ignore

    result = evaluate_live_readiness("google", preflight, proofs)
    assert result["state"] == "BLOCKED_UNKNOWN"


def test_evaluate_live_readiness_unknown_status():
    preflight = {
        "provider_id": "openai",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["openai"])}
    proofs["finite_timeout"]["status"] = "UNKNOWN"

    result = evaluate_live_readiness("openai", preflight, proofs)
    assert result["state"] == "BLOCKED_UNKNOWN"


def test_evaluate_live_readiness_empty_evidence():
    preflight = {
        "provider_id": "openai",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["openai"])}
    proofs["finite_timeout"]["evidence_ref"] = "   "

    result = evaluate_live_readiness("openai", preflight, proofs)
    assert result["state"] == "BLOCKED_UNKNOWN"


def test_evaluate_live_readiness_mismatched_provider_id():
    preflight = {
        "provider_id": "anthropic",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["openai"])}

    result = evaluate_live_readiness("openai", preflight, proofs)
    assert result["state"] == "BLOCKED_UNKNOWN"


def test_evaluate_live_readiness_static_preflight_unknown():
    preflight = {
        "provider_id": "openai",
        "static_configuration_status": "UNKNOWN",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["openai"])}

    result = evaluate_live_readiness("openai", preflight, proofs)
    assert result["state"] == "BLOCKED_UNKNOWN"


def test_evaluate_live_readiness_static_pass_with_incomplete_proofs():
    preflight = {
        "provider_id": "openai",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["openai"])}
    # Add an extra unexpected proof
    proofs["some_extra_proof"] = {"status": "CONFIRMED", "evidence_ref": "http"}

    result = evaluate_live_readiness("openai", preflight, proofs)
    assert result["state"] == "BLOCKED_UNKNOWN"


def test_evaluate_live_readiness_immutability():
    preflight = {
        "provider_id": "openai",
        "static_configuration_status": "PASS",
        "live_ready": False,
        "retry_count": 0,
        "fallback_state": "disabled",
    }
    proofs = {key: {"status": "CONFIRMED", "evidence_ref": "http://evidence"} for key in (COMMON_PROOFS | PROVIDER_PROOFS["openai"])}

    result1 = evaluate_live_readiness("openai", preflight, proofs)

    # Mutate inputs to ensure they don't affect already returned result (which is a new dict)
    preflight["static_configuration_status"] = "UNKNOWN"

    # Actually, evaluate_live_readiness creates a new dict. We verify the returned dict is distinct.
    result2 = evaluate_live_readiness("openai", preflight, proofs)

    assert result1["state"] == "READY_FOR_HUMAN_APPROVAL"
    assert result2["state"] == "BLOCKED_UNKNOWN"

    # Ensure returned dict has expected fixed values
    assert result1["live_ready"] is False
    assert result1["dispatch_allowed"] is False


def test_no_ambient_io_imports():
    src_path = Path("src/providers/live_readiness.py")
    if not src_path.exists():
        pytest.skip(f"source path not found: {src_path}")

    tree = ast.parse(src_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                assert name.name not in ["os", "subprocess", "socket", "http", "requests", "sys"], f"Prohibited import: {name.name}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module not in ["os", "subprocess", "socket", "http", "requests", "sys"], f"Prohibited import: {node.module}"
