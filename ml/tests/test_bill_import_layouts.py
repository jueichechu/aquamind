import asyncio
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

SCRIPT = Path(__file__).resolve().parents[2] / 'evals/bill_import_layouts.py'
spec = importlib.util.spec_from_file_location('bill_import_layouts', SCRIPT)
layouts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layouts)


class BillLayoutEvaluationTests(unittest.TestCase):
    def test_default_lists_cases_without_credentials_and_live_requires_explicit_consent(self):
        listed = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, check=True)
        cases = json.loads(listed.stdout)
        self.assertEqual(len({row['id'] for row in cases}), len(cases))
        self.assertEqual({row['media_type'] for row in cases},
            {'application/pdf', 'image/jpeg', 'image/png', 'image/webp'})
        with tempfile.TemporaryDirectory() as folder:
            refused = subprocess.run([sys.executable, str(SCRIPT), '--run-live', cases[0]['id'],
                '--documents', folder, '--results', folder], capture_output=True, text=True)
            self.assertEqual(refused.returncode, 2)
            self.assertIn('--share-with-ai', refused.stderr)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_scoring_does_not_count_failed_calls_or_missing_values_as_success(self):
        case = layouts.load_cases()[0]
        fields = {name: values[0] for name, values in case['expected'].items()}
        report = {'status': 'completed', 'extraction': {'fields': fields, 'warnings': [],
            'evidence': {'reading_type': 'actual'}}}
        self.assertEqual(layouts.score(case, report), [])
        self.assertTrue(layouts.score(case, report | {'status': 'failed'}))
        report['extraction']['fields'].pop('usage')
        self.assertIn('Unexpected usage', layouts.score(case, report))
        report['extraction']['warnings'] = ['multiple_bills']
        self.assertIn('Unexpected warning: multiple_bills', layouts.score(case, report))

    def test_scaled_unit_and_multi_bill_expectations_reject_false_successes(self):
        scaled = next(row for row in layouts.load_cases() if row['id'] == 'layout-3')
        fields = {name: values[0] for name, values in scaled['expected'].items()}
        report = {'status': 'completed', 'extraction': {'fields': fields, 'warnings': ['ambiguous_unit']}}
        self.assertEqual(layouts.score(scaled, report), [])
        fields.update(usage='5', usage_unit='us_gallons')
        self.assertIn('Unexpected usage_unit', layouts.score(scaled, report))
        separate = next(row for row in layouts.load_cases() if row['id'] == 'layout-4')
        report['extraction']['warnings'] = ['multiple_bills']
        self.assertIn('Expected all fields to be withheld', layouts.score(separate, report))

    def test_paid_trial_marks_before_call_and_cannot_replay_even_after_failure(self):
        case = layouts.load_cases()[0]
        for fails in (False, True):
            with self.subTest(fails=fails), tempfile.TemporaryDirectory() as folder:
                documents = Path(folder) / 'documents'; documents.mkdir()
                (documents / case['file']).write_bytes(b'%PDF-1.7 fictional unit-test bytes')
                results = Path(folder) / 'results'
                async def extract(*args):
                    self.assertTrue((results / f"{case['id']}.started").exists())
                    if fails:
                        raise RuntimeError('private provider details')
                    return SimpleNamespace(model_dump=lambda: {'fields': {}, 'warnings': []})
                client = MagicMock()
                client.return_value.__aenter__ = AsyncMock(return_value=SimpleNamespace())
                client.return_value.__aexit__ = AsyncMock(return_value=False)
                with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-placeholder', 'OPENAI_MODEL': 'test-model'}), \
                     patch('dotenv.load_dotenv'), patch('openai.AsyncOpenAI', client), \
                     patch('aquamind_ml.bill_import.extract_report', side_effect=extract):
                    record = asyncio.run(layouts.run_trial(case, documents, results))
                    self.assertEqual(record['status'], 'failed' if fails else 'completed')
                    self.assertNotIn('private provider details', (results / f"{case['id']}.json").read_text())
                    with self.assertRaises(FileExistsError):
                        asyncio.run(layouts.run_trial(case, documents, results))
                    self.assertEqual(client.call_count, 1)
                    self.assertEqual(client.call_args.kwargs['max_retries'], 0)
