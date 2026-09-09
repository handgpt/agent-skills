#!/usr/bin/env python3
"""Install managed Codex skills and optionally migrate global instructions."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import tempfile

MARKERS = (
    "codex-skills advisor checkpoints",
    "codex-skills antigravity advisory",
    "codex-skills gemini advisory",
)
PREFERENCES = "codex-skills workflow preferences"
LEGACY_SKILLS = tuple(f"{prefix}-{kind}" for prefix in ("agy", "gemini")
                      for kind in ("design-checkpoint", "error-analysis", "review"))


def without_blocks(text: str, names: tuple[str, ...]) -> str:
    """Remove only balanced known blocks; never consume unmarked user text."""
    active = None
    kept = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        starts = next((n for n in names if stripped == f"# >>> {n} >>>"), None)
        ends = next((n for n in names if stripped == f"# <<< {n} <<<"), None)
        if starts:
            if active:
                raise ValueError("Nested managed AGENTS markers; repair before installing")
            active = starts
        elif ends:
            if active != ends:
                raise ValueError("Unmatched managed AGENTS end marker; repair before installing")
            active = None
        elif active is None:
            kept.append(line)
    if active:
        raise ValueError("Unclosed managed AGENTS marker; repair before installing")
    return "".join(kept)


def with_block(text: str, name: str, body: str) -> str:
    separator = "" if not text or text.endswith("\n") else "\n"
    return text + separator + f"# >>> {name} >>>\n" + body.rstrip() + f"\n# <<< {name} <<<\n"


def read_agents(path: Path) -> str:
    if path.is_symlink():
        raise ValueError(f"Refusing to replace symlinked instructions: {path}")
    return path.read_text() if path.exists() else ""


def install(*, source: Path, home: Path, codex_home: Path,
            global_agents: bool = False, preferences: bool = False) -> Path:
    skills_dest = codex_home / "skills"
    source = source.resolve()
    if source == skills_dest.resolve() or source.is_relative_to(skills_dest.resolve()):
        raise ValueError("Installation source must be separate from the destination")
    updates: dict[Path, str] = {}
    # Preflight both instruction files before making any deployment changes.
    if global_agents or preferences:
        legacy = home / "AGENTS.md"
        target = codex_home / "AGENTS.md"
        if legacy.resolve() == target.resolve():
            raise ValueError("Codex home must differ from the user home for AGENTS migration")
        previous = read_agents(target)
        base = without_blocks(previous, MARKERS + ((PREFERENCES,) if preferences else ()))
        updated = with_block(base, MARKERS[0], (source / "templates/home-AGENTS.snippet.md").read_text())
        if preferences:
            updated = with_block(updated, PREFERENCES,
                                 (source / "templates/workflow-preferences.snippet.md").read_text())
        updates[target] = updated
        if legacy.exists():
            old = read_agents(legacy)
            updates[legacy] = without_blocks(old, MARKERS)

    backup_root = codex_home / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="advisor-install-", dir=backup_root))
    skills_dest.mkdir(parents=True, exist_ok=True)
    # Stage complete managed directories before replacing installed copies.
    with tempfile.TemporaryDirectory(prefix=".advisor-stage-", dir=codex_home) as tmp:
        stage = Path(tmp)
        shutil.copytree(source.parent / "common/scripts", stage / "shared/scripts",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(source / "skills/shared/references", stage / "shared/references")
        for entry in (source / "skills").iterdir():
            if entry.name != "shared" and (entry / "SKILL.md").is_file():
                shutil.copytree(entry, stage / entry.name,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for entry in stage.iterdir():
            target = skills_dest / entry.name
            if target.exists() or target.is_symlink():
                target.rename(backup / entry.name)
            entry.rename(target)
        for name in LEGACY_SKILLS:
            old = skills_dest / name
            if old.exists() or old.is_symlink():
                old.rename(backup / name)

    # Install global instructions before removing the old marked home block.
    for path, text in updates.items():
        original = path.read_text() if path.exists() else None
        if original == text:
            continue
        if original is not None:
            shutil.copy2(path, backup / ("codex-AGENTS.md" if path.parent == codex_home else "home-AGENTS.md"))
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".AGENTS-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w") as handle:
                handle.write(text)
            if path.exists():
                shutil.copymode(path, temporary)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-global-agents", "--install-home-agents", action="store_true",
                        help="Install global rules in Codex home; migrate only managed ~/AGENTS.md blocks")
    parser.add_argument("--install-workflow-preferences", action="store_true",
                        help="Also install optional bounded delegation, validation, and artifact preferences")
    args = parser.parse_args()
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex").expanduser()
    backup = install(source=Path(__file__).resolve().parents[1], home=home, codex_home=codex_home,
                     global_agents=args.install_global_agents,
                     preferences=args.install_workflow_preferences)
    print(f"Installed skills to {codex_home / 'skills'}")
    print(f"Previous managed files backed up to {backup}")
    if args.install_global_agents or args.install_workflow_preferences:
        print(f"Updated {codex_home / 'AGENTS.md'} and removed legacy managed home blocks")
    print("Restart Codex and start a new task to load updated instructions.")


if __name__ == "__main__":
    main()
