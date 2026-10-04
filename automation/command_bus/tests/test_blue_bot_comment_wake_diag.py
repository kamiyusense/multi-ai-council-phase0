"""Fake-only tests for the inert bot comment wake diagnostic."""
import json
import tempfile
import unittest
from pathlib import Path

from automation.command_bus import blue_bot_comment_wake_diag as diag
from automation.command_bus.github_readonly import ReadResponse

ID = 'blue-wake-diag-20261004T110000Z-01'
PR = {'number': 167, 'state': 'open', 'merged': False, 'labels': [{'name': 'cloud-blue'}], 'head': {'sha': 'a' * 40}}


class Reader:
    def __init__(self, comments=(), pr=PR):
        self.comments, self.pr = list(comments), pr

    def get(self, url):
        if url.endswith('/pulls/167'):
            return ReadResponse(self.pr, {})
        return ReadResponse([{'id': i + 1, 'body': b} for i, b in enumerate(self.comments)], {})


class Poster:
    def __init__(self, fail=False):
        self.calls, self._used, self.fail = [], False, fail

    def post(self, body):
        self.calls.append(body)
        self._used = True
        if self.fail:
            raise TimeoutError('timeout')
        return {'id': 9, 'user': {'login': 'github-actions[bot]'}, 'created_at': 'x'}


class Tests(unittest.TestCase):
    def go(self, reader, poster, diag_id=ID):
        with tempfile.TemporaryDirectory() as d:
            return diag.run(reader, poster, diag_id, Path(d) / 'r.json')

    def test_posts_once_inert(self):
        p = Poster()
        r = self.go(Reader(), p)
        self.assertEqual(r['status'], 'POSTED_UNVERIFIED')
        self.assertEqual(len(p.calls), 1)
        self.assertTrue(p.calls[0].startswith('[BLUE_BOT_COMMENT_WAKE_DIAGNOSTIC_V1]\n'))
        self.assertFalse(p.calls[0].startswith('[CW_BLUE'))
        json.loads(p.calls[0].split('\n', 1)[1])

    def test_blocks_before_post(self):
        for reader in (Reader(comments=[diag.DIAG_PREFIX + '\nold']), Reader(comments=['x ' + ID]),
                       Reader(pr={**PR, 'state': 'closed'}), Reader(pr={**PR, 'labels': []})):
            p = Poster()
            self.assertEqual(self.go(reader, p)['status'], 'STOPPED_BEFORE_POST')
            self.assertEqual(p.calls, [])

    def test_bad_id(self):
        p = Poster()
        self.assertEqual(self.go(Reader(), p, 'bad')['status'], 'STOPPED_BEFORE_POST')
        self.assertEqual(p.calls, [])

    def test_failed_post_unknown_no_resend(self):
        p = Poster(fail=True)
        self.assertEqual(self.go(Reader(), p)['status'], 'STOPPED_UNKNOWN')
        self.assertEqual(len(p.calls), 1)

    def test_post_budget(self):
        c = diag.CommentPostOnce('t')
        c._used = True
        with self.assertRaises(ValueError):
            c.post(diag.body_for(ID))
        with self.assertRaises(ValueError):
            diag.CommentPostOnce('t').post('[CW_BLUE_V1]\nx')


if __name__ == '__main__':
    unittest.main()
