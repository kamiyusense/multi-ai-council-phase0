"""Exact current operator-interface evidence plus immutable historical proof."""
import hashlib
import json
import subprocess
from pathlib import Path
from .validate_symphony_g73 import validate as historical
from ..symphony_result_manifest import safe_path

ROOT = Path(__file__).resolve().parents[3]
# Last fresh merged main before the production connection extension. Historical
# manifests are preserved byte-for-byte; only superseded source uses this pin.
HISTORICAL_CONVERGENCE_HEAD = "c989aeb08018684ed092c6ce9b78a434903e4b8c"
CONVERGENCE_SUPERSEDED = {".github/workflows/symphony-controller-static.yml",
    "automation/command_bus/symphony_operator_capability.py",
    "automation/command_bus/tests/test_symphony_operator_convergence.py",
    "automation/command_bus/scripts/validate_symphony_operator_static.py"}
HISTORICAL_OPERATOR_HEAD = "8bfe01b64cdf9206dc47af32b5f25c85ab1be8ed"
SUPERSEDED = {"automation/command_bus/scripts/validate_symphony_g73.py",
    ".github/workflows/symphony-controller-static.yml",
    ".github/workflows/symphony-g63-synthetic-verifier.yml",
    "automation/command_bus/scripts/validate_symphony_operator_static.py"}


def validate(root=ROOT):
    historical(root)
    base = root / 'docs/evidence/symphony-prelive-static'
    manifest = json.loads((base / 'manifest.json').read_text())
    seen = set()
    for entry in manifest['files']:
        path = entry['path']
        if not safe_path(path) or path in seen:
            raise ValueError('unsafe/duplicate operator evidence path')
        seen.add(path)
        raw = (subprocess.check_output(['git','show',HISTORICAL_OPERATOR_HEAD+':'+path],cwd=root)
               if path in SUPERSEDED else (root / path).read_bytes())
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('operator current source/evidence bytes changed: ' + path)
    gates = json.loads((base / 'gates.json').read_text())
    cp = json.loads((base / 'checkpoint.json').read_text())
    if (gates['LIVE_GO'] is not False or gates['actual_real_candidate_qualification'] != 'NOT_QUALIFIED'
            or gates['actual_real_write_capability'] != 'NOT_WIRED' or gates['human_one_run_approval'] != 'NONE'
            or cp['mode'] != 'OFF' or any(cp['forbidden_counts'].values())):
        raise ValueError('operator STATIC boundary changed')
    current = root / 'docs/evidence/symphony-prelive-convergence'
    if (current / 'manifest.json').exists():
        sealed = json.loads((current / 'manifest.json').read_text())
        fresh_seen = set()
        for entry in sealed['files']:
            path = entry['path']
            if not safe_path(path) or path in fresh_seen:
                raise ValueError('unsafe/duplicate convergence evidence path')
            fresh_seen.add(path)
            raw = (subprocess.check_output(['git','show',HISTORICAL_CONVERGENCE_HEAD+':'+path],cwd=root)
                   if path in CONVERGENCE_SUPERSEDED else (root / path).read_bytes())
            if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('current convergence source/evidence changed: '+path)
        gate = json.loads((current / 'gates.json').read_text())
        if (gate['LIVE_GO'] is not False or gate['human_one_run_approval'] != 'NONE'
                or gate['actual_real_candidate_qualification'] != 'NOT_RUN'
                or any(gate['forbidden_counts'].values())):
            raise ValueError('convergence approval boundary changed')
    connection_count = validate_current_connection(root)
    print(json.dumps({'result': 'PASS', 'historical_operator_files': len(seen),
                      'current_connection_files': connection_count, 'LIVE': 0,
                      'actual_candidate': 'NOT_QUALIFIED', 'real_sender': 'NOT_WIRED'}))


def validate_current_connection(root):
    base=root/'docs/evidence/symphony-production-connection'
    if not base.exists():
        raise ValueError('production connection evidence missing')
    manifest=json.loads((base/'manifest.json').read_text());seen=set()
    for entry in manifest['files']:
        path=entry['path']
        if not safe_path(path) or path in seen:raise ValueError('unsafe connection manifest')
        seen.add(path);raw=(root/path).read_bytes()
        if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('current connection evidence mismatch: '+path)
    gates=json.loads((base/'checkpoint.json').read_text())
    if (gates['result']!='PRELIVE_BLOCKED' or gates['mode']!='OFF'
            or gates['LIVE_GO'] is not False or gates['actual_candidate_qualified'] is not False
            or any(gates['forbidden_counts'].values())):
        raise ValueError('current connection OFF boundary violated')
    return len(seen)


if __name__ == '__main__':
    validate()
