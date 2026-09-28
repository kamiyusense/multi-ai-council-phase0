from typing import Any

from src.relay.core_adapter import RelayCoreAdapter
from .bundle import ProviderAdapterBundle, _PROVIDER_ORDER


def build_core_pr3_adapter_map(bundle: ProviderAdapterBundle) -> dict[str, RelayCoreAdapter]:
    if not isinstance(bundle, ProviderAdapterBundle):
        raise TypeError("bundle must be a ProviderAdapterBundle")

    source_adapters = bundle.adapters

    if set(source_adapters) != set(_PROVIDER_ORDER):
        raise ValueError("Bundle adapters must exactly match the canonical three-provider set")

    for provider_id in _PROVIDER_ORDER:
        adapter = source_adapters.get(provider_id)
        if not isinstance(adapter, RelayCoreAdapter):
            raise TypeError(f"Adapter for {provider_id} is missing or not a RelayCoreAdapter")
        if adapter.provider_id != provider_id:
            raise ValueError(f"Adapter provider_id {adapter.provider_id} does not match map key {provider_id}")

        for method in ("prepare", "preflight", "dispatch", "collect", "abort", "classify"):
            if not callable(getattr(adapter, method, None)):
                raise TypeError(f"Adapter missing required callable {method}()")

    return {
        "openai": source_adapters["openai"],
        "anthropic": source_adapters["anthropic"],
        "google": source_adapters["google"],
    }
