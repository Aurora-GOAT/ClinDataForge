import argparse
import json
from pathlib import Path
from clinforge.artifacts import write_json_no_overwrite
from clinforge.evaluate import evaluate
from clinforge.pipeline import run_pipeline


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="examples/generated_fixture")
    parser.add_argument("--out", default="reports/demo_run")
    args = parser.parse_args(argv)
    result = evaluate(Path(args.data) / "synthetic_notes.jsonl", Path(args.data) / "gold_annotations.jsonl")
    result["pipeline_audit"] = run_pipeline(Path(args.data) / "synthetic_notes.jsonl", args.out,
        "synthetic-only-demo-key-2026", synthetic=True)
    write_json_no_overwrite(Path(args.out) / "synthetic_benchmark.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
