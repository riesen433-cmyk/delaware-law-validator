#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RELEASE_DIR = PROJECT_ROOT / "release"
PACKAGE_NAME = "delaware-law-data-v1.0.0.zip"


def main() -> int:
    required = [
        DATA_DIR / "delaware_law_data_v1.0.0.sqlite",
        DATA_DIR / "delaware_law_data_v1.0.0.sqlite.sha256",
        DATA_DIR / "manifest.json",
        DATA_DIR / "coverage-report.json",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        print("Missing required data files:")
        for path in missing:
            print(f"- {path}")
        return 2

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    package_path = RELEASE_DIR / PACKAGE_NAME
    if package_path.exists():
        package_path.unlink()

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in required:
            zf.write(path, path.relative_to(PROJECT_ROOT))
        raw_md_dir = DATA_DIR / "raw_md"
        if raw_md_dir.exists():
            for path in sorted(raw_md_dir.glob("*.md")):
                zf.write(path, path.relative_to(PROJECT_ROOT))
        raw_court_rules_dir = DATA_DIR / "raw_court_rules"
        if raw_court_rules_dir.exists():
            for path in sorted(raw_court_rules_dir.glob("*.md")):
                zf.write(path, path.relative_to(PROJECT_ROOT))
        semantic_dir = DATA_DIR / "semantic"
        if semantic_dir.exists():
            for path in sorted(semantic_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(PROJECT_ROOT))

    print(f"Created {package_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
