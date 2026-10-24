"""Grok CLI launch description for the Council (docs/RELAY_TOWER_DIRECTION_V4.md section 4, step S8).

STATIC: this module only describes a launch.  It never starts a process.  The first real run is step S9 and needs
the owner's explicit approval, which the caller must hold before turning a ``GrokLaunch`` into a process.

* Official modes only, with subscription sign-in: ``grok --no-auto-update agent stdio`` (ACP) or
  ``grok --no-auto-update -p <prompt>`` (headless).
* The child environment is built from an allowlist.  ``XAI_API_KEY`` and every other API key or credential
  variable never reach the child, so the CLI can only use its cached subscription sign-in.
* No model, endpoint or billing override is passed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

__all__ = ["GrokLaunch", "child_env", "acp_launch", "headless_launch", "GrokLaunchError"]

_ALLOWED_ENV = ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "WINDIR", "COMSPEC",
                "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL", "TERM")
_SECRET_NAME = re.compile(r"(API_?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|^XAI_|BASE_URL)", re.IGNORECASE)
_MAX_PROMPT = 20_000


class GrokLaunchError(ValueError):
    """A launch description that must not be used (fail closed)."""


@dataclass(frozen=True)
class GrokLaunch:
    argv: tuple[str, ...]
    env: Mapping[str, str]
    mode: str                      # "acp" or "headless"
    live: bool = False             # always False here; S9 decides with the owner's approval


def child_env(parent: Mapping[str, str]) -> dict[str, str]:
    """Only allowlisted, non-secret variables are copied.  ``XAI_API_KEY`` can never pass."""
    env = {k: v for k, v in parent.items() if k in _ALLOWED_ENV and isinstance(v, str)}
    leaked = [k for k in env if _SECRET_NAME.search(k)]
    if leaked or "XAI_API_KEY" in env:
        raise GrokLaunchError("SECRET_IN_CHILD_ENV")
    return env


def acp_launch(parent_env: Mapping[str, str], binary: str = "grok") -> GrokLaunch:
    _check_binary(binary)
    return GrokLaunch((binary, "--no-auto-update", "agent", "stdio"), child_env(parent_env), "acp")


def headless_launch(prompt: str, parent_env: Mapping[str, str], binary: str = "grok") -> GrokLaunch:
    _check_binary(binary)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > _MAX_PROMPT or "\x00" in prompt:
        raise GrokLaunchError("PROMPT")
    return GrokLaunch((binary, "--no-auto-update", "-p", prompt), child_env(parent_env), "headless")


def _check_binary(binary: str) -> None:
    name = binary.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name not in {"grok", "grok.exe", "grok.cmd"}:
        raise GrokLaunchError("NOT_THE_GROK_CLI")
