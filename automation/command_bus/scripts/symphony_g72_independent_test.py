"""Operator-owned synthetic behavior check; candidate self-tests are untrusted.

Runs only in the approved readonly/no-network container. The trusted parent
checks a separate candidate interpreter's exit and exact behavior, and alone
returns the verifier result. No candidate attestation/credential is supplied.
"""
import json
import subprocess
import sys
from pathlib import Path
from .symphony_g63_synthetic_verifier import verify_isolation


def check():
    verify_isolation()
    pins=json.loads(Path('/candidate-inputs.json').read_text())
    if pins['test_modules'] != ['operator.value_equals_two']:
        raise RuntimeError('operator test configuration changed')
    code="import json,runpy; result=runpy.run_path('/candidate/value.py'); print(json.dumps({'value':result.get('value')}))"
    child=subprocess.run([sys.executable,'-I','-c',code],capture_output=True,encoding='utf-8',timeout=10)
    if child.returncode!=0 or child.stderr or child.stdout.strip()!='{"value": 2}':
        raise RuntimeError('independent synthetic behavior check failed')
    print(json.dumps({'operator_synthetic_behavior':'PASS','candidate_self_tests_used':False,
        'actual_candidate_attestation':False,'model_starts':0}))


if __name__=='__main__':check()
