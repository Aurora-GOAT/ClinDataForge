"""NegEx/ConText-style clinical context scope resolution (v2).

Why this module exists
----------------------
The v1 classifier (`med_extract.classify_context`) applied cue lists to a fixed
character window that was cut at *any* punctuation, including the colon and the
comma. On the phase-3 corpus that produced 783 `history -> affirmed` errors, all
of them Chinese: the section header `既往史：` sits *before* the colon, so the cue
fell outside the window, and follow-up items `，并有X，并有Y` inherited only one
clause back.

This rewrite implements the two ideas that make NegEx (Chapman 2001) and ConText
(Harkema 2009) work, instead of inventing another heuristic:

1. **Scope, not window.** A trigger governs the run from the trigger up to a
   hard terminator (sentence end / semicolon). Commas and colons do *not*
   terminate a run, which is exactly what enumerations need
   ("denies A, B, C" / "既往有A，并有B，并有C").
2. **Termination terms.** A contrastive conjunction between the trigger and the
   mention ends the scope ("但", "不过", "however", "except").

Three project-specific additions are required because Chinese phenotype
surfaces can themselves contain a negation character (`无言语` = absent speech,
`前脑无裂畸形` = holoprosencephaly, `无力` = weakness) and because Chinese notes
put section bodies on the next line:

3. **Mention masking.** Extracted mention spans are replaced by a filler
   character before trigger matching, so a negation cue never fires from inside
   an entity name. This is NegEx's pseudo-negation problem, solved
   structurally instead of with a hand-written exception list.
4. **Section-header line continuation.** A newline is *not* a terminator when
   the preceding line ends with a colon, so `既往史：\nA、B、C` keeps the header
   in scope. This mirrors the section-header handling of ConText.
5. **Nearest-trigger precedence.** Among triggers preceding the mention inside
   the same run, the one ending closest to the mention wins; ties break by the
   documented v1 priority suspicion > negation > history, because
   "尚需评估有无X" contains the negation character while expressing suspicion.

Cue vocabularies
----------------
`CUE_SETS['v1']` is the unchanged phase-3 list, kept so the improvement can be
attributed to scope handling rather than to extra words.
`CUE_SETS['negex']` adds trigger families taken from the NegEx / ConText
publications ("negative for", "past medical history", "no evidence of",
"不除外", "需警惕", ...). The ablation v1-scope vs negex-scope is reported
separately.

Known limitations (stated, not hidden): preceding triggers only, so
post-position cues ("A待排") are missed; a fixed cue lexicon, so unseen
phrasings are missed; a Chinese cue inside a term that is absent from the
extraction lexicon can still fire.
"""
from __future__ import annotations

import re

CONTEXT_SCOPE_VERSION = 'ctxscope-1.1.0'
MASK_CHAR = '\u2581'  # ▁ fills mention spans before trigger matching

# Priority is the documented v1 ordering, reused as a tie-break only.
STATUS_PRIORITY = {'suspected': 0, 'negated': 1, 'history': 2}

CUE_SETS = {
    'v1': {
        'zh': {
            'suspected': ('尚需评估有无', '疑似', '疑有', '疑为', '待排', '考虑', '不能除外', '可能'),
            'negated': ('否认', '未见', '不伴', '无', '没有'),
            'history': ('既往史', '既往', '曾有', '幼时', '儿时'),
        },
        'en': {
            'suspected': ('suspicion of', 'suspected', 'possible', 'to be confirmed',
                          'rule out', 'cannot exclude'),
            'negated': ('denies', 'denied', 'no ', 'without', 'not ', 'free of'),
            'history': ('past history', 'history of', 'previously', 'in childhood'),
        },
    },
    'negex': {
        'zh': {
            'suspected': ('尚需评估有无', '需警惕', '警惕', '不能除外', '不除外', '疑似',
                          '疑有', '疑为', '待排', '考虑', '可能'),
            'negated': ('否认', '未见', '未闻及', '未出现', '未有', '不伴', '阴性', '无', '没有'),
            'history': ('既往史', '既往', '过去史', '曾有', '曾患', '幼时', '儿时'),
        },
        'en': {
            'suspected': ('suspicion of', 'suspected', 'possible', 'to be confirmed',
                          'rule out', 'cannot exclude', 'cannot rule out'),
            'negated': ('no evidence of', 'negative for', 'denies', 'denied',
                        'no ', 'without', 'not ', 'free of'),
            'history': ('past medical history', 'past surgical history', 'past history',
                        'history of', 'previously', 'in childhood', 'prior history'),
        },
    },
}

# Hard terminators end a scope. Colons and commas deliberately do NOT.
# English adds the ASCII full stop and semicolon: ctxscope-1.0.0 omitted the
# full stop, which let a history trigger leak into the following English
# sentence. The omission was found by the first held-out run and is recorded in
# the phase-4 revision log; the frozen corpus was not touched.
HARD_TERMINATORS = {
    'zh': '。！？!?\n；;',
    'en': '。！？!?.;;\n',
}
# Contrastive conjunctions end the scope of an earlier trigger.
TERMINATION_TERMS = {
    'zh': ('但是', '但', '不过', '然而', '除外', '反之', '除此之外'),
    'en': ('however', 'but ', 'except', 'although', 'nevertheless', 'apart from'),
}
# A newline preceded by a colon is a section-header line, not a boundary.
HEADER_COLONS = ('：', ':')


def _build_triggers(language, cue_set):
    table = CUE_SETS[cue_set][language]
    entries = []
    for status, cues in table.items():
        for cue in cues:
            entries.append((cue, status))
    entries.sort(key=lambda item: -len(item[0]))
    pattern = re.compile('|'.join(re.escape(cue) for cue, _ in entries),
                         re.IGNORECASE if language == 'en' else 0)
    lookup = {cue.casefold(): status for cue, status in entries}
    return pattern, lookup


_CACHE = {}


def _trigger_table(language, cue_set):
    key = (language, cue_set)
    if key not in _CACHE:
        _CACHE[key] = _build_triggers(language, cue_set)
    return _CACHE[key]


def mask_mentions(text, spans):
    """Replace mention spans by MASK_CHAR, preserving every offset."""
    if not spans:
        return text
    chars = list(text)
    n = len(chars)
    for start, end in spans:
        for index in range(max(0, start), min(n, end)):
            chars[index] = MASK_CHAR
    return ''.join(chars)


class ContextResolver:
    """Per-document resolver: precomputes masking, terminators and triggers once."""

    def __init__(self, text, language='zh', mask_spans=(), cue_set='negex'):
        if cue_set not in CUE_SETS:
            raise ValueError('cue_set must be one of ' + ', '.join(CUE_SETS))
        self.language = language if language in CUE_SETS[cue_set] else 'zh'
        self.cue_set = cue_set
        self.text = text
        self.view = mask_mentions(text, mask_spans)
        breaks = HARD_TERMINATORS[self.language]
        # effective terminator positions (newline after a header colon is not one)
        self.is_terminator = bytearray(len(self.view))
        for index, char in enumerate(self.view):
            if char not in breaks:
                continue
            if char == '\n':
                probe = index - 1
                while probe >= 0 and self.view[probe] in ' \t\u3000':
                    probe -= 1
                if probe >= 0 and self.view[probe] in HEADER_COLONS:
                    continue
            self.is_terminator[index] = 1
        self.terminations = [term.casefold() for term in TERMINATION_TERMS[self.language]]
        pattern, lookup = _trigger_table(self.language, cue_set)
        self.hits = []
        for match in pattern.finditer(self.view):
            surface = match.group(0)
            status = lookup.get(surface.casefold())
            if status is None:
                continue
            self.hits.append((match.start(), match.end(), status, surface))
        self.hits.sort()

    def _run_start(self, index):
        while index > 0 and not self.is_terminator[index - 1]:
            index -= 1
        return index

    def _terminated(self, gap):
        folded = gap.casefold()
        return any(term in folded for term in self.terminations)

    def _decide(self, start, keep_trace=False):
        run_start = self._run_start(start)
        chosen, trace = None, []
        for t_start, t_end, status, surface in self.hits:
            if t_end > start:
                break
            if t_start < run_start:
                continue
            terminated = self._terminated(self.view[t_end:start])
            if keep_trace:
                trace.append({'cue': surface, 'status': status, 'end': t_end,
                              'terminated': terminated})
            if terminated:
                continue
            rank = (t_end, -STATUS_PRIORITY[status], len(surface))
            if chosen is None or rank > chosen[0]:
                chosen = (rank, status, surface)
        result = {'status': chosen[1] if chosen else 'affirmed',
                  'cue': chosen[2] if chosen else None,
                  'run': self.view[run_start:start]}
        if keep_trace:
            result['considered'] = trace
        return result

    def classify(self, start):
        """Resolve the status governing a mention that begins at `start`."""
        return self._decide(start)['status']

    def debug(self, start):
        """Same decision plus the evidence, for error analysis and tests."""
        return self._decide(start, keep_trace=True)


def resolve_context(text, mention, language=None, mask_spans=(), cue_set='negex'):
    """Functional wrapper used by tests and one-off analysis."""
    lang = language or mention.get('lang', 'zh')
    return ContextResolver(text, lang, mask_spans, cue_set).classify(mention['start'])
