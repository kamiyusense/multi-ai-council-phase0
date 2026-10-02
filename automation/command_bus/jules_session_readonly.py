"""One existing completed Jules Session GET; no dispatch/adoption authority."""
from __future__ import annotations
import json
import re
from typing import Any
from urllib.request import Request, build_opener
from .github_readonly import _NoRedirect, _pairs
from .jules_session_acceptance import _parse_provider_time, extract_session_acceptance

_ERROR = "Jules Session readback unavailable"
_SOURCE = "sources/github/kamiyusense/multi-ai-council-phase0"
_LIMIT = 1024 * 1024


class SessionReadbackUnavailable(ValueError):
    """Fixed public error plus a safe stage label; no remote values/cause."""
    def __init__(self, stage: str):
        super().__init__(_ERROR)
        self.stage = stage if isinstance(stage, str) and stage in {
            'existing_key', 'expected_identity', 'expected_time', 'transport',
            'response_size', 'json', 'session_identity_time', 'repository',
            'outputs', 'update_time'} else 'unspecified'


def _reject_constant(value: str) -> None:
    raise ValueError(_ERROR)


def _safe_branch(value: Any) -> bool:
    return (isinstance(value, str)
            and re.fullmatch(r"jules-work/[A-Za-z0-9][A-Za-z0-9._/-]*", value) is not None
            and not any(x in value for x in ("..", "//", "@{"))
            and all(not p.startswith(".") and not p.endswith((".", ".lock"))
                    for p in value.split("/"))
            and not value.endswith("/"))


class JulesSessionGetReader:
    def __init__(self, existing_key: str):
        if (not isinstance(existing_key, str) or not existing_key
                or any(ord(c) < 33 or ord(c) > 126 for c in existing_key)):
            raise SessionReadbackUnavailable('existing_key')
        self._key = existing_key
        self._opener = build_opener(_NoRedirect())

    def read_completed_session(self, session_id: str, *, expected_branch: str,
                               expected_create_time: str, expected_pr: int) -> dict[str, Any]:
        """Exactly one bounded GET; invalid expectations cause zero I/O.

        Fixed error text and suppressed exception chains protect ordinary
        tracebacks. KeyboardInterrupt/SystemExit propagate. No retry/fallback.
        """
        stage = 'expected_identity'
        try:
            if (not isinstance(session_id, str)
                    or re.fullmatch(r"[0-9]+", session_id) is None
                    or not _safe_branch(expected_branch)
                    or type(expected_pr) is not int or expected_pr <= 0):
                raise ValueError(_ERROR)
            stage = 'expected_time'
            expected_time = _parse_provider_time(expected_create_time)
            stage = 'transport'
            request = Request(
                "https://jules.googleapis.com/v1alpha/sessions/" + session_id,
                method="GET", headers={"X-Goog-Api-Key": self._key})
            with self._opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError(_ERROR)
                raw = response.read(_LIMIT + 1)
            stage = 'response_size'
            if not isinstance(raw, bytes) or len(raw) > _LIMIT:
                raise ValueError(_ERROR)
            stage = 'json'
            data = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)
            if not isinstance(data, dict):
                raise ValueError(_ERROR)
            stage = 'session_identity_time'
            accepted = extract_session_acceptance(data, expected_branch=expected_branch)
            if (accepted.session_name != "sessions/" + session_id
                    or _parse_provider_time(data.get("createTime")) != expected_time
                    or data.get("state") != "COMPLETED"):
                raise ValueError(_ERROR)
            stage = 'repository'
            context = data.get("sourceContext")
            if not isinstance(context, dict) or context.get("source") != _SOURCE:
                raise ValueError(_ERROR)
            stage = 'outputs'
            outputs = data.get("outputs")
            url = "https://github.com/kamiyusense/multi-ai-council-phase0/pull/" + str(expected_pr)
            if (not isinstance(outputs, list) or len(outputs) != 1
                    or not isinstance(outputs[0], dict)
                    or not isinstance(outputs[0].get("pullRequest"), dict)
                    or outputs[0]["pullRequest"].get("url") != url):
                raise ValueError(_ERROR)
            result = {
                "name": accepted.session_name, "createTime": data["createTime"],
                "state": "COMPLETED",
                "sourceContext": {"source": _SOURCE,
                                  "githubRepoContext": {"startingBranch": expected_branch}},
                "outputs": [{"pullRequest": {"url": url}}],
            }
            stage = 'update_time'
            if "updateTime" in data:
                update = _parse_provider_time(data["updateTime"])
                if update < expected_time:
                    raise ValueError(_ERROR)
                result["updateTime"] = data["updateTime"]
            return result
        except Exception:
            raise SessionReadbackUnavailable(stage) from None
