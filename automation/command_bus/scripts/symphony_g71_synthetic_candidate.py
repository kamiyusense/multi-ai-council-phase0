"""Independent isolated synthetic byte qualification. Not worker attestation."""
import ast
import hashlib
import json
from pathlib import Path
from ..symphony_git_adoption import construct_candidate, _git_oid
from ..symphony_result_manifest import FileEntry, inventory_digest
from .symphony_g63_synthetic_verifier import verify_isolation


def qualify():
    verify_isolation()
    # Trusted synthetic bytes; never checkout/execute a worker candidate.
    files={'value.py':FileEntry(b'value = 2\n')}
    for p,e in files.items():ast.parse(e.data.decode('utf-8'),filename=p)
    candidate=construct_candidate(parent='a'*40,files=files,created_at='2026-10-10T01:00:00Z',adoption_id='g71-synthetic')
    assert all(_git_oid(kind,data)==oid for oid,(kind,data) in candidate.objects.items())
    sources=sorted(Path('automation/command_bus').glob('symphony_g71*.py'))
    for p in sources:ast.parse(p.read_text(),filename=str(p))
    report={'protocol':'SYMPHONY_G64_SYNTHETIC_CANDIDATE_PREFLIGHT_V1','result':'PASS',
        'candidate_oid':candidate.commit,'tree_oid':candidate.tree,'source_digest':inventory_digest(files),
        'file_sha256':{p:hashlib.sha256(e.data).hexdigest() for p,e in files.items()},
        'real_worker_candidate':False,'actual_candidate_attestation':False,'actual_result_adoption':0,
        'model_starts':0,'object_writes':0,'ref_writes':0,'g71_syntax_files':len(sources)}
    print(json.dumps(report));return report


if __name__=='__main__':qualify()
