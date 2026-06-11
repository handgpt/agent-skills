#!/usr/bin/env python3
"""Run a bounded Antigravity CLI design checkpoint and print advisory output."""
from __future__ import annotations

import sys
from pathlib import Path


def _common_scripts_dir() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        for relative in (Path("common") / "scripts", Path("shared") / "scripts"):
            candidate = parent / relative
            if (candidate / "agy_runner.py").is_file() and (
                candidate / "agy_entrypoints" / "run_agy_design_check.py"
            ).is_file():
                return candidate
    raise RuntimeError("Could not locate common Antigravity runner scripts.")


_COMMON_SCRIPTS = str(_common_scripts_dir())
if _COMMON_SCRIPTS not in sys.path:
    sys.path.insert(0, _COMMON_SCRIPTS)

import agy_runner  # noqa: E402
from agy_entrypoints.run_agy_design_check import main  # noqa: E402

agy_runner.configure_platform(agy_runner.CODEX_AGY_PLATFORM)


if __name__ == "__main__":
    raise SystemExit(main())
