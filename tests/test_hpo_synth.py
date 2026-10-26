"""Tests for HPO knowledge parsing, knowledge-constrained generation and
the medical extraction/context/lab modules."""
import json
import unittest

from clinforge.hpo_knowledge import parse_frequency, FREQUENCY_TERMS, LAB_PHENOTYPES, REFERENCE_INTERVALS
from clinforge.med_extract import (build_term_index, find_phenotype_mentions,
                                   classify_context, parse_labs_v2)
from clinforge.synthgen import CaseBuilder, sample_lab_value, GENERATOR_VERSION
import random


class TestFrequencyParsing(unittest.TestCase):
    def test_frequency_term_ids(self):
        self.assertEqual(parse_frequency('HP:0040280'), 1.0)
        self.assertEqual(parse_frequency('HP:0040285'), 0.0)

    def test_ratio_and_percent(self):
        self.assertAlmostEqual(parse_frequency('1/2'), 0.5)
        self.assertAlmostEqual(parse_frequency('45%'), 0.45)

    def test_empty_and_garbage_default(self):
        self.assertEqual(parse_frequency(''), 0.20)
        self.assertEqual(parse_frequency('nonsense'), 0.20)


class TestCaseBuilder(unittest.TestCase):
    def test_spans_track_text(self):
        b = CaseBuilder()
        b.text('患者')
        b.entity('癫痫发作', {'label': 'PHENOTYPE'})
        b.text('，')
        b.entity('2026年', {'label': 'DATE'})
        text = b.build()
        self.assertEqual(text, '患者癫痫发作，2026年')
        for e in b.entities:
            self.assertEqual(text[e['start']:e['end']], e['text'])


class TestLabSampling(unittest.TestCase):
    def test_direction_consistency(self):
        rng = random.Random(1)
        for _ in range(200):
            for analyte, spec in (('GLUCOSE', 'high'), ('GLUCOSE', 'low'), ('HGB', 'low'), ('ALT', 'high')):
                value, unit, std, std_unit = sample_lab_value(rng, analyte, spec, use_alt_unit=True)
                ref = REFERENCE_INTERVALS[analyte]
                if spec == 'high':
                    self.assertGreater(std, ref['hi'])
                else:
                    self.assertLess(std, ref['lo'])
                self.assertEqual(std_unit, ref['unit'])

    def test_std_matches_displayed_value(self):
        rng = random.Random(2)
        value, unit, std, _ = sample_lab_value(rng, 'GLUCOSE', 'high', use_alt_unit=True)
        if unit == 'mg/dL':
            self.assertAlmostEqual(std, round(value / 18.016, 2), places=2)
        value, unit, std, _ = sample_lab_value(rng, 'HGB', 'low', use_alt_unit=True)
        if unit == 'g/dL':
            self.assertAlmostEqual(std, round(value * 10.0, 2), places=2)


def _mini_kb():
    terms = {
        'HP:0001250': {'name': 'Seizure', 'synonyms': ['Seizures'], 'alt_ids': [], 'is_obsolete': False},
        'HP:0001903': {'name': 'Anemia', 'synonyms': [], 'alt_ids': [], 'is_obsolete': False},
        'HP:0005522': {'name': 'Pyridoxine-responsive sideroblastic anemia', 'synonyms': [],
                       'alt_ids': [], 'is_obsolete': False},
    }
    return {'terms': terms}


MINI_GLOSS = {'phenotypes': {'HP:0001250': '癫痫发作', 'HP:0001903': '贫血',
                             'HP:0005522': '吡哆醇反应性铁粒幼细胞贫血'},
              'diseases': {}}


class TestExtraction(unittest.TestCase):
    def setUp(self):
        self.index = build_term_index(_mini_kb(), MINI_GLOSS)

    def test_longest_match_wins_zh(self):
        text = '既往有吡哆醇反应性铁粒幼细胞贫血，否认癫痫发作。'
        mentions = find_phenotype_mentions(text, self.index)
        found = {(m['start'], m['end'], m['hp_id']) for m in mentions}
        self.assertIn((text.find('吡哆醇'), text.find('吡哆醇') + len('吡哆醇反应性铁粒幼细胞贫血'), 'HP:0005522'), found)
        self.assertIn((text.find('癫痫'), text.find('癫痫') + 4, 'HP:0001250'), found)
        # the substring 贫血 inside the longer term must NOT double-count
        anemia_mentions = [m for m in mentions if m['hp_id'] == 'HP:0001903']
        self.assertEqual(len(anemia_mentions), 0)

    def test_context_negation_suspicion_history(self):
        text = '尚需评估有无癫痫发作，否认贫血，既往有贫血史。'
        mentions = find_phenotype_mentions(text, self.index)
        by_pos = {m['start']: m for m in mentions}
        seiz = [m for m in mentions if m['hp_id'] == 'HP:0001250'][0]
        self.assertEqual(classify_context(text, seiz, 'zh'), 'suspected')
        anemias = sorted([m for m in mentions if m['hp_id'] == 'HP:0001903'], key=lambda m: m['start'])
        self.assertEqual(classify_context(text, anemias[0], 'zh'), 'negated')
        self.assertEqual(classify_context(text, anemias[1], 'zh'), 'history')

    def test_affirmed_default(self):
        text = '查体发现贫血。'
        m = find_phenotype_mentions(text, self.index)[0]
        self.assertEqual(classify_context(text, m, 'zh'), 'affirmed')

    def test_en_word_boundary(self):
        text = 'The patient denies seizure-like movements but has anemia.'
        mentions = find_phenotype_mentions(text, self.index)
        hp = {m['hp_id'] for m in mentions}
        self.assertIn('HP:0001903', hp)


class TestLabsV2(unittest.TestCase):
    def test_glucose_unit_conversion(self):
        entries, issues = parse_labs_v2('空腹血糖 126 mg/dL，血红蛋白 8.9 g/dL。')
        by = {e['analyte']: e for e in entries}
        self.assertAlmostEqual(by['GLUCOSE']['value_std'], round(126 / 18.016, 2), places=2)
        self.assertEqual(by['GLUCOSE']['unit_std'], 'mmol/L')
        self.assertAlmostEqual(by['HGB']['value_std'], 89.0, places=2)
        self.assertEqual(by['HGB']['unit_std'], 'g/L')

    def test_standard_unit_passthrough(self):
        entries, _ = parse_labs_v2('ALT 88 U/L')
        self.assertEqual(entries[0]['value_std'], 88.0)
        self.assertEqual(entries[0]['unit_std'], 'U/L')

    def test_conflicting_values_flagged(self):
        _, issues = parse_labs_v2('ALT 88 U/L，复查 ALT 120 U/L')
        self.assertIn('CONFLICTING_VALUES_ALT', issues)


if __name__ == '__main__':
    unittest.main()
