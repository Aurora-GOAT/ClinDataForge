"""Transparent, conservative medical TEXT operators. Research prototype, not PHI certification."""
from __future__ import annotations
import hashlib
import hmac
import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

VERSION = '0.1.1'

# A deliberately narrow, auditable recognizer: never claim full PHI coverage.
PII_PATTERNS = {
    'NAME': re.compile(r'(?:(?<=姓名[:：])|(?<=患者姓名[:：])|(?<=Patient: ))([\u4e00-\u9fff]{2,4}|[A-Za-z]+ [A-Za-z]+)', re.I),
    'PHONE': re.compile(r'(?<!\d)(?:1[3-9]\d[ -]?\d{4}[ -]?\d{4})(?!\d)'),
    'MRN': re.compile(r'(?<=病历号[:：])[A-Z0-9-]{6,22}|(?<=MRN: )[A-Z0-9-]{6,22}', re.I),
}

@dataclass(frozen=True)
class PHISpan:
    start: int
    end: int
    label: str


def find_phi(text: str) -> list[PHISpan]:
    hits = []
    for label, pattern in PII_PATTERNS.items():
        for m in pattern.finditer(text):
            start, end = m.span(1) if m.lastindex else m.span()
            hits.append(PHISpan(start, end, label))
    hits.sort(key=lambda x: (x.start, -(x.end-x.start)))
    nonoverlap: list[PHISpan] = []
    for span in hits:
        if not nonoverlap or span.start >= nonoverlap[-1].end:
            nonoverlap.append(span)
    return nonoverlap


def mask_phi(text: str, spans: list[PHISpan]) -> str:
    output = []
    pos = 0
    for span in spans:
        if span.start < pos:
            continue
        output.extend((text[pos:span.start], '['+span.label+']'))
        pos = span.end
    output.append(text[pos:])
    return ''.join(output)


LAB_ALIASES = {
    'temp_c': r'(?:体温|T|temperature)',
    'glucose_mmol_l': r'(?:血糖|GLU|blood\s+glucose|glucose)',
    'hemoglobin_g_l': r'(?:血红蛋白|HGB|Hb|hemoglobin)',
    'alt_u_l': r'(?:谷丙转氨酶|ALT|alanine\s+aminotransferase)',
}
LAB_UNITS = {
    'temp_c': r'(?:℃|°\s*C|°\s*F)',
    'glucose_mmol_l': r'(?:mg\s*/\s*dL|mmol\s*/\s*L)',
    'hemoglobin_g_l': r'(?:g\s*/\s*dL|g\s*/\s*L)',
    'alt_u_l': r'(?:U\s*/\s*L)',
}
LAB_RANGE = {'temp_c': (25, 46), 'glucose_mmol_l': (0.5, 55),
             'hemoglobin_g_l': (20, 250), 'alt_u_l': (0, 5000)}
LAB_RE = {
    field: re.compile(r'(?<![A-Za-z0-9_])(?:' + LAB_ALIASES[field] + r')(?![A-Za-z0-9_])\s*(?:[:：=]\s*|\s+)'
                      + r'(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>' + LAB_UNITS[field] + r')', re.I)
    for field in LAB_ALIASES
}


def parse_labs(text: str) -> tuple[dict, list[str]]:
    result = {}
    issues = []
    for field, pattern in LAB_RE.items():
        matches = list(pattern.finditer(text))
        if len(matches) > 1:
            issues.append('AMBIGUOUS_MULTIPLE_'+field.upper())
            continue
        if not matches:
            continue
        m = matches[0]
        value = float(m.group('value'))
        unit = re.sub(r'\s+', '', m.group('unit')).lower()
        if field == 'temp_c':
            converted = (value-32)*5/9 if 'f' in unit else value
        elif field == 'glucose_mmol_l':
            converted = value/18.0182 if unit == 'mg/dl' else value
        elif field == 'hemoglobin_g_l':
            converted = value*10 if unit == 'g/dl' else value
        else:
            converted = value
        lo, hi = LAB_RANGE[field]
        if not math.isfinite(converted) or not lo <= converted <= hi:
            issues.append('OUT_OF_BROAD_RANGE_'+field.upper())
            continue
        result[field] = round(converted, 4)
    return result, issues


def extract_complaint(text: str) -> str | None:
    m = re.search(r'(?:主诉[:：]|症状描述[:：]|Complaint: )\s*([^;；\n|。]+)', text, flags=re.I)
    return m.group(1).strip()[:160] if m else None


def doc_fingerprint(text: str) -> str:
    plain = ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())
    return plain


def shingles(text: str, n: int = 3) -> set[str]:
    if len(text) <= n:
        return {text}
    return {text[i:i+n] for i in range(len(text)-n+1)}


def similarity(a: str, b: str) -> float:
    aa, bb = shingles(doc_fingerprint(a)), shingles(doc_fingerprint(b))
    return len(aa & bb) / len(aa | bb) if aa | bb else 1.0


def pseudo_id(raw: str, key: str) -> str:
    if not isinstance(key, str) or len(key) < 12:
        raise ValueError('Provide a string HMAC key of at least 12 characters')
    return hmac.new(key.encode(), raw.encode(), hashlib.sha256).hexdigest()[:20]


def quality_score(labs: dict, complaint: str | None, masked_note: str, issues: list[str], phi_residue: bool) -> float:
    # Operational routing score only, not a clinical truth/safety probability.
    score = 0.15 + (0.22 if complaint else 0) + min(len(labs), 3)*0.16 + min(len(masked_note)/120, 1)*0.15
    score -= 0.25*len(issues)
    if phi_residue:
        score -= 0.5
    return round(max(0, min(1, score)), 3)


def process_record(row: dict, key: str) -> dict:
    """Return an IN-MEMORY research record, not a safe text-export contract.

    Unknown PHI may remain in masked_text and complaint. Only the pipeline's
    explicit metadata projection may be persisted by the current prototype.
    """
    if not isinstance(row, Mapping):
        raise ValueError('Each record must be a JSON object')
    text = row.get('text')
    if not isinstance(text, str):
        raise ValueError('Missing string text field')
    if any(not isinstance(row.get(name), str) or not row[name].strip()
           for name in ('record_id','patient_group','encounter_group')):
        raise ValueError('record_id, patient_group and encounter_group must be nonempty strings')
    spans = find_phi(text)
    masked = mask_phi(text, spans)
    labs, issues = parse_labs(text)
    complaint = extract_complaint(masked)
    # This is a residual PATTERN scan, not a PHI guarantee.
    residue = bool(find_phi(masked))
    if len(text) < 15:
        issues.append('TEXT_TOO_SHORT')
    if not labs:
        issues.append('NO_SUPPORTED_LAB')
    if not complaint:
        issues.append('NO_SUPPORTED_COMPLAINT')
    if residue:
        issues.append('UNMASKED_KNOWN_PATTERN')
    score = quality_score(labs, complaint, masked, issues, residue)
    return {
        'record_key': pseudo_id(row['record_id'], key),
        'patient_group_key': pseudo_id(row['patient_group'], key),
        'encounter_group_key': pseudo_id(row['encounter_group'], key),
        'masked_text': masked,
        'complaint': complaint,
        'labs': labs,
        'quality_score': score,
        'operator_issues': issues,
        'phi_pattern_hits': len(spans),
        'status': 'quarantine' if issues else 'accepted',
        'schema_version': VERSION,
    }


def deduplicate(records: list[dict], threshold: float = .82) -> list[dict]:
    """Within-ENCOUNTER duplicate detection; distinct encounters are never merged."""
    groups: dict[tuple[str,str], list[dict]] = defaultdict(list)
    for row in records:
        groups[(row['patient_group_key'],row['encounter_group_key'])].append(row)
    for same_patient in groups.values():
        representatives: list[dict] = []
        for rec in same_patient:
            # A high character overlap alone must not erase a lab update or a
            # changed complaint. Missing and present lab fields also conflict.
            leader = next((r for r in representatives
                           if rec.get('labs') == r.get('labs')
                           and doc_fingerprint(rec.get('complaint') or '') == doc_fingerprint(r.get('complaint') or '')
                           and similarity(rec['masked_text'], r['masked_text']) >= threshold), None)
            if leader is None:
                representatives.append(rec)
                rec['duplicate_of'] = None
            else:
                rec['duplicate_of'] = leader['record_key']
                rec['status'] = 'quarantine'
                if 'DUPLICATE_WITHIN_PATIENT' not in rec['operator_issues']:
                    rec['operator_issues'].append('DUPLICATE_WITHIN_PATIENT')
    return records


def build_sft_candidates(accepted: list[dict]) -> list[dict]:
    """Deterministic *candidates* only. No expert validation, not model training data."""
    result = []
    for r in accepted:
        bucket = int(r['patient_group_key'][:8],16)%10
        split = 'train' if bucket < 8 else ('dev' if bucket==8 else 'test')
        response = json.dumps({'complaint': r['complaint'], 'labs': r['labs']}, ensure_ascii=False, sort_keys=True)
        result.append({'id': r['record_key'], 'split': split, 'patient_group_key':r['patient_group_key'], 'instruction': '从这段脱敏病历中抽取主诉和标准化检验值；只输出JSON。',
                       'input': r['masked_text'], 'output': response,
                       'provenance': 'heuristic_draft_requires_human_validation'})
    return result
