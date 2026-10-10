"""Bounded official artifact GET and in-memory ZIP inspection; no extraction/write.

Only the first fixed GitHub API request receives credentials. Redirects are
explicitly followed with new credential-free requests. No automatic retries.
The metadata reader is independently configured, never supplied by a worker.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import urllib.error
import urllib.request
import zipfile
from urllib.parse import urlsplit

MAX_ARCHIVE = 16 * 1024 * 1024
MAX_MEMBER = 2 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024
MAX_MEMBERS = 256
MAX_RATIO = 100
MAX_REDIRECTS = 2


class ArchiveUnavailable(RuntimeError):
    """UNKNOWN acquisition or invalid bytes: neither can establish PASS."""


def strict_json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError('duplicate JSON key')
            out[k] = v
        return out
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def inspect_archive(raw: bytes, *, digest: str | None = None, require_attestation=False):
    """Validate every member including hidden extras; return bounded bytes only."""
    if type(raw) is not bytes or len(raw) > MAX_ARCHIVE:
        raise ArchiveUnavailable('archive response over limit/nonbytes')
    if digest is not None and digest != 'sha256:' + hashlib.sha256(raw).hexdigest():
        raise ArchiveUnavailable('archive digest mismatch')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            infos = z.infolist(); names = set(); total = 0; out = {}
            if not infos or len(infos) > MAX_MEMBERS:
                raise ValueError('archive member count')
            for i in infos:
                name = i.filename; parts = name.rstrip('/').split('/')
                if (i.orig_filename != name or not name or name.startswith('/') or '\\' in name
                        or ':' in name or any(p in ('', '.', '..') or p.casefold() == '.git' for p in parts)
                        or any(ord(c) < 32 or ord(c) == 127 for c in name)):
                    raise ValueError('unsafe archive member path')
                # Case aliases cannot become two files on Windows.
                key = name.rstrip('/').casefold()
                if key in names:
                    raise ValueError('duplicate/archive case alias')
                names.add(key)
                mode = i.external_attr >> 16; kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (kind == stat.S_IFDIR) != i.is_dir() and kind:
                    raise ValueError('symlink/special/type mismatch')
                if i.flag_bits & 1 or i.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError('encrypted/unsupported member')
                total += i.file_size
                if (i.file_size > MAX_MEMBER or total > MAX_TOTAL
                        or i.file_size > MAX_RATIO * max(i.compress_size, 1)):
                    raise ValueError('archive decompression limit')
                if i.is_dir():
                    if i.file_size:
                        raise ValueError('directory contains bytes')
                    continue
                # Never extract to disk; check true size + CRC with bounded read.
                with z.open(i) as f:
                    data = f.read(MAX_MEMBER + 1)
                if len(data) != i.file_size or len(data) > MAX_MEMBER:
                    raise ValueError('archive truncated/over limit')
                out[name] = data
            for key in names:
                if any('/'.join(key.split('/')[:n]) in {p.casefold() for p in out}
                       for n in range(1, len(key.split('/')))):
                    raise ValueError('file/directory prefix collision')
            if require_attestation and 'attestation.json' not in out:
                raise ValueError('attestation missing')
            return out
    except (OSError, ValueError, RuntimeError, EOFError, zipfile.BadZipFile, NotImplementedError) as exc:
        raise ArchiveUnavailable('unsafe/incomplete artifact archive') from exc


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _allowed_redirect(url):
    p = urlsplit(url)
    return (p.scheme == 'https' and p.username is None and p.password is None and not p.fragment
            and p.port in (None, 443) and p.hostname is not None
            and (p.hostname.endswith('.blob.core.windows.net')
                 or p.hostname.endswith('.actions.githubusercontent.com')))


class GitHubArtifactArchiveGET:
    """Real GET-only adapter. Token is private and never copied to redirects."""
    def __init__(self, *, repository, metadata_http, token, opener=None):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('fixed repository required')
        self.repository = repository; self.metadata_http = metadata_http
        self.__token = token
        self._opener = opener or urllib.request.build_opener(_NoRedirect())
        self.requests = 0; self.redirects = 0

    def __call__(self, repository, artifact_id):
        if repository != self.repository or type(artifact_id) is not int or artifact_id <= 0:
            raise ArchiveUnavailable('artifact/repository identity mismatch')
        endpoint = f'repos/{self.repository}/actions/artifacts/{artifact_id}'
        status, meta = self.metadata_http.request('GET', endpoint)
        digest = meta.get('digest') if type(meta) is dict else None
        if (status != 200 or type(meta) is not dict or type(meta.get('id')) is not int
                or meta['id'] != artifact_id or meta.get('expired') is not False
                or not isinstance(digest, str) or not re.fullmatch('sha256:[0-9a-f]{64}', digest)
                or type(meta.get('size_in_bytes')) is not int or not 0 < meta['size_in_bytes'] <= MAX_ARCHIVE):
            raise ArchiveUnavailable('official artifact metadata unavailable')
        url = 'https://api.github.com/' + endpoint + '/zip'
        headers = {'Authorization': 'Bearer ' + self.__token, 'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28'}
        try:
            for redirects in range(MAX_REDIRECTS + 1):
                self.requests += 1
                try:
                    response = self._opener.open(urllib.request.Request(url, headers=headers, method='GET'), timeout=30)
                except urllib.error.HTTPError as e:
                    if e.code not in (301, 302, 303, 307, 308) or redirects >= MAX_REDIRECTS:
                        e.close(); raise ArchiveUnavailable('artifact GET/redirect unavailable') from None
                    next_url = e.headers.get('Location', ''); e.close()
                    if not _allowed_redirect(next_url):
                        raise ArchiveUnavailable('artifact redirect rejected')
                    url = next_url; headers = {'Accept': 'application/zip'}
                    self.redirects += 1
                    continue
                with response:
                    if response.status != 200:
                        raise ArchiveUnavailable('artifact incomplete response')
                    length = response.headers.get('Content-Length')
                    if length is not None and (not length.isdecimal() or int(length) > MAX_ARCHIVE):
                        raise ArchiveUnavailable('artifact response size invalid')
                    raw = response.read(MAX_ARCHIVE + 1)
                    if len(raw) > MAX_ARCHIVE or length is not None and len(raw) != int(length):
                        raise ArchiveUnavailable('artifact response truncated/over limit')
                inspect_archive(raw, digest=digest)
                return raw
        except ArchiveUnavailable:
            raise
        except Exception:
            # Do not leak signed URLs, credential headers or exception bodies.
            raise ArchiveUnavailable('artifact acquisition UNKNOWN; no retry') from None
        raise ArchiveUnavailable('artifact redirect limit')
