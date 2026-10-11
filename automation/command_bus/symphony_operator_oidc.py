"""Offline GitHub OIDC adapter for the existing operator envelope verifier.

GitHub's signed aud must cover the DOMAIN + exact canonical envelope bytes.
The existing Signal identity-only audience is never send authority. An approved
main issuer workflow must request this exact digest audience for one reviewed
operator payload; this adapter neither requests tokens nor installs that issuer.
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from .github_oidc_claims_policy import GitHubOidcExpectedContext, evaluate_github_oidc_claims_policy
from .symphony_g63_archive import strict_json
from .symphony_operator_candidate import clock
from .symphony_operator_sender import DOMAIN, PROTOCOL
from .symphony_result_manifest import canonical

ISSUER = 'https://token.actions.githubusercontent.com'
AUDIENCE_PREFIX = 'urn:symphony:operator-direct-authorization-v1:sha256:'
_HELPER = Path(__file__).with_name('symphony_operator_oidc_signature.mjs')


def authorization_audience(signed):
    if type(signed) is not bytes or not signed.startswith(DOMAIN) or len(signed) > 128 * 1024:
        raise ValueError('bounded domain-separated authorization required')
    return AUDIENCE_PREFIX + hashlib.sha256(signed).hexdigest()


class GitHubOIDCEnvelopeSignatureVerifier:
    """Operator injects PUBLIC issuer metadata/JWKS and exact reviewed context.

    No network, signer, key generation, credential lookup or token persistence.
    This callable is only the signature component of OperatorEnvelopeVerifier:
    original envelope expiry + durable nonce/fence gates still own send/replay.
    Historical signatures may authenticate already-fenced GET-only recovery.
    """
    def __init__(self, *, issuer, key_id, context, actor_id, metadata, jwks, now,
                 node_executable='/usr/bin/node'):
        if (type(context) is not GitHubOidcExpectedContext or not callable(now)
                or context.event_name != 'workflow_dispatch' or context.ref != 'refs/heads/main'
                or context.sha != context.workflow_sha
                or not context.workflow_ref.startswith(context.repository + '/.github/workflows/')
                or not context.workflow_ref.endswith('@refs/heads/main')
                or context.job_workflow_ref is not None
                or type(actor_id) is not str or not actor_id.isdigit()
                or not Path(node_executable).is_absolute()):
            raise ValueError('operator-pinned manual main issuer context required')
        if (type(metadata) is not dict or metadata.get('issuer') != ISSUER
                or metadata.get('jwks_uri') != ISSUER + '/.well-known/jwks'
                or 'RS256' not in metadata.get('id_token_signing_alg_values_supported', [])):
            raise ValueError('independently acquired GitHub issuer metadata required')
        if (type(jwks) is not dict or type(jwks.get('keys')) is not list
                or not 0 < len(jwks['keys']) <= 64
                or any(type(k) is not dict or set(k) & {'d','p','q','dp','dq','qi','oth','k'}
                       for k in jwks['keys'])):
            raise ValueError('public issuer JWKS only; private key input prohibited')
        self.issuer, self.key_id, self.context, self.actor_id = issuer, key_id, context, actor_id
        self._metadata, self._jwks = copy.deepcopy(metadata), copy.deepcopy(jwks)
        self.now, self.node = now, node_executable

    def __call__(self, issuer, key_id, signed, token):
        try:
            if (issuer, key_id) != (self.issuer, self.key_id):
                return False
            audience = authorization_audience(signed)
            e = strict_json(signed[len(DOMAIN):])
            if (type(e) is not dict or set(e) != {'protocol','issuer','key_id','payload'}
                    or e['protocol'] != PROTOCOL
                    or (e['issuer'], e['key_id']) != (issuer, key_id)
                    or DOMAIN + canonical(e).encode() != signed
                    or type(token) is not str or not 0 < len(token) <= 32768):
                return False
            # Token and public keys travel in stdin only. No shell/env/argv secret.
            child = subprocess.run([self.node, str(_HELPER)],
                input=canonical({'token': token, 'metadata': self._metadata, 'jwks': self._jwks}),
                capture_output=True, encoding='utf-8', errors='strict', timeout=10,
                env={}, check=False)
            if child.returncode != 0 or child.stderr or len(child.stdout) > 16384:
                return False
            result = strict_json(child.stdout.encode())
            if set(result) != {'verified_claims'}:
                return False
            claims = result['verified_claims']
            now_epoch = int(clock(self.now()).timestamp())
            # Verification of an old signature is not a new send authorization.
            # Outer envelope expiry (bounded by exp below) prevents expired sends.
            historical_now = min(now_epoch, claims['exp'] - 1)
            expected = replace(self.context, audience=audience)
            decision = evaluate_github_oidc_claims_policy(claims, expected, now_epoch=historical_now)
            p = e['payload']
            issued, expires = clock(p['issued_at']).timestamp(), clock(p['expires_at']).timestamp()
            return (decision.status == 'MATCH' and claims.get('actor_id') == self.actor_id
                    and 0 < claims['exp'] - claims['iat'] <= 600
                    and issued <= claims['iat'] < expires <= claims['exp']
                    and 0 < expires - issued <= 600)
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, UnicodeError):
            return False
