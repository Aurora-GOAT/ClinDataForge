"""Provenance helpers must persist only fixed aggregate keys and fingerprints."""
import json
import unittest

from scripts.trace_mimic_provenance import aggregate_structured, compare_historical, replay_csv_pair


class MimicProvenanceTest(unittest.TestCase):
    def test_structured_summary_does_not_echo_patient_or_clinical_values(self):
        rows = [{'subject_id': 'SYNTHETIC_PRIVATE_CANARY', 'stay_id': 'SYN-STAY-1',
                 'chiefcomplaint_raw': 'SYNTHETIC_PRIVATE_CANARY', 'diagnoses': [{'code': 'SYNTHETIC_PRIVATE_CANARY'}]},
                {'subject_id': 'SYNTHETIC_PRIVATE_CANARY', 'stay_id': 'SYN-STAY-2', 'diagnoses': []}]
        summary = aggregate_structured(('\n'.join(json.dumps(row) for row in rows)).encode())
        self.assertEqual(summary, {'rows': 2, 'unique_subject_ids': 1, 'unique_stay_ids': 2,
                                   'diagnosis_links': 1, 'stays_with_diagnoses': 1})
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(summary))

    def test_historical_comparison_reports_numeric_differences_only(self):
        result = compare_historical({'rows': 222, 'provenance': 'SYNTHETIC_PRIVATE_CANARY',
                                     'temperature': {'paired': 195}},
                                    {'rows': 85, 'temperature': {'paired': 195}})
        self.assertEqual(result, [{'metric': 'rows', 'historical': 222, 'recomputed': 85}])
        self.assertEqual(compare_historical({'rows': 222}, {'rows': 222, 'new_count': 0}), [])

    def test_replay_fingerprints_without_returning_rows(self):
        rows = [{'subject_id': 'SYNTHETIC_PRIVATE_CANARY', 'stay_id': 'SYN-STAY', 'diagnoses': []}]
        expected = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode()

        class FakeUpstream:
            @staticmethod
            def analyze(*args, **kwargs):
                return {'n_triage_rows': 1, 'n_unique_patients_in_triage': 1,
                        'n_unique_stays_in_triage': 1, 'n_diagnosis_rows': 0,
                        'n_stays_with_matched_diagnosis': 0}, rows

        result = replay_csv_pair(FakeUpstream, 'unused-synthetic-triage', 'unused-synthetic-diagnoses', expected)
        self.assertTrue(result['exact_lf_serialized_bytes_match_existing_derivative'])
        self.assertEqual(len(result['replayed_derivative_sha256']), 64)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
