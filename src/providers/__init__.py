"""Provider policy descriptors for the static Relay branch."""

from .policy import (
    ANTIGRAVITY_POLICY,
    CLAUDE_POLICY,
    CODEX_POLICY,
    ProviderPolicy,
)
from .preflight import validate_provider_static

__all__ = [
    "ANTIGRAVITY_POLICY",
    "CLAUDE_POLICY",
    "CODEX_POLICY",
    "ProviderPolicy",
    "validate_provider_static",
]
