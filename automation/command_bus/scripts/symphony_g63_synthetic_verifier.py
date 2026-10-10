"""Credential-free synthetic qualification, never a real candidate attestation."""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
from ..symphony_result_manifest import digest


def verify_isolation():
    if os.environ.get('SYMPHONY_G63_ISOLATED') != '1':
        raise RuntimeError('only the qualified no-network/read-only container may run this check')
    forbidden=('GITHUB_TOKEN','GH_TOKEN','OPENAI_API_KEY','CODEX_API_KEY','AZURE_OPENAI_API_KEY',
               'OPENAI_BASE_URL','OPENAI_API_BASE','ACTIONS_RUNTIME_TOKEN','SYMPHONY_G5_OBSERVER_KEY_HEX')
    if any(k in os.environ for k in forbidden):
        raise RuntimeError('forbidden credential selector present')
    if os.geteuid() == 0:
        raise RuntimeError('container must be nonroot')
    # Runtime evidence rather than a YAML assertion alone.
    mounts=Path('/proc/mounts').read_text().splitlines()
    for required in ('/','/source'):
        if not any(row.split()[1]==required and 'ro' in row.split()[3].split(',') for row in mounts):
            raise RuntimeError('read-only root/source missing')
    interfaces=Path('/proc/net/dev').read_text().splitlines()[2:]
    if any(row.split(':')[0].strip()!='lo' for row in interfaces):
        raise RuntimeError('network interface present')
    if Path('/var/run/docker.sock').exists():
        raise RuntimeError('host Docker socket exposed')
    print(json.dumps({'isolation':'PASS','credential_selectors':0,'network':'none','root':'readonly',
                      'source':'readonly','uid':os.geteuid(),'model_starts':0}))


def syntax():
    verify_isolation()
    files=sorted(Path('automation/command_bus').glob('symphony_g63*.py'))
    for p in files:ast.parse(p.read_text(),filename=str(p))
    print(json.dumps({'synthetic_syntax':'PASS','files':len(files)}))


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['syntax']:syntax()
    elif sys.argv[1:] == ['isolation']:verify_isolation()
    else:raise SystemExit('syntax or isolation required; no candidate/adoption mode')
