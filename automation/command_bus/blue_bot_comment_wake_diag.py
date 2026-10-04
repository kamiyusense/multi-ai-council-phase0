"""One inert bot-authored PR comment on Blue carrier #167, to observe a Work wake.

The comment starts with its own prefix, never a command or receipt prefix, so a
woken Work run must NO-OP. No Jules, provider, target write, retry or fallback.
A comment never proves a wake by itself; the Work task's last_run_time does.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, build_opener

from .blue_work_reconcile_prepare import RECEIPT_PREFIX
from .github_readonly import ROOT, GitHubGetReader, _NoRedirect, read_all

DIAG_PREFIX = '[BLUE_BOT_COMMENT_WAKE_DIAGNOSTIC_V1]'
DIAG_ID = re.compile(r'blue-wake-diag-\d{8}T\d{6}Z-\d{2}')
CARRIER_PR, CARRIER_LABEL = 167, 'cloud-blue'


def required(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def body_for(diag_id: str) -> str:
    required(DIAG_ID.fullmatch(diag_id) is not None, 'diag_id format')
    return (f'{DIAG_PREFIX}\n{{"diag_id": "{diag_id}", "purpose": "observe whether a bot-authored PR '
            'conversation comment wakes the Blue Work task", "command": false, "expected_work_result": "NO_OP", '
            '"retry": 0, "fallback": "disabled"}')


def check(reader, diag_id: str) -> dict:
    pr = reader.get(ROOT + f'/pulls/{CARRIER_PR}').data
    required(pr.get('number') == CARRIER_PR and pr.get('state') == 'open' and pr.get('merged') is False, 'carrier not open')
    required(CARRIER_LABEL in [x.get('name') for x in pr.get('labels', [])], 'carrier label missing')
    comments = read_all(reader, ROOT + f'/issues/{CARRIER_PR}/comments?per_page=100')
    for row in comments:
        text = row.get('body') or ''
        required(not text.startswith(DIAG_PREFIX), 'diagnostic budget consumed (1 per lifetime)')
        required(diag_id not in text, 'diag_id already used')
    return {'comments_before': len(comments), 'carrier_head': pr['head']['sha']}


class CommentPostOnce:
    """Fixed issue-comment endpoint. Budget is consumed before the network call."""
    def __init__(self, token: str):
        required(bool(token) and '\n' not in token and '\r' not in token, 'GITHUB_TOKEN unavailable')
        self._token, self._used = token, False
        self._opener = build_opener(_NoRedirect())

    def post(self, body: str) -> dict:
        required(not self._used, 'POST budget consumed')
        required(body.startswith(DIAG_PREFIX + '\n') and not body.startswith(RECEIPT_PREFIX), 'fixed comment body')
        self._used = True
        request = Request(ROOT + f'/issues/{CARRIER_PR}/comments', method='POST',
                          data=json.dumps({'body': body}).encode(),
                          headers={'Authorization': 'Bearer ' + self._token, 'Accept': 'application/vnd.github+json',
                                   'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'})
        with self._opener.open(request, timeout=30) as response:
            required(response.status == 201, 'POST outcome not confirmed')
            return json.loads(response.read(1024 * 1024))


def run(reader, poster, diag_id: str, output: Path) -> dict:
    result = {'diag_id': diag_id, 'status': 'ATTEMPTING', 'retry': 0, 'fallback': 'disabled',
              'jules_or_provider_calls': 0, 'target_mutation': 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        result.update(check(reader, diag_id))
        output.write_text(json.dumps(result, indent=2))  # durable BEFORE the single POST
        posted = poster.post(body_for(diag_id))
        result.update(status='POSTED_UNVERIFIED', comment_id=posted.get('id'),
                      author=(posted.get('user') or {}).get('login'), created_at=posted.get('created_at'))
    except Exception as exc:  # outcome of a failed POST is UNKNOWN; never resend
        result['status'] = 'STOPPED_UNKNOWN' if result['status'] == 'POSTED_UNVERIFIED' or getattr(poster, '_used', False) else 'STOPPED_BEFORE_POST'
        result['reason'] = type(exc).__name__ + ': ' + str(exc)[:200]
    output.write_text(json.dumps(result, indent=2))
    return result


def main() -> int:
    diag_id = os.environ.get('DIAG_ID', '')
    token = os.environ.get('GITHUB_TOKEN', '')
    result = run(GitHubGetReader(token), CommentPostOnce(token), diag_id, Path('blue-bot-comment-diag/result.json'))
    print(json.dumps(result))
    return 0 if result['status'] == 'POSTED_UNVERIFIED' else 1


if __name__ == '__main__':
    sys.exit(main())
