"""G7.2 append-only evidence, exact historical bytes, explicit OFF boundary."""
import hashlib
import json
import subprocess
from pathlib import Path
from ..symphony_result_manifest import safe_path
from .validate_symphony_g63 import validate as historical
ROOT=Path(__file__).resolve().parents[3]
G63_HEAD='7da022aa24e82df6b23ccea8fc6d8da3c451a57a'
G71_HEAD='79bb9ea3d46503cce8654f4b5f2e9b849c10b6aa'
WORKFLOWS={'.github/workflows/symphony-controller-static.yml','.github/workflows/symphony-g63-synthetic-verifier.yml'}
G71_SUPERSEDED=WORKFLOWS|{'automation/command_bus/symphony_g71_campaign.py'}


def validate(root=ROOT):
    historical(root,historical_only=True)
    count=0
    for name in ('symphony-g63-static','symphony-g71-static','symphony-g72-static'):
        m=json.loads((root/'docs/evidence'/name/'manifest.json').read_text())
        seen=set()
        for entry in m['files']:
            path=entry['path']
            if not safe_path(path) or path in seen:raise ValueError('unsafe/duplicate manifest path')
            seen.add(path)
            ref=(G63_HEAD if name=='symphony-g63-static' and path in WORKFLOWS
                 else G71_HEAD if name=='symphony-g71-static' and path in G71_SUPERSEDED else None)
            raw=subprocess.check_output(['git','show',ref+':'+path],cwd=root) if ref else (root/path).read_bytes()
            if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
                raise ValueError('immutable byte mismatch: '+path)
            count+=1
    cp=json.loads((root/'docs/evidence/symphony-g72-static/checkpoint.json').read_text())
    if any(cp['counts'].values()) or cp['publisher_capability']!='UNSUPPLIED':
        raise ValueError('STATIC boundary violated')
    print(json.dumps({'result':'PASS','g63_g71_g72_verified_files':count,
        'historical_g71_head':G71_HEAD,'superseded_g71_sources':sorted(G71_SUPERSEDED),'live_count':0}))


if __name__=='__main__':validate()
