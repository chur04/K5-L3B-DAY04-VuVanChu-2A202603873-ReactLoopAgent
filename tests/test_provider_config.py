"""Offline checks for Groq requests and local configuration."""
import contextlib
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from providers import Provider, load_env
from status_tools import SCHEMAS


class ProviderConfigTests(unittest.TestCase):
    def test_groq_preserves_tool_call_protocol(self):
        message = {
            'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'groq-call', 'type': 'function', 'function': {
                'name': 'get_status', 'arguments': '{"provider":"github"}'}}],
        }
        response = {'choices': [{'message': message, 'finish_reason': 'tool_calls'}],
                    'usage': {'total_tokens': 10}}
        with patch.dict(os.environ, {'GROQ_API_KEY': 'dummy'}), patch(
                'providers.post_json', return_value=response) as post:
            result = Provider('groq', 'test-model').complete(
                [{'role': 'user', 'content': 'Check GitHub'}], SCHEMAS)
        self.assertEqual(post.call_args.args[0], 'https://api.groq.com/openai/v1/chat/completions')
        self.assertEqual(post.call_args.args[2]['tools'], SCHEMAS)
        self.assertIs(result['message'], message)
        self.assertEqual(result['calls'][0]['id'], 'groq-call')
        self.assertEqual(result['calls'][0]['arguments'], '{"provider":"github"}')

    def test_env_quotes_export_and_process_priority(self):
        contents = ("# comment\nexport PROVIDER=groq\nMODEL='model-name'\n"
                    'GROQ_API_KEY="dummy=key"\nEXTRA=value # comment\n')
        with patch.dict(os.environ, {'MODEL': 'terminal-model'}, clear=True), patch(
                'providers.Path.is_file', return_value=True), patch(
                'providers.Path.read_text', return_value=contents):
            load_env('unused.env')
            self.assertEqual(os.environ['PROVIDER'], 'groq')
            self.assertEqual(os.environ['MODEL'], 'terminal-model')
            self.assertEqual(os.environ['GROQ_API_KEY'], 'dummy=key')
            self.assertEqual(os.environ['EXTRA'], 'value')

    def test_missing_env_is_optional(self):
        with patch('providers.Path.is_file', return_value=False), patch(
                'providers.Path.read_text') as read:
            load_env('missing.env')
        read.assert_not_called()

    def test_run_cli_accepts_groq(self):
        import run
        result = {'status': 'completed', 'answer': 'ok', 'trace': [], 'usage': []}
        with patch.object(run, 'load_env'), patch.object(run, 'run', return_value=result) as execute, patch.object(
                sys, 'argv', ['run.py', '--provider', 'groq', '--model', 'test-model', 'question']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.main(), 0)
        self.assertEqual(execute.call_args.args[2:4], ('groq', 'test-model'))


if __name__ == '__main__':
    unittest.main()
