"""Offline checks for bounded retries and shared Groq pacing."""
import contextlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import providers

URL = 'https://api.groq.com/openai/v1/chat/completions'


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


def response():
    result = MagicMock()
    result.__enter__.return_value = io.BytesIO(b'{"ok": true}')
    return result


def error(code=429, retry_after='2.5'):
    headers = {} if retry_after is None else {'Retry-After': retry_after}
    return urllib.error.HTTPError(URL, code, 'test error', headers, io.BytesIO(b''))


class GroqRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        patches = [
            patch.dict(providers._GROQ_SCHEDULE, {}, clear=True),
            patch.dict(os.environ, {'GROQ_MIN_INTERVAL': '3', 'GROQ_RETRY_BUDGET': '180'}),
            patch('providers.time.monotonic', side_effect=self.clock.monotonic),
            patch('providers.time.sleep', side_effect=self.clock.sleep),
        ]
        for active in patches:
            active.start()
            self.addCleanup(active.stop)
        self.stderr = contextlib.redirect_stderr(io.StringIO())
        self.stderr.__enter__()
        self.addCleanup(self.stderr.__exit__, None, None, None)

    def send(self, url=URL):
        return providers.post_json(url, {'Authorization': 'Bearer dummy'}, {'model': 'test-model'})

    def test_retry_after_is_respected(self):
        with patch('providers.urllib.request.urlopen', side_effect=[error(retry_after='7.5'), response()]) as request:
            self.assertTrue(self.send()['ok'])
        self.assertEqual(request.call_count, 2)
        self.assertGreaterEqual(sum(self.clock.waits), 7.5)

    def test_missing_retry_after_uses_backoff(self):
        with patch('providers.urllib.request.urlopen', side_effect=[error(retry_after=None), response()]):
            self.assertTrue(self.send()['ok'])
        self.assertGreaterEqual(sum(self.clock.waits), 30)

    def test_persistent_429_stops_after_five_attempts(self):
        with patch('providers.urllib.request.urlopen', side_effect=[error(retry_after='1') for _ in range(5)]) as request:
            with self.assertRaises(RuntimeError) as raised:
                self.send()
        self.assertEqual(request.call_count, 5)
        self.assertEqual(raised.exception.__cause__.code, 429)

    def test_daily_length_wait_does_not_retry_early(self):
        with patch('providers.urllib.request.urlopen', side_effect=error(retry_after='86400')) as request:
            with self.assertRaises(RuntimeError):
                self.send()
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.clock.waits, [])

    def test_long_wait_can_be_enabled_explicitly(self):
        with patch.dict(os.environ, {'GROQ_RETRY_BUDGET': '7200'}), patch(
                'providers.urllib.request.urlopen', side_effect=[error(retry_after='417'), response()]):
            self.assertTrue(self.send()['ok'])
        self.assertGreaterEqual(sum(self.clock.waits), 417)

    def test_invalid_retry_budget_is_rejected_before_request(self):
        for value in ('0', '-1', 'nan', 'inf', 'bad'):
            with self.subTest(value=value), patch.dict(os.environ, {'GROQ_RETRY_BUDGET': value}), patch(
                    'providers.urllib.request.urlopen') as request:
                with self.assertRaises(ValueError):
                    self.send()
                request.assert_not_called()

    def test_bad_request_is_not_retried(self):
        with patch('providers.urllib.request.urlopen', side_effect=error(code=400)) as request:
            with self.assertRaises(RuntimeError):
                self.send()
        self.assertEqual(request.call_count, 1)

    def test_other_providers_keep_existing_retry_policy(self):
        with patch('providers.urllib.request.urlopen', side_effect=error()) as request:
            with self.assertRaises(RuntimeError):
                self.send('https://api.openai.com/v1/chat/completions')
        self.assertEqual(request.call_count, 1)

    def test_pacing_is_shared_across_calls(self):
        with patch('providers.urllib.request.urlopen', side_effect=[response(), response()]):
            self.send()
            self.send()
        self.assertGreaterEqual(sum(self.clock.waits), 3)


if __name__ == '__main__':
    unittest.main()
