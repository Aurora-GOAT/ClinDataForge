"""Post-optimisation re-read of the frozen phase-2 PHI test split.

Purpose: verify that the throughput work (fp32 weights, batched inference,
more intra-op threads) did not change what the gate finds. This is a regression
check, not a new experiment:

  * the data file must hash to the value recorded in the frozen experiment;
  * the threshold, prompts, chunking and fusion are unchanged;
  * methods C and D are re-run and compared span-by-span with the frozen
    predictions that produced the published phase-2 numbers;
  * metrics are recomputed with the same evaluation code and printed next to the
    frozen values, so any difference is visible rather than assumed away.

The frozen phase-2 result stays the primary reported number. This run exists
because a performance change that silently changes recall would be a defect.

Usage:
  .venv-phi python -m scripts.evaluate_phi_optimized \
      --config configs/phase4_phi_fast.json --out reports/phase4_perf/test_run_fast
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clinforge.phi_evaluation import normalize_spans, record_counts, summarize  # noqa: E402
from clinforge.phi_experiment import sha256  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / 'reports/phase2_phi_v1/test_run'


def load_jsonl(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='data/phase2_phi_v1')
    parser.add_argument('--config', default='configs/phase4_phi_fast.json')
    parser.add_argument('--model', default='models/phase2_gliner_pii')
    parser.add_argument('--methods', default='C,D')
    parser.add_argument('--limit', type=int, default=0,
                        help='debug only: evaluate the first N test rows (0 = all)')
    parser.add_argument('--out', default='reports/phase4_perf/test_run_fast')
    args = parser.parse_args(argv)

    out = ROOT / args.out
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)

    frozen_results = json.loads((FROZEN / 'results.json').read_text(encoding='utf-8'))
    data_sha = sha256(ROOT / args.data / 'test.jsonl')
    if data_sha != frozen_results['dataset_sha256']:
        raise SystemExit('Test split differs from the frozen experiment; refusing to compare')

    rows = load_jsonl(ROOT / args.data / 'test.jsonl')
    if args.limit:
        rows = rows[:args.limit]
    config = json.loads((ROOT / args.config).read_text(encoding='utf-8'))
    from clinforge.phi_models import create_detector

    report = {'data_sha256': data_sha, 'config': config, 'methods': {}}
    for method in args.methods.split(','):
        started = time.perf_counter()
        detector = create_detector(method, ROOT / args.model, config)
        warmup = load_jsonl(ROOT / args.data / 'train.jsonl')[0]
        detector.find(warmup['text'])
        per_doc, predictions = [], []
        batch = int(config.get('batch_size', 1) or 1)
        for begin in range(0, len(rows), batch):
            group = rows[begin:begin + batch]
            tick = time.perf_counter()
            spans_list = detector.find_many([row['text'] for row in group])
            share = (time.perf_counter() - tick) / len(group)
            for row, spans in zip(group, spans_list):
                clean = normalize_spans(spans, row['text'])
                per_doc.append(share)
                predictions.append({'doc_id': row['doc_id'],
                                    'spans': [{'label': label, 'start': start, 'end': end}
                                              for label, start, end in clean]})
        wall = time.perf_counter() - started
        with open(out / f'{method}_predictions.jsonl', 'w', encoding='utf-8') as handle:
            for row in predictions:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')

        # ---- metrics, same code path as phase 2 -------------------------
        counts = []
        for row, prediction in zip(rows, predictions):
            counts.append(record_counts(row, prediction['spans']))
        summary = summarize(counts)

        # ---- span-level agreement with the frozen predictions ----------
        frozen = {json.loads(line)['doc_id']: {(s['label'], s['start'], s['end'])
                                               for s in json.loads(line)['spans']}
                  for line in open(FROZEN / method / 'predictions.jsonl', encoding='utf-8')}
        identical = only_frozen = only_new = 0
        differing_docs = []
        for prediction in predictions:
            doc = prediction['doc_id']
            current = {(s['label'], s['start'], s['end']) for s in prediction['spans']}
            base = frozen.get(doc, set())
            if current == base:
                identical += 1
            else:
                only_frozen += len(base - current)
                only_new += len(current - base)
                if len(differing_docs) < 8:
                    differing_docs.append({'doc_id': doc,
                                           'missing_vs_frozen': sorted(base - current)[:5],
                                           'added_vs_frozen': sorted(current - base)[:5]})
        result = {
            'method': method,
            'metrics_optimized': summary,
            'metrics_frozen': frozen_results['methods'][method]['overall'],
            'documents': len(predictions),
            'docs_identical_to_frozen': identical,
            'doc_identity_rate': round(identical / len(predictions), 4),
            'spans_missing_vs_frozen': only_frozen,
            'spans_added_vs_frozen': only_new,
            'differing_docs_examples': differing_docs,
            'mean_ms_per_doc': round(sum(per_doc) / len(per_doc) * 1000, 1),
            'p95_ms_per_doc': round(sorted(per_doc)[int(.95 * len(per_doc)) - 1] * 1000, 1),
            'docs_per_second': round(len(rows) / sum(per_doc), 3),
            'wall_seconds_including_init': round(wall, 2),
            'detector_metadata': detector.metadata,
        }
        report['methods'][method] = result
        print(json.dumps({k: result[k] for k in ('method', 'metrics_optimized', 'metrics_frozen',
                                                 'doc_identity_rate', 'spans_missing_vs_frozen',
                                                 'spans_added_vs_frozen', 'mean_ms_per_doc',
                                                 'p95_ms_per_doc')}, ensure_ascii=False, indent=1))
        detector.close()

    (out / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
