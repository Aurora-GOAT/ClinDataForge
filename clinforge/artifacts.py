"""Append-only experiment artifacts: strict JSON and exclusive creation."""
from __future__ import annotations
import json
from pathlib import Path


def write_json_no_overwrite(path, value):
    """Serialize before opening, reject non-finite values and existing destinations."""
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    return destination
