"""Bounded local research batch; persist metadata only, withhold all text."""
from __future__ import annotations
import collections
import hashlib
import io
import json
import pathlib
import sqlite3
import tempfile
from contextlib import closing
from .operators import process_record, deduplicate, pseudo_id, VERSION


def dump_jsonl(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        for row in data:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')


def load_jsonl(path):
    with open(path, encoding='utf-8') as f:
        yield from _jsonl_rows(f)


def _jsonl_rows(lines):
    for line_number, line in enumerate(lines, 1):
        if line.strip():
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f'Malformed JSONL at line {line_number}') from e


def _export_metadata(record):
    """Allowlist projection: never persist free text or individual lab values."""
    fields = ('record_key', 'patient_group_key', 'encounter_group_key', 'status',
              'quality_score', 'operator_issues', 'phi_pattern_hits',
              'schema_version', 'duplicate_of')
    result = {field: record[field] for field in fields}
    result['lab_count'] = len(record['labs'])
    result['text_withheld'] = True
    return result


def run_pipeline(input_path, output_dir, key, *, synthetic=False) -> dict:
    if not synthetic:
        raise PermissionError('This prototype intentionally refuses to process real patient text. Run synthetic fixtures only; for the public de-identified MIMIC demo use audit-public-demo.')
    # Configuration failures are run failures, never malformed source records.
    pseudo_id('configuration-preflight', key)
    inp = pathlib.Path(input_path)
    out = pathlib.Path(output_dir)
    if not inp.is_file():
        raise FileNotFoundError(inp)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError(f'Refusing to overwrite existing output: {out}')
    # Bounded prototype: hold data in RAM for group-wise dedup. Not distributed or streaming.
    # Hash exactly the byte snapshot that is parsed, not a second read later.
    source_bytes = inp.read_bytes()
    file_hash = hashlib.sha256(source_bytes).hexdigest()
    parsed = []
    raw_errors = 0
    seen_record_keys = set()
    for record in _jsonl_rows(io.StringIO(source_bytes.decode('utf-8'))):
        try:
            processed = process_record(record, key)
        except (ValueError, TypeError, KeyError):
            # Omit malformed raw payload entirely from persisted output.
            raw_errors += 1
            continue
        if processed['record_key'] in seen_record_keys:
            # Never include the source identifier in the error or write a
            # partially successful batch with duplicate database primary keys.
            raise ValueError('Duplicate record_id in input batch')
        seen_record_keys.add(processed['record_key'])
        parsed.append(processed)
    deduplicate(parsed)
    accepted = [r for r in parsed if r['status'] == 'accepted']
    quarantine = [r for r in parsed if r['status'] != 'accepted']
    issues = collections.Counter(issue for r in parsed for issue in r['operator_issues'])
    audit = {'version': VERSION, 'input_rows': len(parsed)+raw_errors,
             'processed_rows': len(parsed), 'malformed_rows_dropped_without_raw_export': raw_errors,
             'accepted_rows': len(accepted), 'quarantined_rows': len(quarantine),
             'duplicate_rows_quarantined': issues['DUPLICATE_WITHIN_PATIENT'],
             'known_pattern_phi_spans_masked': sum(r['phi_pattern_hits'] for r in parsed),
             'accepted_fraction': round(len(accepted)/len(parsed), 4) if parsed else None,
             'operator_issue_counts': dict(sorted(issues.items())),
             'export_policy': 'metadata_only_no_text_or_individual_lab_values',
             'text_rows_withheld': len(parsed),
             'sft_candidates_exported': 0,
             'sft_candidates_withheld': len(accepted),
             'sft_withholding_reason': 'Independent PHI safety acceptance incomplete; all text export disabled.',
             'warnings': ['Research prototype, NOT a certified de-identification system.',
                          'Accepted means operator routing only, not privacy approval or clinical validity.',
                          'All text and SFT candidates are withheld pending independent privacy acceptance.',
                          'Do not send patient data to public APIs; do not treat score as clinical validity.']}
    manifest = {'source_sha256_local_only': file_hash,
                'synthetic_data_mode': synthetic, 'version': VERSION,
                'output_count': len(parsed), 'raw_source_not_copied': True,
                'export_policy': audit['export_policy']}
    out.parent.mkdir(parents=True, exist_ok=True)
    # All writes finish on the same filesystem before one directory rename.
    # File/SQL failures clean the temporary sibling and leave no final output.
    with tempfile.TemporaryDirectory(prefix=f'.{out.name}.staging-', dir=out.parent) as temporary:
        stage = pathlib.Path(temporary)
        dump_jsonl(stage/'accepted.jsonl', map(_export_metadata, accepted))
        dump_jsonl(stage/'quarantine.jsonl', map(_export_metadata, quarantine))
        dump_jsonl(stage/'sft_candidate_UNREVIEWED.jsonl', [])
        (stage/'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
        with closing(sqlite3.connect(stage/'audit.db')) as db:
            with db:
                db.execute('CREATE TABLE records(record_key TEXT PRIMARY KEY, patient_group_key TEXT, encounter_group_key TEXT, status TEXT, quality_score REAL, issue_count INTEGER, lab_count INTEGER)')
                db.executemany('INSERT INTO records VALUES(?,?,?,?,?,?,?)',
                               [(r['record_key'], r['patient_group_key'], r['encounter_group_key'], r['status'], r['quality_score'],
                                 len(r['operator_issues']), len(r['labs'])) for r in parsed])
                db.execute('CREATE INDEX ix_records_status ON records(status)')
        (stage/'provenance.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        if out.exists():
            # rmdir is deliberately nonrecursive: a racing writer's content
            # causes failure rather than being removed or overwritten.
            if not out.is_dir() or any(out.iterdir()):
                raise FileExistsError(f'Refusing to overwrite existing output: {out}')
            out.rmdir()
        stage.rename(out)
    return audit
