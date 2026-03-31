---
description: Advisory Codex CLI second-opinion for high-impact technical design decisions. Use before locking in architecture, protocol, migration plan, or other major design choice.
---

# Codex Design Checkpoint

Get a short, critical second opinion from Codex before locking in a major technical direction.

## Instructions

1. **Decide whether to use it.** Use for decisions that are expensive to reverse. Skip for routine implementation.

2. **Prepare a compact brief** in `/tmp` with decision, goal, constraints, options considered, preferred direction, and known risks.

3. **Run the advisory pass.** Execute:

   ```bash
   python3 $AGENT_SKILLS_DIR/claude-code/skills/codex-design-checkpoint/scripts/run_codex_design_check.py \
     --project-root <path/to/project> \
     --brief-file /tmp/design-brief.md \
     --context-file <path/to/doc-or-spec.md>
   ```

4. **Read the output.** Evaluate each point yourself. Accept, reject, or defer explicitly.

## Guardrails

- Codex runs in read-only sandbox mode.
- Do not upload secrets or credentials.

$ARGUMENTS
