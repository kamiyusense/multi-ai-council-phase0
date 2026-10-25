"""Exact current operator-interface evidence plus immutable historical proof."""
import hashlib
import json
import subprocess
from pathlib import Path
from .validate_symphony_g63 import sealed_source
from .validate_symphony_g73 import validate as historical
from ..symphony_result_manifest import safe_path

ROOT = Path(__file__).resolve().parents[3]
# Last fresh merged main before the production connection extension. Historical
# manifests are preserved byte-for-byte; only superseded source uses this pin.
# The first production-connection receipt remains immutable after host repair.
HISTORICAL_CONNECTION_HEAD = "0d32c7fa345b8eea73deae1505ec2c59ed7116e7"
HOST_RECOVERY_HEAD = "f9226a228720ed9801e73bccdf8c52777b5a2ce9"
HOST_RECOVERY_SUPERSEDED = {"automation/command_bus/symphony_codex_app_server.py",
    "automation/command_bus/scripts/validate_symphony_operator_static.py"}

INSTALLATION_SUPERSEDED = {".github/workflows/symphony-operator-installation-static.yml"}

CONNECTION_SUPERSEDED = {"automation/command_bus/symphony_codex_app_server.py",
    "automation/command_bus/scripts/validate_symphony_operator_static.py"}

HISTORICAL_CONVERGENCE_HEAD = "c989aeb08018684ed092c6ce9b78a434903e4b8c"
CONVERGENCE_SUPERSEDED = {".github/workflows/symphony-controller-static.yml",
    ".github/workflows/symphony-g63-synthetic-verifier.yml",
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
               if path in SUPERSEDED else sealed_source(root,path))
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
                   if path in CONVERGENCE_SUPERSEDED else sealed_source(root,path))
            if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('current convergence source/evidence changed: '+path)
        gate = json.loads((current / 'gates.json').read_text())
        if (gate['LIVE_GO'] is not False or gate['human_one_run_approval'] != 'NONE'
                or gate['actual_real_candidate_qualification'] != 'NOT_RUN'
                or any(gate['forbidden_counts'].values())):
            raise ValueError('convergence approval boundary changed')
    connection_count = validate_current_connection(root)
    validate_installation_readiness(root)
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
        seen.add(path)
        raw=(subprocess.check_output(['git','show',HISTORICAL_CONNECTION_HEAD+':'+path],cwd=root)
             if path in CONNECTION_SUPERSEDED | INSTALLATION_SUPERSEDED else sealed_source(root,path))
        if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('current connection evidence mismatch: '+path)
    gates=json.loads((base/'checkpoint.json').read_text())
    if (gates['result']!='PRELIVE_BLOCKED' or gates['mode']!='OFF'
            or gates['LIVE_GO'] is not False or gates['actual_candidate_qualified'] is not False
            or any(gates['forbidden_counts'].values())):
        raise ValueError('current connection OFF boundary violated')
    # The new seal validates current repaired source, never reseals old receipts.
    recovery = base / 'host-recovery'
    if not (recovery / 'manifest.json').exists():
        raise ValueError('host recovery evidence missing')
    current_seen = set()
    for entry in json.loads((recovery/'manifest.json').read_text())['files']:
        path=entry['path']
        if not safe_path(path) or path in current_seen:
            raise ValueError('unsafe recovery manifest')
        current_seen.add(path)
        raw=(subprocess.check_output(["git","show",HOST_RECOVERY_HEAD+":"+path],cwd=root)
             if path in HOST_RECOVERY_SUPERSEDED else sealed_source(root,path))
        if len(raw)!=entry['bytes'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            raise ValueError('current host recovery evidence mismatch: '+path)
    if not CONNECTION_SUPERSEDED <= current_seen:
        raise ValueError('repaired current source absent from recovery seal')
    cp=json.loads((recovery/'checkpoint.json').read_text())
    if (cp['LIVE_GO'] is not False or cp['mode']!='OFF' or cp['result']!='PRELIVE_BLOCKED'
            or any(cp['forbidden_counts'].values())):
        raise ValueError('host recovery OFF boundary violated')
    return len(seen)


def validate_installation_readiness(root):
    base=root/"docs/evidence/symphony-production-connection/installation-readiness"
    sealed=json.loads((base/"manifest.json").read_text());seen=set()
    for entry in sealed["files"]:
        path=entry["path"]
        if not safe_path(path) or path in seen:raise ValueError("unsafe readiness seal")
        seen.add(path)
        raw=(subprocess.check_output(['git','show','87c81bb5a7b5f9a199f450edd12544a0b532afd8:'+path],cwd=root)
             if path in {'automation/command_bus/scripts/validate_symphony_operator_static.py',
                         'automation/command_bus/symphony_subscription_startup.patch',
                         'automation/command_bus/symphony_sqlite_storage.py',
                         'automation/command_bus/tests/test_symphony_sqlite_installation.py'} else sealed_source(root,path))
        if len(raw)!=entry["bytes"] or hashlib.sha256(raw).hexdigest()!=entry["sha256"]:
            raise ValueError("current installation readiness bytes differ: "+path)
    required={"automation/command_bus/symphony_sqlite_storage.py",
        "automation/command_bus/symphony_codex_app_server.py",
        "automation/command_bus/scripts/validate_symphony_operator_static.py",
        "automation/command_bus/tests/test_symphony_sqlite_installation.py"}
    if not required<=seen:raise ValueError("current storage source missing from seal")
    cp=json.loads((base/"checkpoint.json").read_text())
    if (cp["LIVE_GO"] is not False or cp["mode"]!="OFF"
            or cp["production_cutover"] is not False or any(cp["forbidden_counts"].values())):
        raise ValueError("installation activation boundary violated")
    correction=base/"format-correction"
    entries=json.loads((correction/"manifest.json").read_text())["files"]
    corrected=set()
    for entry in entries:
        path=entry["path"]
        if not safe_path(path) or path in corrected:raise ValueError("unsafe correction seal")
        corrected.add(path)
        raw=(subprocess.check_output(['git','show','0714d94ce1e255c0de088586e2ea094bd0a43829:'+path],cwd=root)
             if path=='automation/command_bus/scripts/validate_symphony_operator_static.py'
             else sealed_source(root,path))
        if len(raw)!=entry["bytes"] or hashlib.sha256(raw).hexdigest()!=entry["sha256"]:
            raise ValueError("current correction bytes differ: "+path)
    if not {"automation/command_bus/symphony_subscription_startup.patch",
            "automation/command_bus/scripts/validate_symphony_operator_static.py"}<=corrected:
        raise ValueError("current corrected source absent from seal")
    cp=json.loads((correction/"checkpoint.json").read_text())
    if (cp["applied_source_byte_equal"] is not True or cp["mode"]!="OFF"
            or cp["LIVE_GO"] is not False or any(cp["forbidden_counts"].values())):
        raise ValueError("format correction boundary differs")
    recovery=base/"ci-recovery"
    actual=set()
    for entry in json.loads((recovery/"manifest.json").read_text())["files"]:
        path=entry["path"]
        if not safe_path(path) or path in actual:raise ValueError("unsafe CI recovery seal")
        actual.add(path);raw=sealed_source(root,path)
        if len(raw)!=entry["bytes"] or hashlib.sha256(raw).hexdigest()!=entry["sha256"]:
            raise ValueError("current CI recovery bytes differ: "+path)
    if not {"automation/command_bus/symphony_sqlite_storage.py",
            "automation/command_bus/tests/test_symphony_sqlite_installation.py",
            "automation/command_bus/scripts/validate_symphony_operator_static.py"}<=actual:
        raise ValueError("current race repair absent from seal")
    cp=json.loads((recovery/"checkpoint.json").read_text())
    if cp["LIVE_GO"] is not False or any(cp["forbidden_counts"].values()):
        raise ValueError("CI recovery activation boundary differs")


if __name__ == '__main__':
    validate()
