"""Preserve previous manifests; qualify changed workflows at pinned old bytes."""
import hashlib
import json
import subprocess
from pathlib import Path
from ..symphony_result_manifest import safe_path
from .validate_symphony_g63 import validate as historical
ROOT=Path(__file__).resolve().parents[3]
G63_HEAD='7da022aa24e82df6b23ccea8fc6d8da3c451a57a'
SUPERSEDED={'.github/workflows/symphony-controller-static.yml','.github/workflows/symphony-g63-synthetic-verifier.yml'}


def validate(root=ROOT):
    historical(root,historical_only=True)
    count=0
    for name in ('symphony-g63-static','symphony-g71-static'):
        m=json.loads((root/'docs/evidence'/name/'manifest.json').read_text())
        seen=set()
        for e in m['files']:
            p=e['path']
            if not safe_path(p) or p in seen:raise ValueError('unsafe/duplicate manifest entry')
            seen.add(p)
            data=(subprocess.check_output(['git','show',G63_HEAD+':'+p],cwd=root)
                  if name=='symphony-g63-static' and p in SUPERSEDED else (root/p).read_bytes())
            if len(data)!=e['bytes'] or hashlib.sha256(data).hexdigest()!=e['sha256']:
                raise ValueError('immutable byte mismatch: '+p)
            count+=1
    cp=json.loads((root/'docs/evidence/symphony-g71-static/checkpoint.json').read_text())
    if any(cp['counts'].values()):raise ValueError('real STATIC counts not zero')
    print(json.dumps({'result':'PASS','g63_g71_verified_files':count,'superseded_workflows':sorted(SUPERSEDED),
                      'historical_commit':G63_HEAD,'live_count':0}))


if __name__=='__main__':validate()
