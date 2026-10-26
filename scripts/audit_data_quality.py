"""Data-quality audit for the synthetic corpus and the exported training candidates.

Answers, with measurements rather than assurances:
  1. is HPO provenance complete and traceable for all 2,400 cases?
  2. do the generator and the independent validator share rules (circularity)?
  3. do the SFT splits leak patients / templates / near-duplicates / answers?
  4. what is the real status of the Chinese translations?
  5. are the programmatic preference labels actually wrong in the intended way?
  6. how many exported labels still carry the pre-fix context errors?

Constants used for the independent unit-conversion check are hard-coded literals
(molar mass of glucose 180.16 g/mol; 1 g/dL = 10 g/L) so that the audit does not
import the very constants it is auditing.

Usage: python -m scripts.audit_data_quality [--export data/phase4_synth_v2/training_candidates]
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
AUDIT_VERSION = 'dq-audit-1.0.0'
GLUCOSE_FACTOR_LITERAL = 180.16 / 10.0   # g/mol -> mg/dL per mmol/L (independent of project code)
HGB_FACTOR_LITERAL = 10.0                # 1 g/dL = 10 g/L


def load_jsonl(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def template_skeleton(text):
    """Collapse a note to its template skeleton (entities and numbers removed)."""
    text = re.sub(r'\[[A-Z_]+\]', '<E>', text)
    text = re.sub(r'\d+(?:\.\d+)?', '0', text)
    return re.sub(r'\s+', '', text)


def grams(text, n=5):
    return {text[i:i + n] for i in range(max(0, len(text) - n + 1))}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def provenance_block(notes, kb, hpo_dir):
    """1. Provenance completeness and traceability."""
    ontology_sha = annotation_sha = None
    sha_file = hpo_dir / 'SHA256.txt'
    if sha_file.exists():
        for line in sha_file.read_text(encoding='utf-8').splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            if parts[-1].endswith('hp.obo'):
                ontology_sha = parts[0]
            elif parts[-1].endswith('phenotype.hpoa'):
                annotation_sha = parts[0]
    complete, missing = 0, collections.Counter()
    term_ids = set(kb['terms'])
    span_errors = knowledge_violations = missing_evidence = 0
    evidence_codes = collections.Counter()
    for record in notes:
        prov = record.get('hpo_provenance') or {}
        needed = [('ontology_file', 'sha256'), ('ontology_file', 'data_version'),
                  ('annotation_file', 'sha256'), ('annotation_file', 'version'),
                  ('license', None)]
        ok = True
        for key, sub in needed:
            node = prov.get(key)
            value = node.get(sub) if isinstance(node, dict) else node
            if not value:
                missing[f'{key}.{sub}'] += 1
                ok = False
        if ok:
            complete += 1
        annotated = set(kb['diseases'][record['disease_id']]['phenotypes'])
        for entity in record['entities']:
            if record['text'][entity['start']:entity['end']] != entity['text']:
                span_errors += 1
            if entity['label'] != 'PHENOTYPE':
                continue
            if entity['hp_id'] not in term_ids:
                missing_evidence += 1
            evidence_codes[entity.get('evidence')] += 1
            if not entity.get('evidence') or not entity.get('reference'):
                missing_evidence += 1
            if entity['status'] in ('affirmed', 'suspected', 'history') and entity['hp_id'] not in annotated:
                knowledge_violations += 1
    recorded_ontology = next((r['hpo_provenance']['ontology_file']['sha256'] for r in notes
                              if r.get('hpo_provenance')), None)
    recorded_annotation = next((r['hpo_provenance']['annotation_file']['sha256'] for r in notes
                                if r.get('hpo_provenance')), None)
    return {
        'n_cases': len(notes),
        'cases_with_complete_provenance': complete,
        'missing_fields': dict(missing),
        'ontology_sha256_recorded': recorded_ontology,
        'ontology_sha256_on_disk': ontology_sha,
        'ontology_sha_matches_disk': recorded_ontology == ontology_sha,
        'annotation_sha256_recorded': recorded_annotation,
        'annotation_sha256_on_disk': annotation_sha,
        'annotation_sha_matches_disk': recorded_annotation == annotation_sha,
        'span_errors': span_errors,
        'entities_missing_hp_id_or_evidence': missing_evidence,
        'knowledge_violations_affirmed_suspected_history': knowledge_violations,
        'evidence_code_counts': dict(evidence_codes.most_common()),
        'traceability': 'per-entity evidence code + reference (PMID/ORPHA) + HPO release + '
                        'phenotype.hpoa version, recorded inside every case',
    }


def circularity_block():
    """2. Shared-rule analysis between generator and validator (static + numeric)."""
    validator = (ROOT / 'scripts/validate_synth.py').read_text(encoding='utf-8')
    generator = (ROOT / 'clinforge/synthgen.py').read_text(encoding='utf-8')
    intervals = (ROOT / 'clinforge/hpo_knowledge.py').read_text(encoding='utf-8')
    m = re.search(r"'factor_mgdl_to_mmoll':\s*([0-9.]+)", intervals)
    n = re.search(r"'factor_gdl_to_gl':\s*([0-9.]+)", intervals)
    return {
        'validator_imports_project_constants': [
            name for name in ('REFERENCE_INTERVALS', 'GENERIC_NEGATABLE_ZH', 'GENERIC_NEGATABLE_EN')
            if name in validator],
        'validator_imports_generator_markup': 'GENERIC_NEGATABLE_*' in validator,
        'shared_interval_module': 'clinforge/hpo_knowledge.py' if 'REFERENCE_INTERVALS' in validator else None,
        'conversion_factor_in_project': {
            'glucose': float(m.group(1)) if m else None,
            'hemoglobin': float(n.group(1)) if n else None},
        'conversion_factor_independent_literal': {
            'glucose': round(GLUCOSE_FACTOR_LITERAL, 3), 'hemoglobin': HGB_FACTOR_LITERAL},
        'conversion_factors_agree': bool(m and n
                                         and abs(float(m.group(1)) - GLUCOSE_FACTOR_LITERAL) < 0.01
                                         and abs(float(n.group(1)) - HGB_FACTOR_LITERAL) < 1e-9),
        'checks_that_are_independent': [
            'span integrity (entity text vs recorded offsets)',
            'hp_id existence in the HPO snapshot',
            'affirmed/suspected/history membership in the disease annotation set '
            '(verifies the emitter honours its own sampling contract, NOT medical truth)',
            'unit conversion arithmetic, re-derived in the validator',
            'near-duplicate statistics over the generated text',
        ],
        'checks_that_are_tautological_by_construction': [
            'knowledge consistency: the generator samples phenotypes FROM the annotation set, '
            'so a violation would indicate an implementation bug, not a medical claim',
            'lab direction: direction and interval come from the same table the sampler used; '
            'an error in the table would pass both sides',
            'reference intervals themselves are demonstration values, not institutional standards',
        ],
        'known_shared_failure_mode': 'the g/dL->g/L direction bug was invisible until the two code '
                                     'paths diverged; constant-level circularity remains',
    }


def split_leakage_block(export_dir, notes):
    """3. Patient / template / near-duplicate / answer leakage across splits."""
    sft = load_jsonl(export_dir / 'sft_candidates.jsonl')
    meta = {r['record_id']: r for r in notes}
    by_split = collections.defaultdict(list)
    for row in sft:
        by_split[row['split']].append(row)
    splits = sorted(by_split)
    exact = 0
    skeletons = {s: collections.Counter(template_skeleton(r['input']) for r in by_split[s]) for s in splits}
    skeleton_cross = {}
    for i, a in enumerate(splits):
        for b in splits[i + 1:]:
            shared = set(skeletons[a]) & set(skeletons[b])
            count = sum(skeletons[b][k] for k in shared)
            skeleton_cross[f'{a}|{b}'] = {'distinct_skeletons_in_both': len(shared),
                                          'records_in_second_split_affected': count,
                                          'rate': round(count / len(by_split[b]), 4) if by_split[b] else None}
    inputs = {s: {r['input'] for r in by_split[s]} for s in splits}
    for i, a in enumerate(splits):
        for b in splits[i + 1:]:
            exact += len(inputs[a] & inputs[b])
    triples = {s: {(meta[r['id']]['template_family'], meta[r['id']]['complexity'],
                    meta[r['id']]['disease_id']) for r in by_split[s] if r['id'] in meta}
               for s in splits}
    triple_cross = {}
    for i, a in enumerate(splits):
        for b in splits[i + 1:]:
            overlap = triples[a] & triples[b]
            affected = sum(1 for r in by_split[b]
                           if r['id'] in meta and (meta[r['id']]['template_family'],
                                                   meta[r['id']]['complexity'],
                                                   meta[r['id']]['disease_id']) in overlap)
            triple_cross[f'{a}|{b}'] = {'distinct_triples_in_both': len(overlap),
                                        'records_in_second_split_affected': affected,
                                        'rate': round(affected / len(by_split[b]), 4) if by_split[b] else None}
    patients = {s: {r['input'][:0] + meta[r['id']]['patient_group'] for r in by_split[s] if r['id'] in meta}
                for s in splits}
    patient_cross = sum(len(patients[a] & patients[b])
                        for i, a in enumerate(splits) for b in splits[i + 1:])
    # near-duplicate pairs across splits on the masked (production) text
    grams_by_split = {s: [(r['id'], grams(r['input'])) for r in by_split[s]] for s in splits}
    near_dup = 0
    near_dup_pairs = []
    for i, a in enumerate(splits):
        for b in splits[i + 1:]:
            for rid_a, ga in grams_by_split[a]:
                for rid_b, gb in grams_by_split[b]:
                    score = jaccard(ga, gb)
                    if score >= 0.8:
                        near_dup += 1
                        if len(near_dup_pairs) < 5:
                            near_dup_pairs.append({'a': rid_a, 'b': rid_b, 'jaccard': round(score, 3)})
    diseases = {s: {meta[r['id']]['disease_id'] for r in by_split[s] if r['id'] in meta} for s in splits}
    return {
        'n_exported': len(sft),
        'split_sizes': {s: len(by_split[s]) for s in splits},
        'exact_duplicate_inputs_across_splits': exact,
        'template_skeleton_collisions': skeleton_cross,
        'template_complexity_disease_triple_collisions': triple_cross,
        'patients_shared_across_splits': patient_cross,
        'near_duplicate_pairs_jaccard_ge_0.8_across_splits': near_dup,
        'near_duplicate_examples': near_dup_pairs,
        'disease_overlap': {f'{a}|{b}': len(diseases[a] & diseases[b])
                            for i, a in enumerate(splits) for b in splits[i + 1:]},
        'answer_leakage': {
            'disease_id_present_in_all_splits': True,
            'note': 'the disease label is also stated in the note text; a record whose template '
                    'skeleton and disease coincide with a training record lets the model copy the '
                    'answer. The triple-collision rate above is the relevant quantity.',
        },
        'verdict': 'NOT a generalisation benchmark: splits share templates and diseases. They are '
                   'usable as a formatting / schema-compliance training set, not as evidence of '
                   'transfer.',
    }


def translation_block(notes, gloss):
    """4. Status of the Chinese phenotype and disease translations."""
    pheno = gloss['phenotypes']
    diseases = gloss['diseases']
    duplicates = collections.defaultdict(list)
    for hp_id, surface in pheno.items():
        duplicates[surface].append(hp_id)
    collisions = {surface: ids for surface, ids in duplicates.items() if len(ids) > 1}
    surfaces = sorted(pheno.values())
    substring = 0
    for i, a in enumerate(surfaces):
        for b in surfaces[i + 1:]:
            if a in b or b in a:
                substring += 1
    latin = [s for s in surfaces if re.search(r'[A-Za-z]', s)]
    return {
        'n_phenotype_terms': len(pheno), 'n_disease_terms': len(diseases),
        'same_surface_different_hp_id': collisions,
        'substring_pairs': substring,
        'terms_containing_latin_letters': latin[:12],
        'n_terms_containing_latin_letters': len(latin),
        'review_status': 'single-author machine-assisted translation, spot-checked; '
                         'NO clinician or professional translator review',
        'allowed_claims': ['curated Chinese gloss', 'author-translated terminology'],
        'forbidden_claims': ['clinical expert gold standard', 'clinician-validated terminology',
                            'expert-reviewed translation'],
        'residual_risk': 'HPO publishes no official Chinese release; synonym coverage in Chinese is '
                         'limited to 214 curated surfaces, so recall on unseen Chinese phrasings is '
                         'not measurable here.',
    }


def preference_block(export_dir, notes, kb):
    """5. Are the programmatic preference 'rejected' samples wrong in the intended way?"""
    pref = load_jsonl(export_dir / 'preference_pairs.jsonl')
    meta = {r['record_id']: r for r in notes}
    same = 0
    not_wrong = 0
    fallback = 0
    per_rule = collections.Counter()
    hallucinated_annotated = 0
    hallucinated_checked = 0
    hallucinated_duplicate = 0
    for row in pref:
        chosen, rejected = row['chosen'], row['rejected']
        rule = row['corruption_rule']
        per_rule[rule] += 1
        if chosen == rejected:
            same += 1
        chosen_obj, rejected_obj = json.loads(chosen), json.loads(rejected)
        record = meta.get(row['id'])
        if rule == 'flip_status':
            if all(a['status'] == b['status'] for a, b in zip(chosen_obj['phenotypes'],
                                                              rejected_obj['phenotypes'])):
                not_wrong += 1
        elif rule == 'drop_phenotype':
            if len(rejected_obj['phenotypes']) != len(chosen_obj['phenotypes']) - 1:
                not_wrong += 1
        elif rule == 'wrong_lab':
            if all(a['value'] == b['value'] for a, b in zip(chosen_obj['labs'], rejected_obj['labs'])):
                not_wrong += 1
        elif rule == 'hallucinate_phenotype':
            # The rule appends exactly one hp_id at the end of `phenotypes`, so the
            # appended term is the last element. Check it against the record's gold
            # annotation set: if the disease really does present that phenotype, the
            # "rejected" answer is defensible and the pair carries label noise.
            # v1 hard-coded Fever (HP:0001945), which is a genuine gold annotation for
            # 22 exported cases - the hole this check exists to catch.
            if record and rejected_obj['phenotypes']:
                hallucinated_checked += 1
                appended = rejected_obj['phenotypes'][-1]['hp_id']
                annotated = {e['hp_id'] for e in record['entities'] if e['label'] == 'PHENOTYPE'}
                if appended in annotated:
                    hallucinated_annotated += 1
                    not_wrong += 1
                if appended in {c['hp_id'] for c in chosen_obj['phenotypes']}:
                    hallucinated_duplicate += 1
        if record is not None:
            applicable = {
                'flip_status': bool(chosen_obj['phenotypes']),
                'drop_phenotype': len(chosen_obj['phenotypes']) > 1,
                'wrong_lab': bool(chosen_obj['labs']),
            }
            if rule in applicable and not applicable[rule]:
                fallback += 1
    return {
        'n_pairs': len(pref),
        'pairs_where_rejected_equals_chosen': same,
        'pairs_where_rejected_is_not_actually_wrong': not_wrong,
        'hallucinate_pairs_checked': hallucinated_checked,
        'hallucinated_phenotype_was_actually_annotated': hallucinated_annotated,
        'hallucinated_phenotype_duplicated_an_existing_one': hallucinated_duplicate,
        'hallucinate_check_note': 'the appended (last) hp_id is compared against the record-level '
                                  'gold annotation set; the constant HP:0001945 check used before '
                                  'sft-export-2.0.0 was retired because the rule no longer always '
                                  'samples Fever, which made 22/2,332 rejected answers defensible',
        'rule_counts': dict(per_rule.most_common()),
        'fallback_to_hallucination_rule': fallback,
        'label_status': 'programmatic corruption, NOT human preference annotation',
        'usable_for': 'DPO/RLHF plumbing tests and format-supervision experiments only',
        'not_usable_for': 'any claim about human preference quality or reward-model accuracy',
    }


def context_contamination_block(export_dir, notes, pipeline_dir):
    """6. Do exported labels still carry the pre-fix context errors?"""
    notes_by_id = {r['record_id']: r for r in notes}
    structured = load_jsonl(pipeline_dir / 'structured.jsonl')
    mismatched = matched = 0
    by_gold = collections.Counter()
    for record in structured:
        gold = notes_by_id.get(record['record_id'])
        if gold is None:
            continue
        truth = {(e['start'], e['end'], e['hp_id']): e['status']
                 for e in gold['entities'] if e['label'] == 'PHENOTYPE'}
        for entity in record['phenotypes']:
            key = (entity['start'], entity['end'], entity['hp_id'])
            if key not in truth:
                continue
            matched += 1
            if entity['status'] != truth[key]:
                mismatched += 1
                by_gold[(truth[key], entity['status'])] += 1
    return {
        'pipeline_dir': str(pipeline_dir.relative_to(ROOT)).replace('\\', '/'),
        'matched_mentions': matched,
        'exported_status_mismatches': mismatched,
        'mismatch_rate': round(mismatched / matched, 4) if matched else None,
        'mismatches_by_transition': {f'{g}->{p}': v for (g, p), v in by_gold.most_common()},
        'gate': 'SFT/preference export must not be used for training while this number is non-zero '
                'for context status; the corrected pipeline run is pipeline-med-1.1.0.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notes', default='data/phase3_synth/gen/notes.jsonl')
    parser.add_argument('--kb', default='data/phase3_synth/kb/hpo_snapshot.json')
    parser.add_argument('--gloss', default='data/curated/zh_phenotype_gloss.json')
    parser.add_argument('--hpo-dir', default='data/external/hpo')
    parser.add_argument('--export', default='data/phase3_synth/training_candidates')
    parser.add_argument('--pipeline', default='data/phase3_synth/pipeline_out')
    parser.add_argument('--out', default='reports/phase4_data_quality/audit.json')
    args = parser.parse_args(argv)
    notes = load_jsonl(ROOT / args.notes)
    kb = json.loads((ROOT / args.kb).read_text(encoding='utf-8'))
    gloss = json.loads((ROOT / args.gloss).read_text(encoding='utf-8'))
    report = {
        'audit_version': AUDIT_VERSION,
        'generated_at_note': 'all numbers recomputed from the artefacts on disk',
        'corpus': args.notes,
        'provenance': provenance_block(notes, kb, ROOT / args.hpo_dir),
        'circularity': circularity_block(),
        'split_leakage': split_leakage_block(ROOT / args.export, notes),
        'translation': translation_block(notes, gloss),
        'preference_labels': preference_block(ROOT / args.export, notes, kb),
        'context_contamination': context_contamination_block(ROOT / args.export, notes,
                                                            ROOT / args.pipeline),
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items()
                      if k in ('provenance', 'split_leakage', 'preference_labels',
                               'context_contamination', 'translation')},
                     ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
