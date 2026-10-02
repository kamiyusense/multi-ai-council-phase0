"""One existing completed Session readback; no result adoption or successor."""
import json
import os
import sys
from pathlib import Path
from .github_readonly import _pairs
from .jules_session_readonly import JulesSessionGetReader, SessionReadbackUnavailable, safe_diagnostic_checks


def prepare_readback(request, reader):
    if (not isinstance(request, dict) or set(request) != {
            'session_id', 'expected_branch', 'expected_create_time', 'expected_pr',
            'retry', 'fallback', 'purpose'}
            or type(request['retry']) is not int or request['retry'] != 0
            or request['fallback'] != 'disabled'
            or not isinstance(request['purpose'], str) or request['purpose'] not in {
                'existing-completed-session-readback-only',
                'existing-completed-session-diagnostic-only'}):
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
    output = Path(args[1])
    if output.exists() or output.is_symlink():
        raise FileExistsError('readback output already exists; no GET attempted')
    request = json.loads(Path(args[0]).read_text(), object_pairs_hook=_pairs)
    code = 0
    try:
        result = prepare_readback(request, JulesSessionGetReader(os.environ.get('JULES_API_KEY', '')))
        result['status'] = 'OBSERVED_COMPLETED'
    except SessionReadbackUnavailable as exc:
        classified = SessionReadbackUnavailable(exc.stage, exc.checks)
        result = {'status': 'UNKNOWN', 'failure_stage': classified.stage,
                  'diagnostic_checks': safe_diagnostic_checks(classified.checks),
                  'adoption_performed': False, 'new_session_created': False,
                  'work_review_posted': False, 'successor_dispatched': False,
                  'retry': 0, 'fallback': 'disabled'}
        code = 2
    with output.open('x') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print('Existing Session readback saved: ' + result['status'] + '; no adoption or successor.')
    if request.get('purpose') == 'existing-completed-session-diagnostic-only':
        print('[SESSION_DIAGNOSTIC_V1] ' + json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
