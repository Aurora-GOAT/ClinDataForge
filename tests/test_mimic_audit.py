import json
import tempfile
import unittest
from pathlib import Path
from clinforge.mimic_audit import audit_public_structured

class MimicAggregateTest(unittest.TestCase):
    def test_aggregate_only_and_fahrenheit_check(self):
        sample=[{'subject_id':'SENSITIVE01','stay_id':'ST1','measurements':{'temperature':{'value':98.6,'unit':'degF'},'heartrate':{'value':None}},
                 'temperature_celsius_derived':37.0, 'diagnoses':[{'code':'Z00','system':'ICD-10-CM','seq_num':'1'}],
                 'chiefcomplaint_search_tags_not_diagnoses':['unclassified'], 'flags':[{'issue':'broad_range_flag'}]}]
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'input.jsonl'
            p.write_text(''.join(json.dumps(x)+'\n' for x in sample),encoding='utf-8')
            a=audit_public_structured(p)
        self.assertEqual(a['rows'],1)
        self.assertEqual(a['diagnosis_links'],1)
        self.assertEqual(a['stays_with_diagnoses'],1)
        self.assertEqual(a['temperature_f_to_c']['mismatch_over_0_011_c'],0)
        self.assertEqual(a['missing_measurements']['heartrate']['count'],1)
        self.assertNotIn('SENSITIVE01',json.dumps(a))
        self.assertNotIn('ST1',json.dumps(a))
    def test_duplicate_stays_counted(self):
        records=[{'subject_id':'p1','stay_id':'s1','measurements':{},'diagnoses':[],'flags':[]},
                 {'subject_id':'p1','stay_id':'s1','measurements':{},'diagnoses':[],'flags':[]}]
        with tempfile.TemporaryDirectory() as f:
            p=Path(f)/'input.jsonl'
            p.write_text(''.join(json.dumps(x)+'\n' for x in records),encoding='utf-8')
            a=audit_public_structured(p)
        self.assertEqual(a['duplicate_stay_ids'],1)
        self.assertEqual(a['stays_without_diagnoses'],2)

    def _audit_rows(self, records):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.jsonl'
            path.write_text(''.join(json.dumps(row) + '\n' for row in records), encoding='utf-8')
            return audit_public_structured(path)

    def test_absent_measurement_counts_as_missing(self):
        result = self._audit_rows([{'measurements': {'heartrate': {'value': 70}}}, {'measurements': {}}])
        self.assertEqual(result['missing_measurements']['heartrate'], {'count': 1, 'rate': 0.5})
        self.assertEqual(result['missing_measurements']['temperature']['count'], 2)

    def test_invalid_values_counted_separately_from_missing(self):
        result = self._audit_rows([
            {'measurements': {'heartrate': {'value': 'nan'}}},
            {'measurements': {'heartrate': {'value': True}}},
            {'measurements': {'heartrate': {'value': 'unparseable'}}},
            {'measurements': {'heartrate': {'value': None}}},
            {'measurements': {'heartrate': {'value': 70}}},
            {'measurements': {}},
        ])
        self.assertEqual(result['missing_measurements']['heartrate'], {'count': 2, 'rate': 0.3333})
        self.assertEqual(result['invalid_measurements']['heartrate'], {'count': 3, 'rate': 0.5})
        json.dumps(result, allow_nan=False)

    def test_missing_identifiers_are_not_distinct_or_duplicate_ids(self):
        result = self._audit_rows([{}, {'subject_id': None, 'stay_id': ''}])
        self.assertEqual(result['unique_subject_ids'], 0)
        self.assertEqual(result['unique_stay_ids'], 0)
        self.assertEqual(result['duplicate_stay_ids'], 0)
        self.assertEqual(result['missing_subject_id_rows'], 2)
        self.assertEqual(result['missing_stay_id_rows'], 2)

    def test_unknown_categories_never_export_arbitrary_strings(self):
        result = self._audit_rows([{'flags': ['SYNTHETIC_SECRET_FLAG'],
            'diagnoses': [{'system': 'SYNTHETIC_SECRET_DIAG', 'seq_num': '1'}],
            'measurements': {'SYNTHETIC_SECRET_FIELD': {'value': None}},
            'chiefcomplaint_search_tags_not_diagnoses': ['SYNTHETIC_SECRET_TAG']}])
        serialized = json.dumps(result, allow_nan=False)
        self.assertNotIn('SYNTHETIC_SECRET', serialized)
        self.assertEqual(result['diagnosis_code_system_counts'], {'OTHER': 1})
        self.assertEqual(result['flag_counts'], {'OTHER': 1})
        self.assertEqual(result['complaint_search_tag_counts'], {'OTHER': 1})
        self.assertEqual(result['unknown_measurement_key_occurrences'], 1)

    def test_unknown_units_and_nonfinite_values_not_valid_pairs(self):
        result = self._audit_rows([
            {'measurements': {'temperature': {'value': 98.6, 'unit': 'Kelvin'}}, 'temperature_celsius_derived': 98.6},
            {'measurements': {'temperature': {'value': 'nan', 'unit': 'degF'}}, 'temperature_celsius_derived': 37},
            {'measurements': {'temperature': {'value': 98.6, 'unit': 'degF'}}, 'temperature_celsius_derived': float('inf')},
            {'measurements': {'temperature': {'value': True, 'unit': 'degF'}}, 'temperature_celsius_derived': 37},
        ])
        check = result['temperature_f_to_c']
        self.assertEqual(check['paired_records'], 0)
        self.assertIsNone(check['mean_absolute_error_in_c'])
        self.assertEqual(check['invalid_numeric_pairs'], 3)
        self.assertEqual(check['unsupported_unit_pairs'], 1)
        json.dumps(result, allow_nan=False)

    def test_numeric_aggregate_overflow_fails_closed(self):
        row = {'measurements': {'temperature': {'value': 1e308, 'unit': 'degC'}},
            'temperature_celsius_derived': 0}
        with self.assertRaises(ValueError):
            self._audit_rows([row, row])

    def test_malformed_structures_fail_without_echoing_source(self):
        for row in ([], {'diagnoses': 'SYNTHETIC_SECRET'}, {'measurements': []}, {'flags': {}},
                    {'chiefcomplaint_search_tags_not_diagnoses': 'SYNTHETIC_SECRET'}):
            with self.subTest(row_type=type(row).__name__):
                with self.assertRaises(ValueError) as caught:
                    self._audit_rows([row])
                self.assertNotIn('SYNTHETIC_SECRET', str(caught.exception))

if __name__=='__main__':unittest.main()
