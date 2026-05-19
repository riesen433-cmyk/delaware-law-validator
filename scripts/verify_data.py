#!/usr/bin/env python3
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "delaware_law_data_v1.0.0.sqlite"
MANIFEST_PATH = PROJECT_ROOT / "data" / "manifest.json"


def main() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 2
    if not MANIFEST_PATH.exists():
        print(f"Manifest not found: {MANIFEST_PATH}")
        return 2

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    expected = manifest.get("database_sha256")
    actual = file_sha256(DB_PATH)
    if actual != expected:
        print("FAILED: database hash does not match manifest.")
        print(f"expected: {expected}")
        print(f"actual:   {actual}")
        return 1

    print("OK: database hash matches manifest.")
    print(f"data_version: {manifest.get('data_version')}")
    print(f"coverage: {manifest.get('coverage', {}).get('included')}")
    return 0


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
