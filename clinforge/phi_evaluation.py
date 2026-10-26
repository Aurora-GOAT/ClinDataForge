"""PHI metrics and paired cluster bootstrap, independent of recognition methods.

Offsets are Unicode code points in the original text, half-open [start, end).
Clinical preservation labels are a separate, explicitly limited annotation layer.
"""
from __future__ import annotations

import collections
import math
import random

LABELS = ('NAME', 'PHONE', 'PATIENT_ID', 'DATE', 'ADDRESS', 'SSN', 'EMAIL', 'INSURANCE_ID')


def normalize_spans(spans, text):
    """Validate and deduplicate predictions without repairing offset errors."""
    result = set()
    for span in spans:
        if isinstance(span, dict):
            start, end, label = span.get('start'), span.get('end'), span.get('label')
        elif hasattr(span, 'start'):
            start, end, label = span.start, span.end, span.label
        else:
            raise TypeError(f'Unsupported prediction payload: {type(span).__name__}')
        label = 'PATIENT_ID' if label == 'MRN' else label
        if label not in LABELS or type(start) is not int or type(end) is not int:
            raise ValueError('Prediction requires supported label and integer offsets')
        if not 0 <= start < end <= len(text):
            raise ValueError('Prediction offsets outside text')
        result.add((label, start, end))
    return sorted(result, key=lambda s: (s[1], s[2], s[0]))


def merged_intervals(spans, text):
    intervals = []
    for _, start, end in normalize_spans(spans, text):
        if intervals and start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    return intervals


def redact_text(text, spans):
    """Mask the union of all predictions; no overlap may leave a suffix exposed."""
    output, position = [], 0
    for start, end in merged_intervals(spans, text):
        output.extend((text[position:start], '[PHI]'))
        position = end
    output.append(text[position:])
    return ''.join(output)


def _positions(spans):
    return {position for _, start, end in spans for position in range(start, end)}


def record_counts(row, predictions):
    """Return sufficient statistics; never infer safety from the absence of labels."""
    text = row['text']
    actual = set(normalize_spans(row['entities'], text))
    predicted = set(normalize_spans(predictions, text))
    by_label = {}
    for label in LABELS:
        gold = {s for s in actual if s[0] == label}
        inferred = {s for s in predicted if s[0] == label}
        by_label[label] = [len(gold & inferred), len(inferred - gold), len(gold - inferred)]
    marked = _positions(predicted)
    gold_positions = _positions(actual)
    protected_positions = set()
    protected_damaged = 0
    for span in row.get('protected_spans', []):
        start, end = span.get('start'), span.get('end')
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            raise ValueError('Invalid clinical preservation span')
        positions = set(range(start, end))
        if positions & gold_positions:
            raise ValueError('Clinical preservation labels overlap PHI gold')
        protected_positions.update(positions)
        protected_damaged += bool(positions & marked)
    total = [sum(values[i] for values in by_label.values()) for i in range(3)]
    return {'doc_id': row['doc_id'], 'language': row['language'],
            # Nested defaults are evaluated eagerly in Python, so every level
            # must be a .get(); otherwise a missing optional key raises.
            'bootstrap_group': row.get('bootstrap_group', row.get('split_group', row.get('template_group', row['doc_id']))),
            'tp': total[0], 'fp': total[1], 'fn': total[2], 'by_label': by_label,
            'has_phi': int(bool(actual)),
            'all_entities_exact': int(actual.issubset(predicted)),
            'all_gold_phi_characters_masked': int(gold_positions.issubset(marked)),
            'gold_phi_characters': len(gold_positions),
            'missed_phi_characters': len(gold_positions - marked),
            'protected_clinical_characters': len(protected_positions),
            'deleted_protected_clinical_characters': len(protected_positions & marked),
            'protected_clinical_spans': len(row.get('protected_spans', [])),
            'damaged_protected_clinical_spans': protected_damaged,
            'non_phi_characters': len(text) - len(gold_positions),
            'deleted_non_phi_characters': len(marked - gold_positions),
            'predicted_span_count': len(predicted)}


def _divide(numerator, denominator):
    return numerator / denominator if denominator else None


def prf(tp, fp, fn):
    return {'tp': tp, 'fp': fp, 'fn': fn,
            'precision': _divide(tp, tp + fp), 'recall': _divide(tp, tp + fn),
            'f1': _divide(2 * tp, 2 * tp + fp + fn)}


def summarize(counts):
    counts = list(counts)
    sums = collections.Counter()
    label_counts = {label: [0, 0, 0] for label in LABELS}
    for row in counts:
        for key, value in row.items():
            if type(value) is int:
                sums[key] += value
        for label, values in row['by_label'].items():
            for i, value in enumerate(values):
                label_counts[label][i] += value
    positive_rows = [row for row in counts if row['has_phi']]
    negative_rows = [row for row in counts if not row['has_phi']]
    return {'n_records': len(counts), 'n_positive_records': len(positive_rows),
            'n_negative_records': len(negative_rows),
            'entity_exact': prf(sums['tp'], sums['fp'], sums['fn']),
            'per_label': {label: prf(*values) for label, values in label_counts.items()},
            'all_entities_exact_positive_rate': _divide(sum(row['all_entities_exact'] for row in positive_rows), len(positive_rows)),
            'all_gold_phi_masked_positive_rate': _divide(sum(row['all_gold_phi_characters_masked'] for row in positive_rows), len(positive_rows)),
            'all_gold_phi_masked_all_records_rate': _divide(sums['all_gold_phi_characters_masked'], len(counts)),
            'phi_character_residual_rate': _divide(sums['missed_phi_characters'], sums['gold_phi_characters']),
            'protected_clinical_character_deletion_rate': _divide(sums['deleted_protected_clinical_characters'], sums['protected_clinical_characters']),
            'protected_clinical_span_damage_rate': _divide(sums['damaged_protected_clinical_spans'], sums['protected_clinical_spans']),
            'non_phi_character_deletion_rate': _divide(sums['deleted_non_phi_characters'], sums['non_phi_characters']),
            'negative_record_any_redaction_rate': _divide(sum(row['predicted_span_count'] > 0 for row in negative_rows), len(negative_rows)),
            'denominators': {key: sums[key] for key in (
                'gold_phi_characters', 'missed_phi_characters', 'protected_clinical_characters',
                'deleted_protected_clinical_characters', 'protected_clinical_spans',
                'damaged_protected_clinical_spans', 'non_phi_characters', 'deleted_non_phi_characters')}}


def _percentile(values, probability):
    ordered = sorted(values)
    location = (len(ordered) - 1) * probability
    left, right = math.floor(location), math.ceil(location)
    return ordered[left] + (ordered[right] - ordered[left]) * (location - left)


def paired_bootstrap(left, right, *, reps=2000, seed=20261025):
    """Paired cluster resampling, stratified by language; deltas are right-left."""
    if reps < 100:
        raise ValueError('Use at least 100 bootstrap replicates')
    left, right = list(left), list(right)
    if not left or [r['doc_id'] for r in left] != [r['doc_id'] for r in right]:
        raise ValueError('Paired methods require the same nonempty document order')
    strata = collections.defaultdict(dict)
    for index, (a, b) in enumerate(zip(left, right)):
        if (a['language'], a['bootstrap_group']) != (b['language'], b['bootstrap_group']):
            raise ValueError('Paired grouping differs')
        strata[a['language']].setdefault(a['bootstrap_group'], []).append(index)
    metrics = ('recall', 'f1', 'all_gold_phi_masked_positive_rate',
               'protected_clinical_character_deletion_rate')

    def values(rows):
        result = summarize(rows)
        return {'recall': result['entity_exact']['recall'], 'f1': result['entity_exact']['f1'],
                **{key: result[key] for key in metrics[2:]}}

    full_left, full_right = values(left), values(right)
    rng = random.Random(seed)
    distributions = {key: [] for key in metrics}
    for _ in range(reps):
        indices = []
        for groups in strata.values():
            group_values = list(groups.values())
            for _ in group_values:
                indices.extend(rng.choice(group_values))
        a, b = values(left[i] for i in indices), values(right[i] for i in indices)
        for key in metrics:
            if a[key] is not None and b[key] is not None:
                distributions[key].append(b[key] - a[key])
    result = {}
    for key, samples in distributions.items():
        result[key] = {'delta_right_minus_left': full_right[key] - full_left[key]
                       if full_left[key] is not None and full_right[key] is not None else None,
                       'ci95_percentile': [_percentile(samples, .025), _percentile(samples, .975)] if samples else None,
                       'valid_replicates': len(samples)}
    return {'reps': reps, 'seed': seed, 'resampling_unit': 'patient/template connected component, stratified by language',
            'groups_per_language': {language: len(groups) for language, groups in strata.items()},
            'interval_scope': 'Conditional on these synthetic sources and fixed methods; not population clinical safety or pretrained contamination assurance.',
            'metrics': result}


def error_rows(row, predictions):
    """Raw examples are permitted only for the pinned synthetic benchmark."""
    gold = set(normalize_spans(row['entities'], row['text']))
    predicted = set(normalize_spans(predictions, row['text']))
    examples = []
    for kind, spans in [('false_negative', gold - predicted), ('false_positive', predicted - gold)]:
        for label, start, end in sorted(spans, key=lambda s: (s[1], s[2], s[0])):
            examples.append({'doc_id': row['doc_id'], 'language': row['language'], 'kind': kind,
                             'label': label, 'start': start, 'end': end,
                             'value': row['text'][start:end],
                             'context': row['text'][max(0, start - 35):min(len(row['text']), end + 35)]})
    return examples
