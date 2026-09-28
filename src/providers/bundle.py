from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from .base import ProviderStaticProfile
from .factory import create_core_adapter
from src.relay.core_adapter import RelayCoreAdapter


_PROVIDER_ORDER = ("openai", "anthropic", "google")
_REQUIRED_BRIDGE_METHODS = (
    "prepare",
    "preflight",
    "dispatch",
    "collect",
    "abort",
    "classify",
)


def _require_bridge_compatible(bridge: object) -> None:
    for name in _REQUIRED_BRIDGE_METHODS:
        if not callable(getattr(bridge, name, None)):
            raise TypeError(f"bridge must provide callable {name}()")


class ProviderAdapterBundle:
    """Immutable static/mock three-provider adapter bundle."""

    __slots__ = ("_adapters",)

    def __init__(
        self,
        profiles: Mapping[str, ProviderStaticProfile],
        bridges: Mapping[str, object],
    ) -> None:
        if not isinstance(profiles, Mapping):
            raise TypeError("profiles must be a mapping keyed by provider_id")
        if not isinstance(bridges, Mapping):
            raise TypeError("bridges must be a mapping keyed by provider_id")

        expected = set(_PROVIDER_ORDER)
        if set(profiles) != expected:
            raise ValueError(
                "Profiles must exactly match canonical provider set "
                "{'openai', 'anthropic', 'google'}"
            )
        if set(bridges) != expected:
            raise ValueError(
                "Bridges must exactly match canonical provider set "
                "{'openai', 'anthropic', 'google'}"
            )

        profile_snapshot = dict(profiles)
        bridge_snapshot = dict(bridges)

        adapters: dict[str, RelayCoreAdapter] = {}
        for provider_id in _PROVIDER_ORDER:
            profile = profile_snapshot[provider_id]
            if not isinstance(profile, ProviderStaticProfile):
                raise TypeError("profile values must be ProviderStaticProfile")
            if profile.provider_id != provider_id:
                raise ValueError(
                    f"profile key/provider_id mismatch: {provider_id}/"
                    f"{profile.provider_id}"
                )

            bridge = bridge_snapshot[provider_id]
            _require_bridge_compatible(bridge)
            adapters[provider_id] = create_core_adapter(profile, bridge)  # type: ignore[arg-type]

        self._adapters = MappingProxyType(adapters)

    @property
    def adapters(self) -> Mapping[str, RelayCoreAdapter]:
        return self._adapters

    def get_adapters_in_order(self) -> tuple[RelayCoreAdapter, ...]:
        return tuple(self._adapters[provider_id] for provider_id in _PROVIDER_ORDER)
