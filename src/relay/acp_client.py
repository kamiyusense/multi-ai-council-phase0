import json
import copy

class ACPClient:
    def __init__(self):
        self.state = "UNINITIALIZED"
        self.config = None
        self.has_prompted = False

    def initialize(self, config_path):
        if self.state != "UNINITIALIZED":
            raise RuntimeError("Already initialized")

        with open(config_path, 'r') as f:
            config = json.load(f)

        if config.get("protocol") != "mock-v1" or config.get("auth", {}).get("kind") != "account":
            raise ValueError("Unsupported protocol or auth")

        self.config = config
        self.state = "INITIALIZED"

    def open(self):
        if self.state != "INITIALIZED":
            raise RuntimeError("Cannot open from current state")
        self.state = "OPEN"

    def prompt(self, session, payload, callbacks=None):
        if self.state != "OPEN":
            raise RuntimeError("Cannot prompt from current state")
        if self.has_prompted:
            raise RuntimeError("One prompt only")

        if callbacks:
            for cb in callbacks:
                if cb() is True:
                    raise RuntimeError("Callbacks never auto-approve")

        self.has_prompted = True
        return {"terminal_bytes": copy.deepcopy(payload)}

    def cancel(self, session):
        if self.state == "CANCELLED":
            raise RuntimeError("Idempotency-fail on second cancel")
        self.state = "CANCELLED"

    def close(self):
        if self.state == "UNINITIALIZED":
            raise RuntimeError("Cannot close from uninitialized")
        if self.state == "CANCELLED":
            # allowed only as cleanup
            pass
        self.state = "CLOSED"
