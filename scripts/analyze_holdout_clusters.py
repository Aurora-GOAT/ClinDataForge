"""Cluster-aware uncertainty for the frozen 260-note context holdout.

Why
---
`scripts/audit_split_relations.py` found that the 260 holdout notes contain only
186 distinct normalised texts and, at Jaccard >= 0.80, collapse into 64
connected components (largest 10 notes).  Treating 1,618 mentions as independent
observations would produce confidence intervals that are too narrow.

This script recomputes the same predictions (same extractor, same resolver, no
tuning) and reports a **cluster bootstrap** over the 64 near-duplicate
components.  It is an uncertainty analysis, not a new experiment: the frozen
point estimates do not change.

Output: reports/phase4_split_relations/holdout_bootstrap.json

Usage: python -m scripts.analyze_holdout_clusters
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.context_scope import ContextResolver
from clinforge.hpo_knowledge import load_knowledge_base
from clinforge.med_extract import build_term_index, classify_context, find_phenotype_mentions
from clinforge.synthgen import CURATED_DISEASES, load_gloss

ROOT = Path(__file__).resolve().parent.parent
STATUSES = ('affirmed', 'suspected', 'history', 'negated')
SYSTEMS = ('v1', 'v2_scope_v1', 'v2_scope_ng')


def load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def per_mention_predictions() -> dict[str, dict[str, list[tuple[str, str]]]]:
    kb = load_knowledge_base(ROOT / 'data/phase3_synth/kb/hpo_snapshot.json')
    gloss = load_gloss(ROOT / 'data/curated/zh_phenotype_gloss.json')
    allowed = set()
    for disease_id in CURATED_DISEASES:
        if disease_id in kb['diseases']:
            allowed |= set(kb['diseases'][disease_id]['phenotypes'])
    index = build_term_index(kb, gloss, allowed)

    out = {}
    for record in load_jsonl(ROOT / 'data/phase4_context/holdout_notes.jsonl'):
        text, lang = record['text'], record['language']
        gold = {(e['start'], e['end'], e['hp_id']): e['status']
                for e in record['entities'] if e['label'] == 'PHENOTYPE'}
        mentions = find_phenotype_mentions(text, index)
        spans = [(m['start'], m['end']) for m in mentions]
        resolvers = {'v2_scope_v1': ContextResolver(text, lang, spans, 'v1'),
                     'v2_scope_ng': ContextResolver(text, lang, spans, 'negex')}
        rows = {name: [] for name in SYSTEMS}
        for mention in mentions:
            key = (mention['start'], mention['end'], mention['hp_id'])
            if key not in gold:
                continue
            truth = gold[key]
            rows['v1'].append((truth, classify_context(text, mention, lang)))
            for name, resolver in resolvers.items():
                rows[name].append((truth, resolver.classify(mention['start'])))
        out[record['record_id']] = rows
    return out


def metrics(pairs: list[tuple[str, str]]) -> dict:
    confusion = Counter(pairs)
    tp = {s: confusion.get((s, s), 0) for s in STATUSES}
    fp = {s: sum(v for (g, p), v in confusion.items() if p == s and g != s) for s in STATUSES}
    fn = {s: sum(v for (g, p), v in confusion.items() if g == s and p != s) for s in STATUSES}
    per_class = {}
    for s in STATUSES:
        precision = tp[s] / (tp[s] + fp[s]) if tp[s] + fp[s] else None
        recall = tp[s] / (tp[s] + fn[s]) if tp[s] + fn[s] else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else 0.0
        per_class[s] = f1
    return {
        'accuracy': sum(tp.values()) / len(pairs) if pairs else None,
        'macro_f1': sum(per_class.values()) / len(per_class),
        'history_to_affirmed': confusion.get(('history', 'affirmed'), 0),
    }


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float('nan')
    pos = (len(ordered) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=20261027)
    parser.add_argument('--relations', default='reports/phase4_split_relations/relations.json')
    parser.add_argument('--out', default='reports/phase4_split_relations/holdout_bootstrap.json')
    args = parser.parse_args(argv)

    relations = json.loads((ROOT / args.relations).read_text(encoding='utf-8'))
    clusters = relations['near_duplicates']['holdout_structure']['cluster_members']
    cluster_of = {record_id: idx for idx, members in enumerate(clusters) for record_id in members}

    predictions = per_mention_predictions()
    missing = set(predictions) - set(cluster_of)
    if missing:
        raise ValueError(f'{len(missing)} records have no cluster assignment')

    all_pairs = {name: [p for rows in predictions.values() for p in rows[name]] for name in SYSTEMS}
    point = {name: metrics(all_pairs[name]) for name in SYSTEMS}

    rng = random.Random(args.seed)
    boot = {name: {'accuracy': [], 'macro_f1': []} for name in SYSTEMS}
    for _ in range(args.iterations):
        draw = [rng.randrange(len(clusters)) for _ in range(len(clusters))]
        pairs = {name: [] for name in SYSTEMS}
        for idx in draw:
            for record_id in clusters[idx]:
                for name in SYSTEMS:
                    pairs[name].extend(predictions[record_id][name])
        for name in SYSTEMS:
            row = metrics(pairs[name])
            boot[name]['accuracy'].append(row['accuracy'])
            boot[name]['macro_f1'].append(row['macro_f1'])

    report = {
        'analysis': 'cluster bootstrap over near-duplicate connected components',
        'why': '260 notes contain 186 distinct texts and 64 near-duplicate clusters; '
               'mention-level intervals would be too narrow',
        'iterations': args.iterations,
        'seed': args.seed,
        'n_records': len(predictions),
        'n_mentions': len(all_pairs['v1']),
        'n_clusters': len(clusters),
        'largest_cluster': max(len(c) for c in clusters),
        'systems': {},
    }
    for name in SYSTEMS:
        report['systems'][name] = {
            'point': {k: (round(v, 4) if isinstance(v, float) else v) for k, v in point[name].items()},
            'accuracy_ci95': [round(percentile(boot[name]['accuracy'], 0.025), 4),
                              round(percentile(boot[name]['accuracy'], 0.975), 4)],
            'macro_f1_ci95': [round(percentile(boot[name]['macro_f1'], 0.025), 4),
                              round(percentile(boot[name]['macro_f1'], 0.975), 4)],
            'history_to_affirmed_point': point[name]['history_to_affirmed'],
        }

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({
        'n_records': report['n_records'], 'n_mentions': report['n_mentions'],
        'n_clusters': report['n_clusters'], 'largest_cluster': report['largest_cluster'],
        'systems': report['systems'],
        'output': str(out_path.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
