"""Export SFT / preference data CANDIDATES from accepted synthetic records.

Scope and honesty constraints:
  * source = pipeline-accepted SYNTHETIC records only (never real patient text);
  * outputs are *candidates*: preference 'rejected' responses are produced by
    documented programmatic corruption rules, NOT human preference labels;
  * splits are patient-group hashed (each synthetic case is its own patient)
    with the disease set shared across splits (documented: this measures
    formatting, not generalisation to unseen diseases);
  * nothing here claims an executed SFT/LoRA/DPO run.

Usage: python -m scripts.export_training_candidates --out data/phase3_synth/training_candidates
"""
from __future__ import annotations
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
EXPORT_VERSION = 'sft-export-2.0.0'

INSTRUCTION = ('从以下合成病历中抽取结构化信息：列出全部医学表型（含 HPO 编码与状态：'
               'affirmed/suspected/history/negated）与检验结果（标准化单位）。仅输出 JSON。')


def load_jsonl(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def canonical_output(record):
    return json.dumps({
        'disease_suspected': record.get('disease_id'),
        'phenotypes': [{'hp_id': p['hp_id'], 'status': p['status']} for p in record['phenotypes']],
        'labs': [{'analyte': l['analyte'], 'value': l['value_std'], 'unit': l['unit_std']}
                 for l in record['labs']],
    }, ensure_ascii=False, sort_keys=True)


def corrupt(record, rng, kb):
    """Documented programmatic corruption for preference 'rejected' samples.

    The hallucinated phenotype is drawn from HPO terms that are NOT annotated for
    the record's disease. v1 hard-coded Fever (HP:0001945), which is a genuine
    annotation for 22 of the exported cases, so those 'rejected' answers were in
    fact acceptable - a measured 0.94% label-noise rate. Fixed in sft-export-2.0.0.
    """
    kind = rng.choice(['flip_status', 'drop_phenotype', 'wrong_lab', 'hallucinate_phenotype'])
    out = json.loads(canonical_output(record))
    if kind == 'flip_status' and out['phenotypes']:
        i = rng.randrange(len(out['phenotypes']))
        cur = out['phenotypes'][i]['status']
        out['phenotypes'][i]['status'] = {'affirmed': 'negated', 'negated': 'affirmed',
                                          'suspected': 'affirmed', 'history': 'affirmed'}[cur]
    elif kind == 'drop_phenotype' and len(out['phenotypes']) > 1:
        out['phenotypes'].pop(rng.randrange(len(out['phenotypes'])))
    elif kind == 'wrong_lab' and out['labs']:
        i = rng.randrange(len(out['labs']))
        out['labs'][i]['value'] = round(out['labs'][i]['value'] * 2.5, 2)
    else:
        kind = 'hallucinate_phenotype'
        annotated = set(kb['diseases'][record['disease_id']]['phenotypes'])
        present = {p['hp_id'] for p in out['phenotypes']}
        pool = sorted(set(kb['terms']) - annotated - present)
        if not pool:
            raise ValueError('No non-annotated HPO term available for corruption')
        out['phenotypes'].append({'hp_id': pool[rng.randrange(len(pool))], 'status': 'affirmed'})
    return kind, json.dumps(out, ensure_ascii=False, sort_keys=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pipeline', default='data/phase3_synth/pipeline_out')
    parser.add_argument('--kb', default='data/phase3_synth/kb/hpo_snapshot.json')
    parser.add_argument('--out', default='data/phase3_synth/training_candidates')
    args = parser.parse_args(argv)
    out = ROOT / args.out
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    kb = json.loads((ROOT / args.kb).read_text(encoding='utf-8'))
    accepted = load_jsonl(ROOT / args.pipeline / 'structured.jsonl')
    rng = random.Random(20261026)
    sft, pref = [], []
    for rec in accepted:
        bucket = int(hashlib.sha256(rec['patient_group'].encode()).hexdigest()[:8], 16) % 10
        split = 'train' if bucket < 8 else ('dev' if bucket == 8 else 'test')
        sft.append({'id': rec['record_id'], 'split': split, 'instruction': INSTRUCTION,
                    'input': rec['masked_text'], 'output': canonical_output(rec),
                    'source': 'synthetic_knowledge_constrained',
                    'provenance': 'pipeline_accepted_synthetic; NOT human-reviewed by default'})
        kind, rejected = corrupt(rec, rng, kb)
        pref.append({'id': rec['record_id'], 'split': split, 'instruction': INSTRUCTION,
                     'input': rec['masked_text'],
                     'chosen': canonical_output(rec), 'rejected': rejected,
                     'corruption_rule': kind,
                     'provenance': 'rule-based corruption; NOT human preference labels'})
    for name, rows in (('sft_candidates.jsonl', sft), ('preference_pairs.jsonl', pref)):
        with open(out / name, 'w', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    pipeline_audit_path = ROOT / args.pipeline / 'audit.json'
    pipeline_audit = (json.loads(pipeline_audit_path.read_text(encoding='utf-8'))
                      if pipeline_audit_path.exists() else {})
    stats = {
        'export_version': EXPORT_VERSION,
        'source_pipeline_version': pipeline_audit.get('pipeline_version'),
        'source_context_version': pipeline_audit.get('context_version'),
        'source_context_scope_version': pipeline_audit.get('context_scope_version'),
        'n_accepted_source': len(accepted),
        'sft_by_split': {s: sum(1 for r in sft if r['split'] == s) for s in ('train', 'dev', 'test')},
        'preference_corruption_rules': {k: sum(1 for r in pref if r['corruption_rule'] == k)
                                        for k in ('flip_status', 'drop_phenotype', 'wrong_lab', 'hallucinate_phenotype')},
        'disclaimer': 'Candidates only. No SFT/LoRA/DPO training was executed. Preference rejected '
                      'responses are programmatic corruptions, not human preference labels.',
    }
    (out / 'export_manifest.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
