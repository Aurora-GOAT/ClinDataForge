import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from clinforge.artifacts import write_json_no_overwrite
from scripts import benchmark_speed, make_review_queue, render_dashboard, run_stress


class ArtifactSafetyTest(unittest.TestCase):
    def test_json_exclusive_create_preserves_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.json"
            write_json_no_overwrite(path, {"version": "first"})
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_json_no_overwrite(path, {"version": "second"})
            self.assertEqual(path.read_bytes(), original)

    def test_nonfinite_json_rejected_before_file_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            for value in (float("nan"), float("inf"), -float("inf")):
                path = Path(folder) / "invalid.json"
                with self.assertRaises(ValueError):
                    write_json_no_overwrite(path, {"measurement": value})
                self.assertFalse(path.exists())

    def test_stress_and_speed_refuse_existing_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.json"
            path.write_text("historical", encoding="utf-8")
            for entrypoint in (run_stress.main, benchmark_speed.main):
                with self.assertRaises(FileExistsError):
                    entrypoint(["--out", str(path)])
                self.assertEqual(path.read_text(encoding="utf-8"), "historical")

    def _benchmark(self):
        return {"metrics": {"test": {"precision": 1, "recall": 1, "f1": 1, "tp": 1, "fp": 0, "fn": 0}},
            "pipeline_audit": {"input_rows": 1, "processed_rows": 1, "accepted_rows": 0,
                "quarantined_rows": 1, "operator_issue_counts": {}}}

    def test_dashboard_uses_explicit_reports_and_dynamic_counts(self):
        benchmark = self._benchmark()
        document = render_dashboard.render_dashboard(benchmark)
        self.assertNotIn("MIMIC", document)
        self.assertNotIn("指定的合成压力测试", document)
        stress = {"n_cases": 7, "n_phi_gold": 21, "pipeline_phi_span_exact":
            {"precision": 1, "recall": 0.5, "f1": 0.6667, "fn": 10}}
        document = render_dashboard.render_dashboard(benchmark, stress=stress)
        self.assertIn("7条病例", document)
        self.assertIn("21个PHI标注", document)
        self.assertNotIn("60条", document)
        self.assertNotIn("180个", document)

    def test_dashboard_escapes_report_metadata(self):
        benchmark = self._benchmark()
        benchmark["pipeline_audit"]["input_rows"] = '<script>alert(1)</script>'
        document = render_dashboard.render_dashboard(benchmark)
        self.assertNotIn('<script>', document)
        self.assertIn('&lt;script&gt;', document)

    def test_dashboard_exclusive_write(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "benchmark.json", Path(folder) / "dashboard.html"
            write_json_no_overwrite(source, self._benchmark())
            output.write_text("historical", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                render_dashboard.main(["--benchmark", str(source), "--out", str(output)])
            self.assertEqual(output.read_text(encoding="utf-8"), "historical")

    def test_review_queue_never_exports_text_or_unknown_issue_strings(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "input.jsonl", Path(folder) / "queue.csv"
            source.write_text(json.dumps({"record_key": "a" * 20, "quality_score": 0.8,
                "operator_issues": ["SYNTHETIC_SECRET_ISSUE"], "masked_text": "SYNTHETIC_SECRET_TEXT"}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                make_review_queue.main(["--source", str(source), "--out", str(output)])
            content = output.read_text(encoding="utf-8-sig")
            self.assertNotIn("SYNTHETIC_SECRET", content)
            self.assertNotIn("masked_excerpt", content)
            self.assertIn("OTHER", content)
            with self.assertRaises(FileExistsError):
                make_review_queue.main(["--source", str(source), "--out", str(output)])

    def test_review_queue_rejects_non_pseudonymous_key_without_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "input.jsonl", Path(folder) / "queue.csv"
            source.write_text(json.dumps({"record_key": "SYNTHETIC_NAME", "quality_score": 0.8,
                "operator_issues": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                make_review_queue.main(["--source", str(source), "--out", str(output)])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
