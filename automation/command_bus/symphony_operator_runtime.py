"""Explicit installation adapters; NOT ACTIVATED, no CLI or credential discovery.

Trusted future jobs inject immutable review/source pins and approved memory-only
credentials. Import/construction performs no request, token issuance or write.
Existing attach_same_job, candidate verifier, stores and CAS own the lifecycle.
No candidate-controlled configuration, env token lookup or generic worker API.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener

from .symphony_github_adapter import GitHubExecutorContentsClient
from .symphony_github_readers import API, _NoRedirect
from .symphony_g63_archive import strict_json
from .symphony_operator_sender import PROTOCOL
from .symphony_result_manifest import SHA, DIGEST, canonical, digest, safe_branch, safe_path
from .symphony_git_adoption import _git_oid

REPOSITORY = 'kamiyusense/multi-ai-council-phase0'
MAX_JSON = 2 * 1024 * 1024


@dataclass(frozen=True)
class RuntimePins:
    source_commit: str
    workflow_id: int
    workflow_path: str
    run_id: int
    job_id: int
    actor_id: str
    review_path: str
    review_sha256: str

    def validate(self):
        if (not SHA.fullmatch(self.source_commit or '')
                or any(type(x) is not int or x <= 0 for x in (self.workflow_id,self.run_id,self.job_id))
                or type(self.actor_id) is not str or not self.actor_id.isdigit()
                or self.workflow_path != '.github/workflows/symphony-operator-authorize.yml'
                or not safe_path(self.review_path) or not self.review_path.startswith('operator_reviews/')
                or not DIGEST.fullmatch(self.review_sha256 or '')):
            raise PermissionError('independently installed immutable runtime pins required')


class IndependentReviewReader:
    """Read exact canonical unsigned bytes from separately reviewed source pin.

    Pins are installed trusted-job configuration, never workflow inputs. A file
    in a candidate/PR comment, matching self-hash, or actor ADMIN is not approval.
    This reader alone is not signature validation; attach_same_job owns that.
    """
    def __init__(self, *, http, pins):
        if type(pins) is not RuntimePins:
            raise PermissionError('trusted runtime pins required')
        pins.validate();self._http,self._pins = http,pins

    def read(self):
        p=self._pins
        try:
            status,body=self._http.request('GET',f'repos/{REPOSITORY}/contents/{quote(p.review_path,safe="/")}?ref={p.source_commit}')
            raw=base64.b64decode(body['content'].replace('\n',''),validate=True)
            envelope=strict_json(raw)
            if (status != 200 or body.get('type') != 'file' or body.get('path') != p.review_path
                    or body.get('encoding') != 'base64' or len(raw)>128*1024
                    or _git_oid('blob',raw) != body.get('sha')
                    or hashlib.sha256(raw).hexdigest() != p.review_sha256
                    or type(envelope) is not dict or set(envelope) != {'protocol','issuer','key_id','payload'}
                    or envelope['protocol'] != PROTOCOL or canonical(envelope).encode()!=raw):
                raise ValueError('review mismatch')
            return raw
        except Exception:
            raise PermissionError('independent reviewed intention unavailable') from None


class GitHubJobContextReader:
    """Fresh REST run/job/workflow/repository/main readback, never env identity."""
    def __init__(self, *, http, pins):
        if type(pins) is not RuntimePins:raise PermissionError('runtime pins required')
        pins.validate();self._http,self._pins=http,pins

    def read(self):
        p=self._pins;root=f'repos/{REPOSITORY}'
        def get(path):
            status,body=self._http.request('GET',root+('/'+path if path else ''))
            if status != 200 or type(body) is not dict:raise PermissionError('fresh job context unavailable')
            return body
        try:
            repo=get('');run=get(f'actions/runs/{p.run_id}');job=get(f'actions/jobs/{p.job_id}')
            workflow=get(f'actions/workflows/{p.workflow_id}');main=get('git/ref/heads/main')
            if (repo.get('full_name') != REPOSITORY or repo.get('default_branch') != 'main'
                    or repo.get('archived') is not False
                    or run.get('id') != p.run_id or run.get('workflow_id') != p.workflow_id
                    or run.get('event') != 'workflow_dispatch' or run.get('head_branch') != 'main'
                    or run.get('head_sha') != p.source_commit or run.get('run_attempt') != 1
                    or type(run.get('run_attempt')) is not int
                    or run.get('status') != 'in_progress'
                    or run.get('actor',{}).get('id') != int(p.actor_id)
                    or run.get('triggering_actor',{}).get('id') != int(p.actor_id)
                    or job.get('id') != p.job_id or job.get('run_id') != p.run_id
                    or job.get('head_sha') != p.source_commit or job.get('status') != 'in_progress'
                    or workflow.get('id') != p.workflow_id or workflow.get('path') != p.workflow_path
                    or main.get('ref') != 'refs/heads/main'
                    or main.get('object',{}).get('type') != 'commit'
                    or main.get('object',{}).get('sha') != p.source_commit
                    or type(repo.get('id')) is not int or type(repo.get('owner',{}).get('id')) is not int):
                raise ValueError('job source/identity mismatch')
            return {'repository':REPOSITORY,'repository_id':str(repo['id']),
                'repository_owner_id':str(repo['owner']['id']),'actor_id':p.actor_id,
                'event_name':'workflow_dispatch','ref':'refs/heads/main','sha':p.source_commit,
                'workflow_sha':p.source_commit,'workflow_ref':REPOSITORY+'/'+p.workflow_path+'@refs/heads/main',
                'run_id':str(p.run_id),'run_attempt':'1'}
        except Exception:
            raise PermissionError('independent main job context unavailable') from None


class MemoryOnlyOIDCRequest:
    """One explicit same-job request; request bearer and returned JWT stay memory.

    The future reviewed job injects its platform request URL/token. No env/argv
    lookup, token cache, refresh, fallback, retry or evidence logger exists here.
    Unknown write/issuance result consumes this instance; durable issuer intent
    in attach_same_job prevents another instance from issuing the same approval.
    """
    def __init__(self, *, request_url, request_token, context_reader, expected_context):
        u=urlsplit(request_url)
        if (u.scheme!='https' or u.port not in (None,443) or u.username or u.password or u.fragment
                or not u.hostname or not u.hostname.endswith('.actions.githubusercontent.com')
                or any(k.lower()=='audience' for k,v in parse_qsl(u.query))
                or type(request_token) is not str or not request_token
                or any(ord(c)<33 or ord(c)>126 for c in request_token)
                or type(context_reader) is not GitHubJobContextReader or type(expected_context) is not dict):
            raise PermissionError('explicit approved same-job OIDC request source required')
        self._url,self._token,self._reader,self._expected=request_url,request_token,context_reader,copy.deepcopy(expected_context)
        self._attempted=set();self._pid=os.getpid();self._lock=threading.Lock()

    def __repr__(self):return 'MemoryOnlyOIDCRequest(<redacted>, once-only)'

    def __call__(self,audience):
        try:
            if (type(audience) is not str or not re.fullmatch(r'urn:symphony:operator-direct-authorization-v1:sha256:[0-9a-f]{64}',audience)
                    or self._reader.read()!=self._expected):
                raise ValueError('fresh same-job audience/context required')
            with self._lock:
                if self._attempted or self._pid!=os.getpid():raise ValueError('issuance already attempted')
                self._attempted.add("issuance")
            u=urlsplit(self._url);query=parse_qsl(u.query)+[('audience',audience)]
            url=urlunsplit((u.scheme,u.netloc,u.path,urlencode(query),'') )
            req=Request(url,headers={'Authorization':'Bearer '+self._token},method='GET')
            with build_opener(_NoRedirect()).open(req,timeout=15) as reply:
                if reply.status!=200:raise ValueError('issuance status unknown')
                raw=reply.read(16385)
            if len(raw)>16384:raise ValueError('issuance over limit')
            body=strict_json(raw);token=body.get('value')
            if type(token) is not str or not 0<len(token)<=8192:raise ValueError('JWT missing')
            # Signature/claims are verified immediately by existing same-job
            # attachment. Never export or log this JWT; no authority by itself.
            return token
        except Exception:
            raise PermissionError('OIDC issuance unavailable; GET-only recovery') from None


class _MemoryJSONHTTP:
    def __init__(self,token):
        if type(token) is not str or not token or any(ord(c)<33 or ord(c)>126 for c in token):
            raise PermissionError('explicit memory-only approved credential required')
        self._token=token

    def send(self,method,path,body=None):
        try:
            data=canonical(body).encode() if body is not None else None
            req=Request(API+'/'+path,method=method,data=data,headers={
                'Authorization':'Bearer '+self._token,'Accept':'application/vnd.github+json',
                'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json'})
            try:
                with build_opener(_NoRedirect()).open(req,timeout=30) as reply:
                    status,raw=reply.status,reply.read(MAX_JSON+1)
            except HTTPError as exc:
                status,raw=exc.code,exc.read(MAX_JSON+1) if exc.fp else b''
            if len(raw)>MAX_JSON:raise ValueError('over limit')
            return status,strict_json(raw) if raw else None
        except Exception:
            raise PermissionError('bounded GitHub operation outcome unknown; read back only') from None


class ScopedOperatorLedgerClient(GitHubExecutorContentsClient):
    """Create-only at installed nondefault namespaces; no update/lookup defaults.

    This is an approved operator credential seam, never worker-accessible. Token
    rights remain repo-scoped; this application allowlist is not GitHub rules.
    """
    def __init__(self,*,token,branch,default_branch,namespaces):
        if (not safe_branch(branch,default_branch) or type(namespaces) is not tuple or not namespaces
                or any(not safe_path(n.rstrip('/')) for n in namespaces)):
            raise PermissionError('installed exact nondefault ledger scope required')
        super().__init__(token,REPOSITORY);self.branch=branch;self._namespaces=namespaces
        self._io=_MemoryJSONHTTP(token);self._attempted=set();self._lock=threading.Lock();self._pid=os.getpid()

    def __repr__(self):return 'ScopedOperatorLedgerClient(<redacted>, create-only)'

    def _scope(self,path):
        if not safe_path(path) or not any(path.startswith(n) if n.endswith('/') else path==n for n in self._namespaces):
            raise PermissionError('outside installed ledger scope')

    def _request(self,method,path,body=None):
        prefix,sep,query=path.partition('?');self._scope(unquote(prefix.removeprefix('contents/')))
        if not prefix.startswith('contents/'):raise PermissionError('Contents only')
        if method=='GET':
            if body is not None or dict(parse_qsl(query))!={'ref':self.branch}:raise PermissionError('exact branch GET only')
        elif method=='PUT':
            if (sep or type(body) is not dict or set(body)!={'branch','message','content'}
                    or body['branch']!=self.branch or len(body['content'])>2*1024*1024):
                raise PermissionError('create only; no sha/update')
            with self._lock:
                if self._pid!=os.getpid() or path in self._attempted:raise PermissionError('ambiguous create never resent')
                self._attempted.add(path)
        else:raise PermissionError('ledger write method refused')
        return self._io.send(method,f'repos/{REPOSITORY}/'+path,body)

    def get(self,path,ref):
        value=super().get(path,ref)
        if value is not None and _git_oid('blob',value.text.encode())!=value.sha:
            raise PermissionError('ledger blob hash conflict')
        return value

    def update(self,*args,**kwargs):raise PermissionError('create-only ledger; update forbidden')


class ReviewedNarrowCapabilityFactory:
    """Explicit operator factory; no default token acquisition or auto-send.

    Plan/claims already independently verified by attach_same_job. Reviewed
    installation also supplies the credential callback and effective permission
    assertion; schema/metadata alone cannot establish those platform permissions.
    The factory is unreachable from OFF workflows and never exposed to workers.
    """
    def __init__(self,*,plan,credential_callback,permission_check):
        if not callable(credential_callback) or not callable(permission_check):
            raise PermissionError('approved credential and independent permission callbacks required')
        self._plan=copy.deepcopy(plan);self._credential=credential_callback;self._permissions=permission_check

    def __call__(self,claims):
        if (type(claims) is not dict or claims.get('plan_digest')!=self._plan.get('plan_digest')
                or digest(self._plan.get('object_requests'))!=claims.get('objects_digest')
                or claims.get('single_update_refs')!=self._plan.get('single_ref_request')
                or claims.get('max_ref_updates')!=1 or type(claims.get('max_ref_updates')) is not int
                or claims.get('force') is not False or claims.get('other_mutations')!=[]
                or self._permissions(copy.deepcopy(claims)) is not True):
            raise PermissionError('independent approved plan/permissions unavailable')
        return _NarrowCapability(claims=claims,plan=self._plan,token=self._credential())


class _NarrowCapability:
    def __init__(self,*,claims,plan,token):
        self._claims,self._plan=copy.deepcopy(claims),copy.deepcopy(plan);self._io=_MemoryJSONHTTP(token)
        self._attempts=set();self._pid=os.getpid();self._lock=threading.Lock()
        b=claims['candidate_binding']
        if (b['repository']!=REPOSITORY or not safe_branch(b['target_branch'],b['default_branch'])
                or not safe_branch(b['ledger_branch'],b['default_branch']) or b['target_branch']==b['ledger_branch']):
            raise PermissionError('exact distinct nondefault refs required')
        namespaces=tuple(n.get('exact_path') or n['path_prefix']
            for n in claims['allowed_ledger_namespaces']
            if n['branch']==b['ledger_branch'] and n['create_only'] is True)
        self._ledger=ScopedOperatorLedgerClient(token=token,branch=b['ledger_branch'],
            default_branch=b['default_branch'],namespaces=namespaces)

    def __repr__(self):return 'OperatorNarrowCapability(<redacted>, no generic client)'

    def post_exact_objects(self,repository,requests):
        if repository!=REPOSITORY or requests!=self._plan['object_requests']:raise PermissionError('exact reviewed inventory only')
        with self._lock:
            if self._pid!=os.getpid() or 'objects' in self._attempts:raise PermissionError('objects already attempted; readback only')
            self._attempts.add('objects')
        root='git/'
        if any(req['method']!='POST' or req['path'] not in (root+'blobs',root+'trees',root+'commits') for req in requests):
            raise PermissionError('fixed object method/path only')
        for req in requests:
            status,reply=self._io.send('POST',f'repos/{REPOSITORY}/'+req['path'],req['body'])
            if status!=201 or type(reply) is not dict or reply.get('sha')!=req['expected_oid']:
                raise PermissionError('object response unknown; GET-only recovery')

    def update_exact_ref(self,repository,request):
        if repository!=REPOSITORY or request!=self._plan['single_ref_request']:raise PermissionError('exact reviewed CAS only')
        update=request['variables']['input']['refUpdates']
        b=self._claims['candidate_binding']
        if (len(update)!=1 or update[0].get('force') is not False
                or update[0].get('name')!='refs/heads/'+b['target_branch']
                or update[0].get('beforeOid')!=b['expected_target_head']
                or update[0].get('afterOid')!=b['candidate_commit']):
            raise PermissionError('one nondefault expected-head force:false update only')
        with self._lock:
            if self._pid!=os.getpid() or 'ref' in self._attempts:raise PermissionError('CAS already attempted; readback only')
            self._attempts.add('ref')
        return self._io.send('POST','graphql',{'query':request['document'],'variables':request['variables']})

    def create_ledger_record(self,repository,branch,path,text,message):
        b=self._claims['candidate_binding'];names=[]
        for n in self._claims['allowed_ledger_namespaces']:
            if n['branch']==branch and n['create_only'] is True:names.append(n.get('exact_path') or n['path_prefix'])
        if repository!=REPOSITORY or branch!=b['ledger_branch'] or not names:raise PermissionError('signed nondefault ledger only')
        # A single client is constructed before calls, preventing concurrent
        # lazy allocation from discarding the once-only create fence.
        return self._ledger.create(path,text,message,branch)


def attach_reviewed_runtime(*, pins, read_http, requested_unsigned, token_once,
                            signature_verifier, transport_inputs, now):
    """Connect existing same-job attachment to independently pinned real GETs.

    No default runtime/credential, activation flag, stage, dispatch or publisher.
    Tokens are acquired only after the original schema/nonce/intent/rules gates.
    """
    from .symphony_operator_installation import attach_same_job
    reviewed=IndependentReviewReader(http=read_http,pins=pins).read()
    context=GitHubJobContextReader(http=read_http,pins=pins).read()
    return attach_same_job(requested_unsigned=requested_unsigned,reviewed_unsigned=reviewed,
        signature_verifier=signature_verifier,token_once=token_once,
        transport_inputs=transport_inputs,job_context=context,now=now)


class PinnedVerifierExecutor:
    """Bounded local executor for an explicitly reviewed verification-only job.

    Derives its sole allowlist from the existing authenticated source/snapshot
    route, revalidates immutable inputs on every call, and runs cached pinned
    Docker images offline. No candidate command, token, upload or dispatch API.
    Construction grants no CI/operator authority; installation owns invocation.
    """
    def __init__(self, *, route_inputs, timeout_seconds=120):
        from .symphony_operator_verifier_route import prepare_real_verifier_route
        if type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=600:
            raise ValueError('bounded verification timeout required')
        self._inputs=dict(route_inputs);self._timeout=timeout_seconds
        self._plan=prepare_real_verifier_route(**self._inputs)
        c=self._plan['commands']
        self._commands=tuple(tuple(x) for x in [c['syntax'],*c['tests'],c['secret_scan']])
        self._pid=os.getpid()

    def __call__(self, argv):
        from tempfile import TemporaryFile
        from .symphony_operator_verifier_route import prepare_real_verifier_route
        from .symphony_subscription_boundary import subscription_worker_environment
        if (type(argv) is not tuple or argv not in self._commands or self._pid!=os.getpid()
                or prepare_real_verifier_route(**self._inputs)!=self._plan):
            raise PermissionError('exact immutable operator-derived verifier command required')
        try:
            # File capture prevents candidate output from growing Python memory.
            # Only <=2 MiB bytes may reach the existing digest-only emitter.
            with TemporaryFile() as out, TemporaryFile() as err:
                reply=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                    timeout=self._timeout,check=False,
                    env=subscription_worker_environment(dict(os.environ)))
                out.seek(0);err.seek(0);stdout=out.read(MAX_JSON+1);stderr=err.read(MAX_JSON+1)
            if len(stdout)>MAX_JSON or len(stderr)>MAX_JSON:
                raise ValueError('verifier output over limit')
            return {'returncode':reply.returncode,'stdout':stdout,'stderr':stderr}
        except Exception:
            raise PermissionError('bounded independent verifier failed; no attestation') from None
