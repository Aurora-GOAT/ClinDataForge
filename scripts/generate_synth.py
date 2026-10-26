"""Generate the knowledge-constrained rare-disease synthetic corpus (P0).

Outputs (never overwritten):
  <out>/notes.jsonl        full records: text + gold entity spans + provenance
  <out>/cases.jsonl        structured case specifications (no free text)
  <out>/dedup_pairs.jsonl  labelled duplicate / non-duplicate evaluation pairs
  <out>/generation_manifest.json

Usage: python -m scripts.generate_synth --out data/phase3_synth/gen [--n-cases 2400]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.hpo_knowledge import load_knowledge_base
from clinforge.synthgen import SynthGenerator, load_gloss, GENERATOR_VERSION

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(path, rows):
    with open(path, 'w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')


def build_dedup_pairs(records, seed, n_per_kind=40):
    """Labelled pairs for duplicate-detection evaluation.

    duplicate            same patient, same encounter, near-identical text
                         (PHI header values swapped / trivial punctuation);
    same_patient_visit   same patient, NEW encounter, regenerated case with
                         independently sampled phenotypes and labs -> the
                         medical content changes and MUST NOT be merged;
    different_patient    two different patients with the same disease.
    """
    rng = random.Random(seed)
    by_disease = {}
    for rec in records:
        by_disease.setdefault(rec['disease_id'], []).append(rec)
    pairs = []

    def scrub_phi(text, entities):
        """Replace PHI header values with different synthetic values."""
        repl = []
        for e in entities:
            if e['label'] == 'NAME':
                repl.append((e, '仝卓'))
            elif e['label'] == 'PHONE':
                repl.append((e, '17700001111'))
            elif e['label'] == 'PATIENT_ID':
                repl.append((e, 'R9999999'))
            elif e['label'] == 'DATE':
                repl.append((e, '2026-01-05'))
        for e, new in sorted(repl, key=lambda x: -x[0]['start']):
            text = text[:e['start']] + new + text[e['end']:]
        return text

    dup_pool = [r for r in records if r['with_phi']]
    for i in range(n_per_kind):
        a = rng.choice(dup_pool)
        pairs.append({'pair_id': f'DD-{i:04d}', 'kind': 'duplicate', 'gold': 'DUPLICATE',
                      'record_a': a['case_id'], 'patient_group': a['case_id'],
                      'encounter_a': a['case_id'] + '-E1', 'encounter_b': a['case_id'] + '-E1',
                      'text_a': a['text'], 'text_b': scrub_phi(a['text'], a['entities'])})
    for i in range(n_per_kind):
        disease_id = rng.choice(list(by_disease))
        a = rng.choice(by_disease[disease_id])
        b = rng.choice(by_disease[disease_id])
        pairs.append({'pair_id': f'SV-{i:04d}', 'kind': 'same_patient_visit', 'gold': 'NOT_DUPLICATE',
                      'record_a': a['case_id'], 'record_b': b['case_id'],
                      'patient_group': a['case_id'],
                      'encounter_a': a['case_id'] + '-E1', 'encounter_b': a['case_id'] + '-E2',
                      'text_a': a['text'], 'text_b': b['text']})
    for i in range(n_per_kind):
        disease_id = rng.choice(list(by_disease))
        a, b = rng.sample(by_disease[disease_id], 2)
        pairs.append({'pair_id': f'DP-{i:04d}', 'kind': 'different_patient', 'gold': 'NOT_DUPLICATE',
                      'record_a': a['case_id'], 'record_b': b['case_id'],
                      'patient_group': a['case_id'] + '|' + b['case_id'],
                      'encounter_a': a['case_id'] + '-E1', 'encounter_b': b['case_id'] + '-E1',
                      'text_a': a['text'], 'text_b': b['text']})
    # same patient, same encounter, but the lab RESULT changed: a genuine
    # update that must survive dedup even when character overlap is high.
    lab_pool = [r for r in records
                if any(e['label'] == 'LAB_VALUE' and e.get('hp_id') for e in r['entities'])]
    for i in range(n_per_kind):
        a = rng.choice(lab_pool)
        text_b = a['text']
        labs = [e for e in a['entities'] if e['label'] == 'LAB_VALUE']
        for e in sorted(labs, key=lambda x: -x['start']):
            unit = e['unit_raw']
            try:
                raw = float(e['text'].split(' ')[0])
            except ValueError:
                continue
            bumped = raw * 1.3 if e['direction'] == 'high' else raw * 0.7
            shown = int(round(bumped)) if '.' not in e['text'].split(' ')[0] else round(bumped, 1)
            text_b = text_b[:e['start']] + f'{shown} {unit}' + text_b[e['end']:]
        if text_b == a['text']:
            continue
        pairs.append({'pair_id': f'LU-{i:04d}', 'kind': 'same_encounter_lab_update', 'gold': 'NOT_DUPLICATE',
                      'record_a': a['case_id'], 'patient_group': a['case_id'],
                      'encounter_a': a['case_id'] + '-E1', 'encounter_b': a['case_id'] + '-E1',
                      'text_a': a['text'], 'text_b': text_b})
    return pairs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kb', default='data/phase3_synth/kb/hpo_snapshot.json')
    parser.add_argument('--gloss', default='data/curated/zh_phenotype_gloss.json')
    parser.add_argument('--out', default='data/phase3_synth/gen')
    parser.add_argument('--n-cases', type=int, default=2400)
    parser.add_argument('--seed', type=int, default=20261026)
    args = parser.parse_args(argv)
    out = ROOT / args.out
    if out.exists():
        raise FileExistsError(f'Refusing to overwrite: {out}')
    out.mkdir(parents=True)
    kb = load_knowledge_base(ROOT / args.kb)
    gloss = load_gloss(ROOT / args.gloss)
    generator = SynthGenerator(kb, gloss, seed=args.seed, n_cases=args.n_cases)
    records = generator.generate()
    for rec in records:
        rec['record_id'] = rec['case_id']
        rec['patient_group'] = 'PAT-' + rec['case_id']
        rec['encounter_group'] = 'ENC-' + rec['case_id']
    notes_path, cases_path, pairs_path = out/'notes.jsonl', out/'cases.jsonl', out/'dedup_pairs.jsonl'
    write_jsonl(notes_path, records)
    write_jsonl(cases_path, [
        {k: r[k] for k in ('case_id', 'disease_id', 'disease_name', 'disease_name_zh', 'language',
                           'template_family', 'complexity', 'with_phi', 'age_years', 'onset_hp',
                           'spec', 'generator_version', 'seed')}
        for r in records])
    pairs = build_dedup_pairs(records, args.seed + 1)
    write_jsonl(pairs_path, pairs)
    manifest = {
        'generator_version': GENERATOR_VERSION, 'seed': args.seed, 'n_cases': len(records),
        'n_dedup_pairs': len(pairs),
        'hpo_provenance': kb['provenance'],
        'files': {p.name: sha256_file(p) for p in (notes_path, cases_path, pairs_path)},
    }
    (out/'generation_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'cases': len(records), 'pairs': len(pairs),
                      'zh': sum(1 for r in records if r['language'] == 'zh'),
                      'manifest': manifest['files']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
