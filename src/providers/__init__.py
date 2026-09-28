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
from .base import ProviderStaticProfile
from .codex_acp import build_codex_profile
from .claude_acp import build_claude_profile
from .antigravity_acp import build_antigravity_profile

__all__.extend([
    "ProviderStaticProfile",
    "build_codex_profile",
    "build_claude_profile",
    "build_antigravity_profile"
])
