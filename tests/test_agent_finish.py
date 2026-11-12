"""Do not execute calls from interrupted or unsupported model responses."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent
from status_tools import StatusTools
from test_lab import FakeProvider, tool_call


class InterruptedResponseTests(unittest.TestCase):
    def test_abnormal_finish_never_executes_tool_calls(self):
        for finish in ('length', 'content_filter', 'unknown'):
            with self.subTest(finish=finish):
                response = tool_call('interrupted', 'get_status', '{"provider":"github"}')
                response['finish'] = finish
                tools = StatusTools()
                with patch.object(tools, 'execute') as execute:
                    result = run_agent('Check GitHub', FakeProvider([response]), tools, max_steps=1)
                self.assertEqual(result['status'], 'error')
                execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
