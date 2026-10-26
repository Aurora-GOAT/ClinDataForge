"""Synthetic regression canaries; these are not a PHI generalization benchmark."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from clinforge.pipeline import load_jsonl, run_pipeline


KEY = 'synthetic-regression-key-2026'
CANARY = 'SYNTHETIC-PRIVATE-CANARY-71'


class PrivacyBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / (CANARY + '.jsonl')
        self.output = self.root / 'out'

    def tearDown(self):
        self.temp.cleanup()

    def record(self, **changes):
        row = {'record_id': 'R1', 'patient_group': 'P1', 'encounter_group': 'E1',
               'text': f'Name={CANARY} | mail={CANARY}@example.invalid | Complaint: headache | T=37°C',
               'source_type': {'untrusted_free_text': CANARY}}
        row.update(changes)
        return row

    def write_rows(self, rows):
        self.source.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')

    def assert_no_final_or_staging(self):
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob('.out.staging-*')), [])

    def test_all_persisted_artifacts_withhold_unknown_phi_and_free_metadata(self):
        rows = [self.record(record_id=CANARY, patient_group=CANARY, encounter_group=CANARY),
                self.record(record_id='R2', text=f'{CANARY}; Complaint: {CANARY}')]
        self.write_rows(rows)
        audit = run_pipeline(self.source, self.output, KEY, synthetic=True)
        self.assertEqual(audit['accepted_rows'], 1)
        self.assertEqual(audit['quarantined_rows'], 1)
        self.assertEqual(audit['text_rows_withheld'], 2)
        self.assertEqual(audit['sft_candidates_withheld'], 1)
        self.assertEqual((self.output/'sft_candidate_UNREVIEWED.jsonl').read_bytes(), b'')
        for artifact in self.output.iterdir():
            with self.subTest(artifact=artifact.name):
                self.assertNotIn(CANARY.encode(), artifact.read_bytes())
        for filename in ('accepted.jsonl', 'quarantine.jsonl'):
            for row in load_jsonl(self.output/filename):
                self.assertFalse({'text', 'masked_text', 'complaint', 'source_type', 'labs'} & row.keys())
                self.assertTrue(row['text_withheld'])
        provenance = json.loads((self.output/'provenance.json').read_text(encoding='utf-8'))
        self.assertNotIn('source_basename', provenance)
        self.assertEqual(provenance['source_sha256_local_only'], hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_non_synthetic_flag_cannot_be_bypassed_with_valid_key(self):
        self.write_rows([self.record()])
        with self.assertRaises(PermissionError):
            run_pipeline(self.source, self.output, KEY, synthetic=False)
        self.assert_no_final_or_staging()

    def test_bad_key_fails_before_any_output(self):
        self.write_rows([self.record()])
        for key in ('', 'short', None, 123):
            with self.subTest(key=key), self.assertRaises(ValueError):
                run_pipeline(self.source, self.output, key, synthetic=True)
            self.assert_no_final_or_staging()

    def test_malformed_schema_rows_drop_without_echo_or_crash(self):
        rows = [self.record(), [], None, {'text': CANARY},
                self.record(record_id=' '), self.record(record_id='R2', patient_group='')]
        self.write_rows(rows)
        audit = run_pipeline(self.source, self.output, KEY, synthetic=True)
        self.assertEqual(audit['input_rows'], 6)
        self.assertEqual(audit['processed_rows'], 1)
        self.assertEqual(audit['malformed_rows_dropped_without_raw_export'], 5)
        self.assertTrue(all(CANARY.encode() not in p.read_bytes() for p in self.output.iterdir()))

    def test_duplicate_identifiers_fail_without_partial_output_or_raw_error(self):
        self.write_rows([self.record(record_id=CANARY), self.record(record_id=CANARY)])
        with self.assertRaisesRegex(ValueError, 'Duplicate record_id') as error:
            run_pipeline(self.source, self.output, KEY, synthetic=True)
        self.assertNotIn(CANARY, str(error.exception))
        self.assert_no_final_or_staging()

    def test_malformed_json_after_valid_record_leaves_no_output(self):
        self.write_rows([self.record()])
        with self.source.open('a', encoding='utf-8') as handle:
            handle.write('not-json\n')
        with self.assertRaisesRegex(ValueError, 'line 2'):
            run_pipeline(self.source, self.output, KEY, synthetic=True)
        self.assert_no_final_or_staging()

    def test_file_write_failure_leaves_no_partial_output(self):
        self.write_rows([self.record()])
        with mock.patch('clinforge.pipeline.dump_jsonl', side_effect=OSError('synthetic injected write failure')):
            with self.assertRaises(OSError):
                run_pipeline(self.source, self.output, KEY, synthetic=True)
        self.assert_no_final_or_staging()

    def test_sql_failure_after_file_writes_leaves_no_partial_output(self):
        self.write_rows([self.record()])
        with mock.patch('clinforge.pipeline.sqlite3.connect', side_effect=sqlite3.OperationalError('synthetic injected SQL failure')):
            with self.assertRaises(sqlite3.OperationalError):
                run_pipeline(self.source, self.output, KEY, synthetic=True)
        self.assert_no_final_or_staging()

    def test_existing_empty_output_directory_can_be_published(self):
        self.write_rows([self.record()])
        self.output.mkdir()
        run_pipeline(self.source, self.output, KEY, synthetic=True)
        self.assertTrue((self.output/'audit.db').is_file())
        self.assertEqual(list(self.root.glob('.out.staging-*')), [])

    def test_existing_nonempty_output_is_never_overwritten(self):
        self.write_rows([self.record()])
        self.output.mkdir()
        previous = self.output/'existing.txt'
        previous.write_text('preserve prior evidence', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            run_pipeline(self.source, self.output, KEY, synthetic=True)
        self.assertEqual(previous.read_text(encoding='utf-8'), 'preserve prior evidence')


if __name__ == '__main__':
    unittest.main()
