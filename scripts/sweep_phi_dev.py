"""Development-set threshold and fusion selection. Never reads the test split.

A single inference pass per model dumps every candidate above a low score floor;
the threshold grid is then evaluated offline, so no extra inference is needed
and the frozen test is never used for tuning.

Selection rule (pre-registered, v2.1 in docs/PHI_EVALUATION_PROTOCOL_CN.md),
applied independently to B, C and D:
  1. maximise entity-level F1;
  2. ties broken by higher recall, then by lower protected-clinical deletion.

v2 used "maximise recall, then F1 within 1 point". On the development frontier
that rule selected the lowest threshold available, which masked 22.8% of
protected clinical characters and modified 100% of hard-negative records, i.e.
it traded away essentially all utility. The rule was changed to F1 before any
test data was read; the full frontier is reported so the recall-first point
remains visible.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from clinforge.artifacts import write_json_no_overwrite
from clinforge.phi_evaluation import record_counts, summarize
from clinforge.phi_models import GLiNEROnnxDetector, PresidioDetector, RuleDetector
from clinforge.phi_rules import find_context_phi, union_spans

ROOT = Path(__file__).resolve().parents[1]
GLINER_FLOOR = .05
PRESIDIO_FLOOR = .0
GLINER_GRID = [round(.05 * i, 2) for i in range(1, 19)]
PRESIDIO_GRID = [round(.1 * i, 2) for i in range(0, 10)]
RECALL_TOLERANCE = .01


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def dump(path, rows):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def decode(candidates, threshold):
    return GLiNEROnnxDetector.decode(candidates, threshold)


def evaluate(rows, predictions_by_doc):
    counts = []
    for row in rows:
        counts.append(record_counts(row, predictions_by_doc[row['doc_id']]))
    result = summarize(counts)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='data/phase2_phi_v1')
    parser.add_argument('--model', default='models/phase2_gliner_pii')
    parser.add_argument('--config', default='configs/phase2_phi_dev.json')
    parser.add_argument('--out', default='reports/phase2_dev_sweep')
    parser.add_argument('--from-sweep', help='Re-apply the selection rule to an existing sweep directory, without new inference')
    args = parser.parse_args(argv)
    data, out = ROOT / args.data, ROOT / args.out
    if out.exists():
        raise FileExistsError('Refusing to overwrite development sweep')
    out.mkdir(parents=True)
    if args.from_sweep:
        previous = (ROOT / args.from_sweep)
        sweep = json.loads((previous / 'sweep.json').read_text(encoding='utf-8'))['rows']
        selection = {'rule': 'max F1; ties by higher recall, then lower protected-clinical deletion',
                     'source': args.from_sweep,
                     'per_method': {method: pick(sweep, method) for method in ('B', 'C', 'D')},
                     'recall_first_alternative': pick(sweep, None, recall_first=True)}
        write_json_no_overwrite(out / 'selection.json', selection)
        print(json.dumps({m: v['chosen'] for m, v in selection['per_method'].items()}, ensure_ascii=False, indent=2))
        return
    config = json.loads((ROOT / args.config).read_text(encoding='utf-8'))
    rows = load(data / 'dev.jsonl')

    timing = {}
    started = time.perf_counter()
    rule = RuleDetector(config)
    predictions_a = {}
    for row in rows:
        predictions_a[row['doc_id']] = rule.find(row['text'])
    timing['A_inference_seconds'] = time.perf_counter() - started

    started = time.perf_counter()
    gliner = GLiNEROnnxDetector(args.model, config)
    timing['C_initialization_seconds'] = time.perf_counter() - started
    started = time.perf_counter()
    gliner_candidates = {}
    for row in rows:
        gliner_candidates[row['doc_id']] = gliner.candidates(row['text'], GLINER_FLOOR)
    timing['C_inference_seconds'] = time.perf_counter() - started

    started = time.perf_counter()
    presidio = PresidioDetector(config)
    timing['B_initialization_seconds'] = time.perf_counter() - started
    started = time.perf_counter()
    presidio_candidates = {}
    for row in rows:
        presidio_candidates[row['doc_id']] = presidio.adapter.analyze(row['text'], PRESIDIO_FLOOR)
    timing['B_inference_seconds'] = time.perf_counter() - started

    rule_spans = {row['doc_id']: find_context_phi(row['text']) for row in rows}

    dump(out / 'candidates_gliner.jsonl', [{'doc_id': row['doc_id'], 'spans': gliner_candidates[row['doc_id']]} for row in rows])
    dump(out / 'candidates_presidio.jsonl', [{'doc_id': row['doc_id'], 'spans': presidio_candidates[row['doc_id']]} for row in rows])
    dump(out / 'predictions_A.jsonl', [{'doc_id': row['doc_id'], 'spans': predictions_a[row['doc_id']]} for row in rows])

    def predictions(groups):
        return {row['doc_id']: union_spans(*[group[row['doc_id']] for group in groups]) for row in rows}

    sweep = []
    for threshold in GLINER_GRID:
        decoded = {row['doc_id']: decode(gliner_candidates[row['doc_id']], threshold) for row in rows}
        metrics = evaluate(rows, decoded)
        sweep.append({'method': 'C', 'gliner_threshold': threshold, 'presidio_threshold': None,
                      'components': ['gliner'], **digest(metrics)})
        d1 = predictions([decoded, rule_spans])
        sweep.append({'method': 'D', 'gliner_threshold': threshold, 'presidio_threshold': None,
                      'components': ['context_rules', 'gliner'], **digest(evaluate(rows, d1))})
        for p_threshold in PRESIDIO_GRID:
            p_decoded = {row['doc_id']: [s for s in presidio_candidates[row['doc_id']] if s['score'] >= p_threshold] for row in rows}
            d2 = predictions([decoded, rule_spans, p_decoded])
            sweep.append({'method': 'D', 'gliner_threshold': threshold, 'presidio_threshold': p_threshold,
                          'components': ['context_rules', 'gliner', 'presidio'], **digest(evaluate(rows, d2))})
            if threshold == GLINER_GRID[0]:
                sweep.append({'method': 'B', 'gliner_threshold': None, 'presidio_threshold': p_threshold,
                              'components': ['presidio'], **digest(evaluate(rows, p_decoded))})

    write_json_no_overwrite(out / 'sweep.json', {'rows': sweep, 'grid': {
        'gliner_floor': GLINER_FLOOR, 'presidio_floor': PRESIDIO_FLOOR,
        'gliner_grid': GLINER_GRID, 'presidio_grid': PRESIDIO_GRID}})

    selection = {'rule': 'max F1; ties by higher recall, then lower protected-clinical deletion',
                 'per_method': {method: pick(sweep, method) for method in ('B', 'C', 'D')},
                 'recall_first_alternative': pick(sweep, None, recall_first=True),
                 'method_A_dev': digest(evaluate(rows, predictions_a)),
                 'timing_seconds': timing,
                 'config': config}
    write_json_no_overwrite(out / 'selection.json', selection)
    print(json.dumps({method: value['chosen'] for method, value in selection['per_method'].items()},
                     ensure_ascii=False, indent=2))


def pick(sweep, method, recall_first=False):
    """Apply the pre-registered selection rule to one method (or to all)."""
    candidates = sweep if method is None else [row for row in sweep if row['method'] == method]
    if not candidates:
        raise ValueError('No candidate configuration for method %s' % method)
    if recall_first:
        best = max(row['recall'] for row in candidates)
        shortlist = [row for row in candidates if row['recall'] >= best - RECALL_TOLERANCE]
        best_f1 = max(row['f1'] for row in shortlist)
        shortlist = [row for row in shortlist if row['f1'] >= best_f1 - 1e-12]
        return {'rule': 'recall first (v2 rule, retained for reporting only)', 'chosen': min(
            shortlist, key=lambda row: row['protected_deletion_rate'])}
    best = max(row['f1'] for row in candidates)
    shortlist = [row for row in candidates if row['f1'] >= best - 1e-12]
    chosen = max(shortlist, key=lambda row: (row['recall'], -row['protected_deletion_rate']))
    return {'rule': 'max F1; ties by higher recall then lower protected-clinical deletion',
            'n_candidates': len(candidates), 'chosen': chosen}


def digest(result):
    return {'recall': result['entity_exact']['recall'], 'precision': result['entity_exact']['precision'],
            'f1': result['entity_exact']['f1'],
            'all_gold_phi_masked_positive_rate': result['all_gold_phi_masked_positive_rate'],
            'all_entities_exact_positive_rate': result['all_entities_exact_positive_rate'],
            'protected_deletion_rate': result['protected_clinical_character_deletion_rate'],
            'non_phi_deletion_rate': result['non_phi_character_deletion_rate'],
            'negative_record_any_redaction_rate': result['negative_record_any_redaction_rate']}


if __name__ == '__main__':
    main()
