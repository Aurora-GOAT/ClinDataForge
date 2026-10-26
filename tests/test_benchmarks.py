# -*- coding: utf-8 -*-
"""Offline benchmark interface tests: loading, scoring, leakage-audit hash, gating."""
import json
import os
import tempfile
import unittest

from clinforge.benchmarks import (LIVE_EVAL_STATUS, load_medmcqa_jsonl,
                                  score_predictions, sha256_file)


class TestBenchmarks(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, 'dev.jsonl')
        rows = [{'question': 'Q1', 'opa': 'a', 'opb': 'b', 'opc': 'c', 'opd': 'd',
                 'cop': 2, 'subject_name': 'Anatomy'},
                {'question': 'Q2', 'opa': 'a', 'opb': 'b', 'opc': 'c', 'opd': 'd',
                 'cop': 0}]
        with open(self.path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(json.dumps(r) for r in rows))

    def test_load_and_hash(self):
        items = load_medmcqa_jsonl(self.path)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['answer_idx'], 2)
        self.assertEqual(items[0]['subject'], 'Anatomy')
        self.assertEqual(len(sha256_file(self.path)), 64)

    def test_score_with_wilson(self):
        items = load_medmcqa_jsonl(self.path)
        out = score_predictions(items, {items[0]['id']: 2, items[1]['id']: 1})
        self.assertEqual(out['n'], 2)
        self.assertEqual(out['correct'], 1)
        self.assertAlmostEqual(out['accuracy'], 0.5)
        self.assertLess(out['wilson95'][0], 0.5)
        self.assertGreater(out['wilson95'][1], 0.5)

    def test_missing_prediction_skipped(self):
        items = load_medmcqa_jsonl(self.path)
        out = score_predictions(items, {items[0]['id']: 2})
        self.assertEqual(out['n'], 1)
        self.assertEqual(out['correct'], 1)

    def test_invalid_cop_rejected(self):
        bad = os.path.join(self.dir, 'bad.jsonl')
        with open(bad, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps({'question': 'x', 'opa': 'a', 'opb': 'b',
                                     'opc': 'c', 'opd': 'd', 'cop': 9}))
        with self.assertRaises(ValueError):
            load_medmcqa_jsonl(bad)

    def test_live_eval_blocked_by_default(self):
        self.assertEqual(LIVE_EVAL_STATUS['status'], 'BLOCKED')
        self.assertIn('authorized', LIVE_EVAL_STATUS['reason'].lower()
                      .replace('authorised', 'authorized'))


if __name__ == '__main__':
    unittest.main()
