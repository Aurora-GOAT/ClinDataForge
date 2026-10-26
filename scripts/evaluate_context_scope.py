"""Evaluate context-status classifiers: v1 window vs v2 scope resolution.

Three systems are compared on identical data and identical mention sets:

  v1           med_extract.classify_context   (fixed character window)
  v2_scope_v1  ContextResolver + the v1 cue list   (scope fix only)
  v2_scope_ng  ContextResolver + the NegEx/ConText cue families (scope + lexicon)

Reporting v2_scope_v1 separately is what lets the improvement be attributed to
scope handling rather than to extra cue words.

Corpora
  dev     : data/phase3_synth/gen/notes.jsonl  (USED FOR DEVELOPMENT - not a test)
  holdout : data/phase4_context/holdout_notes.jsonl (frozen before evaluation)

Usage:
  python -m scripts.evaluate_context_scope --corpus dev
  python -m scripts.evaluate_context_scope --corpus holdout
"""
from __future__ import annotations
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.hpo_knowledge import load_knowledge_base
from clinforge.synthgen import load_gloss, CURATED_DISEASES
from clinforge.med_extract import (build_term_index, find_phenotype_mentions,
                                   classify_context, EXTRACTOR_VERSION)
from clinforge.context_scope import ContextResolver, CONTEXT_SCOPE_VERSION

ROOT = Path(__file__).resolve().parent.parent
STATUSES = ('affirmed', 'suspected', 'history', 'negated')
CORPORA = {
    'dev': 'data/phase3_synth/gen/notes.jsonl',
    'holdout': 'data/phase4_context/holdout_notes.jsonl',
}


def load_jsonl(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def per_class(confusion):
    """Precision/recall/F1 per status from a gold->pred count matrix."""
    table = {}
    for status in STATUSES:
        tp = confusion.get((status, status), 0)
        fp = sum(v for (g, p), v in confusion.items() if p == status and g != status)
        fn = sum(v for (g, p), v in confusion.items() if g == status and p != status)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = (2 * precision * recall / (precision + recall)) if precision and recall else (
            0.0 if precision is not None and recall is not None else None)
        table[status] = {'precision': None if precision is None else round(precision, 4),
                         'recall': None if recall is None else round(recall, 4),
                         'f1': None if f1 is None else round(f1, 4),
                         'support': tp + fn, 'predicted': tp + fp}
    total = sum(confusion.values())
    correct = sum(v for (g, p), v in confusion.items() if g == p)
    macro = [row['f1'] for row in table.values() if row['f1'] is not None]
    table['_overall'] = {
        'n': total,
        'accuracy': round(correct / total, 4) if total else None,
        'macro_f1': round(sum(macro) / len(macro), 4) if macro else None,
    }
    return table


def confusion_block(confusion):
    block = {}
    for gold in STATUSES:
        block[gold] = {pred: confusion.get((gold, pred), 0) for pred in STATUSES}
    return block


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', choices=tuple(CORPORA), required=True)
    parser.add_argument('--notes', default=None)
    parser.add_argument('--out', default=None)
    parser.add_argument('--allow-existing', action='store_true')
    args = parser.parse_args(argv)
    notes_path = ROOT / (args.notes or CORPORA[args.corpus])
    out_path = ROOT / (args.out or f'reports/phase4_context/{args.corpus}_eval.json')
    if out_path.exists() and not args.allow_existing:
        raise FileExistsError(f'{out_path} exists; evaluation outputs are write-once')

    kb = load_knowledge_base(ROOT / 'data/phase3_synth/kb/hpo_snapshot.json')
    gloss = load_gloss(ROOT / 'data/curated/zh_phenotype_gloss.json')
    allowed = set()
    for did in CURATED_DISEASES:
        if did in kb['diseases']:
            allowed |= set(kb['diseases'][did]['phenotypes'])
    index = build_term_index(kb, gloss, allowed)

    records = load_jsonl(notes_path)
    systems = {
        'v1': collections.Counter(),
        'v2_scope_v1': collections.Counter(),
        'v2_scope_ng': collections.Counter(),
    }
    by_lang = {name: collections.defaultdict(collections.Counter) for name in systems}
    by_family = {name: collections.defaultdict(collections.Counter) for name in systems}
    n_matched = 0
    for record in records:
        text, lang = record['text'], record['language']
        gold = {(e['start'], e['end'], e['hp_id']): e['status']
                for e in record['entities'] if e['label'] == 'PHENOTYPE'}
        mentions = find_phenotype_mentions(text, index)
        spans = [(m['start'], m['end']) for m in mentions]
        resolvers = {'v2_scope_v1': ContextResolver(text, lang, spans, 'v1'),
                     'v2_scope_ng': ContextResolver(text, lang, spans, 'negex')}
        for mention in mentions:
            key = (mention['start'], mention['end'], mention['hp_id'])
            if key not in gold:
                continue
            n_matched += 1
            truth = gold[key]
            predictions = {'v1': classify_context(text, mention, lang)}
            for name, resolver in resolvers.items():
                predictions[name] = resolver.classify(mention['start'])
            for name, predicted in predictions.items():
                systems[name][(truth, predicted)] += 1
                by_lang[name][lang][(truth, predicted)] += 1
                by_family[name][record['template_family']][(truth, predicted)] += 1

    report = {
        'corpus': args.corpus, 'notes_file': str(notes_path.relative_to(ROOT)).replace('\\', '/'),
        'n_records': len(records), 'n_matched_mentions': n_matched,
        'extractor_version': EXTRACTOR_VERSION, 'context_scope_version': CONTEXT_SCOPE_VERSION,
        'statuses': list(STATUSES),
        'systems': {},
    }
    for name, confusion in systems.items():
        report['systems'][name] = {
            'per_class': per_class(confusion),
            'confusion': confusion_block(confusion),
            'confusion_matrix_gold_rows': True,
            'by_language': {lang: per_class(c)['_overall'] for lang, c in by_lang[name].items()},
            'by_family': {fam: per_class(c)['_overall'] for fam, c in by_family[name].items()},
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def line(name):
        row = report['systems'][name]['per_class']
        parts = [f'{name:12s} acc={row["_overall"]["accuracy"]:.4f} macroF1={row["_overall"]["macro_f1"]:.4f}']
        for status in STATUSES:
            cell = row[status]
            parts.append(f'{status}: P{cell["precision"]:.3f} R{cell["recall"]:.3f} F{cell["f1"]:.3f}')
        return ' | '.join(parts)

    print(f'corpus={args.corpus} records={len(records)} matched_mentions={n_matched}')
    for name in systems:
        print(line(name))
    for name in systems:
        block = report['systems'][name]['confusion']
        errors = {f'{g}->{p}': v for g, row in block.items() for p, v in row.items() if g != p and v}
        print(name, 'errors:', dict(sorted(errors.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
