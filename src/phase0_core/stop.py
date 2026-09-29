from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StopController:
    stop_requested: bool = False
    no_new_dispatch: bool = False
    reason: str | None = None

    def request_stop(self, reason: str) -> None:
        self.stop_requested = True
        self.no_new_dispatch = True
        self.reason = reason

    def require_dispatch_allowed(self) -> None:
        if self.no_new_dispatch:
            raise RuntimeError(f"new dispatch blocked: {self.reason or 'stop requested'}")
