"""Template-internal self-check of the medical pipeline on synthetic gold.

IMPORTANT: these metrics measure the pipeline against generator gold labels
(template-internal self-check). They are NOT independent clinical extraction
accuracy and are reported separately from the phase-2 independent PHI
benchmark.

Usage: python -m scripts.evaluate_pipeline_synth --out reports/phase3_pipeline_eval
"""
from __future__ import annotations
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.operators import process_record, deduplicate
from clinforge.phi_rules import find_context_phi

ROOT = Path(__file__).resolve().parent.parent
KEY = 'clindataforge-phase3-dedup-eval'


def load_jsonl(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {'precision': None if p is None else round(p, 4),
            'recall': None if r is None else round(r, 4),
            'f1': None if f is None else round(f, 4), 'tp': tp, 'fp': fp, 'fn': fn}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gen', default='data/phase3_synth/gen')
    parser.add_argument('--pipeline', default='data/phase3_synth/pipeline_out')
    parser.add_argument('--out', default='reports/phase3_pipeline_eval')
    args = parser.parse_args(argv)
    out = ROOT / args.out
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    gold = {r['case_id']: r for r in load_jsonl(ROOT / args.gen / 'notes.jsonl')}
    processed = {r['record_id']: r for r in load_jsonl(ROOT / args.pipeline / 'structured.jsonl')}
    processed.update({r['record_id']: r for r in load_jsonl(ROOT / args.pipeline / 'quarantine.jsonl')})

    # ---- phenotype extraction + context --------------------------------
    tp = fp = fn = 0
    status_confusion = collections.Counter()
    per_lang = collections.defaultdict(lambda: [0, 0, 0])
    for cid, g in gold.items():
        p = processed.get(cid)
        if p is None:
            continue
        gold_ents = {(e['start'], e['end'], e['hp_id']): e for e in g['entities'] if e['label'] == 'PHENOTYPE'}
        pred_ents = {(e['start'], e['end'], e['hp_id']): e for e in p['phenotypes']}
        for key in gold_ents.keys() & pred_ents.keys():
            tp += 1
            status_confusion[(gold_ents[key]['status'], pred_ents[key]['status'])] += 1
        fp += len(pred_ents.keys() - gold_ents.keys())
        fn += len(gold_ents.keys() - pred_ents.keys())
        bucket = per_lang[g['language']]
        bucket[0] += len(gold_ents.keys() & pred_ents.keys())
        bucket[1] += len(pred_ents.keys() - gold_ents.keys())
        bucket[2] += len(gold_ents.keys() - pred_ents.keys())
    pheno = prf(tp, fp, fn)
    total_matched = sum(status_confusion.values())
    status_acc = round(sum(v for (g_s, p_s), v in status_confusion.items() if g_s == p_s) / total_matched, 4)

    # ---- disease mentions ----------------------------------------------
    dtp = dfp = dfn = 0
    for cid, g in gold.items():
        p = processed.get(cid)
        if p is None:
            continue
        gold_d = {(e['start'], e['end']) for e in g['entities'] if e['label'] == 'DISEASE'}
        pred_d = {(e['start'], e['end']) for e in p.get('disease_mentions', [])}
        dtp += len(gold_d & pred_d)
        dfp += len(pred_d - gold_d)
        dfn += len(gold_d - pred_d)
    disease = prf(dtp, dfp, dfn)

    # ---- lab standardisation --------------------------------------------
    lab_total = lab_ok = lab_spurious = 0
    lab_by_analyte = collections.defaultdict(lambda: [0, 0, 0])
    for cid, g in gold.items():
        p = processed.get(cid)
        if p is None:
            continue
        gold_labs = [e for e in g['entities'] if e['label'] == 'LAB_VALUE']
        pred_labs = p.get('labs', [])
        used = set()
        for gl in gold_labs:
            lab_total += 1
            found = False
            for i, pl in enumerate(pred_labs):
                if i in used or pl['analyte'] != gl['analyte']:
                    continue
                if abs(pl['value_std'] - gl['value_std']) <= max(0.05, 0.02 * abs(gl['value_std'])):
                    used.add(i)
                    found = True
                    break
            lab_by_analyte[gl['analyte']][0 if found else 1] += 1
            if found:
                lab_ok += 1
        lab_spurious += len(pred_labs) - len(used)
    lab = {'n_gold': lab_total, 'n_correct_std': lab_ok,
           'std_accuracy': round(lab_ok / lab_total, 4) if lab_total else None,
           'n_spurious': lab_spurious,
           'by_analyte': {k: {'correct': v[0], 'missed_or_wrong': v[1]} for k, v in sorted(lab_by_analyte.items())}}

    # ---- PHI gate (template-internal only) -------------------------------
    ptp = pfp = pfn = 0
    for cid, g in gold.items():
        p = processed.get(cid)
        if p is None:
            continue
        gold_phi = {(e['start'], e['end'], e['label']) for e in g['entities']
                    if e['label'] in ('NAME', 'PHONE', 'PATIENT_ID', 'DATE')}
        # pipeline stores masked_text; recover gate spans via lineage count only:
        # exact-span comparison needs raw spans -> stored in quarantine/structured? we
        # approximate with count-level matching plus text masking coverage below.
        pfn += len(gold_phi)
    # coverage check: every gold PHI span must be masked in masked_text
    masked_ok = masked_total = 0
    for cid, g in gold.items():
        p = processed.get(cid)
        if p is None:
            continue
        for e in g['entities']:
            if e['label'] in ('NAME', 'PHONE', 'PATIENT_ID', 'DATE'):
                masked_total += 1
                if e['text'] not in p['masked_text']:
                    masked_ok += 1
    phi_gate = {'gold_phi_entities': pfn,
                'gold_phi_masked_in_output': masked_ok,
                'gold_phi_masking_rate': round(masked_ok / masked_total, 4) if masked_total else None,
                'note': 'template-internal masking coverage on synthetic PHI; independent PHI metrics are in phase-2 reports'}

    # ---- dedup labelled pairs --------------------------------------------
    # The production pipeline deduplicates PHI-MASKED text (dedup runs after
    # the PHI gate), so this evaluation masks gold PHI spans first; evaluating
    # on raw text would penalise the pipeline for header differences it never
    # sees in production.
    notes_by_id = {r['case_id']: r for r in load_jsonl(ROOT / args.gen / 'notes.jsonl')}

    def mask_for_dedup(text):
        """Uniform deterministic mask for BOTH sides of a pair.

        Production dedup runs on hybrid-gated text; this evaluation uses the
        deterministic phase-2 rule layer on both sides (GLiNER omitted for
        speed), so A and B receive identical treatment and any residual PHI
        difference (e.g. undetected names) affects both sides symmetrically.
        """
        for s in sorted(find_context_phi(text), key=lambda x: (x['start'], x['end']),
                        reverse=True):
            text = text[:s['start']] + '<' + s['label'] + '>' + text[s['end']:]
        return text

    pairs = load_jsonl(ROOT / args.gen / 'dedup_pairs.jsonl')
    dedup_conf = collections.Counter()
    per_kind = collections.defaultdict(collections.Counter)
    mask_sources = collections.Counter()
    for pair in pairs:
        rows = []
        for suffix in ('a', 'b'):
            masked = mask_for_dedup(pair['text_' + suffix])
            mask_sources['phase2_context_rules'] += 1
            rows.append(process_record(
                {'record_id': pair['pair_id'] + '-' + suffix,
                 'patient_group': pair['patient_group'],
                 'encounter_group': pair['encounter_' + suffix],
                 'text': masked}, KEY))
        deduplicate(rows)
        predicted = 'DUPLICATE' if rows[1].get('duplicate_of') else 'NOT_DUPLICATE'
        dedup_conf[(pair['gold'], predicted)] += 1
        per_kind[pair['kind']][(pair['gold'], predicted)] += 1
    d_tp = dedup_conf[('DUPLICATE', 'DUPLICATE')]
    d_fp = dedup_conf[('NOT_DUPLICATE', 'DUPLICATE')]
    d_fn = dedup_conf[('DUPLICATE', 'NOT_DUPLICATE')]
    dedup = prf(d_tp, d_fp, d_fn)
    dedup['masking_protocol'] = ('both sides masked with the deterministic phase-2 context-rule '
                                 'layer (find_context_phi) as a fast approximation of the '
                                 'production hybrid gate; GLiNER omitted for evaluation speed')
    dedup['mask_sources'] = dict(mask_sources)
    dedup['per_kind'] = {k: {f'{g_}->{p_}': c for (g_, p_), c in v.items()}
                         for k, v in per_kind.items()}
    dedup['per_kind_correct'] = {k: round(sum(c for (g_, p_), c in v.items() if g_ == p_) / sum(v.values()), 4)
                                 for k, v in per_kind.items()}

    # ---- stage performance from lineage ----------------------------------
    stage_ms = collections.defaultdict(list)
    for row in load_jsonl(ROOT / args.pipeline / 'lineage.jsonl'):
        for entry in row['lineage']:
            if 'ms' in entry:
                stage_ms[entry['stage']].append(entry['ms'])
    perf = {stage: {'mean_ms': round(sum(v) / len(v), 3),
                    'p95_ms': round(sorted(v)[int(0.95 * (len(v) - 1))], 2),
                    'n': len(v)} for stage, v in sorted(stage_ms.items())}

    report = {
        'evaluation_scope': 'template-internal self-check on generator gold labels; NOT independent clinical accuracy',
        'n_records_evaluated': len(processed),
        'phenotype_extraction': pheno,
        'phenotype_extraction_by_language': {k: prf(*v) for k, v in per_lang.items()},
        'context_status_accuracy_on_matched': status_acc,
        'context_confusion_top': [{'gold': k[0], 'pred': k[1], 'n': v}
                                  for k, v in status_confusion.most_common(12)],
        'disease_mention_extraction': disease,
        'lab_standardisation': lab,
        'phi_gate_synthetic': phi_gate,
        'dedup_pairs': dedup,
        'stage_performance': perf,
    }
    (out / 'pipeline_eval.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
