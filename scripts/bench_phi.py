"""Micro-benchmark of the GLiNER ONNX frontend to locate the real bottleneck.

Measures, on the same synthetic notes and the same machine:
  * session initialisation cost,
  * tokenisation/preparation cost vs. ONNX forward cost,
  * forward cost as a function of intra-op thread count and batch size,
  * peak RSS.

No optimisation is applied here; this script only measures. Findings are
reported in docs/CONTEXT_AND_PERF_CN.md.

Usage: .venv-phi python -m scripts.bench_phi [--limit 24]
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


def rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1048576, 1)
    except ImportError:
        return None


def bench_threads(texts, threads, warmup=2):
    import numpy as np
    import onnxruntime as ort
    from clinforge.phi_models import GLiNEROnnxDetector, WEIGHTS_RELPATH
    cfg = {'threshold': 0.2, 'threads': threads, 'chunk_words': 160}
    t0 = time.perf_counter()
    det = GLiNEROnnxDetector(ROOT / 'models/phase2_gliner_pii', cfg)
    init_s = round(time.perf_counter() - t0, 2)
    # warm up the graph (ORT does layout/kernel selection on first run)
    for text in texts[:warmup]:
        det.find(text)
    per_doc, per_chunk = [], []
    for text in texts:
        words = det.words_of(text) if hasattr(det, 'words_of') else None
        t = time.perf_counter()
        det.find(text)
        per_doc.append(time.perf_counter() - t)
    chunk_times = []
    for text in texts[:6]:
        from clinforge.phi_models import split_words
        chunk = split_words(text)[:160]
        t = time.perf_counter()
        det._chunk_scores(chunk)
        chunk_times.append(time.perf_counter() - t)
    info = {'threads': threads, 'init_s': init_s,
            'mean_ms_per_doc': round(statistics.mean(per_doc) * 1000, 1),
            'p95_ms_per_doc': round(sorted(per_doc)[int(.95 * len(per_doc)) - 1] * 1000, 1),
            'mean_ms_per_160word_chunk': round(statistics.mean(chunk_times) * 1000, 1),
            'rss_mb': rss_mb()}
    det.close()
    del det
    return info


def bench_batch(texts, threads, batch_sizes=(1, 2, 4, 8)):
    """Can the frozen graph accept a real batch dimension?"""
    import numpy as np
    import onnxruntime as ort
    from clinforge.phi_models import GLiNEROnnxDetector, split_words, PROMPTS
    cfg = {'threshold': 0.2, 'threads': threads, 'chunk_words': 160}
    det = GLiNEROnnxDetector(ROOT / 'models/phase2_gliner_pii', cfg)
    chunks = [split_words(t)[:160] for t in texts[:8]]
    results = []
    for bs in batch_sizes:
        batch = chunks[:bs]
        t = time.perf_counter()
        try:
            prepped = [det.prepare(c) for c in batch]
            max_len = max(p['input_ids'].shape[1] for p in prepped)
            # pad to a common length and build a batched word mask
            merged = {}
            for name in prepped[0]:
                if name == 'span_idx':
                    merged[name] = np.stack([p[name][0] for p in prepped])[None]
                elif name == 'span_mask':
                    merged[name] = np.stack([p[name][0] for p in prepped])[None]
                else:
                    pad = max_len - prepped[0][name].shape[1] if prepped[0][name].ndim == 2 and prepped[0][name].shape[1] > 1 else 0
                    if name == 'text_lengths':
                        merged[name] = np.concatenate([p[name] for p in prepped], axis=0)
                    else:
                        rows = []
                        for p in prepped:
                            width = p[name].shape[1]
                            pad_width = max_len - width
                            rows.append(np.pad(p[name], ((0, 0), (0, pad_width))))
                        merged[name] = np.concatenate(rows, axis=0)
            out = det.session.run(None, merged)[0]
            ok = True
            shape = list(out.shape)
        except Exception as exc:  # noqa: BLE001 - benchmark probe
            ok, shape = False, str(exc)[:200]
        elapsed = round((time.perf_counter() - t) * 1000, 1)
        results.append({'batch': bs, 'ok': ok, 'shape': shape,
                        'ms_total': elapsed, 'ms_per_doc': round(elapsed / bs, 1)})
    det.close()
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=16)
    parser.add_argument('--out', default='reports/phase4_perf/bench_raw.json')
    args = parser.parse_args(argv)
    notes = [json.loads(line) for line in
             open(ROOT / 'data/phase3_synth/gen/notes.jsonl', encoding='utf-8')][:args.limit]
    texts = [n['text'] for n in notes]
    report = {'n_notes': len(texts), 'avg_chars': round(sum(map(len, texts)) / len(texts), 1),
              'rss_after_import_mb': rss_mb(), 'thread_sweep': [], 'batch_probe': []}
    for threads in (2, 4, 8):
        report['thread_sweep'].append(bench_threads(texts, threads))
        print(report['thread_sweep'][-1], flush=True)
    report['batch_probe'] = bench_batch(texts, 8)
    print(json.dumps(report['batch_probe'], ensure_ascii=False, indent=1))
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
