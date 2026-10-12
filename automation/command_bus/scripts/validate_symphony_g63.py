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


def validate(root=ROOT, *, historical_only=False):
    count=0;historical_source=0
    for name in ('symphony-g61-static','symphony-g61-ci-recovery','symphony-g62-static'):
        m=json.loads((root/'docs/evidence'/name/'manifest.json').read_text())
        seen=set()
        for entry in m['files']:
            path=entry['path']
            if not safe_path(path) or path in seen:raise ValueError('unsafe/duplicate evidence path')
            seen.add(path)
            if path in SUPERSEDED:
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
            seen.add(path);data=(root/path).read_bytes()
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
