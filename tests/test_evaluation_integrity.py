"""Regression checks for measured audit defects, independent of PHI tuning."""
import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from clinforge.evaluate import evaluate
from clinforge.synthetic import make_dataset, save_dataset


class EvaluationIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.rows, self.labels = make_dataset(20)

    def tearDown(self):
        self.tmp.cleanup()

    def measure(self, rows=None, labels=None):
        for filename, data in [('records.jsonl', self.rows if rows is None else rows),
                               ('labels.jsonl', self.labels if labels is None else labels)]:
            (self.base / filename).write_text(
                ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in data),
                encoding='utf-8')
        return evaluate(self.base / 'records.jsonl', self.base / 'labels.jsonl')

    def test_temperature_corruption_does_not_change_alt_or_gold(self):
        rows, labels = make_dataset(600)
        bad_style_one = 0
        for row, gold in zip(rows, labels):
            if gold['generated_from_template'] != 1:
                continue
            # Check the literal independently, rather than calling the lab parser.
            alt = re.search(r'\bALT=(\d+(?:\.\d+)?)\s+U/L', row['text'])
            self.assertIsNotNone(alt)
            self.assertEqual(float(alt.group(1)), gold['labs']['alt_u_l'])
            if gold['intentional_bad_temperature']:
                bad_style_one += 1
                self.assertIn('T=700 °F', row['text'])
                self.assertNotIn('temp_c', gold['labs'])
                self.assertLess(float(alt.group(1)), 200)
        self.assertEqual(bad_style_one, 6)  # Five originals plus one near copy.

    def test_fixture_save_preserves_existing_files(self):
        folder = self.base / 'fixture'
        save_dataset(folder, n=20)
        before = {path.name: path.read_bytes() for path in folder.iterdir()}
        with self.assertRaises(FileExistsError):
            save_dataset(folder, n=30)
        self.assertEqual(before, {path.name: path.read_bytes() for path in folder.iterdir()})

    def test_fixture_save_refuses_even_unrelated_nonempty_directory(self):
        folder = self.base / 'fixture'
        folder.mkdir()
        (folder / 'historical.txt').write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):
            save_dataset(folder, n=20)
        self.assertEqual(list(folder.iterdir()), [folder / 'historical.txt'])

    def test_fixture_serialization_is_deterministic_lf(self):
        save_dataset(self.base / 'a', n=20)
        save_dataset(self.base / 'b', n=20)
        for path in (self.base / 'a').iterdir():
            self.assertEqual(path.read_bytes(), (self.base / 'b' / path.name).read_bytes())
            self.assertNotIn(b'\r\n', path.read_bytes())

    def test_actual_patient_split_leak_rejected_despite_distinct_clusters(self):
        # Index 0 is template0/dev; index3 is template1/test.
        self.rows[3]['patient_group'] = self.rows[0]['patient_group']
        with self.assertRaisesRegex(ValueError, 'Actual patient group crosses splits'):
            self.measure()

    def test_duplicate_cluster_cannot_cross_patient_or_encounter(self):
        for field in ('patient_group', 'encounter_group'):
            with self.subTest(field=field):
                rows = copy.deepcopy(self.rows)
                rows[1][field] = 'ANOTHER-GROUP'
                with self.assertRaisesRegex(ValueError, 'Duplicate cluster crosses'):
                    self.measure(rows)

    def test_duplicate_record_ids_rejected(self):
        self.rows[1]['record_id'] = self.rows[0]['record_id']
        self.labels[1]['record_id'] = self.labels[0]['record_id']
        with self.assertRaisesRegex(ValueError, 'Duplicate record_id'):
            self.measure()

    def test_nonfinite_and_boolean_gold_labs_rejected(self):
        for value in (float('nan'), float('inf'), -float('inf'), True, '37.0'):
            with self.subTest(value=value):
                labels = copy.deepcopy(self.labels)
                labels[0]['labs']['temp_c'] = value
                with self.assertRaisesRegex(ValueError, 'finite numeric'):
                    self.measure(labels=labels)

    def test_invalid_gold_spans_rejected(self):
        bad_spans = [
            {'label': 'NAME', 'start': -1, 'end': 1},
            {'label': 'NAME', 'start': 0, 'end': 10000},
            {'label': 'NAME', 'start': 3, 'end': 3},
            {'label': 'NAME', 'start': True, 'end': 3},
            {'label': 'UNKNOWN', 'start': 0, 'end': 3},
        ]
        for span in bad_spans:
            with self.subTest(span=span):
                labels = copy.deepcopy(self.labels)
                labels[0]['phi_spans'] = [span]
                with self.assertRaises(ValueError):
                    self.measure(labels=labels)
        labels = copy.deepcopy(self.labels)
        labels[0]['phi_spans'].append(dict(labels[0]['phi_spans'][0]))
        with self.assertRaisesRegex(ValueError, 'overlap or are duplicated'):
            self.measure(labels=labels)

    def test_patient_count_and_aggregate_evaluation_scope_are_explicit(self):
        rows = [copy.deepcopy(self.rows[i]) for i in (0, 3)]
        labels = [copy.deepcopy(self.labels[i]) for i in (0, 3)]
        rows[1]['patient_group'] = rows[0]['patient_group']
        labels[1]['split'] = labels[0]['split']
        result = self.measure(rows, labels)
        self.assertEqual(result['n_patient_groups'], 1)
        self.assertEqual(result['n_duplicate_clusters'], 2)
        self.assertEqual(result['evaluation_scope']['records_by_split'], {'dev': 2})
        self.assertIn('All supplied', result['evaluation_scope']['scored_records'])

    def test_wrong_duplicate_links_not_hidden_by_correct_record_classification(self):
        rows, labels = [], []
        for i in range(4):
            row = copy.deepcopy(self.rows[0])
            gold = copy.deepcopy(self.labels[0])
            row['record_id'] = gold['record_id'] = f'ROW-{i}'
            gold['duplicate_cluster'] = f'CLUSTER-{i // 2}'
            rows.append(row)
            labels.append(gold)

        def wrong_links(processed):
            for item in processed:
                item['duplicate_of'] = None
            processed[1]['duplicate_of'] = processed[2]['record_key']  # Future and wrong cluster.
            processed[3]['duplicate_of'] = processed[0]['record_key']  # Earlier but wrong cluster.

        with patch('clinforge.evaluate.deduplicate', side_effect=wrong_links):
            result = self.measure(rows, labels)
        self.assertEqual(result['metrics']['pipeline_duplicate_record_detection']['f1'], 1.0)
        self.assertEqual(result['duplicate_link_evaluation']['tp'], 0)
        self.assertEqual(result['duplicate_link_evaluation']['fp'], 2)
        self.assertEqual(result['duplicate_link_evaluation']['fn'], 2)

    def test_empty_fixture_is_not_a_valid_experiment(self):
        with self.assertRaisesRegex(ValueError, 'empty fixture'):
            self.measure([], [])

    def test_legacy_five_metrics_remain_reproducible(self):
        project = Path(__file__).resolve().parents[1]
        fixture = project / 'examples' / 'generated_fixture'
        measured = evaluate(fixture / 'synthetic_notes.jsonl', fixture / 'gold_annotations.jsonl')
        historical = json.loads((project / 'reports' / 'demo_run' / 'synthetic_benchmark.json').read_text('utf-8'))
        self.assertEqual(measured['metrics'], historical['metrics'])
        self.assertEqual(measured['duplicate_link_evaluation']['f1'], 1.0)


if __name__ == '__main__':
    unittest.main()
