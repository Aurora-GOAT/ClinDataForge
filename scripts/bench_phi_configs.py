"""Measure the PHI gate before/after the phase-4 optimisation, on one machine.

Each configuration runs in its own process (peak RSS is a process property), on
the same synthetic notes, with the same weights revision, prompts, chunking and
threshold. Only precision / threads / batch size vary.

Modes
  --run NAME     run one configuration and write reports/phase4_perf/<NAME>/
  --report       build the comparison table and the span-agreement check

Configurations
  baseline_fp16_t2_b1  frozen phase-2 settings (fp16, 2 threads, one doc at a time)
  fp32_t4_b1           precision only, to separate dtype from batching
  fp32_t4_b8           precision + batching
  fp32_t8_b8           precision + batching + more intra-op threads

Usage: .venv-phi python -m scripts.bench_phi_configs --run baseline_fp16_t2_b1 --limit 60
"""
from __future__ import annotations
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = {
    'baseline_fp16_t2_b1': {'threshold': 0.2, 'threads': 2, 'chunk_words': 160,
                            'dtype': 'fp16', 'batch_size': 1},
    'fp32_t4_b1': {'threshold': 0.2, 'threads': 4, 'chunk_words': 160,
                   'dtype': 'fp32', 'batch_size': 1},
    'fp32_t4_b8': {'threshold': 0.2, 'threads': 4, 'chunk_words': 160,
                   'dtype': 'fp32', 'batch_size': 8},
    'fp32_t4_b8_unsorted': {'threshold': 0.2, 'threads': 4, 'chunk_words': 160,
                            'dtype': 'fp32', 'batch_size': 8, 'batch_sort': False},
    'fp32_t4_b8_sorted': {'threshold': 0.2, 'threads': 4, 'chunk_words': 160,
                          'dtype': 'fp32', 'batch_size': 8, 'batch_sort': True},
    'fp32_t8_b1': {'threshold': 0.2, 'threads': 8, 'chunk_words': 160,
                   'dtype': 'fp32', 'batch_size': 1},
    'fp32_t8_b8': {'threshold': 0.2, 'threads': 8, 'chunk_words': 160,
                   'dtype': 'fp32', 'batch_size': 8},
}


def peak_rss_mb():
    import os
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
                    'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage',
                    'PagefileUsage', 'PeakPagefileUsage')]

        process = ctypes.WinDLL('kernel32', use_last_error=True).GetCurrentProcess
        process.restype = wintypes.HANDLE
        reader = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
        reader.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        reader.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not reader(process(), ctypes.byref(counters), counters.cb):
            raise OSError('peak memory unavailable')
        return round(counters.PeakWorkingSetSize / 1048576, 1)
    import resource
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def run(name, limit):
    from clinforge.phi_models import GLiNEROnnxDetector
    config = CONFIGS[name]
    out = ROOT / 'reports/phase4_perf' / name
    out.mkdir(parents=True, exist_ok=True)
    notes = [json.loads(line) for line in
             open(ROOT / 'data/phase3_synth/gen/notes.jsonl', encoding='utf-8')][:limit]
    texts = [note['text'] for note in notes]
    started = time.perf_counter()
    detector = GLiNEROnnxDetector(ROOT / 'models/phase2_gliner_pii', config)
    init_seconds = round(time.perf_counter() - started, 2)
    # warm-up: ONNX Runtime selects kernels and allocates arenas on first run
    detector.find_many(texts[:2])
    detector.n_forward_calls = 0
    detector.n_chunks = 0
    per_doc = []
    spans_out = []
    batch = config['batch_size']
    total_started = time.perf_counter()
    for begin in range(0, len(texts), batch):
        group = texts[begin:begin + batch]
        tick = time.perf_counter()
        results = detector.find_many(group)
        elapsed = time.perf_counter() - tick
        share = elapsed / len(group)
        for offset, spans in enumerate(results):
            per_doc.append(share)
            spans_out.append({'doc_id': notes[begin + offset]['record_id'],
                              'spans': [[s['label'], s['start'], s['end']] for s in spans]})
    wall = time.perf_counter() - total_started
    result = {
        'config_name': name, 'config': config, 'n_records': len(texts),
        'n_characters': sum(len(t) for t in texts),
        'initialization_seconds': init_seconds,
        'inference_seconds': round(wall, 2),
        'mean_ms_per_doc': round(statistics.mean(per_doc) * 1000, 1),
        'p95_ms_per_doc': round(sorted(per_doc)[max(0, int(.95 * len(per_doc)) - 1)] * 1000, 1),
        'docs_per_second': round(len(texts) / wall, 3),
        'peak_rss_mb': peak_rss_mb(),
        'n_forward_calls': detector.n_forward_calls,
        'n_chunks': detector.n_chunks,
        'chunks_per_call': round(detector.n_chunks / detector.n_forward_calls, 2)
        if detector.n_forward_calls else None,
        'detector_metadata': detector.metadata,
    }
    (out / 'performance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    with open(out / 'spans.jsonl', 'w', encoding='utf-8') as handle:
        for row in spans_out:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    detector.close()
    print(json.dumps(result, ensure_ascii=False, indent=1)[:1600])
    return 0


def report():
    rows, spans = {}, {}
    for name in CONFIGS:
        path = ROOT / 'reports/phase4_perf' / name / 'performance.json'
        if path.exists():
            rows[name] = json.loads(path.read_text(encoding='utf-8'))
            spans[name] = {json.loads(line)['doc_id']: {tuple(s) for s in json.loads(line)['spans']}
                           for line in open(path.parent / 'spans.jsonl', encoding='utf-8')}
    baseline = rows.get('baseline_fp16_t2_b1')
    table = []
    for name, row in rows.items():
        entry = dict(row)
        if baseline:
            entry['speedup_mean'] = round(baseline['mean_ms_per_doc'] / row['mean_ms_per_doc'], 2)
            entry['speedup_wall'] = round(baseline['inference_seconds'] / row['inference_seconds'], 2)
            shared = sorted(set(spans[name]) & set(spans['baseline_fp16_t2_b1']))
            identical = sum(1 for doc in shared if spans[name][doc] == spans['baseline_fp16_t2_b1'][doc])
            only_b = sum(len(spans['baseline_fp16_t2_b1'][doc] - spans[name][doc]) for doc in shared)
            only_n = sum(len(spans[name][doc] - spans['baseline_fp16_t2_b1'][doc]) for doc in shared)
            entry['agreement'] = {'docs_compared': len(shared), 'docs_identical': identical,
                                  'doc_identity_rate': round(identical / len(shared), 4) if shared else None,
                                  'spans_only_in_baseline': only_b, 'spans_only_in_new': only_n}
        table.append(entry)
    out = ROOT / 'reports/phase4_perf/comparison.json'
    out.write_text(json.dumps({'configs': CONFIGS, 'table': table}, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    header = f"{'config':22s} {'ms/doc':>8s} {'p95':>8s} {'docs/s':>7s} {'RSS MB':>8s} {'calls':>6s} {'x':>5s} {'identical':>10s} {'spanΔ':>7s}"
    print(header)
    for entry in table:
        agree = entry.get('agreement', {})
        print(f"{entry['config_name']:22s} {entry['mean_ms_per_doc']:8.1f} {entry['p95_ms_per_doc']:8.1f} "
              f"{entry['docs_per_second']:7.2f} {entry['peak_rss_mb']:8.1f} {entry['n_forward_calls']:6d} "
              f"{entry.get('speedup_mean', 1.0):5.2f} "
              f"{agree.get('doc_identity_rate', 1.0):10.4f} "
              f"{agree.get('spans_only_in_baseline', 0) + agree.get('spans_only_in_new', 0):7d}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', choices=tuple(CONFIGS))
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--limit', type=int, default=60)
    args = parser.parse_args(argv)
    if args.report:
        return report()
    if not args.run:
        parser.error('--run or --report required')
    return run(args.run, args.limit)


if __name__ == '__main__':
    raise SystemExit(main())
