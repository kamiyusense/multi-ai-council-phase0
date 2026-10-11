"""Prepare the real verifier's existing Docker/CI route; no execution or writes.

Only the operator owns input contracts/source/snapshot readers. The resulting
argv is data for a future approved exact-candidate CI job, never an authority or
synthetic qualification. No CI dispatch, candidate staging or container starts.
"""
import hashlib
from pathlib import Path

from .symphony_github_git_transport import prepare_candidate_requests
from .symphony_operator_candidate import (OperatorCandidateContract, operator_attestation_binding,
                                         clock)
from .symphony_result_manifest import seal_manifest, inventory_digest, digest
from .symphony_workspace_snapshot import scan_workspace
from .symphony_g73_host import _root

COMMON = ('--pull=never','--rm','--network','none','--read-only','--cap-drop','ALL',
          '--security-opt','no-new-privileges','--user','65534:65534','--pids-limit','64',
          '--memory','256m','--cpus','2','--tmpfs','/tmp:rw,noexec,nosuid,size=64m')


def prepare_real_verifier_route(*, contract, manifest, candidate, attempt, snapshots,
                                source, source_inventory, candidate_root, now):
    """Hash actual immutable inputs before deriving operator-owned argv.

    Snapshot acquisition, Git objects, original verification/provenance and
    task inspector remain unchanged. This does not grant CI/run/send authority.
    """
    if type(contract) is not OperatorCandidateContract or seal_manifest(manifest) != manifest:
        raise ValueError('exact operator contract and sealed manifest required')
    c = contract; c.execution.validate()
    if not clock(c.issued_at) <= clock(now) < clock(c.expires_at):
        raise ValueError('operator verification contract expired')
    if (attempt.state != 'TERMINAL' or attempt.started is None or attempt.terminal is None
            or attempt.started.get('observation_source') != 'LIVE_OBSERVATION'
            or attempt.started.get('provider_kind') != 'OFFICIAL_SYMPHONY_CODEX'
            or attempt.started.get('provider_attempt_ref') != manifest['worker_run_id']):
        raise ValueError('fresh actual completed worker lifetime required; STATIC refused')
    preserved = snapshots.load(c.snapshot_id, expected_worker_run_id=manifest['worker_run_id'],
        expected_campaign_id=manifest['campaign_id'], expected_attempt_id=manifest['attempt_id'],
        expected_workspace_fingerprint=manifest['workspace_fingerprint'])
    if (snapshots.manifest_sha256(c.snapshot_id) != c.snapshot_manifest_sha256
            or preserved.files != candidate.files or candidate.parent != manifest['expected_target_head']
            or candidate.commit != c.ci.candidate_commit or candidate.tree != c.candidate_tree
            or inventory_digest(candidate.files) != manifest['source_digest']):
        raise ValueError('real snapshot/candidate identity conflict')
    prepare_candidate_requests(candidate)
    src, root = _root(source), _root(candidate_root)
    source_files, _, source_anomalies = scan_workspace(str(src))
    candidate_files, _, candidate_anomalies = scan_workspace(str(root))
    if (source_inventory.head != c.workflow_source_commit or source_inventory.complete is not True
            or source_inventory.trustworthy is not True or source_anomalies
            or source_files != dict(source_inventory.files)):
        raise ValueError('complete independently authenticated operator source tree required')
    if src == root or src in root.parents or root in src.parents:
        raise ValueError('operator source and candidate must be separate')
    if candidate_anomalies or candidate_files != dict(candidate.files):
        raise ValueError('isolated candidate bytes differ from preserved snapshot')
    # Source commit must be operator-GET-hashed independently by caller and
    # original PinnedSourceCIVerifier. Here every executable/config pin is exact.
    for path, sha in (*c.execution.tests, c.execution.scanner_config, (c.ci.workflow_path,c.ci.workflow_sha256)):
        p = _root(src / path)
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
            raise ValueError('operator-owned trusted source pin conflict')
    workflow = candidate.files.get(c.ci.workflow_path)
    if workflow is None or workflow.sha256 != c.ci.workflow_sha256:
        raise ValueError('candidate lacks identical independently pinned workflow')
    mounts = ('--mount',f'type=bind,src={src},dst=/source,readonly',
              '--mount',f'type=bind,src={root},dst=/candidate,readonly','--workdir','/source')
    def python(*args):
        return ['docker','run',*COMMON,*mounts,'-e','PYTHONDONTWRITEBYTECODE=1',
                c.execution.python_image,'python','-I',*args]
    # Operator scripts are independently pinned. Never import/run candidate
    # tests, selectors, .git hooks or a candidate scanner configuration.
    syntax = python('-c', 'import ast,pathlib; [(ast.parse(p.read_bytes(),filename=str(p))) for p in pathlib.Path("/candidate").rglob("*.py")]')
    tests = [python('/source/' + path) for path,_ in c.execution.tests]
    scanner = ['docker','run',*COMMON,*mounts,c.execution.scanner_image,
        'dir','/candidate','--config','/source/' + c.execution.scanner_config[0],
        '--gitleaks-ignore-path','/tmp/absent','--ignore-gitleaks-allow','--redact','--no-banner']
    binding = operator_attestation_binding(c,manifest,candidate,attempt)
    plan = {'binding':binding,'mode':'OFF','authorized_to_execute':False,
        'commands':{'syntax':syntax,'tests':tests,'secret_scan':scanner},
        'required_ci_steps':list(c.ci.required_steps),
        'candidate_code_tests_selected':False,'model_dispatch':0,'publication':0,
        'candidate_remote_staging':'REQUIRES_SEPARATE_EXPLICIT_APPROVAL',
        'runtime_workflow':'REQUIRES_OPERATOR_REVIEWED_EXACT_CANDIDATE_HEAD_JOB',
        'next_reader':'OperatorCandidateVerifier.read',
        'attestation_emitter':'export_real_attestation + original strict attestation.json',
        'whole_ZIP_digest':'DETACHED_AFTER_TRUSTED_CI_ARCHIVE'}
    return {**plan,'plan_digest':digest(plan)}


def run_real_verifier_job(*, job_context, run_command, **inputs):
    """Trusted, explicitly invoked verification-only job; no dispatch/publication.

    An operator-reviewed exact-candidate CI job supplies its independently read
    numeric run/job identity and a bounded local command executor. The existing
    strict GET reader authenticates the uploaded archive afterwards; this local
    emission alone does not qualify a candidate. No model or credential factory.
    """
    import io
    import zipfile
    from .symphony_operator_candidate import export_real_attestation
    from .symphony_result_manifest import canonical
    from .symphony_result_verification import (external_record, builtin_secret_patterns,
                                               assemble_verification, builtin_syntax)
    c, m = inputs['contract'], inputs['manifest']
    expected = {'repository':c.ci.repository, 'workflow_id':c.ci.workflow_id,
        'run_id':c.ci.run_id, 'run_attempt':c.ci.run_attempt, 'job_id':c.ci.job_id,
        'head_sha':c.ci.candidate_commit, 'workflow_source_commit':c.workflow_source_commit}
    if (type(job_context) is not dict or job_context != expected
            or any(type(job_context[k]) is not int or job_context[k] <= 0
                   for k in ('workflow_id','run_id','run_attempt','job_id'))
            or not callable(run_command)):
        raise ValueError('exact independently pinned CI job identity and trusted executor required')
    plan = prepare_real_verifier_route(**inputs)
    records = []; invocations = []
    for check, commands in (('syntax',[plan['commands']['syntax']]),
                            ('tests',plan['commands']['tests']),
                            ('secret_scan',[plan['commands']['secret_scan']])):
        observations=[]
        for argv in commands:
            if prepare_real_verifier_route(**inputs) != plan:
                raise ValueError('immutable verifier inputs changed before check')
            # Executor owns timeout/capture. Candidate output is never authority
            # or published raw: only result code and bounded byte digests survive.
            reply = run_command(tuple(argv))
            if (type(reply) is not dict or set(reply) != {'returncode','stdout','stderr'}
                    or type(reply['returncode']) is not int
                    or any(type(reply[k]) is not bytes or len(reply[k]) > 2*1024*1024
                           for k in ('stdout','stderr'))):
                raise ValueError('bounded independent executor result required')
            observations.append({'returncode':reply['returncode'],
                'stdout_sha256':hashlib.sha256(reply['stdout']).hexdigest(),
                'stderr_sha256':hashlib.sha256(reply['stderr']).hexdigest()})
            invocations.append({'check':check,'argv_digest':digest(list(argv)),**observations[-1]})
            if reply['returncode'] != 0:
                raise ValueError('independent '+check+' failed; no real attestation emitted')
        records.append(external_record(m, check=check, verifier_id=c.ci.verifier_id,
            status='PASS',details={'commands':observations},observed_at=inputs['now']))
    source = inputs['snapshots'].load(c.snapshot_id)
    # Parse all changed JSON/TOML as well as Python using existing built-in guard.
    parsed,_ = builtin_syntax(m,source,verifier_id='g61-syntax',observed_at=inputs['now'])
    if parsed['status'] != 'PASS':
        raise ValueError('existing parse-only verification failed')
    record,_ = builtin_secret_patterns(m,source,verifier_id='g61-patterns',observed_at=inputs['now'])
    records.append(record)
    bundle = assemble_verification(m,records,trusted_verifiers={c.ci.verifier_id:'EXTERNAL_CI',
        'g61-patterns':'G61_BUILTIN_SECRET_PATTERNS'},worker_run_id=m['worker_run_id'])
    if not bundle.evidence.trustworthy or not all(bundle.evidence.checks.values()):
        raise ValueError('original required verification checks failed')
    if prepare_real_verifier_route(**inputs) != plan:
        raise ValueError('immutable verifier inputs changed after checks')
    body={'protocol':'SYMPHONY_G62_CI_ATTESTATION_V1','run_id':c.ci.run_id,
        'run_attempt':c.ci.run_attempt,'job_id':c.ci.job_id,'candidate_commit':c.ci.candidate_commit,
        'records':records,**{k:m[k] for k in ('result_digest','source_digest','scope_digest','expected_target_head')}}
    strict={**body,'attestation_digest':digest(body)}
    real=export_real_attestation(plan['binding'],check_attestation_digest=strict['attestation_digest'])
    members={'attestation.json':canonical(strict).encode(),
             'operator-attestation.json':canonical(real).encode()}
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw_member in members.items():
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,raw_member)
    raw=stream.getvalue()
    return {'archive':raw,'archive_sha256':hashlib.sha256(raw).hexdigest(),
            'artifact_members':members,
            'archive_sha256_scope':'LOCAL_BUNDLE_ONLY_PIN_ACTUAL_GITHUB_ARCHIVE_DIGEST_AFTER_UPLOAD_GET',
            'invocations':invocations,'candidate_qualified':False,
            'requires':'Original strict GitHub run/job/artifact GET provenance and OperatorCandidateVerifier.read',
            'publication':0,'model_dispatch':0}
