"""Run pinned Official AppServer against a JSONL fake, never a Codex binary.

Explicit existing Elixir/Jason paths only. No downloads, credential discovery,
workflow dispatch or provider process. This is a reproducible STATIC receipt.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[3]
RELATIVE='elixir/lib/symphony_elixir/codex/app_server.ex'
PIN='be10a1b79df723d6d7612b5651c8522704dafb2e'
SOURCE_SHA256='40b87a197e96755a5343ffb7f211fb3c68e90b4dcdb7658f62d971f07f7e4e6e'
CASES=('good','explicit','notice','api','missing','no-auth','custom','paid','fallback',
       'partial','error','api-selector','metered','provider-fallback','billing')
SECRET_NAMES=('SYMPHONY_G5_OBSERVER_KEY_HEX','SYMPHONY_G5_OBSERVER_EVENTS','GITHUB_TOKEN',
    'GH_TOKEN','OPENAI_API_KEY','CODEX_API_KEY','AZURE_OPENAI_API_KEY','OPENAI_BASE_URL','OPENAI_API_BASE')


def check(*, elixir, jason_ebin):
    fixture=ROOT/'automation/command_bus/tests/fixtures/symphony_sqlite_installation'
    raw=gzip.decompress((fixture/'pinned_app_server.ex.gz').read_bytes())
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA256:raise ValueError('source pin conflict')
    patch=ROOT/'automation/command_bus/symphony_subscription_startup.patch'
    results=[]
    with tempfile.TemporaryDirectory(prefix='symphony-startup-static-') as folder:
        root=Path(folder);source=root/RELATIVE;source.parent.mkdir(parents=True);source.write_bytes(raw)
        subprocess.run(['git','init','-q',str(root)],check=True)
        subprocess.run(['git','-C',str(root),'apply','--check',str(patch)],check=True)
        subprocess.run(['git','-C',str(root),'apply',str(patch)],check=True)
        patched_sha=hashlib.sha256(source.read_bytes()).hexdigest()
        baseline=root/'baseline.ex';baseline.write_bytes(raw)
        for case in ('baseline-good',)+CASES:
            workspace=root/case;workspace.mkdir(mode=0o700);log=workspace/'methods.jsonl'
            env={k:v for k,v in os.environ.items() if k not in SECRET_NAMES}
            env.update({'GH_TOKEN':'STATIC_NOT_CREDENTIAL','GITHUB_TOKEN':'STATIC_NOT_CREDENTIAL',
                'SYMPHONY_G5_OBSERVER_KEY_HEX':'STATIC_NOT_KEY','SYMPHONY_G5_OBSERVER_EVENTS':'STATIC_NOT_EVENT'})
            if case=='api-selector':env['OPENAI_API_KEY']='STATIC_NOT_CREDENTIAL'
            # Original baseline is measured WITHOUT these synthetic authority
            # selectors; it is not the credential-filter proof.
            if case=='baseline-good':
                for key in SECRET_NAMES:env.pop(key,None)
            run=subprocess.run([str(elixir),'-pa',str(jason_ebin),str(fixture/'startup_fixture.exs'),
                str(baseline if case=='baseline-good' else source),str(fixture/'codex_jsonl_fixture.py'),
                str(workspace),'good' if case=='baseline-good' else case,str(log)],
                env=env,capture_output=True,text=True,encoding='utf-8',timeout=15)
            calls=[json.loads(s) for s in log.read_text().splitlines()]
            good=case in ('good','explicit','notice','baseline-good')
            turns=sum(c['method']=='turn/start' for c in calls)
            if (run.returncode or turns!=(3 if good else 0)
                    or 'STATIC_SENSITIVE_SENTINEL' in run.stdout+run.stderr
                    or any(c['blocked_environment_names_present'] for c in calls)):
                raise AssertionError('STATIC startup case failed: '+case)
            if good and case!='baseline-good':
                if [c['method'] for c in calls[:5]]!=['initialize','initialized','account/read','config/read','thread/start']:
                    raise AssertionError('same-process startup ordering differs')
            results.append({'case':case,'result':'PASS','mock_turn_starts':turns,
                'methods':[c['method'] for c in calls], 'auth_response_logged':False,
                'child_authority_selectors':0,'model_live':0,
                'output_sha256':hashlib.sha256((run.stdout+run.stderr).encode()).hexdigest()})
    return {'mode':'REAL_ELIXIR_UPSTREAM_WITH_FAKE_JSONL_ONLY','source_pin':PIN,
        'original_source_sha256':SOURCE_SHA256,'patched_source_sha256':patched_sha,
        'patch_sha256':hashlib.sha256(patch.read_bytes()).hexdigest(),'cases':results,
        'good_case_mock_continuation_delta':0,'real_codex_launched':False,
        'live_model_dispatch':0,'scheduler_code_changed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elixir',type=Path,required=True)
    parser.add_argument('--jason-ebin',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(check(elixir=args.elixir,jason_ebin=args.jason_ebin),indent=2))


if __name__=='__main__':main()
