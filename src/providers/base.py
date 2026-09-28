from dataclasses import dataclass
from typing import Any
import copy

@dataclass(frozen=True, slots=True)
class ProviderStaticProfile:
    provider_id: str
    external_agent: str
    pinned_version: str
    _static_preflight_config: dict[str, Any]
    retry_count: int = 0
    fallback_state: str = 'disabled'
    live_ready: bool = False
    live_readiness: str = 'BLOCKED'
    _session_meta: dict[str, Any] | None = None
    binary_name: str | None = None

    def __post_init__(self):
        object.__setattr__(self, '_static_preflight_config', copy.deepcopy(self._static_preflight_config))
        if self._session_meta is not None:
            object.__setattr__(self, '_session_meta', copy.deepcopy(self._session_meta))

    @property
    def static_preflight_config(self) -> dict[str, Any]:
        return copy.deepcopy(self._static_preflight_config)

    @property
    def session_meta(self) -> dict[str, Any] | None:
        if self._session_meta is None:
            return None
        return copy.deepcopy(self._session_meta)

    def get_static_preflight_config(self) -> dict[str, Any]:
        return copy.deepcopy(self._static_preflight_config)
