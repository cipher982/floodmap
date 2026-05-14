#!/usr/bin/env python3
"""Generic entry point for prototype HAND region generation."""

from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

if __name__ == "__main__":
    runpy.run_path(
        str(ROOT / "tools" / "prototypes" / "generate_birmingham_drainage.py"),
        run_name="__main__",
    )
