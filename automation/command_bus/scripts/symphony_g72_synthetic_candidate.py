"""Trusted synthetic acquisition; no candidate code executed on outer runner."""
import ast
import hashlib
import json
import os
import sys
from pathlib import Path
from ..symphony_g72_candidate import CandidateExecutionPins,prepare_candidate_inputs,export_inputs
from ..symphony_result_manifest import FileEntry,SourceResult,seal_manifest,inventory_digest,digest


def inputs(workflow_sha256, python_image, scanner_image):
    files={'value.py':FileEntry(b'value = 2\n'),
        'test_value.py':FileEntry(b'import unittest\nfrom value import value\nclass ValueTest(unittest.TestCase):\n def test_value(self): self.assertEqual(value,2)\n')}
    source=SourceResult(files=files,workspace_fingerprint='f'*64,trustworthy=True,complete=True)
    scope={'allowed_paths':sorted(files),'allowed_prefixes':[]}
    manifest=seal_manifest({'protocol':'SYMPHONY_G6_RESULT_V1','schema_version':1,
        'repository':'fixture/synthetic','target_branch':'fixture/candidate','campaign_id':'g72-synthetic',
        'task_id':'fixture','attempt_id':'fixture-1','generation':1,'attempt_number':1,'runner_generation':1,
        'issue_id':'fixture/synthetic#1','worker_run_id':'f'*32,'expected_target_head':'a'*40,
        'workspace_fingerprint':'f'*64,'scope_digest':digest(scope),'request_digest':digest({'synthetic':True}),
        'source_digest':inventory_digest(files),'mutations':[],'evidence_refs':[]})
    return prepare_candidate_inputs(manifest=manifest,source=source,created_at='2026-10-10T01:00:00Z',
        pins=CandidateExecutionPins(workflow_sha256,('operator.value_equals_two',),python_image,scanner_image),synthetic=True)


def main():
    if sys.argv[1:] == ['export']:
        workflow=Path('.github/workflows/symphony-g63-synthetic-verifier.yml').read_bytes()
        plan=inputs(hashlib.sha256(workflow).hexdigest(),os.environ['PYTHON_IMAGE'],os.environ['SCANNER_IMAGE'])
        root=Path(os.environ['RUNNER_TEMP'])/'g72-candidate'
        export_inputs(plan,root)
        (root.parent/'g72-candidate-inputs.json').write_text(json.dumps(plan,indent=2)+'\n')
        print(json.dumps({'synthetic_candidate_prepared':True,'candidate_commit':plan['candidate_commit'],
                          'actual_candidate_attestation':False,'real_writes':0}))
    elif sys.argv[1:] == ['syntax']:
        from .symphony_g63_synthetic_verifier import verify_isolation
        verify_isolation()
        mounts=Path('/proc/mounts').read_text().splitlines()
        if not any(row.split()[1]=='/candidate' and 'ro' in row.split()[3].split(',') for row in mounts):
            raise RuntimeError('candidate mount must be readonly')
        plan=json.loads(Path('/candidate-inputs.json').read_text())
        if digest({k:v for k,v in plan.items() if k!='input_digest'})!=plan['input_digest']:
            raise RuntimeError('operator candidate inputs corrupted')
        actual={str(p.relative_to('/candidate')) for p in Path('/candidate').rglob('*') if p.is_file()}
        if actual!=set(plan['files']):raise RuntimeError('candidate inventory changed')
        for name,entry in plan['files'].items():
            if hashlib.sha256((Path('/candidate')/name).read_bytes()).hexdigest()!=entry['sha256']:
                raise RuntimeError('candidate bytes changed')
        for p in Path('/candidate').rglob('*.py'):ast.parse(p.read_text(),filename=str(p))
        print(json.dumps({'synthetic_full_candidate_syntax':'PASS','actual_candidate_attestation':False}))
    else:raise SystemExit('export or syntax required')


if __name__=='__main__':main()
