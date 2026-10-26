"""Medical entity extraction, context classification and lab standardisation.

Dictionary-grounded extraction: the term index is built from the verified
HPO snapshot (English official names + non-obsolete synonyms) and the curated
project Chinese gloss. No fabricated terminology: every extracted mention is
anchored to an HP id that exists in the snapshot.

Context classification uses explicit cue lists (documented below) applied to
the sentence-bounded window preceding the mention; priority suspicion >
negation > history > affirmed, because cues such as "尚需评估有无" contain
the negation character "无" while expressing suspicion.

Lab standardisation covers ALT/AST (U/L), glucose (mmol/L <-> mg/dL,
factor 18.016 from molar mass 180.16 g/mol) and hemoglobin (g/L <-> g/dL,
factor 10). Conversion factors are documented, not invented.

This module is evaluated against generator gold labels (template-internal
self-check) and reported separately from any independent benchmark.
"""
from __future__ import annotations
import re
import unicodedata

EXTRACTOR_VERSION = 'medextract-1.0.1'

CONTEXT_CUES = {
    'zh': {
        'suspected': ['尚需评估有无', '疑似', '疑有', '疑为', '待排', '考虑', '不能除外', '可能'],
        'negated': ['否认', '未见', '不伴', '无', '没有'],
        'history': ['既往', '曾有', '幼时', '儿时'],
    },
    'en': {
        'suspected': ['suspicion of', 'suspected', 'possible', 'to be confirmed', 'rule out', 'cannot exclude'],
        'negated': ['denies', 'denied', 'no ', 'without', 'not ', 'free of'],
        'history': ['history of', 'previously', 'past history', 'in childhood'],
    },
}
WINDOW_ZH, WINDOW_EN = 24, 48
# Clause-level breaks: a cue governs only its own clause. zh additionally
# treats commas/colons/quotes as breaks ("尚需评估有无X，否认Y" -> Y negated);
# en keeps commas inside the window because negation lists are comma-separated
# ("denies A, B, C").
SENTENCE_BREAKS_ZH = '。；;！!？?\n，,：:“”"'
SENTENCE_BREAKS_EN = '.;!?\n:'

LAB_ALIASES_V2 = {
    'ALT': r'(?:谷丙转氨酶|丙氨酸氨基转移酶|ALT|alanine\s+aminotransferase)',
    'AST': r'(?:谷草转氨酶|天冬氨酸氨基转移酶|AST|aspartate\s+aminotransferase)',
    'GLUCOSE': r'(?:空腹血糖|血糖|fasting\s+glucose|blood\s+glucose|glucose)',
    'HGB': r'(?:血红蛋白|HGB|Hb|hemoglobin)',
}
LAB_UNITS_V2 = {
    'ALT': r'(?:U\s*/\s*L)',
    'AST': r'(?:U\s*/\s*L)',
    'GLUCOSE': r'(?:mmol\s*/\s*L|mg\s*/\s*dL)',
    'HGB': r'(?:g\s*/\s*dL|g\s*/\s*L)',
}
LAB_DECIMALS = {('GLUCOSE', 'mmol/L'): 1, ('HGB', 'g/dL'): 1}
# Conversion to standard units, documented factors.
GLUCOSE_MGDL_TO_MMOLL = 18.016   # molar mass glucose 180.16 g/mol
HGB_GDL_TO_GL = 10.0


def build_term_index(kb, gloss, allowed_hp_ids=None):
    """(normalized surface form) -> (hp_id, display_text, language).

    The lexicon is scoped to allowed_hp_ids when given: the pipeline demo
    indexes the union of the demo diseases' annotation terms (plus curated zh
    gloss), which is documented as the extraction lexicon scope. An unscoped
    index over all ~20k HPO terms is possible but slower.
    """
    index = {}
    terms = kb['terms']
    for hp_id, zh in gloss['phenotypes'].items():
        if hp_id in terms and (allowed_hp_ids is None or hp_id in allowed_hp_ids):
            index[zh] = (hp_id, zh, 'zh')
    for hp_id, term in terms.items():
        if term['is_obsolete'] or (allowed_hp_ids is not None and hp_id not in allowed_hp_ids):
            continue
        for surface in [term['name'], *term['synonyms']]:
            key = surface.casefold()
            if key not in index:
                index[key] = (hp_id, surface, 'en')
    return index


def find_phenotype_mentions(text, index):
    """Longest-match dictionary scan. zh: substring; en: word-bounded."""
    spans = []  # (start, end, hp_id, surface, lang)
    lowered = text.casefold()
    zh_terms = sorted((t for t in index if index[t][2] == 'zh'), key=len, reverse=True)
    en_terms = sorted((t for t in index if index[t][2] == 'en'), key=len, reverse=True)
    occupied = [False] * (len(text) + 1)

    def free(start, end):
        return not any(occupied[start:end])

    for term in zh_terms:
        start = 0
        while True:
            pos = text.find(term, start)
            if pos < 0:
                break
            end = pos + len(term)
            if free(pos, end):
                hp_id, surface, lang = index[term]
                spans.append((pos, end, hp_id, surface, lang))
                for i in range(pos, end):
                    occupied[i] = True
            start = pos + 1
    for term in en_terms:
        if len(term) < 4:  # avoid noise from ultra-short synonyms
            continue
        start = 0
        while True:
            pos = lowered.find(term, start)
            if pos < 0:
                break
            end = pos + len(term)
            left_ok = pos == 0 or not (lowered[pos - 1].isalnum())
            right_ok = end >= len(lowered) or not (lowered[end].isalnum())
            if left_ok and right_ok and free(pos, end):
                hp_id, surface, lang = index[term]
                spans.append((pos, end, hp_id, surface, lang))
                for i in range(pos, end):
                    occupied[i] = True
            start = pos + 1
    spans.sort()
    return [{'start': s, 'end': e, 'hp_id': h, 'text': text[s:e], 'lang': l}
            for s, e, h, _surface, l in spans]


def classify_context(text, mention, language=None):
    """Sentence-bounded cue-window context classification."""
    start = mention['start']
    lang = language or mention['lang']
    win = WINDOW_ZH if lang == 'zh' else WINDOW_EN
    breaks = SENTENCE_BREAKS_ZH if lang == 'zh' else SENTENCE_BREAKS_EN
    lo = start
    while lo > 0 and text[lo - 1] not in breaks and start - lo < win:
        lo -= 1
    window = text[lo:start]
    check = window if lang == 'zh' else window.casefold()
    for status in ('suspected', 'negated', 'history'):
        for cue in CONTEXT_CUES[lang][status]:
            if cue in check:
                return status
    # Continuation clauses inherit the governing cue of the previous clause:
    # "既往有A，并有B" -> B is history; "denies A, and B" -> B negated.
    continuations = ('并有', '伴', '及', '和') if lang == 'zh' else ('and ', 'also ')
    stripped = check.strip(' 、，,')
    if any(stripped.startswith(c) for c in continuations):
        hi = lo
        while lo > 0 and hi > 0:
            lo = hi - 1
            while lo > 0 and text[lo - 1] not in breaks and hi - lo < win:
                lo -= 1
            prev = text[lo:hi - 1]
            prev_check = prev if lang == 'zh' else prev.casefold()
            for status in ('suspected', 'negated', 'history'):
                for cue in CONTEXT_CUES[lang][status]:
                    if cue in prev_check:
                        return status
            break
    return 'affirmed'


def _norm_unit(unit):
    return re.sub(r'\s+', '', unit).replace('﹪', '').lower()


def parse_labs_v2(text):
    """Multi-analyte lab extraction with unit standardisation.

    Returns (entries, issues). entries: list of dicts with spans, raw value/
    unit and standardised value/unit. Duplicate analyte mentions with
    conflicting values are flagged, not silently merged.
    """
    entries, issues = [], []
    for analyte, alias in LAB_ALIASES_V2.items():
        pattern = re.compile(
            r'(?<![A-Za-z0-9_])(?:' + alias + r')(?![A-Za-z0-9_])'
            r'\s*(?:[:：=]\s*|\s+)'
            r'(?P<value>[-+]?\d+(?:\.\d+)?)\s*'
            r'(?P<unit>' + LAB_UNITS_V2[analyte] + r')', re.I)
        for m in pattern.finditer(text):
            raw = float(m.group('value'))
            unit = _norm_unit(m.group('unit'))
            if analyte == 'GLUCOSE' and unit == 'mg/dl':
                std, std_unit = round(raw / GLUCOSE_MGDL_TO_MMOLL, 2), 'mmol/L'
            elif analyte == 'HGB' and unit == 'g/dl':
                std, std_unit = round(raw * HGB_GDL_TO_GL, 2), 'g/L'
            else:
                std, std_unit = round(raw, 2), 'mmol/L' if analyte == 'GLUCOSE' else ('g/L' if analyte == 'HGB' else 'U/L')
            entries.append({'label': 'LAB_VALUE', 'analyte': analyte,
                            'test_start': m.start(), 'start': m.start('value'), 'end': m.end('unit'),
                            'text': m.group('value') + ' ' + m.group('unit'),
                            'value_raw': raw, 'unit_raw': m.group('unit'),
                            'value_std': std, 'unit_std': std_unit})
    by_analyte = {}
    for e in entries:
        by_analyte.setdefault(e['analyte'], set()).add(e['value_std'])
    for analyte, values in by_analyte.items():
        if len(values) > 1:
            issues.append('CONFLICTING_VALUES_' + analyte)
    entries.sort(key=lambda e: e['start'])
    return entries, issues


def normalize_text(text):
    return unicodedata.normalize('NFKC', text)
