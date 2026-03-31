#!/usr/bin/env python3
"""Update a concise per-project pitfall notebook."""
from __future__ import annotations

import argparse
import subprocess
from datetime import date
from pathlib import Path


DEFAULT_NOTEBOOK_NAME = ".claude-pitfalls.md"
MAX_ENTRIES = 100
HEADER = """# Claude Code Pitfalls

Concise project-specific pitfalls collected after successful fixes.
Read this before non-trivial implementation or review work.
"""


def detect_project_root() -> Path:
    cwd = Path.cwd().resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
            input="",
            check=False,
        )
    except Exception:
        return cwd
    root = result.stdout.strip()
    return Path(root).resolve() if result.returncode == 0 and root else cwd


def normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()


def normalized_title(text: str) -> str:
    return normalize_text(text).casefold()


def parse_title(entry_block: str) -> str:
    first_line = entry_block.splitlines()[0]
    heading = first_line.removeprefix("## ").strip()
    if " | " in heading:
        return heading.split(" | ", 1)[1]
    return heading


def load_entries(notebook_path: Path) -> list[str]:
    if not notebook_path.is_file():
        return []
    text = notebook_path.read_text(encoding="utf-8").strip()
    entries: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                entries.append("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)
    if current:
        entries.append("\n".join(current).strip())
    return entries


def format_entry(*, title: str, symptom: str, cause: str, rule: str) -> str:
    today = date.today().isoformat()
    return "\n".join(
        [
            f"## {today} | {title}",
            f"- Symptom: {symptom}",
            f"- Cause: {cause}",
            f"- Rule: {rule}",
        ]
    )


def write_notebook(notebook_path: Path, entries: list[str]) -> None:
    body = "\n\n".join(entries[:MAX_ENTRIES]).strip()
    content = HEADER.strip() + ("\n\n" + body if body else "") + "\n"
    notebook_path.write_text(content, encoding="utf-8")


def update_notebook(
    *,
    notebook_path: Path,
    title: str,
    symptom: str,
    cause: str,
    rule: str,
) -> Path:
    entry = format_entry(
        title=normalize_text(title),
        symptom=normalize_text(symptom),
        cause=normalize_text(cause),
        rule=normalize_text(rule),
    )
    new_key = normalized_title(title)
    entries = [existing for existing in load_entries(notebook_path) if normalized_title(parse_title(existing)) != new_key]
    entries.insert(0, entry)
    write_notebook(notebook_path, entries)
    return notebook_path


def make_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update a concise per-project pitfall notebook.")
    parser.add_argument("--title", required=True, help="Short pitfall title.")
    parser.add_argument("--symptom", required=True, help="Short symptom summary.")
    parser.add_argument("--cause", required=True, help="Actual root cause.")
    parser.add_argument("--rule", required=True, help="Short rule to avoid repeating the pitfall.")
    parser.add_argument(
        "--notebook-file",
        default=DEFAULT_NOTEBOOK_NAME,
        help=f"Notebook filename relative to the project root. Default: {DEFAULT_NOTEBOOK_NAME}.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_arg_parser()
    args = parser.parse_args(argv)
    project_root = detect_project_root()
    notebook_path = project_root / args.notebook_file
    updated_path = update_notebook(
        notebook_path=notebook_path,
        title=args.title,
        symptom=args.symptom,
        cause=args.cause,
        rule=args.rule,
    )
    print(updated_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
