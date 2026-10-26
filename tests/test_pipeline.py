import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from clinforge.synthetic import make_dataset,save_dataset
from clinforge.pipeline import run_pipeline,load_jsonl
from clinforge.evaluate import evaluate
from clinforge.stress import stress_eval

class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def fixture(self):
        save_dataset(self.base/'input',n=45)
        return self.base/'input'
    def test_deterministic_generator(self):
        a=make_dataset(40,2026)
        b=make_dataset(40,2026)
        self.assertEqual(a,b)
    def test_diff_seed(self):
        self.assertNotEqual(make_dataset(40,1)[0],make_dataset(40,2)[0])
    def test_eval_has_three_metrics(self):
        folder=self.fixture()
        m=evaluate(folder/'synthetic_notes.jsonl',folder/'gold_annotations.jsonl')
        self.assertEqual(m['n_patient_groups'],45)
        self.assertIn('pipeline_phi_span_exact',m['metrics'])
        self.assertTrue(m['split_group_integrity_verified'])
    def test_outputs_and_sqlite(self):
        folder=self.fixture()
        r=run_pipeline(folder/'synthetic_notes.jsonl',self.base/'out','synthetic-only-demo-key-2026',synthetic=True)
        self.assertEqual(r['processed_rows'],len(list(load_jsonl(folder/'synthetic_notes.jsonl'))))
        self.assertEqual(r['accepted_rows']+r['quarantined_rows'],r['processed_rows'])
        # The connection must be closed explicitly: `with connect(...)` only
        # commits, and an open handle keeps the file locked on Windows, which
        # makes TemporaryDirectory cleanup fail and masks the real result.
        connection = sqlite3.connect(self.base / 'out' / 'audit.db')
        try:
            n = connection.execute('SELECT count(*) FROM records').fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(n,r['processed_rows'])
        first=next(load_jsonl(self.base/'out'/'accepted.jsonl'))
        self.assertNotIn('subject_id',first)
        self.assertNotIn('masked_text',first)
        self.assertNotIn('complaint',first)
        self.assertNotIn('labs',first)
        self.assertTrue(first['text_withheld'])
        self.assertGreater(first['lab_count'],0)
    def test_run_repeat_refuses_overwrite(self):
        folder=self.fixture(); out=self.base/'out'
        run_pipeline(folder/'synthetic_notes.jsonl',out,'synthetic-only-demo-key-2026',synthetic=True)
        with self.assertRaises(FileExistsError):
            run_pipeline(folder/'synthetic_notes.jsonl',out,'synthetic-only-demo-key-2026',synthetic=True)
    def test_real_text_refused(self):
        folder=self.fixture()
        with self.assertRaises(PermissionError):
            run_pipeline(folder/'synthetic_notes.jsonl',self.base/'out','this-is-secure-key',synthetic=False)
    def test_invalid_raw_not_exported(self):
        folder=self.base/'input';folder.mkdir()
        (folder/'bad.jsonl').write_text('{"record_id":"R1","patient_group":"P","encounter_group":"E","text":"short"}\n{"text":"no ids"}\n',encoding='utf-8')
        r=run_pipeline(folder/'bad.jsonl',self.base/'out','synthetic-only-demo-key-2026',synthetic=True)
        self.assertEqual(r['malformed_rows_dropped_without_raw_export'],1)
    def test_malformed_jsonl_raises_without_copy(self):
        folder=self.base/'input';folder.mkdir()
        (folder/'bad.jsonl').write_text('NOT JSON\n',encoding='utf-8')
        with self.assertRaises(ValueError):
            run_pipeline(folder/'bad.jsonl',self.base/'out','synthetic-only-demo-key-2026',synthetic=True)
    def test_never_output_gold_labels(self):
        folder=self.fixture()
        run_pipeline(folder/'synthetic_notes.jsonl',self.base/'out','synthetic-only-demo-key-2026',synthetic=True)
        out=' '.join(f.read_text(encoding='utf-8') for f in (self.base/'out').glob('*.jsonl'))
        self.assertNotIn('gold_annotations',out)
        self.assertNotIn('phi_spans',out)
    def test_sft_candidates_withheld(self):
        folder=self.fixture()
        audit=run_pipeline(folder/'synthetic_notes.jsonl',self.base/'out','synthetic-only-demo-key-2026',synthetic=True)
        a=list(load_jsonl(self.base/'out'/'accepted.jsonl'))
        b=list(load_jsonl(self.base/'out'/'sft_candidate_UNREVIEWED.jsonl'))
        self.assertEqual(b,[])
        self.assertEqual(audit['sft_candidates_withheld'],len(a))
        self.assertEqual(audit['sft_candidates_exported'],0)
        self.assertIn('privacy acceptance',audit['warnings'][2])
    def test_stress_lower_than_template(self):
        s=stress_eval(60)
        self.assertLess(s['pipeline_phi_span_exact']['recall'],1.0)
        self.assertGreater(s['pipeline_phi_span_exact']['recall'],0)

if __name__=='__main__':unittest.main()
