"""Resume reruns unscored cases without replacing existing scores."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'evals'))
import run_evals


class EvalResumeTests(unittest.TestCase):
    def setUp(self):
        self.config = {'provider': 'groq', 'model': 'test-model',
                       'judge_provider': 'groq', 'judge_model': 'test-model',
                       'max_steps': 8, 'dataset': 'core'}
        self.cases = [{'id': 'E1', 'question': 'q1', 'expected': 'e1'},
                      {'id': 'E2', 'question': 'q2', 'expected': 'e2'}]
        self.saved = {'config': self.config, 'cases': [
            {'id': 'E1', 'result': {'status': 'max_steps', 'answer': '', 'trace': []},
             'grade': {'status': 'scored', 'score': 0}},
            {'id': 'E2', 'result': {'status': 'error', 'trace': []},
             'grade': {'status': 'unscored', 'score': None}}]}
        self.argv = ['run_evals.py', '--provider', 'groq', '--model', 'test-model',
                     '--judge-provider', 'groq', '--judge-model', 'test-model',
                     '--output', 'report.json', '--resume']

    def run_report(self, saved):
        def read(path, *args, **kwargs):
            return json.dumps(self.cases if path.name == 'cases.json' else saved)
        fresh = {'id': 'E2', 'result': {'status': 'completed', 'trace': []},
                 'grade': {'status': 'scored', 'score': 80}}
        with patch.object(run_evals, 'load_env'), patch.object(
                run_evals, 'run_case', return_value=fresh) as execute, patch(
                'pathlib.Path.read_text', autospec=True, side_effect=read), patch(
                'pathlib.Path.write_text', autospec=True) as write, patch(
                'pathlib.Path.replace', autospec=True), patch.object(
                sys, 'argv', self.argv), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = run_evals.main()
        return status, execute, write

    def test_only_unscored_case_reruns_and_zero_score_is_kept(self):
        status, execute, write = self.run_report(self.saved)
        self.assertEqual(status, 0)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0]['id'], 'E2')
        report = json.loads(write.call_args.args[1])
        self.assertEqual(report['cases'][0], self.saved['cases'][0])
        self.assertEqual(report['summary']['score_0_100'], 40)
        self.assertEqual(report['config'], self.config)

    def test_checkpoint_keeps_finished_case_when_next_case_is_interrupted(self):
        cases = self.cases + [{'id': 'E3', 'question': 'q3', 'expected': 'e3'}]
        saved = copy.deepcopy(self.saved)
        saved['cases'].append({'id': 'E3', 'result': {'status': 'error', 'trace': []},
                               'grade': {'status': 'unscored', 'score': None}})
        fresh = {'id': 'E2', 'result': {'status': 'completed', 'trace': []},
                 'grade': {'status': 'scored', 'score': 80}}
        def read(path, *args, **kwargs):
            return json.dumps(cases if path.name == 'cases.json' else saved)
        with patch.object(run_evals, 'load_env'), patch.object(
                run_evals, 'run_case', side_effect=[fresh, KeyboardInterrupt]), patch(
                'pathlib.Path.read_text', autospec=True, side_effect=read), patch(
                'pathlib.Path.write_text', autospec=True) as write, patch(
                'pathlib.Path.replace', autospec=True) as replace, patch.object(
                sys, 'argv', self.argv), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                run_evals.main()
        report = json.loads(write.call_args.args[1])
        self.assertEqual(report['cases'][0], saved['cases'][0])
        self.assertEqual(report['cases'][1], fresh)
        self.assertEqual(report['cases'][2], saved['cases'][2])
        self.assertEqual(report['summary']['scored_cases'], 2)
        self.assertIsNone(report['summary']['score_0_100'])
        replace.assert_called_once()

    def test_different_model_cannot_resume(self):
        saved = copy.deepcopy(self.saved)
        saved['config']['model'] = 'other-model'
        with self.assertRaises(SystemExit) as raised:
            self.run_report(saved)
        self.assertEqual(raised.exception.code, 2)

    def test_different_case_set_cannot_resume(self):
        saved = copy.deepcopy(self.saved)
        saved['cases'][0]['id'] = 'OTHER'
        with self.assertRaises(SystemExit) as raised:
            self.run_report(saved)
        self.assertEqual(raised.exception.code, 2)


    def test_completed_agent_is_only_regraded(self):
        saved = copy.deepcopy(self.saved)
        saved['cases'][1]['result'] = {
            'status': 'completed', 'answer': 'saved answer',
            'trace': [{'event': 'model', 'step': 1, 'finish': 'stop'}], 'usage': []}
        fresh = {**saved['cases'][1], 'grade': {'status': 'scored', 'score': 80}}
        with patch.object(run_evals, 'regrade_case', return_value=fresh) as regrade:
            status, execute, write = self.run_report(saved)
        self.assertEqual(status, 0)
        execute.assert_not_called()
        regrade.assert_called_once()
        report = json.loads(write.call_args.args[1])
        self.assertEqual(report['cases'][1]['result'], saved['cases'][1]['result'])

    def test_regrade_preserves_original_agent_result(self):
        previous = {'id': 'E2', 'result': {
            'status': 'completed', 'answer': 'original answer',
            'trace': [{'event': 'tool', 'name': 'get_status'}], 'usage': [{}]},
            'grade': {'status': 'unscored', 'score': None}}
        grade = {'status': 'scored', 'score': 75}
        with patch.object(run_evals, '_grade_result', return_value=grade) as grading, patch.object(
                run_evals, 'run_agent') as agent:
            updated = run_evals.regrade_case(self.cases[1], None, previous)
        agent.assert_not_called()
        self.assertIs(updated['result'], previous['result'])
        self.assertIs(grading.call_args.args[1], previous['result'])
        self.assertEqual(updated['grade'], grade)
        self.assertIsNone(previous['grade']['score'])



if __name__ == '__main__':
    unittest.main()
