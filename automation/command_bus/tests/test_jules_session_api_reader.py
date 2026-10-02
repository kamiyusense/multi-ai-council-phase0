import json
import unittest
from urllib.error import HTTPError

from automation.command_bus.jules_direct_readback_authenticator import JulesDirectReadbackAuthenticator
from automation.command_bus.jules_session_api_reader import JulesSessionApiReader

SECRET = "SECRET-KEY-VALUE"


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def read(self, n=-1):
        return self.body if n < 0 else self.body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.requests, self.timeouts = resp, exc, [], []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.exc:
            raise self.exc
        return self.resp


def _session(**over):
    data = {
        "name": "sessions/123", "id": "123",
        "createTime": "2026-10-02T00:00:00Z", "updateTime": "2026-10-02T00:01:00Z",
        "state": "IN_PROGRESS",
        "sourceContext": {"source": "sources/github/o/r",
                          "githubRepoContext": {"startingBranch": "b"}},
        "outputs": [{"pullRequest": {"url": "https://github.com/o/r/pull/1"}}],
        "url": "https://jules.google.com/session/123",
    }
    data.update(over)
    return data


def _reader(resp=None, exc=None, key=SECRET):
    opener = _Opener(resp, exc)
    return JulesSessionApiReader(api_key_provider=lambda: key, opener=opener), opener


class JulesSessionApiReaderTests(unittest.TestCase):
    def test_single_get_returns_whitelisted_raw_state(self):
        reader, opener = _reader(_Resp(json.dumps(_session(state="COMPLETED")).encode()))
        got = reader.read_session("123")
        self.assertEqual(got["state"], "COMPLETED")  # raw state, not reinterpreted
        self.assertEqual(got["sourceContext"]["githubRepoContext"]["startingBranch"], "b")
        self.assertNotIn("outputs", got)
        self.assertNotIn("url", got)
        self.assertEqual(len(opener.requests), 1)
        req = opener.requests[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.full_url, "https://jules.googleapis.com/v1alpha/sessions/123")
        self.assertEqual(opener.timeouts, [30])

    def test_fail_closed_cases_return_none_without_retry(self):
        cases = {
            "non-200": _Resp(b"{}", status=500),
            "dup keys": _Resp(b'{"name":"sessions/123","name":"sessions/123"}'),
            "not object": _Resp(b"[]"),
            "bad json": _Resp(b"{"),
            "name mismatch": _Resp(json.dumps(_session(name="sessions/999")).encode()),
            "too large": _Resp(b" " * (1024 * 1024 + 1)),
        }
        for label, resp in cases.items():
            reader, opener = _reader(resp)
            with self.subTest(label):
                self.assertIsNone(reader.read_session("123"))
                self.assertEqual(len(opener.requests), 1)

    def test_transport_errors_and_bad_inputs(self):
        reader, opener = _reader(exc=HTTPError("u", 403, "m", {}, None))
        self.assertIsNone(reader.read_session("123"))
        self.assertEqual(len(opener.requests), 1)
        reader, opener = _reader(_Resp(b"{}"))
        for bad in ("", "abc", "12/3", "١٢٣", None, 123, "1\n2"):
            self.assertIsNone(reader.read_session(bad))
        self.assertEqual(opener.requests, [])
        for bad_key in ("", "a\nb", None):
            reader, opener = _reader(_Resp(b"{}"), key=bad_key)
            self.assertIsNone(reader.read_session("123"))
            self.assertEqual(opener.requests, [])

    def test_credential_never_in_repr(self):
        reader, _ = _reader(_Resp(b"{}"))
        self.assertNotIn(SECRET, repr(reader))
        self.assertNotIn(SECRET, str(reader.__dict__.get("_opener", "")))

    def test_default_opener_blocks_redirects(self):
        from automation.command_bus.jules_session_api_reader import _NoRedirect
        with self.assertRaises(ValueError):
            _NoRedirect().redirect_request(None, None, 302, "m", {}, "http://x")

    def test_fits_existing_authenticator_contract(self):
        """Reader output feeds the existing authenticator (mock target, fixed clock)."""
        from automation.command_bus.tests import test_jules_direct_readback_authenticator as t

        def run(state):
            payload = t.session(state=state)
            reader_for = JulesSessionApiReader(
                api_key_provider=lambda: SECRET,
                opener=_Opener(_Resp(json.dumps(payload).encode())))

            class Target:
                def read_target(self, repo, pr):
                    return t.target()

            class Clock:
                def now(self):
                    return "2026-09-28T04:00:00+00:00"

            auth = JulesDirectReadbackAuthenticator(
                session_reader=reader_for, target_reader=Target(), clock=Clock())
            return auth.authenticate(t.source(), expected=t.expected())

        self.assertIsNotNone(run("IN_PROGRESS"))
        for state in ("COMPLETED", "FAILED", "AWAITING_USER_FEEDBACK"):
            self.assertIsNone(run(state), state)


if __name__ == "__main__":
    unittest.main()
