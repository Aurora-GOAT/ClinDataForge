"""Freeze data, source, method configuration and weights BEFORE opening test."""
from __future__ import annotations
import argparse
import datetime
from pathlib import Path

from clinforge.artifacts import write_json_no_overwrite
from clinforge.phi_experiment import code_fingerprints, model_fingerprints, sha256


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    data = Path(args.data)
    files = ('train.jsonl', 'dev.jsonl', 'test.jsonl', 'demo_pipeline.jsonl', 'manifest.json')
    lock = {'protocol': 'docs/PHI_EVALUATION_PROTOCOL_CN.md',
            'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'dataset_sha256': {name: sha256(data / name) for name in files},
            'config_sha256': sha256(args.config),
            'protocol_sha256': sha256('docs/PHI_EVALUATION_PROTOCOL_CN.md'),
            'code_sha256': code_fingerprints(), 'model_sha256': model_fingerprints(args.model),
            'bootstrap_reps': 2000, 'bootstrap_seed': 20261025,
            'formal_test_policy': 'One first formal run; identical frozen replays require explicit replay flag, new output directory, no method changes.'}
    write_json_no_overwrite(args.out, lock)
    print('Frozen experiment SHA256:', sha256(args.out))


if __name__ == '__main__':
    main()
