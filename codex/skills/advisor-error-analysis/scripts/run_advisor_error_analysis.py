#!/usr/bin/env python3
"""Run a bounded external advisor error-analysis pass and print advisory output."""
from __future__ import annotations

import sys
from pathlib import Path


def _common_scripts_dir() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        for relative in (Path("common") / "scripts", Path("shared") / "scripts"):
            candidate = parent / relative
            if (candidate / "advisor_runner.py").is_file() and (
                candidate / "advisor_entrypoints" / "run_advisor_error_analysis.py"
            ).is_file():
                return candidate
    raise RuntimeError("Could not locate common advisor runner scripts.")


_COMMON_SCRIPTS = str(_common_scripts_dir())
if _COMMON_SCRIPTS not in sys.path:
    sys.path.insert(0, _COMMON_SCRIPTS)

import advisor_runner  # noqa: E402
from advisor_entrypoints.run_advisor_error_analysis import main  # noqa: E402

advisor_runner.configure_platform(advisor_runner.CODEX_ADVISOR_PLATFORM)


if __name__ == "__main__":
    raise SystemExit(main())
