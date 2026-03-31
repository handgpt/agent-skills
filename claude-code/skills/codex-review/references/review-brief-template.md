# Codex Review Guide

The `codex review` command has built-in diff analysis. You typically do not need a separate brief file. Instead, use the flags to scope the review:

- `--uncommitted` — Review all staged, unstaged, and untracked changes
- `--base <branch>` — Review changes against a base branch (e.g., `main`)
- `--commit <sha>` — Review a specific commit

For custom review instructions, pass a `--prompt` with focus areas:

```
python3 scripts/run_codex_review.py \
  --project-root path/to/project \
  --uncommitted \
  --prompt "Focus on thread safety, error handling edge cases, and whether the new API surface is minimal."
```

Keep custom prompts targeted. Codex works best when given specific areas to scrutinize rather than vague instructions.
