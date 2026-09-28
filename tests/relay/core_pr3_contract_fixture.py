from typing import Any, Protocol, runtime_checkable

# TEST-ONLY runtime-checkable Protocol snapshot matching Core PR #3 contract
# Do not use as production source of truth.

CORE_PR3_HEAD = "494b7296f32dce1c173a7699e4bd2d87f70d31a9"

@runtime_checkable
class CorePR3ProviderAdapterProtocol(Protocol):
    provider_id: str

    def prepare(self, case_context: dict[str, Any]) -> dict[str, Any]:
        ...

    def preflight(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        ...

    def dispatch(self, prepared_context: dict[str, Any]) -> object:
        ...

    def collect(self, process_handle: object) -> bytes:
        ...

    def abort(self, process_handle: object) -> dict[str, Any]:
        ...

    def classify(self, raw_result: bytes) -> dict[str, Any]:
        ...
