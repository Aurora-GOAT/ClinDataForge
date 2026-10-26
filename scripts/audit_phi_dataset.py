"""Independent leak audit for the phase-2 PHI benchmark.

The builder already refuses to emit a split whose near-duplicate components
cross splits. This script re-checks that property with a *different* similarity
definition, so a bug in the builder's own clustering cannot hide a leak.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import itertools
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def audit_mask(row):
    """Second, independent masking: gold PHI and clinical spans -> labels, all
    non-alphanumeric characters removed. Different from the builder skeleton."""
    text, position, parts = row['text'], 0, []
    for span in sorted(row['entities'] + row['protected_spans'], key=lambda s: s['start']):
        if span['start'] < position:
            continue
        parts.extend((text[position:span['start']], '|' + span['label'] + '|'))
        position = span['end']
    parts.append(text[position:])
    return re.sub(r'[^0-9a-z一-鿿|]+', '', ''.join(parts).lower())


def shingles(value, n=6):
    return {value[i:i + n] for i in range(max(1, len(value) - n + 1))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default='data/phase2_phi_v1')
    parser.add_argument('--out', default='reports/phase2_dataset_audit')
    args = parser.parse_args(argv)
    data, out = ROOT / args.data, ROOT / args.out
    if out.exists():
        raise FileExistsError('Refusing to overwrite audit directory')
    out.mkdir(parents=True)

    manifest = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))
    splits = {name: load(data / (name + '.jsonl')) for name in ('train', 'dev', 'test')}
    all_rows = [row for rows in splits.values() for row in rows]

    problems = []
    file_hashes = {}
    for name, expected in manifest['files'].items():
        actual = sha256(data / name)
        file_hashes[name] = {'expected': expected, 'actual': actual, 'match': actual == expected}
        if actual != expected:
            problems.append('File hash changed after build: ' + name)

    asq_hashes = {}
    for name, entry in manifest['sources']['en']['verified_files'].items():
        actual = sha256(ROOT / 'data/external/asq_phi' / name)
        asq_hashes[name] = {'expected': entry['sha256'], 'actual': actual, 'match': actual == entry['sha256']}
        if actual != entry['sha256']:
            problems.append('ASQ-PHI upstream source changed: ' + name)

    # 1. Exact duplicates anywhere, and across splits.
    by_text = collections.defaultdict(list)
    for name, rows in splits.items():
        for row in rows:
            by_text[row['text']].append(name)
    duplicate_texts = {text: sorted(set(v)) for text, v in by_text.items() if len(v) > 1}
    cross_split_text = {t: v for t, v in duplicate_texts.items() if len(v) > 1}

    # 2. Independent near-duplicate check with a different masking rule.
    masks = {row['doc_id']: audit_mask(row) for row in all_rows}
    by_mask = collections.defaultdict(list)
    for name, rows in splits.items():
        for row in rows:
            by_mask[masks[row['doc_id']]].append(name)
    cross_split_mask = {k: sorted(set(v)) for k, v in by_mask.items() if len(v) > 1 and len(set(v)) > 1}

    # 3. Worst-case shingle similarity between different splits (sampled blocks).
    grams = {row['doc_id']: shingles(masks[row['doc_id']]) for row in all_rows}
    worst = []
    indexed = collections.defaultdict(list)
    for row in all_rows:
        for gram in list(grams[row['doc_id']])[:40]:
            indexed[gram].append(row['doc_id'])
    split_of = {row['doc_id']: name for name, rows in splits.items() for row in rows}
    seen = set()
    for bucket in indexed.values():
        if len(bucket) > 60:
            continue
        for a, b in itertools.combinations(sorted(set(bucket)), 2):
            if split_of[a] == split_of[b] or (a, b) in seen:
                continue
            seen.add((a, b))
            left, right = grams[a], grams[b]
            if not left or not right:
                continue
            score = len(left & right) / len(left | right)
            if score >= .5:
                worst.append({'a': a, 'b': b, 'splits': [split_of[a], split_of[b]], 'jaccard': round(score, 4)})
    worst.sort(key=lambda item: -item['jaccard'])

    # 4. Authored template families must not cross splits.
    families = collections.defaultdict(set)
    for name, rows in splits.items():
        for row in rows:
            families[row.get('template_group', row['doc_id'])].add(name)
    cross_family = {k: sorted(v) for k, v in families.items() if len(v) > 1}

    if cross_split_text:
        problems.append('Identical text in multiple splits')
    if cross_split_mask:
        problems.append('Independently masked near-duplicate in multiple splits')
    if cross_family:
        problems.append('Template family in multiple splits')
    if worst:
        problems.append('Cross-split shingle Jaccard >= 0.50 detected')

    summary = {name: {
        'n_records': len(rows),
        'n_with_phi': sum(1 for r in rows if r['entities']),
        'n_without_phi': sum(1 for r in rows if not r['entities']),
        'n_entities': sum(len(r['entities']) for r in rows),
        'languages': dict(collections.Counter(r['language'] for r in rows)),
        'labels': dict(collections.Counter(s['label'] for r in rows for s in r['entities'])),
        'characters': sum(len(r['text']) for r in rows),
        'protected_characters': sum(sum(s['end'] - s['start'] for s in r['protected_spans']) for r in rows),
        'components': len({r['near_duplicate_group'] for r in rows}),
    } for name, rows in splits.items()}

    report = {
        'data_directory': args.data,
        'benchmark_version': manifest['benchmark_version'],
        'files': file_hashes,
        'asq_phi_source_verification': asq_hashes,
        'split_summary': summary,
        'leakage_checks': {
            'duplicate_texts_total': len(duplicate_texts),
            'duplicate_texts_crossing_splits': len(cross_split_text),
            'independent_mask_collisions_crossing_splits': len(cross_split_mask),
            'template_families_crossing_splits': len(cross_family),
            'cross_split_pairs_jaccard_ge_0.50': len(worst),
            'worst_cross_split_pairs': worst[:10],
        },
        'unresolved_asq_phi_values': manifest['unresolved_asq_phi_values'],
        'excluded_asq_phi_types': manifest['excluded_asq_phi_types'],
        'problems': problems,
        'verdict': 'PASS' if not problems else 'FAIL',
    }
    (out / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'verdict': report['verdict'], 'problems': problems,
                      'leakage': report['leakage_checks'], 'summary': summary},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
