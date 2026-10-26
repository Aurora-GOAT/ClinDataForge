"""Fingerprint checks for frozen, local-only PHI experiments."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def code_fingerprints():
    paths = [p for pattern in ('clinforge/*.py', 'scripts/*phi*.py', 'requirements-phi.txt')
             for p in ROOT.glob(pattern)]
    return {p.relative_to(ROOT).as_posix(): sha256(p) for p in sorted(set(paths))}


def model_fingerprints(model_path):
    root = Path(model_path)
    if not root.is_dir():
        raise FileNotFoundError('Local model directory missing')
    files = [p for p in root.rglob('*') if p.is_file() and p.suffix in ('.onnx', '.json', '.txt', '.model')]
    if not any(p.suffix == '.onnx' for p in files):
        raise ValueError('No real ONNX model weights found')
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(files)}


def validate_lock(lock, dataset_dir, config_path, model_path):
    dataset_dir = Path(dataset_dir)
    if lock['code_sha256'] != code_fingerprints():
        raise ValueError('Frozen experiment code differs; test execution refused')
    if lock['config_sha256'] != sha256(config_path):
        raise ValueError('Frozen method configuration differs')
    for name, expected in lock['dataset_sha256'].items():
        if sha256(dataset_dir / name) != expected:
            raise ValueError('Frozen dataset artifact differs')
    if lock['model_sha256'] != model_fingerprints(model_path):
        raise ValueError('Frozen model artifacts differ')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))
