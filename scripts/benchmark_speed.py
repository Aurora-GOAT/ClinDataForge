"""Local throughput; fixed input, fresh temporary outputs, environment-specific only."""
import argparse
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from clinforge.artifacts import write_json_no_overwrite
from clinforge.pipeline import run_pipeline


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="examples/generated_fixture/synthetic_notes.jsonl")
    parser.add_argument("--out", default="reports/local_speed.json")
    parser.add_argument("--reps", type=int, default=5)
    args = parser.parse_args(argv)
    if args.reps < 1:
        parser.error("--reps must be positive")
    if Path(args.out).exists():
        raise FileExistsError("Refusing to overwrite existing speed artifact")
    counts, seconds = [], []
    for _ in range(args.reps):
        with tempfile.TemporaryDirectory() as folder:
            started = time.perf_counter()
            audit = run_pipeline(args.input, Path(folder) / "out", "synthetic-only-demo-key-2026", synthetic=True)
            seconds.append(time.perf_counter() - started)
            counts.append(audit["processed_rows"])
    result = {
        "repetitions": args.reps, "rows_per_repetition": counts[0],
        "wall_seconds_each": seconds,
        "median_wall_seconds": statistics.median(seconds),
        "median_rows_per_second": statistics.median(count / sec for count, sec in zip(counts, seconds)),
        "input_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
        "environment": {"python": sys.version, "platform": platform.platform()},
        "includes": "read JSONL, parse, within-encounter dedup, metadata-only JSONL+SQLite+audit; text export disabled",
        "limitations": ["Small synthetic input fits RAM; do not extrapolate to distributed or TB-scale data.",
            "Local single-process benchmark, environment and disk specific.",
            "Output policy and software revision affect cost; compare only matching configurations."]}
    write_json_no_overwrite(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
