from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('codex_install', SOURCE / 'scripts/install.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InstallTests(unittest.TestCase):
    def test_migrate_preserves_user_content_and_unmanaged_skills_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_home = home / 'custom-codex'
            codex_home.mkdir()
            legacy = home / 'AGENTS.md'
            legacy.write_text('Personal prefix\n' + module.with_block('', module.MARKERS[1], 'Old policy') + 'Personal suffix\n')
            global_file = codex_home / 'AGENTS.md'
            global_file.write_text('Global personal policy\n')
            unrelated = codex_home / 'skills/other/SKILL.md'
            unrelated.parent.mkdir(parents=True)
            unrelated.write_text('Keep this skill')
            backup = module.install(source=SOURCE, home=home, codex_home=codex_home,
                                    global_agents=True, preferences=True)
            self.assertEqual(legacy.read_text(), 'Personal prefix\nPersonal suffix\n')
            self.assertTrue(global_file.read_text().startswith('Global personal policy\n'))
            self.assertEqual((backup / 'codex-AGENTS.md').read_text(), 'Global personal policy\n')
            self.assertIn('Old policy', (backup / 'home-AGENTS.md').read_text())
            self.assertEqual(unrelated.read_text(), 'Keep this skill')
            first = global_file.read_bytes()
            module.install(source=SOURCE, home=home, codex_home=codex_home,
                           global_agents=True, preferences=True)
            self.assertEqual(global_file.read_bytes(), first)
            installed = codex_home / 'skills'
            for name in ('advisor-review', 'advisor-design-checkpoint', 'advisor-error-analysis'):
                reference = installed / name / '../shared/references/advisor-runtime.md'
                self.assertTrue(reference.resolve().is_file())

    def test_unclosed_marker_aborts_before_deployment(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            legacy = home / 'AGENTS.md'
            original = 'User text\n# >>> codex-skills advisor checkpoints >>>\nUnclosed\n'
            legacy.write_text(original)
            with self.assertRaises(ValueError):
                module.install(source=SOURCE, home=home, codex_home=home / '.codex', global_agents=True)
            self.assertEqual(legacy.read_text(), original)
            self.assertFalse((home / '.codex/skills').exists())

    def test_skills_only_does_not_migrate_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            old = module.with_block('', module.MARKERS[0], 'Old')
            (home / 'AGENTS.md').write_text(old)
            module.install(source=SOURCE, home=home, codex_home=home / '.codex')
            self.assertEqual((home / 'AGENTS.md').read_text(), old)
            self.assertFalse((home / '.codex/AGENTS.md').exists())

    def test_whitespace_markers_and_unmatched_end(self):
        block = ' before\n  # >>> codex-skills advisor checkpoints >>>  \nold\n # <<< codex-skills advisor checkpoints <<<\nafter\n'
        self.assertEqual(module.without_blocks(block, module.MARKERS), ' before\nafter\n')
        with self.assertRaises(ValueError):
            module.without_blocks('# <<< codex-skills advisor checkpoints <<<\n', module.MARKERS)

    def test_symlinked_instructions_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            real = home / 'personal.md'
            real.write_text('Do not overwrite')
            (home / 'AGENTS.md').symlink_to(real)
            with self.assertRaises(ValueError):
                module.install(source=SOURCE, home=home, codex_home=home / '.codex', global_agents=True)
            self.assertEqual(real.read_text(), 'Do not overwrite')


if __name__ == '__main__':
    unittest.main()
