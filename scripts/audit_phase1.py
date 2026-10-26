"""Offline, non-overwriting phase-one verification. No external data or APIs."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path

from clinforge.evaluate import baseline_labs, baseline_phi, evaluate
from clinforge.operators import find_phi, parse_labs
from clinforge.pipeline import load_jsonl, run_pipeline
from clinforge.stress import STRESS_TEMPLATES, stress_eval
from clinforge.synthetic import put_value, save_dataset


ROOT = Path(__file__).resolve().parents[1]
KEY = 'synthetic-only-demo-key-2026'


def save(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def score(counts):
    tp, fp, fn = counts
    return {'tp': tp, 'fp': fp, 'fn': fn,
            'precision': round(tp / (tp + fp), 4) if tp + fp else 0,
            'recall': round(tp / (tp + fn), 4) if tp + fn else 0,
            'f1': round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else 0}


def independently_count_metrics(data, gold):
    """Separate counting implementation; uses the same operators and generated gold."""
    rows, labels = list(load_jsonl(data)), list(load_jsonl(gold))
    if len(rows) != len(labels):
        raise AssertionError('Input and gold lengths differ')
    counts = {k: [0, 0, 0] for k in ('baseline_phi', 'pipeline_phi', 'baseline_labs', 'pipeline_labs')}
    errors = []
    for row, label in zip(rows, labels):
        if row['record_id'] != label['record_id']:
            raise AssertionError('Input/gold alignment differs')
        oracle = {(s['label'], s['start'], s['end']) for s in label['phi_spans']}
        for name, spans in [('baseline_phi', baseline_phi(row['text'])),
                            ('pipeline_phi', {(s.label, s.start, s.end) for s in find_phi(row['text'])})]:
            counts[name][0] += len(oracle.intersection(spans))
            counts[name][1] += len(spans.difference(oracle))
            counts[name][2] += len(oracle.difference(spans))
        for name, labs in [('baseline_labs', baseline_labs(row['text'])),
                           ('pipeline_labs', parse_labs(row['text'])[0])]:
            for field in set(labs).union(label['labs']):
                matched = field in labs and field in label['labs'] and math.isclose(
                    labs[field], label['labs'][field], rel_tol=0, abs_tol=.02)
                if matched:
                    counts[name][0] += 1
                else:
                    counts[name][1] += field in labs
                    counts[name][2] += field in label['labs']
                    if name == 'pipeline_labs':
                        errors.append({'record_id': row['record_id'], 'field': field,
                                       'prediction': labs.get(field), 'gold': label['labs'].get(field)})
    return {'metrics': {k: score(v) for k, v in counts.items()}, 'lab_mismatches': errors,
            'scope': 'Independent arithmetic, NOT independent data or annotations.'}


def stress_breakdown():
    """Reused historical diagnostics; deliberately not a new held-out test set."""
    counts = collections.defaultdict(lambda: [0, 0, 0])
    complete = 0
    templates = collections.defaultdict(lambda: {'records': 0, 'fully_masked_records': 0})
    for i in range(60):
        phone = '138' + f'{(371 * i + 1011) % 100000000:08d}'
        if i % 6 == 2:
            phone = phone[:3] + '.' + phone[3:7] + '.' + phone[7:]
        text, gold = put_value(STRESS_TEMPLATES[i % 6], {
            'NAME': ['Alex Taylor', '李若青', '陈佳宁'][i % 3],
            'PHONE': phone, 'MRN': f'EDTEST-{i:06d}'})
        oracle = {(s['label'], s['start'], s['end']) for s in gold}
        predicted = {(s.label, s.start, s.end) for s in find_phi(text)}
        for label in ('NAME', 'PHONE', 'MRN'):
            actual = {s for s in oracle if s[0] == label}
            inferred = {s for s in predicted if s[0] == label}
            counts[label][0] += len(actual & inferred)
            counts[label][1] += len(inferred - actual)
            counts[label][2] += len(actual - inferred)
        # All gold spans must be covered, regardless of the predicted label boundary.
        covered = all(any(p.start <= s['start'] and p.end >= s['end'] for p in find_phi(text)) for s in gold)
        complete += covered
        templates[str(i % 6)]['records'] += 1
        templates[str(i % 6)]['fully_masked_records'] += covered
    return {'n_records': 60, 'n_templates': 6, 'per_label': {k: score(v) for k, v in counts.items()},
            'records_with_all_gold_phi_covered': complete,
            'oracle_record_coverage_rate': round(complete / 60, 4),
            'per_template': dict(templates),
            'limitations': 'Reused synthetic stress diagnostics, 6 repeated templates; no claim of independent generalization or real-world zero-residue safety.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='A new directory; existing paths are rejected')
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    sources = [p for pattern in ('clinforge/*.py', 'scripts/*.py', 'tests/*.py') for p in ROOT.glob(pattern)]
    environment = {'python': sys.version, 'platform': platform.platform(), 'sqlite': sqlite3.sqlite_version,
                   'clock': 'time.perf_counter', 'network_used': False,
                   'code_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in sorted(sources)},
                   'test_command': [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']}
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
    environment['base_git_revision'] = revision.stdout.strip() if revision.returncode == 0 else None
    environment['code_fingerprints_are_authoritative_for_this_run'] = True
    save(out / 'environment.json', environment)
    tests = subprocess.run(environment['test_command'], cwd=ROOT, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding='utf-8')
    with (out / 'unittest.log').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(tests.stdout)
    if tests.returncode:
        save(out / 'FAILED.json', {'test_exit_code': tests.returncode})
        print(tests.stdout)
        return tests.returncode

    original = ROOT / 'examples/generated_fixture'
    corrected = out / 'corrected_fixture_v1'
    save_dataset(corrected, n=600, seed=20261025)
    comparisons = {}
    for name, folder in [('legacy_fixture', original), ('corrected_fixture', corrected)]:
        data, gold = folder / 'synthetic_notes.jsonl', folder / 'gold_annotations.jsonl'
        measured = evaluate(data, gold)
        independent = independently_count_metrics(data, gold)
        names = {'baseline_phi': 'baseline_phi_span_exact', 'pipeline_phi': 'pipeline_phi_span_exact',
                 'baseline_labs': 'baseline_lab_field_exact_with_numeric_tolerance',
                 'pipeline_labs': 'pipeline_lab_field_exact_with_numeric_tolerance'}
        for a, b in names.items():
            if independent['metrics'][a] != measured['metrics'][b]:
                raise AssertionError(f'Metric arithmetic disagreement: {name}/{a}')
        audit = run_pipeline(data, out / (name + '_pipeline'), KEY, synthetic=True)
        save(out / (name + '_benchmark.json'), {'evaluation': measured, 'pipeline_audit': audit,
                                              'independent_arithmetic': independent})
        comparisons[name] = {'source_sha256': hashlib.sha256(data.read_bytes()).hexdigest(),
                             'gold_sha256': hashlib.sha256(gold.read_bytes()).hexdigest(),
                             'n_records': measured['n_records'], 'metrics': measured['metrics'],
                             'lab_mismatch_count': len(independent['lab_mismatches']),
                             'accepted_rows': audit['accepted_rows'], 'quarantined_rows': audit['quarantined_rows']}
    historical = json.loads((ROOT / 'reports/demo_run/synthetic_benchmark.json').read_text(encoding='utf-8'))
    old_rows = list(load_jsonl(original / 'synthetic_notes.jsonl'))
    new_rows = list(load_jsonl(corrected / 'synthetic_notes.jsonl'))
    save(out / 'generator_correction.json', {
        'changed_record_ids': [a['record_id'] for a, b in zip(old_rows, new_rows) if a != b],
        'gold_objects_unchanged': list(load_jsonl(original / 'gold_annotations.jsonl')) == list(load_jsonl(corrected / 'gold_annotations.jsonl')),
        'cause': 'Legacy abnormal T= replacement also matched suffix in ALT=; parser/gold disagreed in six records.',
        'interpretation': 'Any lab metric increase is fixture correction, NOT a new extraction method or independent evaluation.'})
    stress = stress_eval(60)
    save(out / 'stress_eval.json', stress)
    save(out / 'stress_diagnostics.json', stress_breakdown())
    timing = subprocess.run([sys.executable, '-m', 'scripts.benchmark_speed', '--input',
                             str(corrected / 'synthetic_notes.jsonl'), '--out', str(out / 'local_speed.json'),
                             '--reps', '5'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if timing.returncode:
        raise RuntimeError('Speed measurement failed: ' + timing.stderr)
    unchanged = json.loads((ROOT / 'reports/phase1_20261025/baseline/original_file_sha256.json').read_text(encoding='utf-8'))
    preserved = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
                 for name, digest in unchanged.items() if name.startswith(('reports/', 'examples/'))}
    if not all(preserved.values()):
        raise AssertionError('Historical artifact was modified')
    save(out / 'historical_artifact_integrity.json', preserved)
    summary = {'tests_passed': True, 'test_exit_code': tests.returncode,
               'legacy_metric_counts_match_historical': all(comparisons['legacy_fixture']['metrics'][k] == v for k, v in historical['metrics'].items()),
               'stress_matches_historical': stress == json.loads((ROOT / 'reports/stress_eval.json').read_text(encoding='utf-8')),
               'historical_reports_and_examples_preserved': True, 'experiments': comparisons,
               'privacy_release': 'All pipeline record exports are metadata only; text and SFT candidates withheld. Separately saved fixture inputs are explicitly synthetic research data.',
               'independent_phi_acceptance_complete': False,
               'limits': ['Both fixtures have generator-derived gold.', 'No model baseline, medical training, external PHI dataset or real patient input was used.',
                          'Legacy stress set is diagnostic only; do not tune and call it held-out.',
                          'Public MIMIC historical provenance discrepancy is documented separately in public_audit.']}
    if not summary['legacy_metric_counts_match_historical'] or not summary['stress_matches_historical']:
        save(out / 'FAILED.json', {'reason': 'Historical metrics or stress did not reproduce', 'summary': summary})
        raise AssertionError('Historical replay acceptance failed')
    save(out / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
