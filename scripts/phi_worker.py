"""One method per CPU process; actual local inference and peak process memory."""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

from clinforge.artifacts import write_json_no_overwrite
from clinforge.phi_evaluation import normalize_spans


def peak_rss_bytes():
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
        current = ctypes.WinDLL('kernel32', use_last_error=True).GetCurrentProcess
        current.restype = wintypes.HANDLE
        read_memory = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
        read_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
        read_memory.restype = wintypes.BOOL
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not read_memory(current(), ctypes.byref(counters), counters.cb):
            raise OSError('Unable to measure peak process memory')
        return counters.PeakWorkingSetSize
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == 'darwin' else value * 1024)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--method', required=True, choices=('A', 'B', 'C', 'D'))
    parser.add_argument('--input', required=True)
    parser.add_argument('--warmup', required=True, help='Training split only')
    parser.add_argument('--config', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    started = time.perf_counter()
    from clinforge.phi_models import create_detector
    detector = create_detector(args.method, args.model, config)
    detect, metadata = detector.find, detector.metadata
    initialization = time.perf_counter() - started
    warmup_row = next(json.loads(line) for line in Path(args.warmup).read_text(encoding='utf-8').splitlines() if line.strip())
    started = time.perf_counter()
    detect(warmup_row['text'])
    warmup_seconds = time.perf_counter() - started
    timings, predictions = [], []
    characters = 0
    # Gold is loaded by the coordinator only after all methods are frozen.
    # This worker passes only the text to each detector and emits only offsets.
    rows = [json.loads(line) for line in Path(args.input).read_text(encoding='utf-8').splitlines() if line.strip()]
    batch = int(config.get('batch_size', 1) or 1) if hasattr(detector, 'find_many') else 1
    if batch > 1:
        # Batched mode: the elapsed time of one forward batch is attributed
        # equally to the documents in it, and the contract is recorded in
        # performance.json so the two modes are never compared silently.
        for begin in range(0, len(rows), batch):
            group = rows[begin:begin + batch]
            started = time.perf_counter()
            results = detector.find_many([row['text'] for row in group])
            elapsed = time.perf_counter() - started
            share = elapsed / len(group)
            for row, spans in zip(group, results):
                clean = normalize_spans(spans, row['text'])
                timings.append(share)
                characters += len(row['text'])
                predictions.append({'doc_id': row['doc_id'], 'spans': [
                    {'label': label, 'start': start, 'end': end} for label, start, end in clean]})
    else:
        for row in rows:
            started = time.perf_counter()
            spans = detect(row['text'])
            elapsed = time.perf_counter() - started
            clean = normalize_spans(spans, row['text'])
            timings.append(elapsed)
            characters += len(row['text'])
            predictions.append({'doc_id': row['doc_id'], 'spans': [
                {'label': label, 'start': start, 'end': end} for label, start, end in clean]})
    with (out / 'predictions.jsonl').open('x', encoding='utf-8', newline='\n') as stream:
        for row in predictions:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
    total = sum(timings)
    write_json_no_overwrite(out / 'performance.json', {
        'method': args.method, 'n_records': len(rows), 'n_characters': characters,
        'initialization_seconds': initialization, 'training_warmup_seconds': warmup_seconds,
        'inference_seconds': total, 'inference_seconds_each': timings,
        'records_per_second': len(rows) / total if total else None,
        'characters_per_second': characters / total if total else None,
        'peak_process_rss_bytes': peak_rss_bytes(),
        'memory_scope': 'OS peak process working set; includes runtime, weights, initialization, warmup and inference',
        'throughput_scope': ('One sequential document at a time; excludes model load, warmup, JSON I/O and scoring'
                             if batch <= 1 else
                             'Batched inference; one batch time is shared equally across its documents; '
                             'excludes model load, warmup, JSON I/O and scoring'),
        'batch_size': batch,
        'python': sys.version, 'platform': platform.platform(), 'logical_cpu_count': os.cpu_count(),
        'detector_metadata': metadata})


if __name__ == '__main__':
    main()
