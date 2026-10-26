"""Independent validator for the knowledge-constrained synthetic corpus (P0).

Re-derives every check from the generated artefacts + the verified HPO
snapshot, NOT from generator internals:

  * span integrity      text[start:end] must equal the recorded entity text;
  * knowledge violations affirmed/suspected/history PHENOTYPE entities whose
                        hp_id is absent from the disease's annotation set;
                        negated phenotypes absent from annotation AND generic
                        whitelist;
  * lab consistency     numeric value must lie outside/inside the curated
                        demonstration reference interval per direction, and
        raw unit must convert back to the recorded standard value;
  * coverage            disease coverage, phenotype coverage per disease
                        (used / annotated), evidence-code distribution;
  * diversity           language / template family / complexity mix, distinct
                        character 3-gram ratio, note length distribution;
  * near-duplicate rate skeleton (entities replaced by tags) 5-gram Jaccard,
                        all pairs within a disease, mean/p95/max and the
                        share of pairs >= 0.7;
  * review queue        all violations + a stratified 5% sample + length
                        outliers exported for human review (status pending).

Usage: python -m scripts.validate_synth --gen data/phase3_synth/gen --kb data/phase3_synth/kb/hpo_snapshot.json --out reports/phase3_synth_validation
"""
from __future__ import annotations
import argparse
import collections
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.hpo_knowledge import REFERENCE_INTERVALS
from clinforge import lab_standards
from clinforge.synthgen import GENERIC_NEGATABLE_ZH, GENERIC_NEGATABLE_EN

ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def skeleton(text, entities):
    parts, pos = [], 0
    for e in sorted(entities, key=lambda x: x['start']):
        parts.append(text[pos:e['start']])
        parts.append('|' + e['label'] + '|')
        pos = e['end']
    parts.append(text[pos:])
    return re.sub(r'\s+', ' ', ''.join(parts))


def grams(text, n=5):
    compact = re.sub(r'\W+', '', text)
    if len(compact) <= n:
        return {compact}
    return {compact[i:i + n] for i in range(len(compact) - n + 1)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 1.0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gen', default='data/phase3_synth/gen')
    parser.add_argument('--kb', default='data/phase3_synth/kb/hpo_snapshot.json')
    parser.add_argument('--out', default='reports/phase3_synth_validation')
    parser.add_argument('--lab-standards', choices=('project', 'independent'), default='project',
                        help='which constants to validate labs against: the shared project table '
                             '(historical default) or clinforge.lab_standards (second path, '
                             'derived from molar masses and SI definitions)')
    args = parser.parse_args(argv)
    gen, out = ROOT / args.gen, ROOT / args.out
    if out.exists():
        raise FileExistsError(f'Refusing to overwrite: {out}')
    out.mkdir(parents=True)
    records = load_jsonl(gen / 'notes.jsonl')
    kb = json.loads((ROOT / args.kb).read_text(encoding='utf-8'))
    diseases = kb['diseases']

    violations, span_errors, lab_errors = [], [], []
    used_phenotypes = collections.defaultdict(set)
    evidence_counter = collections.Counter()
    family_lang = collections.Counter()
    lengths = []
    for rec in records:
        text = rec['text']
        ann = diseases[rec['disease_id']]['phenotypes']
        absent = diseases[rec['disease_id']]['absent_phenotypes']
        lengths.append(len(text))
        family_lang[(rec['language'], rec['template_family'], rec['complexity'])] += 1
        for e in rec['entities']:
            if text[e['start']:e['end']] != e['text']:
                span_errors.append({'case_id': rec['case_id'], 'entity': e})
                continue
            if e['label'] == 'PHENOTYPE':
                status = e['status']
                used_phenotypes[rec['disease_id']].add(e['hp_id'])
                evidence_counter[e.get('evidence', '?')] += 1
                if status in ('affirmed', 'suspected', 'history'):
                    if e['hp_id'] not in ann:
                        violations.append({'case_id': rec['case_id'], 'kind': 'knowledge_violation',
                                           'detail': f"{status} phenotype {e['hp_id']} not annotated for {rec['disease_id']}",
                                           'text': e['text']})
                elif status == 'negated':
                    if e['hp_id'] not in ann and e['hp_id'] not in absent:
                        violations.append({'case_id': rec['case_id'], 'kind': 'negation_violation',
                                           'detail': f"negated phenotype {e['hp_id']} not annotated for {rec['disease_id']}",
                                           'text': e['text']})
            elif e['label'] == 'SYMPTOM_GENERIC':
                whitelist = GENERIC_NEGATABLE_ZH if rec['language'] == 'zh' else GENERIC_NEGATABLE_EN
                if e['status'] != 'negated' or e['text'] not in whitelist:
                    violations.append({'case_id': rec['case_id'], 'kind': 'generic_symptom_violation',
                                       'detail': f"generic symptom {e['text']} status={e['status']}", 'text': e['text']})
            elif e['label'] == 'LAB_VALUE':
                raw = float(e['text'].split(' ')[0])
                if args.lab_standards == 'independent':
                    # Second path: factors from molar masses, bands from an
                    # independently transcribed table.  Never writes back to
                    # the record; only reports disagreement.
                    check = lab_standards.check_value(raw, e['unit_raw'], e['analyte'],
                                                      e['direction'], e['value_std'])
                    std = check['recomputed_si']
                    if not check['conversion_ok']:
                        lab_errors.append({'case_id': rec['case_id'], 'kind': 'unit_conversion_mismatch',
                                           'raw': e['text'], 'recorded_std': e['value_std'],
                                           'recomputed': std,
                                           'standard_source': 'clinforge.lab_standards'})
                    if not check['direction_ok']:
                        band = lab_standards.BANDS[e['analyte']]
                        lab_errors.append({'case_id': rec['case_id'], 'kind': 'direction_mismatch',
                                           'direction': e['direction'], 'std_value': std,
                                           'interval': [band['lo'], band['hi']],
                                           'standard_source': 'clinforge.lab_standards'})
                else:
                    ref = REFERENCE_INTERVALS[e['analyte']]
                    if e['unit_raw'] == 'mg/dL':   # mg/dL -> mmol/L
                        std = round(raw / ref['factor_mgdl_to_mmoll'], 2)
                    elif e['unit_raw'] == 'g/dL':  # g/dL -> g/L
                        std = round(raw * ref['factor_gdl_to_gl'], 2)
                    else:
                        std = round(raw, 2)
                    if abs(std - e['value_std']) > max(0.02, 0.01 * abs(e['value_std'])):
                        lab_errors.append({'case_id': rec['case_id'], 'kind': 'unit_conversion_mismatch',
                                           'raw': e['text'], 'recorded_std': e['value_std'], 'recomputed': std})
                    lo, hi = ref['lo'], ref['hi']
                    std_ok_range = (e['direction'] == 'high' and std > hi) or \
                                   (e['direction'] == 'low' and std < lo) or \
                                   (e['direction'] == 'normal' and lo <= std <= hi)
                    if not std_ok_range:
                        lab_errors.append({'case_id': rec['case_id'], 'kind': 'direction_mismatch',
                                           'direction': e['direction'], 'std_value': std,
                                           'interval': [lo, hi]})
                if e.get('hp_id') and e['hp_id'] not in ann:
                    violations.append({'case_id': rec['case_id'], 'kind': 'lab_link_violation',
                                       'detail': f"lab linked to {e['hp_id']} not annotated", 'text': e['text']})

    # coverage
    coverage = {}
    for did in sorted({r['disease_id'] for r in records}):
        annotated = set(diseases[did]['phenotypes'])
        used = used_phenotypes.get(did, set())
        coverage[did] = {'disease_name': diseases[did]['disease_name'],
                         'n_annotated': len(annotated), 'n_used': len(used),
                         'coverage_of_annotation': round(len(used & annotated) / len(annotated), 4)}

    # near-duplicate within disease (skeleton 5-gram Jaccard, sampled pairs)
    rng = random.Random(20261026)
    by_disease = collections.defaultdict(list)
    for rec in records:
        by_disease[rec['disease_id']].append(skeleton(rec['text'], rec['entities']))
    nd_stats, nd_overall = {}, []
    for did, texts in sorted(by_disease.items()):
        grams_list = [grams(t) for t in texts]
        sims = []
        pairs = [(i, j) for i in range(len(texts)) for j in range(i + 1, len(texts))]
        if len(pairs) > 3000:
            pairs = rng.sample(pairs, 3000)
        for i, j in pairs:
            sims.append(jaccard(grams_list[i], grams_list[j]))
        sims.sort()
        nd_overall.extend(sims)
        nd_stats[did] = {
            'n_cases': len(texts), 'n_pairs': len(sims),
            'mean': round(sum(sims) / len(sims), 4),
            'p95': round(sims[int(0.95 * (len(sims) - 1))], 4),
            'max': round(sims[-1], 4),
            'share_ge_0_7': round(sum(1 for s in sims if s >= 0.7) / len(sims), 4),
        }
    nd_overall.sort()

    # diversity
    token_counts = [len(re.findall(r'[A-Za-z]+|[\u4e00-\u9fff]', r['text'])) for r in records]
    distinct3, total3 = set(), 0
    for r in records:
        compact = re.sub(r'\W+', '', r['text'])
        for i in range(max(1, len(compact) - 2)):
            distinct3.add(compact[i:i + 3])
            total3 += 1
    lengths.sort()

    report = {
        'n_records': len(records),
        'lab_standards_mode': args.lab_standards,
        'span_integrity_errors': len(span_errors),
        'knowledge_violations': len(violations),
        'knowledge_violation_rate_per_record': round(len({v['case_id'] for v in violations}) / len(records), 6),
        'lab_errors': len(lab_errors),
        'coverage': coverage,
        'phenotype_use': {'distinct_hp_used': len({p for s in used_phenotypes.values() for p in s}),
                          'by_disease': {k: len(v) for k, v in sorted(used_phenotypes.items())}},
        'evidence_distribution': dict(evidence_counter),
        'language_template_mix': {f'{k[0]}|{k[1]}|{k[2]}': v for k, v in sorted(family_lang.items())},
        'length_chars': {'min': lengths[0], 'p50': lengths[len(lengths)//2],
                         'p95': lengths[int(0.95*len(lengths))], 'max': lengths[-1]},
        'diversity': {'distinct_char3gram_ratio': round(len(distinct3)/total3, 6),
                      'n_distinct_char3grams': len(distinct3),
                      'mean_tokens': round(sum(token_counts)/len(token_counts), 2)},
        'near_duplicate': {'overall_mean': round(sum(nd_overall)/len(nd_overall), 4),
                           'overall_p95': round(nd_overall[int(0.95*(len(nd_overall)-1))], 4),
                           'overall_max': round(nd_overall[-1], 4),
                           'overall_share_ge_0_7': round(sum(1 for s in nd_overall if s >= 0.7)/len(nd_overall), 4),
                           'by_disease': nd_stats},
        'provenance': kb['provenance'],
    }
    (out/'validation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    # human review queue: violations + stratified sample + outliers
    rng2 = random.Random(99)
    queue = [{'case_id': v['case_id'], 'reason': v['kind'], 'detail': v.get('detail', ''),
              'review_status': 'PENDING_HUMAN'} for v in violations + lab_errors + span_errors]
    flagged = {q['case_id'] for q in queue}
    by_combo = collections.defaultdict(list)
    for rec in records:
        by_combo[(rec['disease_id'], rec['language'], rec['template_family'])].append(rec['case_id'])
    for combo, ids in sorted(by_combo.items()):
        k = max(1, int(0.05 * len(ids)))
        for cid in rng2.sample(ids, k):
            if cid not in flagged:
                queue.append({'case_id': cid, 'reason': 'stratified_sample', 'detail': '|'.join(map(str, combo)),
                              'review_status': 'PENDING_HUMAN'})
    lo_out, hi_out = lengths[int(0.02*len(lengths))], lengths[int(0.98*len(lengths))]
    for rec in records:
        if (len(rec['text']) <= lo_out or len(rec['text']) >= hi_out) and rec['case_id'] not in flagged:
            queue.append({'case_id': rec['case_id'], 'reason': 'length_outlier',
                          'detail': f"len={len(rec['text'])}", 'review_status': 'PENDING_HUMAN'})
    with open(out/'human_review_queue.csv', 'w', encoding='utf-8') as handle:
        handle.write('case_id,reason,detail,review_status\n')
        for q in queue:
            detail = str(q['detail']).replace(',', ';').replace('\n', ' ')
            handle.write(f"{q['case_id']},{q['reason']},{detail},{q['review_status']}\n")
    report['human_review_queue_size'] = len(queue)
    (out/'validation_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({k: report[k] for k in
                      ('n_records', 'span_integrity_errors', 'knowledge_violations',
                       'knowledge_violation_rate_per_record', 'lab_errors', 'phenotype_use',
                       'human_review_queue_size')}, ensure_ascii=False, indent=2))
    print('near_duplicate overall:', json.dumps({k: v for k, v in report['near_duplicate'].items() if k != 'by_disease'}))


if __name__ == '__main__':
    main()
