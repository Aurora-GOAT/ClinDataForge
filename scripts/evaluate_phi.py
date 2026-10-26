"""Run A/B/C on the same documents; formal test requires a frozen lock."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from clinforge.artifacts import write_json_no_overwrite
from clinforge.phi_evaluation import error_rows, paired_bootstrap, record_counts, summarize
from clinforge.phi_experiment import ROOT, load_json, sha256, validate_lock

METHODS = ('A', 'B', 'C', 'D')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--runtime', default=sys.executable)
    parser.add_argument('--split', choices=('dev', 'test'), default='dev')
    parser.add_argument('--lock')
    parser.add_argument('--replay-frozen', action='store_true')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    out, data = Path(args.out).resolve(), Path(args.data).resolve()
    if out.exists():
        raise FileExistsError('Refusing to overwrite PHI experiment')
    lock = None
    if args.split == 'test':
        if not args.lock:
            raise PermissionError('Formal test requires frozen source/config/data/model lock')
        lock = load_json(args.lock)
        validate_lock(lock, data, args.config, args.model)
        if lock['protocol_sha256'] != sha256(ROOT / lock['protocol']):
            raise ValueError('Frozen evaluation protocol differs')
        marker = Path(args.lock).with_suffix('.first_test_started.json')
        if marker.exists() and not args.replay_frozen:
            raise PermissionError('Test has already been consumed; only identical frozen replay is allowed')
        if not marker.exists():
            write_json_no_overwrite(marker, {'lock_sha256': sha256(args.lock),
                'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'note': 'Do not use resulting test errors to change this method/configuration.'})
    out.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    for method in METHODS:
        command = [args.runtime, '-m', 'scripts.phi_worker', '--method', method,
                   '--input', str(data / (args.split + '.jsonl')), '--warmup', str(data / 'train.jsonl'),
                   '--config', str(Path(args.config).resolve()), '--model', str(Path(args.model).resolve()),
                   '--out', str(out / method)]
        with (out / (method + '_worker.log')).open('x', encoding='utf-8') as log:
            run = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
        if run.returncode:
            write_json_no_overwrite(out / 'FAILED.json', {'method': method, 'exit_code': run.returncode,
                'note': 'No simulated model results. Existing artifacts preserved; method failure is not a skipped document.'})
            raise RuntimeError('Local method failed: ' + method)
    rows = [json.loads(line) for line in (data / (args.split + '.jsonl')).read_text(encoding='utf-8').splitlines() if line.strip()]
    metrics, counts_by_method = {}, {}
    for method in METHODS:
        predictions = [json.loads(line) for line in (out / method / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
        if [r['doc_id'] for r in rows] != [r['doc_id'] for r in predictions]:
            raise AssertionError('Predictions must cover every document in the same order')
        counts, errors = [], []
        for row, predicted in zip(rows, predictions):
            counts.append(record_counts(row, predicted['spans']))
            errors.extend(error_rows(row, predicted['spans']))
        counts_by_method[method] = counts
        with (out / method / 'sufficient_statistics.jsonl').open('x', encoding='utf-8', newline='\n') as stream:
            for count in counts:
                stream.write(json.dumps(count, ensure_ascii=False, allow_nan=False) + '\n')
        write_json_no_overwrite(out / method / 'errors.json', errors)
        metrics[method] = {'overall': summarize(counts),
            'by_language': {lang: summarize(c for c in counts if c['language'] == lang) for lang in sorted({r['language'] for r in rows})},
            'performance': load_json(out / method / 'performance.json')}
    comparisons = {}
    if args.split == 'test':
        for left, right in (('A', 'B'), ('A', 'C'), ('A', 'D'), ('B', 'D'), ('C', 'D')):
            comparisons[right + '_minus_' + left] = paired_bootstrap(
                counts_by_method[left], counts_by_method[right], reps=lock['bootstrap_reps'], seed=lock['bootstrap_seed'])
    write_json_no_overwrite(out / 'results.json', {'split': args.split,
        'dataset_sha256': sha256(data / (args.split + '.jsonl')),
        'config_sha256': sha256(args.config), 'lock_sha256': sha256(args.lock) if lock else None,
        'methods': metrics, 'paired_cluster_bootstrap': comparisons,
        'limits': ['Synthetic data and machine labels; no independent clinician adjudication.',
                  'All-gold coverage is not proof that unlabelled PHI is absent.',
                  'The formal test was not used to select the method threshold or rules.']})
    print(json.dumps({method: value['overall']['entity_exact'] for method, value in metrics.items()}, indent=2))


if __name__ == '__main__':
    main()
