# Instruction maintenance evidence

Reviewed 2026-09-09. These sources support scoped instructions, not a promise of
lower token usage or a particular performance gain.

## Official guidance

- [GPT-6 Astra prompting guidance](https://developers.openai.com/api/docs/guides/latest-model):
  audit skills and AGENTS for conflicting guidance, follow through authorized work,
  specify delegation conditions, and make verification proportional to the change.
- [AGENTS discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md):
  the Codex home AGENTS file is global; project discovery starts at the repository
  root. A home-directory AGENTS file is not a reliable global installation target.
- [Build skills](https://learn.chatgpt.com/docs/build-skills): required name and
  description, optional agents/openai.yaml, and progressive disclosure.
- The bundled skill-creator guidance recommends decision-relevant instructions,
  bounded retries, preserved user scope, and avoiding universal rules derived
  from a single example.

## Community observations and their limits

- [Codex #36973](https://github.com/openai/codex/issues/36973) documents conflicting
  delegation fragments with source references. This supports making the intended
  delegation conditions explicit, not forcing parallelism on every task.
- [Codex #39223](https://github.com/openai/codex/issues/39223) reports current global
  instructions being displaced by stale memory and describes session-log evidence.
  This supports treating past pitfalls as scoped evidence, not current authority.
  It is a user report, not a controlled benchmark or proof of universal behavior.

## Locally verified corrections

- The old policy multiplied ten wrapper attempts by six provider launches on
  authentication failure. Retries now belong to the runner; Codex auth retries
  are opt-in and share one execution budget.
- Explicit audits can have no diff. Automatic review heuristics must not suppress
  a user's requested audit.
- Managed AGENTS installation preserves unmarked content and migrates only known
  marked blocks. Existing config overrides and third-party skill caches are not
  rewritten by the installer.

Workflow preferences are opt-in. They retain required tests, artifact validation,
security boundaries, and user/template requirements while giving concrete stopping
conditions for polishing and avoiding redundant instructions.
