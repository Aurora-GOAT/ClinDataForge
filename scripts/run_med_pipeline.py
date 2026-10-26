"""Run the medical structuring + quality pipeline on the synthetic corpus.

Usage: .venv-phi python -m scripts.run_med_pipeline [--phi-gate hybrid|off]
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.hpo_knowledge import load_knowledge_base
from clinforge.synthgen import load_gloss
from clinforge.pipeline_med import run_med_pipeline

ROOT = Path(__file__).resolve().parent.parent
HMAC_KEY = 'clindataforge-phase3-demo-key'  # demo key for synthetic data only


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notes', default='data/phase3_synth/gen/notes.jsonl')
    parser.add_argument('--kb', default='data/phase3_synth/kb/hpo_snapshot.json')
    parser.add_argument('--gloss', default='data/curated/zh_phenotype_gloss.json')
    parser.add_argument('--frozen-config', default='configs/phase4_phi_fast.json',
                        help='phase4_phi_fast.json = fp32 + batched gate (same weights revision, '
                             'same threshold); phase2_phi_frozen.json reproduces phase 2 exactly')
    parser.add_argument('--model', default='models/phase2_gliner_pii')
    parser.add_argument('--out', default='data/phase3_synth/pipeline_out')
    parser.add_argument('--phi-gate', choices=('hybrid', 'off'), default='hybrid')
    parser.add_argument('--context', choices=('v1', 'v2'), default='v2',
                        help='v1 reproduces the phase-3 window classifier')
    parser.add_argument('--cue-set', choices=('v1', 'negex'), default='negex')
    args = parser.parse_args(argv)
    kb = load_knowledge_base(ROOT / args.kb)
    gloss = load_gloss(ROOT / args.gloss)
    gate = None
    if args.phi_gate == 'hybrid':
        from clinforge.pipeline_med import load_phi_gate
        config = json.loads((ROOT / args.frozen_config).read_text(encoding='utf-8'))
        gate = load_phi_gate(config, ROOT / args.model)
    started = time.perf_counter()
    audit = run_med_pipeline(ROOT / args.notes, ROOT / args.out, kb, gloss, key=HMAC_KEY,
                             phi_gate=gate, context_version=args.context,
                             cue_set=args.cue_set)
    audit['wall_seconds'] = round(time.perf_counter() - started, 2)
    try:
        import psutil
        audit['peak_rss_mb'] = round(psutil.Process().memory_info().rss / 1048576, 1)
    except ImportError:
        audit['peak_rss_mb'] = None
    (ROOT / args.out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(audit, ensure_ascii=False, indent=2)[:2000])


if __name__ == '__main__':
    main()
