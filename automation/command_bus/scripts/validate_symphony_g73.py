"""New manifest + unchanged historical bytes, including superseded workflows."""
import hashlib
import json
import subprocess
from pathlib import Path
from .validate_symphony_g72 import G63_HEAD, G71_HEAD, WORKFLOWS, G71_SUPERSEDED
from .validate_symphony_g63 import validate as historical
from ..symphony_result_manifest import safe_path
ROOT = Path(__file__).resolve().parents[3]
G72_HEAD = 'd9255aeb966a16f484ae0b4044e3e43c38f4c103'
# Last immutable source before the operator-interface CI extension. Old G7.3
# workflows/validator are checked at their real Git bytes; evidence is not resealed.
G73_HEAD = '07735ea07af0b6e0ce01917032ac60f48e2b65d3'
G73_SUPERSEDED = WORKFLOWS | {'automation/command_bus/scripts/validate_symphony_g73.py'}


def validate(root=ROOT):
    historical(root, historical_only=True)
    count = 0
    for name in ('symphony-g63-static', 'symphony-g71-static', 'symphony-g72-static', 'symphony-g73-static'):
        m = json.loads((root / 'docs/evidence' / name / 'manifest.json').read_text())
        seen = set()
        for entry in m['files']:
            p = entry['path']
            if not safe_path(p) or p in seen: raise ValueError('unsafe/duplicate manifest path')
            seen.add(p)
            ref = (G63_HEAD if name == 'symphony-g63-static' and p in WORKFLOWS else
                   G71_HEAD if name == 'symphony-g71-static' and p in G71_SUPERSEDED else
                   G72_HEAD if name == 'symphony-g72-static' and p in WORKFLOWS else
                   G73_HEAD if name == 'symphony-g73-static' and p in G73_SUPERSEDED else None)
            raw = subprocess.check_output(['git','show',ref+':'+p],cwd=root) if ref else (root/p).read_bytes()
            if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('immutable evidence mismatch: '+p)
            count += 1
    cp = json.loads((root/'docs/evidence/symphony-g73-static/checkpoint.json').read_text())
    if any(cp['counts'].values()) or cp['operator_approval'] != 'NONE' or cp['publication_capability'] != 'NOT_WIRED':
        raise ValueError('STATIC boundary violated')
    print(json.dumps({'result':'PASS','verified_files':count,'historical_g72_head':G72_HEAD,'live_count':0}))


if __name__ == '__main__': validate()
