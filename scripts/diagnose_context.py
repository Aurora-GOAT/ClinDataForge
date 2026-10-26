"""Diagnose context-status errors of the current cue classifier.

Reads the generator gold notes, re-runs the dictionary extractor and the
context classifier exactly as `pipeline_med` does (gold entities are used only
for the join, never for the decision), and dumps an error breakdown so the
failure modes are attributable rather than guessed:

  * language, template family, mention section (history/negation/course/...),
  * gold -> predicted status counts,
  * the literal cue window the classifier saw,
  * the preceding clause (for the continuation-inheritance path).

Usage: python -m scripts.diagnose_context --out reports/phase4_context/diagnosis.json
"""
from __future__ import annotations
import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clinforge.hpo_knowledge import load_knowledge_base  # noqa: E402
from clinforge.synthgen import load_gloss, CURATED_DISEASES  # noqa: E402
from clinforge.med_extract import (build_term_index, find_phenotype_mentions,  # noqa: E402
                                   classify_context, WINDOW_ZH, WINDOW_EN,
                                   SENTENCE_BREAKS_ZH, SENTENCE_BREAKS_EN)

ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path):
    with open(path, encoding='utf-8') as handle:
        return [json.loads(line) for line in handle if line.strip()]


def window_of(text, start, lang):
    win = WINDOW_ZH if lang == 'zh' else WINDOW_EN
    breaks = SENTENCE_BREAKS_ZH if lang == 'zh' else SENTENCE_BREAKS_EN
    lo = start
    while lo > 0 and text[lo - 1] not in breaks and start - lo < win:
        lo -= 1
    return lo, text[lo:start]


def section_of(text, start, lang):
    """Coarse section label from the preceding 40 characters (zh/en)."""
    head = text[max(0, start - 40):start]
    probes = [
        ('history', ('既往', 'Past history', 'history of', 'previously noted')),
        ('negation', ('否认', '无', 'No reported', 'denies', 'without')),
        ('suspected', ('疑', '待排', '考虑', '可能', 'suspicion', 'Possible', 'rule out')),
        ('laboratory', ('辅助检查', '血红蛋白', '血糖', '转氨酶', 'ALT', 'AST')),
    ]
    best = ('other', -1)
    for label, cues in probes:
        for cue in cues:
            pos = head.rfind(cue)
            if pos > best[1]:
                best = (label, pos)
    return best[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gen', default='data/phase3_synth/gen')
    parser.add_argument('--split-field', default=None,
                        help='only diagnose records whose split matches this value')
    parser.add_argument('--out', default='reports/phase4_context/diagnosis.json')
    args = parser.parse_args(argv)

    kb = load_knowledge_base(ROOT / 'data/phase3_synth/kb/hpo_snapshot.json')
    gloss = load_gloss(ROOT / 'data/curated/zh_phenotype_gloss.json')
    allowed = set()
    for did in CURATED_DISEASES:
        if did in kb['diseases']:
            allowed |= set(kb['diseases'][did]['phenotypes'])
    index = build_term_index(kb, gloss, allowed)

    records = load_jsonl(ROOT / args.gen / 'notes.jsonl')
    confusion = collections.Counter()
    by_family = collections.defaultdict(collections.Counter)
    by_lang = collections.defaultdict(collections.Counter)
    by_section = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    matched_total = 0

    for rec in records:
        text, lang = rec['text'], rec['language']
        gold = {(e['start'], e['end'], e['hp_id']): e['status']
                for e in rec['entities'] if e['label'] == 'PHENOTYPE'}
        mentions = [m for m in find_phenotype_mentions(text, index)]
        for m in mentions:
            key = (m['start'], m['end'], m['hp_id'])
            if key not in gold:
                continue
            matched_total += 1
            g = gold[key]
            p = classify_context(text, m, lang)
            confusion[(g, p)] += 1
            by_family[rec['template_family']][(g, p)] += 1
            by_lang[lang][(g, p)] += 1
            sec = section_of(text, m['start'], lang)
            by_section[sec][(g, p)] += 1
            if g != p:
                lo, win = window_of(text, m['start'], lang)
                bucket = f'{g}->{p}'
                if len(examples[bucket]) < 12:
                    examples[bucket].append({
                        'case_id': rec['case_id'], 'family': rec['template_family'],
                        'lang': lang, 'section': sec, 'mention': text[m['start']:m['end']],
                        'window': win, 'left_context': text[max(0, m['start'] - 45):m['start']],
                        'record_head': text[:60],
                    })

    def summarise(counter):
        out = {}
        total = sum(counter.values())
        correct = sum(v for (g, p), v in counter.items() if g == p)
        out['n'] = total
        out['accuracy'] = round(correct / total, 4) if total else None
        out['errors'] = {f'{g}->{p}': v for (g, p), v in sorted(counter.items(), key=lambda kv: -kv[1])
                         if g != p}
        return out

    report = {
        'diagnosis_version': 'ctxdiag-1.0.0',
        'n_matched_mentions': matched_total,
        'overall': summarise(confusion),
        'by_language': {k: summarise(v) for k, v in sorted(by_lang.items())},
        'by_family': {k: summarise(v) for k, v in sorted(by_family.items())},
        'by_section': {k: summarise(v) for k, v in sorted(by_section.items())},
        'history_recall': None,
        'examples': dict(examples),
    }
    hist_total = sum(v for (g, _p), v in confusion.items() if g == 'history')
    hist_ok = sum(v for (g, p), v in confusion.items() if g == 'history' and p == 'history')
    report['history_recall'] = round(hist_ok / hist_total, 4) if hist_total else None
    report['history_to_affirmed'] = confusion.get(('history', 'affirmed'), 0)

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('n_matched_mentions', 'overall', 'history_recall',
                                             'history_to_affirmed')}, ensure_ascii=False, indent=2))
    print('--- by family ---')
    for k, v in report['by_family'].items():
        print(k, v['n'], v['accuracy'], v['errors'])
    print('--- by language ---')
    for k, v in report['by_language'].items():
        print(k, v['n'], v['accuracy'], v['errors'])
    print('--- by section ---')
    for k, v in report['by_section'].items():
        print(k, v['n'], v['accuracy'], v['errors'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
