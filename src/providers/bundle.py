from src.providers.base import ProviderStaticProfile
from src.providers.factory import create_core_adapter
from src.relay.bridge import RelayProviderAdapterBridge
from src.relay.core_adapter import RelayCoreAdapter

class ProviderAdapterBundle:
    def __init__(self, profiles: list[ProviderStaticProfile], bridges: dict[str, RelayProviderAdapterBridge]):
        if not isinstance(profiles, list):
            raise TypeError("profiles must be a list")
        if not isinstance(bridges, dict):
            raise TypeError("bridges must be a dict")

        if len(profiles) != 3:
            raise ValueError("Exactly three profiles required")
        if len(bridges) != 3:
            raise ValueError("Exactly three bridges required")

        expected_keys = {"openai", "anthropic", "google"}
        p_keys = set()

        for p in profiles:
            if not isinstance(p, ProviderStaticProfile):
                raise TypeError("profiles items must be ProviderStaticProfile")
            p_keys.add(p.provider_id)

        b_keys = set(bridges.keys())

        if p_keys != expected_keys:
            raise ValueError("Profiles must exactly match canonical provider set {'openai', 'anthropic', 'google'}")
        if b_keys != expected_keys:
            raise ValueError("Bridges must exactly match canonical provider set {'openai', 'anthropic', 'google'}")

        for k in expected_keys:
            if not isinstance(bridges[k], RelayProviderAdapterBridge):
                raise TypeError("bridges items must be RelayProviderAdapterBridge")

        self._adapters: dict[str, RelayCoreAdapter] = {}
        for p in profiles:
            self._adapters[p.provider_id] = create_core_adapter(p, bridges[p.provider_id])

    def get_adapters_in_order(self) -> list[RelayCoreAdapter]:
        return [
            self._adapters["openai"],
            self._adapters["anthropic"],
            self._adapters["google"]
        ]
