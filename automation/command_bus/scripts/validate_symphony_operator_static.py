"""Exact current operator-interface evidence plus immutable historical proof."""
import hashlib
import json
from pathlib import Path
from .validate_symphony_g73 import validate as historical
from ..symphony_result_manifest import safe_path

ROOT = Path(__file__).resolve().parents[3]


def validate(root=ROOT):
    historical(root)
    base = root / 'docs/evidence/symphony-prelive-static'
    manifest = json.loads((base / 'manifest.json').read_text())
    seen = set()
    for entry in manifest['files']:
        path = entry['path']
        if not safe_path(path) or path in seen:
            raise ValueError('unsafe/duplicate operator evidence path')
        seen.add(path); raw = (root / path).read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('operator current source/evidence bytes changed: ' + path)
    gates = json.loads((base / 'gates.json').read_text())
    cp = json.loads((base / 'checkpoint.json').read_text())
    if (gates['LIVE_GO'] is not False or gates['actual_real_candidate_qualification'] != 'NOT_QUALIFIED'
            or gates['actual_real_write_capability'] != 'NOT_WIRED' or gates['human_one_run_approval'] != 'NONE'
            or cp['mode'] != 'OFF' or any(cp['forbidden_counts'].values())):
        raise ValueError('operator STATIC boundary changed')
    print(json.dumps({'result': 'PASS', 'current_operator_files': len(seen), 'LIVE': 0,
                      'actual_candidate': 'NOT_QUALIFIED', 'real_sender': 'NOT_WIRED'}))


if __name__ == '__main__':
    validate()
