"""Phase-2 benchmark and method-dispatch contract tests (stdlib only).

No model weights, network or optional dependency is required. Probes below are
authored here; none of them is copied from the frozen test split.
"""
import importlib.util
import json
import random
import unittest
from pathlib import Path

from clinforge.phi_evaluation import LABELS, normalize_spans, record_counts
from clinforge.phi_models import create_detector
from clinforge.phi_rules import RULE_REVISION, find_context_phi, union_spans

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = load_module('build_phi_benchmark_module', 'scripts/build_phi_benchmark.py')
AUDIT = load_module('audit_phi_dataset_module', 'scripts/audit_phi_dataset.py')


def fixture_row(doc_id='X1', text='Patient Amy Tan, SSN 123-45-6789, amy.tan@example.org',
                entities=None, protected=None):
    return {'doc_id': doc_id, 'language': 'en', 'text': text,
            'entities': entities if entities is not None else [
                {'label': 'NAME', 'start': 8, 'end': 15},
                {'label': 'SSN', 'start': 20, 'end': 31},
                {'label': 'EMAIL', 'start': 33, 'end': 51}],
            'protected_spans': protected if protected is not None else [
                {'start': 0, 'end': 7, 'label': 'CLINICAL'}]}


class MethodDispatchTest(unittest.TestCase):
    def test_unknown_method_rejected(self):
        with self.assertRaises(ValueError):
            create_detector('E', 'models/phase2_gliner_pii', {})

    def test_rule_method_uses_original_recognizer(self):
        detector = create_detector('A', 'models/phase2_gliner_pii', {})
        self.assertEqual(detector.metadata['method'], 'original_v0_1_regex')
        self.assertEqual(detector.find('姓名:张三'), [{'start': 3, 'end': 5, 'label': 'NAME',
                                                      'score': 1.0, 'source': 'original_regex'}])

    def test_model_methods_are_not_simulated_when_dependencies_missing(self):
        """Without numpy/onnxruntime the detector must fail loudly, not return []."""
        for method in ('B', 'C', 'D'):
            with self.subTest(method=method), self.assertRaises(Exception):
                try:
                    create_detector(method, str(ROOT / 'models/does-not-exist'), {})
                except Exception as error:
                    self.assertNotIsInstance(error, SystemExit)
                    raise


class ContextRuleTest(unittest.TestCase):
    def test_supplemental_rules_cover_extended_labels(self):
        text = 'SSN 123-45-6789 and email Amy.Tan@Example.org, member id AB-99120'
        found = {(span['label'], text[span['start']:span['end']]) for span in find_context_phi(text)}
        self.assertIn(('SSN', '123-45-6789'), found)
        self.assertIn(('EMAIL', 'Amy.Tan@Example.org'), found)
        self.assertIn(('INSURANCE_ID', 'AB-99120'), found)

    def test_union_keeps_highest_score_per_exact_span(self):
        merged = union_spans([{'start': 0, 'end': 3, 'label': 'NAME', 'score': .4}],
                             [{'start': 0, 'end': 3, 'label': 'NAME', 'score': .9}])
        self.assertEqual([span['score'] for span in merged], [.9])
        self.assertEqual(RULE_REVISION, 'phase2-context-rules-v1')


class BenchmarkContractTest(unittest.TestCase):
    def test_generated_rows_satisfy_contract(self):
        rows = BUILD.chinese_records()
        BUILD.assert_contract(rows)
        self.assertEqual(len(rows), 320)
        self.assertEqual(sum(1 for row in rows if row['entities']), 280)

    def test_negative_notes_are_distinct(self):
        notes = BUILD.ZH_NEGATIVE_NOTES
        self.assertEqual(len(notes), len(set(notes)), 'negative notes must be individually distinct')
        self.assertEqual(len(notes), len(BUILD.ZH_TEMPLATES))

    def test_builder_and_audit_masks_agree(self):
        """Regression: a mask mismatch silently loosened the leak check."""
        for row in BUILD.chinese_records()[:40]:
            self.assertEqual(BUILD.compact_mask(row), AUDIT.audit_mask(row))

    def test_shingle_set_keeps_separators_that_gram_set_strips(self):
        """gram_set strips '|' because it is \\W; shingle_set must not."""
        value = 'abc|NAME|def'
        self.assertTrue(any('|' in shingle for shingle in BUILD.shingle_set(value, 5)))
        self.assertFalse(any('|' in shingle for shingle in BUILD.gram_set(value, 5)))

    def test_jaccard_pairs_matches_brute_force(self):
        rng = random.Random(20261025)
        sets_list = []
        for _ in range(40):
            universe = [f'g{i}' for i in range(20)]
            sets_list.append({value for value in universe if rng.random() < .5})
        expected = {(i, j) for i in range(40) for j in range(i + 1, 40)
                    if sets_list[i] & sets_list[j]
                    and len(sets_list[i] & sets_list[j]) / len(sets_list[i] | sets_list[j]) >= .5}
        found = {tuple(sorted(pair)) for pair in BUILD.jaccard_pairs(sets_list, .5)}
        self.assertEqual(found, expected)

    def test_split_never_divides_a_component(self):
        rows = BUILD.chinese_records()[:120]
        components = BUILD.near_duplicate_components(rows)
        split_of = BUILD.assign_splits(rows, components)
        by_component = {}
        for index, name in split_of.items():
            by_component.setdefault(components[index], set()).add(name)
        self.assertTrue(all(len(value) == 1 for value in by_component.values()))
        self.assertEqual(set(split_of.values()), {'train', 'dev', 'test'})


class EvaluationContractTest(unittest.TestCase):
    def test_missing_optional_group_keys_do_not_raise(self):
        row = fixture_row()
        self.assertNotIn('template_group', row)
        self.assertNotIn('bootstrap_group', row)
        count = record_counts(row, [])
        self.assertEqual(count['bootstrap_group'], 'X1')
        self.assertEqual(count['by_label']['SSN'], [0, 0, 1])

    def test_all_eight_labels_are_scored(self):
        row = fixture_row()
        count = record_counts(row, row['entities'])
        self.assertEqual(sorted(count['by_label']), sorted(LABELS))
        self.assertEqual(count['tp'], 3)
        self.assertEqual(count['fp'], 0)

    def test_normalize_spans_rejects_unknown_label(self):
        with self.assertRaises(ValueError):
            normalize_spans([{'label': 'BLOOD_TYPE', 'start': 0, 'end': 3}], 'abcdef')

    def test_manifest_declares_every_scored_label(self):
        manifest = json.loads((ROOT / 'data/phase2_phi_v1/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(tuple(manifest['labels']), LABELS)
        for source_label, mapped in BUILD.SOURCE_LABELS.items():
            self.assertIn(mapped, LABELS, source_label)


if __name__ == '__main__':
    unittest.main()
