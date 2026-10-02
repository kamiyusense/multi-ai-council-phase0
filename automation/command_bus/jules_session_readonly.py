"""One existing completed Jules Session GET; no dispatch/adoption authority."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, build_opener
from .github_readonly import _NoRedirect, _pairs
from .jules_session_acceptance import _parse_provider_time, extract_session_acceptance

_ERROR = "Jules Session readback unavailable"
_SOURCE = "sources/github/kamiyusense/multi-ai-council-phase0"
_LIMIT = 1024 * 1024
_CHECKS = frozenset({
    'session_name_matches', 'starting_branch_matches', 'create_time_valid',
    'create_time_exact', 'create_time_same_second', 'completed',
    'repository_matches', 'unique_pr_output_matches', 'update_time_valid'})
_PROVIDER_TIME = re.compile(
    r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
    r'(?:\.([0-9]{1,9}))?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])')


def _exact_time(value: Any) -> tuple[datetime, int]:
    """Reuse aware provider parsing; preserve the nanoseconds datetime drops.

    Equality/order compare aware instants plus the last three fractional digits.
    Legacy seconds-only timing is diagnostic evidence, never exact equality.
    """
    match = _PROVIDER_TIME.fullmatch(value) if isinstance(value, str) else None
    if match is None or value.endswith('-00:00'):
        raise ValueError(_ERROR)
    nanos = int((match.group(1) or '').ljust(9, '0'))
    return _parse_provider_time(value).astimezone(timezone.utc), nanos % 1000


def safe_diagnostic_checks(value: Any) -> dict[str, bool]:
    """Only locally defined Boolean comparisons may cross the log boundary."""
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items()
            if isinstance(key, str) and key in _CHECKS and type(item) is bool}


def _http_stage(code: Any) -> str:
    return 'http_' + str(code) if type(code) is int and code in {
        301, 302, 307, 308, 401, 403, 404, 429, 500, 502, 503} else 'transport'


class SessionReadbackUnavailable(ValueError):
    """Fixed public error plus a safe stage label; no remote values/cause."""
    def __init__(self, stage: str, checks: Any = None):
        super().__init__(_ERROR)
        self.stage = stage if isinstance(stage, str) and stage in {
            'existing_key', 'expected_identity', 'expected_time', 'transport',
            'response_size', 'json', 'session_identity_time', 'session_name',
            'starting_branch', 'create_time', 'completion_state', 'repository',
            'outputs', 'update_time', 'http_301', 'http_302', 'http_307',
            'http_308', 'http_401', 'http_403', 'http_404', 'http_429',
            'http_500', 'http_502', 'http_503'} else 'unspecified'
        self.checks = safe_diagnostic_checks(checks)


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
        checks = {}
        try:
            if (not isinstance(session_id, str)
                    or re.fullmatch(r"[0-9]+", session_id) is None
                    or not _safe_branch(expected_branch)
                    or type(expected_pr) is not int or expected_pr <= 0):
                raise ValueError(_ERROR)
            stage = 'expected_time'
            expected_time = _exact_time(expected_create_time)
            stage = 'transport'
            request = Request(
                "https://jules.googleapis.com/v1alpha/sessions/" + session_id,
                method="GET", headers={"X-Goog-Api-Key": self._key})
            with self._opener.open(request, timeout=30) as response:
                if response.status != 200:
                    stage = _http_stage(response.status)
                    raise ValueError(_ERROR)
                raw = response.read(_LIMIT + 1)
            stage = 'response_size'
            if not isinstance(raw, bytes) or len(raw) > _LIMIT:
                raise ValueError(_ERROR)
            stage = 'json'
            data = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant)
            if not isinstance(data, dict):
                raise ValueError(_ERROR)
            context = data.get("sourceContext")
            github_context = context.get('githubRepoContext') if isinstance(context, dict) else None
            outputs = data.get("outputs")
            url = "https://github.com/kamiyusense/multi-ai-council-phase0/pull/" + str(expected_pr)
            try:
                actual_time = _exact_time(data.get('createTime'))
            except (ValueError, OverflowError):
                actual_time = None
            try:
                update_valid = ('updateTime' not in data or (
                    actual_time is not None and _exact_time(data['updateTime']) >= actual_time))
            except (ValueError, OverflowError):
                update_valid = False
            # Diagnose all comparisons from this ONE response. Same-second is
            # information about legacy timing precision, NEVER an acceptance gate.
            checks = {
                'session_name_matches': data.get('name') == 'sessions/' + session_id,
                'starting_branch_matches': isinstance(github_context, dict) and github_context.get('startingBranch') == expected_branch,
                'create_time_valid': actual_time is not None,
                'create_time_exact': actual_time == expected_time,
                'create_time_same_second': actual_time is not None and actual_time[0].replace(microsecond=0) == expected_time[0].replace(microsecond=0),
                'completed': data.get('state') == 'COMPLETED',
                'repository_matches': isinstance(context, dict) and context.get('source') == _SOURCE,
                'unique_pr_output_matches': isinstance(outputs, list) and len(outputs) == 1 and isinstance(outputs[0], dict) and isinstance(outputs[0].get('pullRequest'), dict) and outputs[0]['pullRequest'].get('url') == url,
                'update_time_valid': update_valid,
            }
            for stage, check in (
                ('session_name', 'session_name_matches'),
                ('starting_branch', 'starting_branch_matches'),
                ('create_time', 'create_time_exact'),
                ('completion_state', 'completed'), ('repository', 'repository_matches'),
                ('outputs', 'unique_pr_output_matches'), ('update_time', 'update_time_valid')):
                if not checks[check]:
                    raise ValueError(_ERROR)
            stage = 'session_identity_time'
            accepted = extract_session_acceptance(data, expected_branch=expected_branch)
            result = {
                "name": accepted.session_name, "createTime": data["createTime"],
                "state": "COMPLETED",
                "sourceContext": {"source": _SOURCE,
                                  "githubRepoContext": {"startingBranch": expected_branch}},
                "outputs": [{"pullRequest": {"url": url}}],
            }
            stage = 'update_time'
            if "updateTime" in data:
                result["updateTime"] = data["updateTime"]
            return result
        except HTTPError as exc:
            raise SessionReadbackUnavailable(_http_stage(exc.code), checks) from None
        except Exception:
            raise SessionReadbackUnavailable(stage, checks) from None
