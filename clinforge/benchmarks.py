"""Extensible medical benchmark interface (offline-first).

Supports loading MedMCQA-style 4-option items from a LOCAL file (jsonl or
parquet path supplied by the user) and scoring arbitrary prediction sources.
No network access and no paid API calls: live model evaluation is blocked by
default and requires explicit operator wiring of a model callable.

Split discipline: callers must keep benchmark items out of any training or
prompt-development set; the loader records the source file SHA256 so leakage
audits can prove which file was used.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

BENCHMARK_VERSION = 'bench-1.0.0'


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_medmcqa_jsonl(path):
    """Load items with fields: question, opa..opd, cop (0-3), optional subject."""
    items = []
    with open(path, encoding='utf-8') as handle:
        for i, line in enumerate(handle):
            if not line.strip():
                continue
            row = json.loads(line)
            options = [row.get('opa'), row.get('opb'), row.get('opc'), row.get('opd')]
            if not all(isinstance(o, str) and o for o in options):
                raise ValueError(f'MedMCQA item {i} missing options')
            cop = row.get('cop')
            if not isinstance(cop, int) or not 0 <= cop <= 3:
                raise ValueError(f'MedMCQA item {i} invalid cop')
            items.append({'id': row.get('id', f'mq-{i}'), 'question': row['question'],
                          'options': options, 'answer_idx': cop,
                          'subject': row.get('subject_name'), 'source': 'medmcqa_local'})
    return items


def score_predictions(items, predictions):
    """predictions: {item_id: chosen_index}. Returns accuracy + Wilson 95% CI."""
    correct = 0
    scored = 0
    for item in items:
        if item['id'] not in predictions:
            continue
        scored += 1
        if predictions[item['id']] == item['answer_idx']:
            correct += 1
    if not scored:
        return {'n': 0, 'accuracy': None}
    acc = correct / scored
    z = 1.959964
    denom = 1 + z * z / scored
    centre = (acc + z * z / (2 * scored)) / denom
    half = z * math.sqrt(acc * (1 - acc) / scored + z * z / (4 * scored * scored)) / denom
    return {'n': scored, 'correct': correct, 'accuracy': round(acc, 4),
            'wilson95': [round(centre - half, 4), round(centre + half, 4)]}


LIVE_EVAL_STATUS = {
    'status': 'BLOCKED',
    'reason': 'Live model evaluation requires an authorised model endpoint. No API key use, '
              'no paid calls: offline framework only until the operator grants explicit authorization.',
}
