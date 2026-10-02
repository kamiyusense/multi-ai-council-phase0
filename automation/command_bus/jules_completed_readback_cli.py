"""One existing completed Session readback; no result adoption or successor."""
import json
import os
import sys
from pathlib import Path
from .github_readonly import _pairs
from .jules_session_readonly import JulesSessionGetReader


def prepare_readback(request, reader):
    if (not isinstance(request, dict) or set(request) != {
            'session_id', 'expected_branch', 'expected_create_time', 'expected_pr',
            'retry', 'fallback', 'purpose'}
            or type(request['retry']) is not int or request['retry'] != 0
            or request['fallback'] != 'disabled'
            or request['purpose'] != 'existing-completed-session-readback-only'):
        raise ValueError('invalid readback request')
    session = reader.read_completed_session(
        request['session_id'], expected_branch=request['expected_branch'],
        expected_create_time=request['expected_create_time'], expected_pr=request['expected_pr'])
    return {'session': session, 'source_mode': 'EXISTING_SESSION_GET',
            'adoption_performed': False, 'new_session_created': False,
            'work_review_posted': False, 'successor_dispatched': False,
            'retry': 0, 'fallback': 'disabled'}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        raise ValueError('request and output paths required')
    request = json.loads(Path(args[0]).read_text(), object_pairs_hook=_pairs)
    result = prepare_readback(request, JulesSessionGetReader(os.environ.get('JULES_API_KEY', '')))
    Path(args[1]).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('Existing completed Session readback saved; no adoption or successor.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
