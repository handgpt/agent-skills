#!/usr/bin/env python3
"""Shared advisory prompt, path, and output helpers for agent skills."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path


META_CHATTER_MARKERS = (
    "what would you like",
    "would you like me to",
    "do you want me to",
    "please tell me",
    "let me know if you'd like",
    "let me know if you would like",
    "i will begin",
    "i'll begin",
    "i will start by",
    "i'll start by",
    "i will inspect",
    "i'll inspect",
    "i will search",
    "i'll search",
    "i will look",
    "i'll look",
    "i have begun",
    "i've begun",
    "i am currently reviewing",
    "i'm currently reviewing",
    "i am going to",
    "i'm going to",
    "i will now",
    "i'll now",
)


def detect_project_root() -> Path:
    """Walk up from cwd to find the Git top-level, or fall back to cwd."""
    cwd = Path.cwd().resolve()
    git = shutil.which("git")
    if not git:
        return cwd
    try:
        result = subprocess.run(
            [git, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(cwd),
            input="",
            check=False,
        )
    except Exception:
        return cwd
    root = result.stdout.strip()
    return Path(root).resolve() if result.returncode == 0 and root else cwd


def detect_workspace_root() -> Path:
    """Prefer the nearest AGENTS-scoped workspace root, then fall back to project root."""
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    return detect_project_root()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _workspace_path(raw_path: str, project_root: Path) -> Path | None:
    cleaned = raw_path.strip()
    if not cleaned:
        return None
    path = Path(cleaned).expanduser()
    return path if path.is_absolute() else (project_root / path).absolute()


def _uses_home_shorthand(path: Path) -> bool:
    try:
        path.resolve().relative_to(Path.home().resolve())
        return True
    except ValueError:
        return False


def _tilde_path(path: Path) -> str:
    try:
        relative_path = path.resolve().relative_to(Path.home().resolve())
    except ValueError:
        return str(path)
    if str(relative_path) == ".":
        return "~"
    return f"~/{relative_path.as_posix()}"


def _display_workspace_path(path: Path, project_root: Path) -> str:
    if _uses_home_shorthand(project_root):
        try:
            relative_path = path.resolve().relative_to(project_root.resolve())
            return "." if str(relative_path) == "." else relative_path.as_posix()
        except ValueError:
            pass
    return _tilde_path(path)


def _append_context_entry(
    described: list[str],
    seen: set[Path],
    path: Path,
    kind: str,
    project_root: Path,
) -> None:
    if path in seen:
        return
    seen.add(path)
    described.append(f"- {_display_workspace_path(path, project_root)} [{kind}]")


def _is_within_any(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(_is_within(path, root) for root in roots)


def _allowed_project_roots(
    project_root: Path, project_roots: tuple[Path, ...] | None = None
) -> tuple[Path, ...]:
    if project_roots:
        normalized_roots: list[Path] = []
        seen: set[Path] = set()
        for root in project_roots:
            resolved_root = root.resolve()
            if resolved_root in seen:
                continue
            seen.add(resolved_root)
            normalized_roots.append(resolved_root)
        if normalized_roots:
            return tuple(normalized_roots)
    return (project_root.resolve(),)


def _detect_git_root_for_path(path: Path) -> Path | None:
    git = shutil.which("git")
    if not git:
        return None
    start_dir = path if path.is_dir() else path.parent
    try:
        result = subprocess.run(
            [git, "-C", str(start_dir), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            input="",
            check=False,
        )
    except Exception:
        return None
    root = result.stdout.strip()
    if result.returncode != 0 or not root:
        return None
    return Path(root).resolve()


def _normalize_multi_project_roots(
    raw_project_roots: list[str],
    raw_paths: list[str],
    default_project_root: Path,
    workspace_boundary: Path,
) -> tuple[Path, ...]:
    resolved_workspace_boundary = workspace_boundary.resolve()
    roots: list[Path] = []
    seen: set[Path] = set()

    def add_root(candidate: Path | None) -> None:
        if candidate is None:
            return
        resolved_candidate = candidate.resolve()
        if not _is_within(resolved_candidate, resolved_workspace_boundary):
            return
        if resolved_candidate in seen:
            return
        seen.add(resolved_candidate)
        roots.append(resolved_candidate)

    for raw_root in raw_project_roots:
        path = Path(raw_root.strip()).expanduser()
        if not path.is_absolute():
            path = (resolved_workspace_boundary / path).absolute()
        if path.exists() and path.is_file():
            path = path.parent
        add_root(path if path.exists() else None)

    if not roots:
        for raw_path in raw_paths:
            path = Path(raw_path.strip()).expanduser()
            if not path.is_absolute():
                path = (resolved_workspace_boundary / path).absolute()
            add_root(_detect_git_root_for_path(path))

    if not roots:
        add_root(default_project_root.resolve())
    return tuple(roots) if roots else (default_project_root.resolve(),)


def _multi_project_workspace_root(
    project_roots: tuple[Path, ...], default_project_root: Path, workspace_boundary: Path
) -> Path:
    if not project_roots:
        return default_project_root.resolve()
    resolved_workspace_boundary = workspace_boundary.resolve()
    common_root = Path(os.path.commonpath([str(path) for path in project_roots]))
    if _is_within(common_root, resolved_workspace_boundary):
        return common_root
    return (
        resolved_workspace_boundary
        if _is_within(resolved_workspace_boundary, common_root)
        else default_project_root.resolve()
    )


def _project_roots_in_scope(
    project_root: Path, project_roots: tuple[Path, ...] | None = None
) -> tuple[Path, ...]:
    allowed_roots = _allowed_project_roots(project_root, project_roots)
    in_scope_roots: list[Path] = []
    seen: set[Path] = set()
    for root in allowed_roots:
        if not _is_within(root, project_root.resolve()) and root != project_root.resolve():
            continue
        if root in seen:
            continue
        seen.add(root)
        in_scope_roots.append(root)
    return tuple(in_scope_roots) if in_scope_roots else (project_root.resolve(),)


def _context_paths(
    raw_paths: list[str],
    project_root: Path,
    project_roots: tuple[Path, ...] | None = None,
) -> list[Path]:
    resolved_project_root = project_root.resolve()
    allowed_roots = _project_roots_in_scope(resolved_project_root, project_roots)
    context_paths: list[Path] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        path = _workspace_path(raw_path, resolved_project_root)
        if path is None:
            continue
        resolved_path = path.resolve()
        if not _is_within(resolved_path, resolved_project_root):
            continue
        if not _is_within_any(resolved_path, allowed_roots):
            continue
        if resolved_path in seen:
            continue
        seen.add(resolved_path)
        context_paths.append(path)
    return context_paths


def describe_paths(
    raw_paths: list[str],
    project_root: Path,
    project_roots: tuple[Path, ...] | None = None,
) -> list[str]:
    described: list[str] = []
    seen: set[Path] = set()
    resolved_project_root = project_root.resolve()
    for path in _context_paths(raw_paths, project_root, project_roots):
        if not path.exists():
            _append_context_entry(described, seen, path, "missing", resolved_project_root)
            continue
        kind = "directory" if path.is_dir() else "file"
        _append_context_entry(described, seen, path, kind, resolved_project_root)
    return described


def _focus_scope_root(
    raw_paths: list[str],
    project_root: Path,
    project_roots: tuple[Path, ...] | None = None,
) -> Path:
    resolved_project_root = project_root.resolve()
    scope_candidates: list[Path] = []
    for path in _context_paths(raw_paths, resolved_project_root, project_roots):
        resolved_path = path.resolve()
        candidate = resolved_path if path.is_dir() else resolved_path.parent
        if not _is_within(candidate, resolved_project_root):
            continue
        scope_candidates.append(candidate)
    if not scope_candidates:
        return resolved_project_root
    common = Path(os.path.commonpath([str(path) for path in scope_candidates]))
    return common if _is_within(common, resolved_project_root) else resolved_project_root


def _project_set_key(
    project_root: Path, project_roots: tuple[Path, ...] | None = None
) -> str:
    normalized_roots = _project_roots_in_scope(project_root, project_roots)
    relative_roots: list[str] = []
    for root in normalized_roots:
        try:
            relative_path = root.relative_to(project_root.resolve())
        except ValueError:
            continue
        relative_roots.append("." if str(relative_path) == "." else relative_path.as_posix())
    if not relative_roots:
        return "."
    return "|".join(sorted(relative_roots))


def build_prompt(
    project_root: Path,
    brief_text: str,
    context_entries: list[str],
    *,
    lane: str,
    focus_root: Path,
    project_roots: tuple[Path, ...] | None = None,
    role_line: str,
    output_contract: str,
    runner_name: str,
) -> str:
    """Assemble the full prompt from a role line, output contract, and paths."""
    resolved_project_root = project_root.resolve()
    resolved_focus_root = focus_root.resolve()
    display_runner_name = runner_name.strip() or "external CLI"
    normalized_project_roots = _project_roots_in_scope(
        resolved_project_root, project_roots
    )
    project_scope_key = _project_set_key(resolved_project_root, normalized_project_roots)
    if not _is_within(resolved_focus_root, resolved_project_root):
        resolved_focus_root = resolved_project_root
    sections = [
        role_line,
        f"You are running inside {display_runner_name} on the same machine as the codebase.",
        (
            "Use the workspace root below as your filesystem boundary. "
            "You may inspect any local file or directory inside that workspace root "
            "if it helps you answer well."
        ),
        (
            "This advisory is only for the projects and directories listed below. "
            "Ignore prior session context about any other project unless it is "
            "explicitly listed in the current projects-in-scope section."
        ),
        (
            "Treat this as a fresh single-turn advisory. Ignore unfinished work, "
            "tool chatter, reminders, draft content, and follow-up questions from "
            "earlier turns in this session."
        ),
        (
            "Return only the final Markdown answer for the current task. Do not add "
            "a preamble, do not describe which tools you might use, and do not ask "
            "what to do next."
        ),
        output_contract,
        "## Projects In Scope",
    ]
    for scoped_root in normalized_project_roots:
        sections.append(
            f"- {scoped_root.name}: {_display_workspace_path(scoped_root, resolved_project_root)}"
        )
    sections.extend(
        [
            "## Current Advisory Target",
            f"- Project Name: {resolved_project_root.name}",
            f"- Advisory Lane: {lane}",
            f"- Project Scope Key: {project_scope_key}",
            f"- Target Directory: {_display_workspace_path(resolved_focus_root, resolved_project_root)}",
            f"- Workspace Root: {_tilde_path(resolved_project_root)}",
            "## Inlined Brief",
            brief_text.strip() or "- The brief file was empty.",
        ]
    )
    if context_entries:
        sections.append("## Priority Paths To Start From")
        sections.extend(context_entries)
        sections.append(
            "Treat those paths as starting points, not as an exhaustive file list. Decide for yourself which other workspace-local files or directories you should inspect."
        )
    else:
        sections.append(
            "No priority paths were supplied. Explore the workspace root as needed, but stay inside it."
        )
    return "\n\n".join(sections).strip() + "\n"


def _expected_markdown_headings(output_contract: str) -> tuple[str, ...]:
    headings: list[str] = []
    for line in output_contract.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            headings.append(stripped)
    return tuple(headings)


def _strip_outer_markdown_fence(output_text: str) -> str:
    lines = output_text.strip().splitlines()
    if len(lines) < 3:
        return output_text.strip()
    first_line = lines[0].strip()
    last_line = lines[-1].strip()
    if not first_line.startswith("```") or last_line != "```":
        return output_text.strip()
    return "\n".join(lines[1:-1]).strip()


def _looks_like_meta_chatter(output_text: str) -> bool:
    lowered = output_text.strip().lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in META_CHATTER_MARKERS)


def _normalize_advisory_output(
    output_text: str, expected_headings: tuple[str, ...] = ()
) -> str:
    stripped_output = _strip_outer_markdown_fence(output_text)
    if not stripped_output:
        return ""

    lines = stripped_output.splitlines()
    if expected_headings:
        expected_heading_set = {heading.casefold() for heading in expected_headings}
        first_expected_heading_index = next(
            (
                index
                for index, line in enumerate(lines)
                if line.strip().casefold() in expected_heading_set
            ),
            None,
        )
        if first_expected_heading_index not in (None, 0):
            prefix = "\n".join(lines[:first_expected_heading_index]).strip()
            if prefix and _looks_like_meta_chatter(prefix):
                lines = lines[first_expected_heading_index:]

    if len(lines) > 1:
        trailing_tail = "\n".join(lines[-3:]).strip()
        if trailing_tail and _looks_like_meta_chatter(trailing_tail):
            trimmed_lines = lines[:]
            for index in range(max(0, len(lines) - 3), len(lines)):
                if _looks_like_meta_chatter("\n".join(lines[index:]).strip()):
                    trimmed_lines = lines[:index]
                    break
            lines = trimmed_lines

    return "\n".join(lines).strip()


def build_output_normalizer(output_contract: str) -> Callable[[str], str]:
    expected_headings = _expected_markdown_headings(output_contract)

    def normalize(output_text: str) -> str:
        return _normalize_advisory_output(output_text, expected_headings)

    return normalize


def build_output_validator(output_contract: str) -> Callable[[str], str]:
    expected_headings = _expected_markdown_headings(output_contract)
    normalize_output = build_output_normalizer(output_contract)

    def validate(output_text: str) -> str:
        stripped_output = normalize_output(output_text)
        if not stripped_output:
            return "External reviewer returned empty output."

        nonempty_lines = [
            line.strip() for line in stripped_output.splitlines() if line.strip()
        ]
        if not nonempty_lines:
            return "External reviewer returned empty output."

        if _looks_like_meta_chatter(stripped_output):
            return "External reviewer returned meta chatter instead of a final advisory."

        if expected_headings:
            actual_headings = {
                line.strip().casefold()
                for line in stripped_output.splitlines()
                if line.strip().startswith("## ")
            }
            if actual_headings and not any(
                heading.casefold() in actual_headings for heading in expected_headings
            ):
                return (
                    "External reviewer output used headings from the wrong advisory shape "
                    "and appears to belong to a different task."
                )
        return ""

    return validate
