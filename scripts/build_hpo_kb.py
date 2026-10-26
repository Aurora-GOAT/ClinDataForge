"""Build the verified HPO knowledge snapshot and select the rare-disease demo set.

Usage: python -m scripts.build_hpo_kb --out data/phase3_synth
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinforge.hpo_knowledge import build_knowledge_base, select_rare_diseases
from clinforge.synthgen import CURATED_DISEASES, DISEASE_SET_RATIONALE

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--src', default='data/external/hpo')
    parser.add_argument('--out', default='data/phase3_synth')
    parser.add_argument('--n-diseases', type=int, default=16)
    parser.add_argument('--seed', type=int, default=20261026)
    parser.add_argument('--min-phenotypes', type=int, default=8)
    parser.add_argument('--algorithmic', action='store_true',
                        help='use the rule-based selector instead of the curated demo set')
    args = parser.parse_args(argv)
    src, out = ROOT / args.src, ROOT / args.out
    snapshot = build_knowledge_base(src / 'hp.obo', src / 'phenotype.hpoa', out / 'kb' / 'hpo_snapshot.json')
    # Curated demo set: every entry must exist in the verified snapshot and
    # meet the minimum annotation depth; the rule-based selector remains
    # available via --algorithmic for sensitivity checks.
    if args.algorithmic:
        chosen = select_rare_diseases(snapshot, args.n_diseases, args.seed, args.min_phenotypes)
        rule = 'algorithmic ranking (see clinforge.hpo_knowledge.select_rare_diseases)'
    else:
        chosen = list(CURATED_DISEASES)
        rule = 'curated demo set (see DISEASE_SET_RATIONALE); each entry verified against snapshot'
        for disease_id in chosen:
            record = snapshot['diseases'].get(disease_id)
            if record is None or len(record['phenotypes']) < args.min_phenotypes:
                raise ValueError(f'Curated disease fails verification: {disease_id}')
    selection = {
        'seed': args.seed, 'min_phenotypes': args.min_phenotypes,
        'rule': rule, 'rationale': None if args.algorithmic else DISEASE_SET_RATIONALE,
        'diseases': [
            {'disease_id': d, 'disease_name': snapshot['diseases'][d]['disease_name'],
             'source': snapshot['diseases'][d]['source'],
             'n_phenotypes': len(snapshot['diseases'][d]['phenotypes']),
             'onsets': snapshot['diseases'][d]['onsets']}
            for d in chosen],
    }
    sel_path = out / 'kb' / 'disease_selection.json'
    if sel_path.exists():
        raise FileExistsError(sel_path)
    sel_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'n_terms': snapshot['n_terms'], 'n_diseases_total': snapshot['n_diseases'],
                      'selected': selection['diseases']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
