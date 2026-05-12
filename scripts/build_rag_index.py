#!/usr/bin/env python3
from __future__ import annotations

import sys

from delaware_law_skill.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["rag-build", *sys.argv[1:]]))
