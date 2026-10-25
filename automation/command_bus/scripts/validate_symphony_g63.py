"""Validate immutable historical evidence at its exact pinned checkpoint.

Old manifests describe old source bytes, not the latest implementation. Only
explicitly superseded development files use Git readback at their immutable
G6.2 commit; all historical evidence and other source are checked in place.
G6.3 changes are independently indexed by their own manifest.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from ..symphony_result_manifest import safe_path

ROOT=Path(__file__).resolve().parents[3]
HISTORICAL_HEAD='db578364c3bb22d5ed1af382085645cfb952f36e'
SUPERSEDED={'.github/workflows/symphony-controller-static.yml'}
# Approved Blue trigger-only change; never substitute new bytes in an old seal.
BLUE_WORKFLOW = '.github/workflows/blue-work-reconcile-static.yml'
BLUE_MANUAL_HEAD = 'e0880da5d848cf7381a7424cf71550d4f0c25e13'
VALIDATOR_SOURCE_HEAD = 'fab6f17a979bcfacd6b07804eb90bfa80edee446'
UPDATED_VALIDATORS = frozenset(
    'automation/command_bus/scripts/validate_symphony_' + name + '.py'
    for name in ('g63', 'g73', 'operator_static')
)
REPAIR_FILES = UPDATED_VALIDATORS | {
    'automation/command_bus/tests/test_symphony_seal_history.py'
}
REPAIR_MANIFEST = 'docs/evidence/symphony-actions-seal-repair/manifest.json'


def sealed_source(root, path):
    """Superseded validators retain their pre-repair bytes in historical seals."""
    if path in UPDATED_VALIDATORS:
        return subprocess.check_output(['git', 'show', VALIDATOR_SOURCE_HEAD + ':' + path], cwd=root)
    return (root / path).read_bytes()


def validate_current_safety(root):
    """Current policy and repaired validators are checked separately, never skipped."""
    approved = subprocess.check_output(['git', 'show', BLUE_MANUAL_HEAD + ':' + BLUE_WORKFLOW], cwd=root)
    if (root / BLUE_WORKFLOW).read_bytes() != approved:
        raise ValueError('current Blue manual-only policy changed')
    manifest = json.loads((root / REPAIR_MANIFEST).read_text())
    if manifest.get('schema_version') != 1:
        raise ValueError('invalid repair manifest version')
    seen = set()
    for entry in manifest['files']:
        path = entry['path']
        if not safe_path(path) or path in seen or path not in REPAIR_FILES:
            raise ValueError('unsafe/duplicate repair manifest path')
        seen.add(path)
        raw = (root / path).read_bytes()
        if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            raise ValueError('current repair source changed: ' + path)
    if seen != REPAIR_FILES:
        raise ValueError('repair source missing from seal')


def validate(root=ROOT, *, historical_only=False):
    validate_current_safety(root)
    count=0;historical_source=0
    for name in ('symphony-g61-static','symphony-g61-ci-recovery','symphony-g62-static'):
        m=json.loads((root/'docs/evidence'/name/'manifest.json').read_text())
        seen=set()
        for entry in m['files']:
            path=entry['path']
            if not safe_path(path) or path in seen:raise ValueError('unsafe/duplicate evidence path')
            seen.add(path)
            if path in SUPERSEDED or path == BLUE_WORKFLOW:
                data=subprocess.check_output(['git','show',HISTORICAL_HEAD+':'+path],cwd=root)
                historical_source+=1
            else:data=(root/path).read_bytes()
            if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
                raise ValueError('historical byte/hash mismatch: '+path)
            count+=1
    if not historical_only:
        m=json.loads((root/'docs/evidence/symphony-g63-static/manifest.json').read_text())
        seen=set()
        for entry in m['files']:
            path=entry['path']
            if not safe_path(path) or path in seen:raise ValueError('unsafe/duplicate G6.3 path')
            seen.add(path);data=sealed_source(root,path)
            if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:
                raise ValueError('G6.3 byte/hash mismatch: '+path)
            count+=1
        cp=json.loads((root/'docs/evidence/symphony-g63-static/checkpoint.json').read_text())
        if any(cp['counts'].values()):raise ValueError('STATIC counts must remain zero')
    if hashlib.sha256((root/'automation/command_bus/symphony_g5_observer.patch').read_bytes()).hexdigest()!='404b4001d279351c8b800816142862ee47dfd209615b0f9211fbe6ccc5170f3b':
        raise ValueError('Official Symphony patch changed')
    print(json.dumps({'result':'PASS','verified_files':count,'historical_source_reads':historical_source,
        'historical_commit':HISTORICAL_HEAD,'live_count':0}))


if __name__=='__main__':validate(historical_only=sys.argv[1:]==['--historical-only'])
