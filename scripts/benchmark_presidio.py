"""Minimal historical 60-case diagnostic; no model download or rule tuning."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

from clinforge.artifacts import write_json_no_overwrite
from clinforge.evaluate import prf
from clinforge.operators import find_phi
from clinforge.presidio_adapter import PresidioAdapter, PresidioUnavailable, environment_status
from clinforge.stress import STRESS_TEMPLATES
from clinforge.synthetic import put_value


def historical_cases():
    # Reproduce the existing generator exactly, without changing its source.
    for i in range(60):
        phone = '138' + f'{(371 * i + 1011) % 100000000:08d}'
        if i % 6 == 2:
            phone = phone[:3] + '.' + phone[3:7] + '.' + phone[7:]
        text, spans = put_value(STRESS_TEMPLATES[i % len(STRESS_TEMPLATES)], {
            'NAME': ['Alex Taylor', '李若青', '陈佳宁'][i % 3],
            'PHONE': phone, 'MRN': f'EDTEST-{i:06d}'})
        yield {'text': text, 'phi_spans': spans}


def measure(detector, cases):
    tp = fp = fn = 0
    seconds = 0.0
    for row in cases:
        started = time.perf_counter()
        inferred = {(span.label, span.start, span.end) for span in detector(row['text'])}
        seconds += time.perf_counter() - started
        gold = {(span['label'], span['start'], span['end']) for span in row['phi_spans']}
        tp += len(inferred & gold)
        fp += len(inferred - gold)
        fn += len(gold - inferred)
    return {'entity_span_exact': prf(tp, fp, fn), 'inference_seconds': seconds,
            'records_per_second': len(cases) / seconds if seconds else None,
            'timing_scope': 'One run of 60 documents, excluding initialization and gold scoring; environment-sensitive.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, help='New JSON file; existing artifacts are rejected')
    args = parser.parse_args(argv)
    if Path(args.out).exists():
        raise FileExistsError('Refusing to overwrite Presidio diagnostic')
    cases = list(historical_cases())
    report = {'scope': 'Historical synthetic diagnostic only; six repeated templates, not independent generalization.',
        'n_records': len(cases), 'n_gold_phi': sum(len(row['phi_spans']) for row in cases),
        'cases_sha256': hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest(),
        'python': sys.version, 'executable': sys.executable, 'platform': platform.platform(),
        'environment': environment_status(), 'original_rules': measure(find_phi, cases),
        'presidio': {'status': 'not_run', 'metrics': None},
        'safety': 'No pipeline integration or text-export permission change; no downloads or external inference.'}
    started = time.perf_counter()
    try:
        adapter = PresidioAdapter()
    except PresidioUnavailable as error:
        report['presidio'].update(reason=str(error),
            initialization_attempt_seconds=time.perf_counter() - started)
    else:
        initialization_seconds = time.perf_counter() - started
        # Runtime errors propagate, rather than being scored as empty predictions.
        report['presidio'] = {'status': 'executed', 'initialization_seconds': initialization_seconds,
            'metadata': adapter.metadata, 'metrics': measure(adapter.find, cases)}
    write_json_no_overwrite(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
