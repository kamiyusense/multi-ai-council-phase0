from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderStaticProfile:
    provider_id: str
    external_agent: str
    pinned_version: str
    _static_preflight_config: dict[str, Any]
    retry_count: int = 0
    fallback_state: str = "disabled"
    live_ready: bool = False
    live_readiness: str = "BLOCKED"
    _session_meta: dict[str, Any] | None = None
    binary_name: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("provider_id", self.provider_id),
            ("external_agent", self.external_agent),
            ("pinned_version", self.pinned_version),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")

        if not isinstance(self._static_preflight_config, dict):
            raise TypeError("_static_preflight_config must be a dictionary")
        if self.retry_count != 0:
            raise ValueError("retry_count must be 0")
        if self.fallback_state != "disabled":
            raise ValueError("fallback_state must be disabled")
        if self.live_ready is not False:
            raise ValueError("live_ready must be false")
        if self.live_readiness != "BLOCKED":
            raise ValueError("live_readiness must be BLOCKED")
        if self._session_meta is not None and not isinstance(self._session_meta, dict):
            raise TypeError("_session_meta must be a dictionary or None")
        if self.binary_name is not None and (
            not isinstance(self.binary_name, str) or not self.binary_name
        ):
            raise ValueError("binary_name must be a non-empty string or None")

        object.__setattr__(
            self,
            "_static_preflight_config",
            deepcopy(self._static_preflight_config),
        )
        if self._session_meta is not None:
            object.__setattr__(self, "_session_meta", deepcopy(self._session_meta))

    @property
    def static_preflight_config(self) -> dict[str, Any]:
        return deepcopy(self._static_preflight_config)

    @property
    def session_meta(self) -> dict[str, Any] | None:
        if self._session_meta is None:
            return None
        return deepcopy(self._session_meta)

    def get_static_preflight_config(self) -> dict[str, Any]:
        return deepcopy(self._static_preflight_config)
