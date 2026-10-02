#!/usr/bin/env python3
"""STATIC fake for `codex app-server` (newline-delimited JSON-RPC), no provider.

Injected through the documented codex-acp `CODEX_PATH` option so the real
bundled Codex is never started. It answers `initialize` plus a small canned set
needed for session/new/close (read-only account/config/model, thread/start); every other
request gets JSON-RPC -32601 and is logged (method names only) to the file in
FAKE_CODEX_LOG, so a test can prove which app-server methods were reached.
It performs no network access and reads no credentials.
"""
import json
import os
import sys

LOG = os.environ.get("FAKE_CODEX_LOG")
_THREADS = [0]


def log(method: str) -> None:
    if LOG:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(method + "\n")


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _canned(method: str, params: dict):
    cwd = (params or {}).get("cwd") or "/"
    if method == "account/read":
        return {"account": {"type": "chatgpt", "email": None, "planType": "plus"}, "requiresOpenaiAuth": False}
    if method == "config/read":
        return {"config": {}, "origins": {}, "layers": None}
    if method == "skills/list":
        return {"data": []}
    if method == "model/list":
        return {"data": [{
            "id": "fake-model", "model": "fake-model", "upgrade": None, "upgradeInfo": None,
            "availabilityNux": None, "displayName": "fake", "description": "static fake",
            "modelSpecialty": None, "hidden": False,
            "supportedReasoningEfforts": [{"reasoningEffort": "none", "description": "none"}],
            "defaultReasoningEffort": "none", "inputModalities": ["text"], "supportsPersonality": False,
            "multiAgentVersion": None, "additionalSpeedTiers": [], "serviceTiers": [],
            "defaultServiceTier": None, "availableAccessPrograms": None, "isDefault": True}],
            "nextCursor": None}
    if method == "thread/start":
        _THREADS[0] += 1
        tid = f"fake-thread-{_THREADS[0]}"
        thread = {"id": tid, "sessionId": tid, "forkedFromId": None, "parentThreadId": None,
                  "preview": "", "ephemeral": False, "section": None, "sectionEnteredAt": None, "projectId": None,
                  "historyMode": "legacy", "modelProvider": "fake", "model": "fake-model", "reasoningEffort": "none",
                  "createdAt": 0, "updatedAt": 0, "recencyAt": None, "status": {"type": "idle"}, "path": None,
                  "cwd": cwd, "cliVersion": "0", "originator": None, "source": "appServer", "threadSource": None,
                  "agentNickname": None, "agentRole": None, "gitInfo": None, "name": None, "turns": []}
        return {"thread": thread, "model": "fake-model", "modelProvider": "fake", "serviceTier": None,
                "disabledPluginIds": [], "cwd": cwd, "instructionSources": [], "approvalPolicy": "never",
                "approvalsReviewer": "user", "sandbox": {"type": "readOnly"}, "reasoningEffort": "none"}
    if method in ("thread/unsubscribe", "thread/archive", "thread/name/set", "skills/extraRoots/set", "turn/interrupt"):
        return {}
    return None


def _turn(status: str) -> dict:
    return {"id": "fake-turn-1", "items": [], "itemsView": "full", "status": status, "error": None,
            "startedAt": 0, "completedAt": None, "durationMs": None}


def _turn_events(thread_id: str, text: str) -> None:
    """Emit a fake (no-provider) turn: one agent-message delta then completion."""
    send({"jsonrpc": "2.0", "method": "item/agentMessage/delta",
          "params": {"threadId": thread_id, "turnId": "fake-turn-1", "itemId": "fake-item-1", "delta": text}})
    send({"jsonrpc": "2.0", "method": "turn/completed",
          "params": {"threadId": thread_id, "turn": _turn("completed")}})


def main() -> None:
    # '\n' only, also on Windows (no CRLF translation of the JSON-RPC stream)
    sys.stdout.reconfigure(newline="\n")
    if sys.argv[1:] != ["app-server"]:
        sys.exit(2)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        if method is None:
            continue
        log(method)
        if "id" not in msg:
            continue
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {
                "userAgent": "fake-codex-app-server/0",
                "codexHome": os.environ.get("CODEX_HOME", "/nonexistent-codex-home"),
                "platformFamily": "unix",
                "platformOs": "linux",
            }})
        elif method == "turn/interrupt" and os.environ.get("FAKE_CODEX_HOLD_TURN"):
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
            send({"jsonrpc": "2.0", "method": "turn/completed", "params": {
                "threadId": msg["params"]["threadId"], "turn": _turn("interrupted")}})
        elif method == "turn/start":
            send({"jsonrpc": "2.0", "id": msg["id"], "result": {"turn": _turn("inProgress")}})
            if not (os.environ.get("FAKE_CODEX_NO_COMPLETE") or os.environ.get("FAKE_CODEX_HOLD_TURN")):  # simulate a hung turn
                _turn_events(msg["params"]["threadId"], os.environ.get("FAKE_CODEX_REPLY", "fake codex reply"))
        elif _canned(method, msg.get("params")) is not None:
            send({"jsonrpc": "2.0", "id": msg["id"], "result": _canned(method, msg.get("params"))})
        else:
            send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "static fake: method not supported"}})


if __name__ == "__main__":
    main()
