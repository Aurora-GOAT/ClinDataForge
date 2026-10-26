import unittest

from clinforge.phi_evaluation import (
    normalize_spans, paired_bootstrap, record_counts, redact_text, summarize)


def fixture(doc_id='toy', language='en', group='g'):
    return {'doc_id': doc_id, 'language': language, 'template_group': group,
            'text': 'Amy fever 37.0 on May 5',
            'entities': [{'label': 'NAME', 'start': 0, 'end': 3},
                         {'label': 'DATE', 'start': 18, 'end': 23}],
            'protected_spans': [{'start': 4, 'end': 14, 'label': 'CLINICAL'}]}


class PHIEvaluationTest(unittest.TestCase):
    def test_exact_boundary_error_counts_as_fp_and_fn(self):
        row = fixture()
        count = record_counts(row, [{'label': 'NAME', 'start': 0, 'end': 2}])
        self.assertEqual((count['tp'], count['fp'], count['fn']), (0, 1, 2))
        self.assertEqual(count['all_gold_phi_characters_masked'], 0)

    def test_label_error_can_mask_phi_but_fail_entity_metric(self):
        row = fixture()
        predicted = [dict(s, label='PHONE') for s in row['entities']]
        result = summarize([record_counts(row, predicted)])
        self.assertEqual(result['entity_exact']['f1'], 0)
        self.assertEqual(result['all_gold_phi_masked_positive_rate'], 1)
        self.assertEqual(result['all_entities_exact_positive_rate'], 0)

    def test_clinical_deletion_has_explicit_denominator(self):
        count = record_counts(fixture(), [{'label': 'NAME', 'start': 0, 'end': 9}])
        self.assertEqual(count['protected_clinical_characters'], 10)
        self.assertEqual(count['deleted_protected_clinical_characters'], 5)
        self.assertEqual(summarize([count])['protected_clinical_character_deletion_rate'], .5)

    def test_empty_phi_does_not_inflate_positive_coverage(self):
        row = dict(fixture(), entities=[])
        result = summarize([record_counts(row, [])])
        self.assertIsNone(result['all_gold_phi_masked_positive_rate'])
        self.assertEqual(result['all_gold_phi_masked_all_records_rate'], 1)
        self.assertEqual(result['negative_record_any_redaction_rate'], 0)

    def test_non_span_payload_raises_type_error(self):
        # Passing the wrapper dict {'doc_id': ..., 'spans': [...]} instead of the span
        # list is the mistake this guard exists for: iterating a dict yields its keys,
        # so without the guard the failure surfaces as a confusing AttributeError on str.
        with self.assertRaises(TypeError):
            normalize_spans({'doc_id': 'toy', 'spans': []}, 'Amy')
        with self.assertRaises(TypeError):
            normalize_spans(['NAME'], 'Amy')
        self.assertEqual(normalize_spans([{'label': 'NAME', 'start': 0, 'end': 3}], 'Amy'),
                         [('NAME', 0, 3)])

    def test_overlap_union_masks_all_characters(self):
        spans = [{'label': 'NAME', 'start': 0, 'end': 3},
                 {'label': 'ADDRESS', 'start': 1, 'end': 9}]
        self.assertEqual(redact_text('Amy fever 37', spans), '[PHI] 37')

    def test_mrn_mapping_and_duplicate_predictions(self):
        spans = [{'label': 'MRN', 'start': 0, 'end': 3}] * 2
        self.assertEqual(normalize_spans(spans, 'ABC'), [('PATIENT_ID', 0, 3)])

    def test_invalid_offsets_and_protected_overlap_rejected(self):
        for span in ({'label': 'NAME', 'start': -1, 'end': 3},
                     {'label': 'DATE', 'start': 0, 'end': 99},
                     {'label': 'OTHER', 'start': 0, 'end': 1}):
            with self.assertRaises(ValueError):
                normalize_spans([span], 'ABC')
        row = dict(fixture(), protected_spans=[{'start': 0, 'end': 3}])
        with self.assertRaises(ValueError):
            record_counts(row, [])

    def test_paired_bootstrap_zero_difference_and_deterministic(self):
        counts = [record_counts(fixture(str(i), group=str(i // 2)), []) for i in range(8)]
        a = paired_bootstrap(counts, counts, reps=100)
        self.assertEqual(a, paired_bootstrap(counts, counts, reps=100))
        self.assertEqual(a['metrics']['recall']['ci95_percentile'], [0, 0])
        self.assertEqual(a['groups_per_language'], {'en': 4})

    def test_paired_bootstrap_direction_and_pairing_rejection(self):
        row = fixture()
        before, after = record_counts(row, []), record_counts(row, row['entities'])
        result = paired_bootstrap([before], [after], reps=100)
        self.assertEqual(result['metrics']['recall']['delta_right_minus_left'], 1)
        self.assertEqual(result['metrics']['recall']['ci95_percentile'], [1, 1])
        with self.assertRaises(ValueError):
            paired_bootstrap([before], [dict(after, doc_id='different')], reps=100)


if __name__ == '__main__':
    unittest.main()
