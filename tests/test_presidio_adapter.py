"""Adapter contract tests; doubles are NEVER reported as real Presidio results."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from clinforge.presidio_adapter import PresidioAdapter, PresidioUnavailable
from clinforge.stress import stress_eval
from scripts.benchmark_presidio import historical_cases, measure
from clinforge.operators import find_phi


class PresidioAdapterTest(unittest.TestCase):
    def test_missing_dependencies_fail_explicitly_before_import(self):
        with patch('clinforge.presidio_adapter.environment_status', return_value={
                'missing_required': ['presidio-analyzer', 'en-core-web-sm']}):
            with self.assertRaisesRegex(PresidioUnavailable, 'Missing local dependencies'):
                PresidioAdapter()

    def test_reject_model_path_or_invalid_threshold(self):
        for arguments in ({'model_name': '../download-model'}, {'score_threshold': 2}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                PresidioAdapter(**arguments)

    def test_mapping_offsets_and_duplicates_contract(self):
        adapter = object.__new__(PresidioAdapter)
        adapter.score_threshold = .5
        result = SimpleNamespace(entity_type='PERSON', start=0, end=3, score=.9)
        adapter._analyzer = SimpleNamespace(analyze=lambda **kwargs: [result, result])
        spans = adapter.find('Amy has fever')
        self.assertEqual([(s.label, s.start, s.end) for s in spans], [('NAME', 0, 3)])

    def test_bad_offsets_do_not_silently_pass(self):
        adapter = object.__new__(PresidioAdapter)
        adapter.score_threshold = .5
        adapter._analyzer = SimpleNamespace(analyze=lambda **kwargs: [
            SimpleNamespace(entity_type='PERSON', start=0, end=99)])
        with self.assertRaises(ValueError):
            adapter.find('Amy')

    def test_runtime_failure_is_not_an_empty_prediction(self):
        adapter = object.__new__(PresidioAdapter)
        adapter.score_threshold = .5
        def fail(**kwargs):
            raise RuntimeError('injected test failure')
        adapter._analyzer = SimpleNamespace(analyze=fail)
        with self.assertRaises(RuntimeError):
            adapter.find('Amy')

    def test_historical_cases_match_original_stress_counts(self):
        cases = list(historical_cases())
        self.assertEqual(len(cases), 60)
        self.assertEqual(sum(len(row['phi_spans']) for row in cases), 180)
        self.assertEqual(measure(find_phi, cases)['entity_span_exact'], stress_eval(60)['pipeline_phi_span_exact'])


if __name__ == '__main__':
    unittest.main()
