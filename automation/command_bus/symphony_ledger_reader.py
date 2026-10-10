"""Pinned GitHub ledger recovery reads; no observer/sender activation.

Reuse the existing Contents protocol/decoder and authenticated GET transport.
The original stores validate their own record/lineage schemas. This adapter
checks immutable ref, scope, object bytes and complete bounded directory reads.
"""
from urllib.parse import quote, unquote

from .symphony_github_adapter import GitHubExecutorContentsClient
from .symphony_git_adoption import _git_oid
from .symphony_result_manifest import SHA, safe_branch, safe_path


class ReadOnlyLedgerContentsClient(GitHubExecutorContentsClient):
    """get/list at one operator-pinned commit; every mutation fails locally.

    ``http`` must be operator-owned (production: ReadOnlyGitHubHttp). No token
    factory, worker input, retry or automatic refresh exists here. A fresh
    instance requires a fresh branch readback. Branch metadata is not authority.
    """
    ROOTS = frozenset({'symphony_attempts', 'symphony_campaigns', 'symphony_adoptions'})

    def __init__(self, http, *, repository, branch, default_branch, expected_head):
        import re
        if (not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository)
                or not isinstance(default_branch, str) or not default_branch
                or not safe_branch(branch, default_branch) or not SHA.fullmatch(expected_head or '')):
            raise ValueError('pinned non-default ledger identity required')
        self._http, self.repository, self.branch, self.head = http, repository, branch, expected_head
        status, repo = http.request('GET', f'repos/{repository}')
        if (status != 200 or type(repo) is not dict or repo.get('full_name') != repository
                or repo.get('default_branch') != default_branch):
            raise RuntimeError('ledger repository/default identity unavailable')
        status, ref = http.request('GET', f'repos/{repository}/git/ref/heads/{quote(branch, safe="/")}')
        if (status != 200 or type(ref) is not dict or ref.get('ref') != 'refs/heads/' + branch
                or ref.get('object', {}).get('type') != 'commit' or ref['object'].get('sha') != expected_head):
            raise RuntimeError('ledger HEAD differs from fresh operator pin')

    def _scope(self, path, ref, *, directory=False):
        stripped = path.rstrip('/') if directory and isinstance(path, str) else path
        if (ref not in (self.branch, self.head) or not safe_path(stripped)
                or stripped.split('/')[0] not in self.ROOTS):
            raise ValueError('ledger read outside pinned ref/scope')
        return stripped

    def _request(self, method, path, body=None):
        if method != 'GET' or body is not None:
            raise PermissionError('ledger client has no write capability')
        prefix, sep, ref = path.partition('?ref=')
        if not sep or not prefix.startswith('contents/') or unquote(ref) != self.head:
            raise ValueError('immutable ledger Contents GET required')
        self._scope(unquote(prefix[len('contents/'):]), self.head, directory=True)
        status, result = self._http.request('GET', f'repos/{self.repository}/{path}')
        # Contents directories have a 1000-entry ceiling: never treat the cap
        # as complete or automatically move to a less constrained transport.
        if type(result) is list:
            root = unquote(prefix[len('contents/'):]).rstrip('/') + '/'
            if (len(result) >= 1000 or any(type(x) is not dict or x.get('type') not in {'file', 'dir'}
                    or type(x.get('path')) is not str or not x['path'].startswith(root)
                    or '/' in x['path'][len(root):] or not x['path'][len(root):] for x in result)
                    or len({x['path'] for x in result}) != len(result)):
                raise RuntimeError('ledger directory completeness unavailable')
        return status, result

    def get(self, path, ref):
        self._scope(path, ref)
        found = super().get(path, self.head)
        if found is not None and _git_oid('blob', found.text.encode('utf-8')) != found.sha:
            raise RuntimeError('ledger blob bytes do not hash to OID')
        return found

    def list(self, prefix, ref):
        prefix = self._scope(prefix, ref, directory=True)
        items = super().list(prefix, self.head)
        if (len({x.path for x in items}) != len(items)
                or any(not x.path.startswith(prefix + '/') for x in items)):
            raise RuntimeError('ledger listing escaped prefix or repeated path')
        return items

    def create(self, *args, **kwargs):
        raise PermissionError('read-only ledger: create refused')

    def update(self, *args, **kwargs):
        raise PermissionError('read-only ledger: update refused')
