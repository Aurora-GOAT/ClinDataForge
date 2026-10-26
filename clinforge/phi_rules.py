"""Task-specified, context-aware supplemental PHI rules.

Built without viewing the frozen test set. This is a development comparator,
not a privacy guarantee; the unchanged v0.1 rules remain method A.
"""
from __future__ import annotations

import re


RULE_REVISION = 'phase2-context-rules-v1'
LABELS = ('NAME', 'PHONE', 'PATIENT_ID', 'DATE', 'ADDRESS')


def _compile(pattern):
    return re.compile(pattern, re.IGNORECASE)


PATTERNS = {
    'PHONE': [
        _compile(r'(?<!\d)(?:(?:\+?86)[ .-]?)?1[3-9]\d(?:[ .-]?\d){8}(?!\d)'),
        _compile(r'(?<!\d)(?:\+?1[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]?\d{3}[ .-]\d{4}(?!\d)'),
        _compile(r'(?:phone|telephone|mobile|tel|contact\s*(?:number)?|call(?:back)?|电话|手机|联系方式|联系电话)\s*(?:is\s*|[:：=]\s*)?(?P<value>\+?[\d(][\d() .-]{6,24}\d)(?!\d)'),
    ],
    'PATIENT_ID': [
        _compile(r'(?:\bMRN|\bmedical\s+record\s*(?:number|no\.?|id)?|\bpatient\s*(?:number|no\.?|id|identifier)|\bchart\s*(?:number|no\.?|id)|\brecord\s*(?:number|no\.?|id)|病历(?:编号|号码|号)|患者(?:编号|号码|号|ID)|就诊(?:编号|号码|号)|住院(?:编号|号码|号)|病例(?:编号|号码|号))\s*(?:is\s*|[:：=#]\s*)?(?P<value>[A-Z0-9][A-Z0-9_-]{2,30})(?![A-Z0-9_-])'),
    ],
    'DATE': [
        _compile(r'(?<!\d)(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])(?!\d)'),
        _compile(r'(?<!\d)(?:0?[1-9]|[12]\d|3[01])[-/](?:0?[1-9]|[12]\d|3[01])[-/](?:(?:19|20)\d{2}|\d{2})(?!\d)'),
        _compile(r'(?:19|20)\d{2}年\s*\d{1,2}月\s*\d{1,2}[日号]'),
        _compile(r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+(?:19|20)\d{2}\b'),
        _compile(r'\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?[,]?\s+(?:19|20)\d{2}\b'),
    ],
    'NAME': [
        re.compile(r'(?:患者姓名|病人姓名|姓名|名字|我叫|名叫|称呼)(?:为|是)?\s*[:：=]?\s*(?P<value>[\u4e00-\u9fff]{2,4})(?=[\s，,。；;|/]|$)'),
        re.compile(r'(?:\b(?:Patient(?:\s+name)?|Name|Full\s+name)\s*[:=]\s*|\b(?:My|His|Her|The\s+patient.s)\s+name\s+is\s+|\b(?:Mr|Mrs|Ms|Dr)\.?\s+)(?P<value>[A-Z][a-z]+(?:[-\u2019\'][A-Z]?[a-z]+)?(?:\s+[A-Z][a-z]+(?:[-\u2019\'][A-Z]?[a-z]+)?){1,4})'),
    ],
    'ADDRESS': [
        re.compile(r'(?:家庭住址|家庭地址|通讯地址|居住地址|住址|地址|现居|居住在|住在)(?:为|是)?\s*[:：=]?\s*(?P<value>[^\s，,。；;\n|]{4,80})'),
        _compile(r'(?:\b(?:home\s+|residential\s+|mailing\s+)?address\s*[:=]\s*|\b(?:resides?|lives?)\s+at\s+)(?P<value>[^;\n|]{5,100}?)(?=(?:\.\s|[;\n|]|$))'),
    ],
    'SSN': [
        _compile(r'(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)'),
        _compile(r'(?:\bSSN\b|\bsocial\s+security\s+(?:number|no\.?|#)\b)\s*(?:is\s*|[:=]\s*)?(?P<value>\d{3}-\d{2}-\d{4}|\d{9})(?!\d)'),
    ],
    'EMAIL': [
        _compile(r'(?P<value>[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)'),
    ],
    'INSURANCE_ID': [
        _compile(r'(?:\b(?:member|policy|beneficiary|health\s+plan(?:\s+beneficiary)?)\s*(?:id|identifier|number|no\.?|#)\b|\binsurance\s+(?:id|number|no\.?)\b)\s*(?:is\s*|[:=]\s*)?(?P<value>[A-Z0-9][A-Z0-9-]{4,20})(?![A-Z0-9-])'),
    ],
}


def find_context_phi(text: str) -> list[dict]:
    if not isinstance(text, str):
        raise TypeError('PHI input must be a string')
    result = set()
    for label, patterns in PATTERNS.items():
        for pattern in patterns:
            for match in pattern.finditer(text):
                start, end = match.span('value') if 'value' in match.groupdict() else match.span()
                while end > start and text[end - 1] in ' .,:;，；。':
                    end -= 1
                if start < end:
                    result.add((start, end, label))
    return [{'start': a, 'end': b, 'label': label, 'score': 1.0, 'source': 'context_rule'}
            for a, b, label in sorted(result)]


def union_spans(*groups):
    """Exact union retains overlaps for transparent evaluation and coverage masking."""
    result = {}
    for spans in groups:
        for span in spans:
            key = (span['start'], span['end'], span['label'])
            if key not in result or span.get('score', 0) > result[key].get('score', 0):
                result[key] = dict(span)
    return [result[key] for key in sorted(result)]
