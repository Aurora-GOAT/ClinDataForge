"""Build and freeze the held-out context corpus.

The corpus is written once, its SHA256 is recorded next to it, and the file is
committed before any evaluation of the v2 classifier touches it. Re-running the
script reproduces byte-identical output (seed 20261027) and fails if a frozen
file would be overwritten with different content.

Usage: python -m scripts.build_context_holdout
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.hpo_knowledge import load_knowledge_base
from clinforge.synthgen import load_gloss
from clinforge.holdout_context import generate, write_corpus, HOLDOUT_VERSION, HOLDOUT_SEED

ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='data/phase4_context/holdout_notes.jsonl')
    parser.add_argument('--force', action='store_true',
                        help='overwrite an existing corpus (only valid before freezing)')
    args = parser.parse_args(argv)
    out = ROOT / args.out
    if out.exists() and not args.force:
        raise FileExistsError(f'{out} already exists; the corpus is frozen')
    kb = load_knowledge_base(ROOT / 'data/phase3_synth/kb/hpo_snapshot.json')
    gloss = load_gloss(ROOT / 'data/curated/zh_phenotype_gloss.json')
    records = generate(kb, gloss)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_corpus(records, out)
    # span self-consistency: every gold entity must literally match its offsets
    bad = 0
    for record in records:
        for entity in record['entities']:
            if record['text'][entity['start']:entity['end']] != entity['text']:
                bad += 1
    manifest = {
        'holdout_version': HOLDOUT_VERSION, 'seed': HOLDOUT_SEED,
        'n_records': len(records),
        'n_entities': sum(len(r['entities']) for r in records),
        'span_errors': bad,
        'sha256': sha256_file(out),
        'file': str(out.relative_to(ROOT)).replace('\\', '/'),
        'status': 'FROZEN — must not be modified after the first evaluation run',
        'independence': 'seed + template realisations + phenotype sampling differ from the '
                        'phase-3 development corpus (synthgen-1.0.0, seed 20261026); '
                        'disease set and cue vocabulary are shared.',
    }
    (out.parent / 'holdout_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if bad:
        raise SystemExit('span self-consistency failed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
