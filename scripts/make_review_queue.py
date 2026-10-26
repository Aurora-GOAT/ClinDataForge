"""Create a metadata-only review queue. No text or human labels are exported."""
import argparse
import csv
import re
from pathlib import Path
from clinforge.pipeline import load_jsonl

ISSUE_CODES = frozenset(("TEXT_TOO_SHORT", "NO_SUPPORTED_LAB", "NO_SUPPORTED_COMPLAINT",
    "UNMASKED_KNOWN_PATTERN", "DUPLICATE_WITHIN_PATIENT", "PRIVACY_NOT_INDEPENDENTLY_VALIDATED",
    "TEXT_EXPORT_BLOCKED", "PHI_COVERAGE_UNVERIFIED")) | frozenset(
    prefix + field for prefix in ("AMBIGUOUS_MULTIPLE_", "OUT_OF_BROAD_RANGE_")
    for field in ("TEMP_C", "GLUCOSE_MMOL_L", "HEMOGLOBIN_G_L", "ALT_U_L"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="reports/demo_run/quarantine.jsonl")
    parser.add_argument("--out", default="reports/demo_run/review_queue_40.csv")
    parser.add_argument("--limit", type=int, default=40)
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit must be non-negative")
    # Allowlist every persisted field, including inputs from historical artifacts.
    records = []
    for record in load_jsonl(args.source):
        key = record.get("record_key")
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{16,64}", key):
            raise ValueError("Review source requires pseudonymous hexadecimal record keys")
        issues = record.get("operator_issues", [])
        safe_issues = sorted({issue if isinstance(issue, str) and issue in ISSUE_CODES else "OTHER" for issue in issues})
        score = record.get("quality_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
            raise ValueError("Review source has invalid quality score")
        records.append({"record_key": key, "quality_score": score, "issues": ";".join(safe_issues)})
    records.sort(key=lambda row: (-(len(row["issues"].split(";")) if row["issues"] else 0), row["quality_score"], row["record_key"]))
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8-sig", newline="") as stream:
        columns = ["record_key", "quality_score", "issues", "annotator_reject", "annotator_reason", "reviewer_id"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records[:args.limit])
    print(f"Created {min(args.limit, len(records))} metadata-only review rows; no text or labels exported.")


if __name__ == "__main__":
    main()
