"""Black-box bootstrap regression tests. No Nintendo data, network or pip installs."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/init_project.sh'
FETCH = Path(__file__).resolve().parents[1] / 'scripts/fetch_base.sh'


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='recomp-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # Hermetic: never pick up the user's real cached base or RECOMP_BASE.
        environment = {k: v for k, v in os.environ.items() if k != 'RECOMP_BASE'}
        environment['XDG_CACHE_HOME'] = str(self.root / 'cache')
        patcher = mock.patch.dict(os.environ, environment, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.base = self.root / 'base with spaces'
        self.base.mkdir()
        self.out = self.root / 'project with spaces'
        self.package = self.root / 'fake game.nsp'
        self.keys = self.root / 'prod.keys'
        self.package.write_bytes(b'synthetic package')
        self.keys.write_bytes(b'synthetic keys')
        for name, content in {
            'tools/nso.py': '''import sys
from helper import VALUE
for p in sys.argv[1:]:
    assert open(p, 'rb').read(4) == b'NSO0', p
print(VALUE)
''',
            'tools/helper.py': 'VALUE = "module report"\n',
            'tools/inventory.py': 'from helper import VALUE\nprint("gap " + VALUE)\n',
            'tools/nca_extract.py': '''import pathlib, sys
if '--info' not in sys.argv:
    p = pathlib.Path(sys.argv[3]) / 'exefs'
    p.mkdir(parents=True)
    (p / 'main').write_bytes(b'NSO0' + bytes(0x3c) + bytes(range(32)) + bytes(0xa0))
    (p / 'sdk').write_bytes(b'NSO0' + bytes(0x3c) + bytes(range(32)) + bytes(0xa0))
    (p / 'main.npdm').write_bytes(b'META-not-an-NSO')
    (p.parent / 'romfs.src').write_text('synthetic-private-descriptor')
''',
            'runtime/rt.h': '// synthetic runtime\n',
            'third_party/example/LICENSE': 'synthetic dependency license\n',
            'Makefile': '# synthetic makefile\n',
            'LICENSE': 'synthetic base license\n',
            'README.md': 'synthetic attribution\n',
        }.items():
            p = self.base / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.base), *args], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def invoke(self, *extra):
        return subprocess.run(['bash', str(SCRIPT), '--pkg', str(self.package), '--keys', str(self.keys),
                               '--out', str(self.out), '--base', str(self.base), *extra],
                              capture_output=True, text=True)

    def scaffold(self):
        result = self.invoke('--no-extract')
        self.assertEqual(result.returncode, 0, result.stderr)

    def interpreter(self):
        # Reuse host Python, so extraction tests cannot create a venv or install packages.
        p = self.out / 'tools/venv/bin/python'
        p.parent.mkdir(parents=True)
        p.symlink_to(sys.executable)
        (self.out / 'tools/venv/.recomp-deps-installed').write_text('synthetic\n')

    def test_scaffold_preserves_inputs_and_copies_only_tracked_sources(self):
        before = [(p.read_bytes(), p.stat().st_mode) for p in (self.package, self.keys)]
        (self.base / 'tools/untracked.keys').write_text('not copied')
        self.scaffold()
        self.assertFalse((self.out / 'tools/untracked.keys').exists())
        self.assertFalse((self.out / 'tools/venv').exists())
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mode) for p in (self.package, self.keys)])
        self.assertTrue((self.out / 'AGENTS.md').is_file())
        self.assertIn(self.git('rev-parse', 'HEAD').stdout.decode().strip(),
                      (self.out / 'docs/BASE.md').read_text())

    def test_extract_imports_siblings_and_excludes_npdm(self):
        self.scaffold()
        self.interpreter()
        result = self.invoke('--no-copy')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('module report', (self.out / 'docs/modules.txt').read_text())
        self.assertIn(bytes(range(32)).hex(), (self.out / 'docs/modules.txt').read_text())
        self.assertIn('gap module report', (self.out / 'docs/GAP.md').read_text())
        self.assertEqual((self.out / 'extracted/romfs.src').stat().st_mode & 0o077, 0)

    def test_inventory_failure_preserves_previous_report_and_fails(self):
        self.scaffold()
        self.interpreter()
        (self.out / 'docs/GAP.md').write_text('prior report')
        (self.out / 'tools/inventory.py').write_text('print("partial")\nraise SystemExit(9)\n')
        result = self.invoke('--no-copy')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.out / 'docs/GAP.md').read_text(), 'prior report')
        self.assertNotIn('Scaffold ready', result.stdout)

    def test_inside_file_symlink_to_outside_is_rejected(self):
        self.out.mkdir()
        alias = self.out / 'alias.nsp'
        alias.symlink_to(self.package)
        result = self.invoke('--pkg', str(alias), '--no-copy', '--no-extract')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.out / 'docs').exists())

    def test_external_symlink_to_inside_is_rejected(self):
        self.out.mkdir()
        inside = self.out / 'inside.nsp'
        inside.write_text('synthetic')
        alias = self.root / 'alias.nsp'
        alias.symlink_to(inside)
        result = self.invoke('--pkg', str(alias), '--no-copy', '--no-extract')
        self.assertNotEqual(result.returncode, 0)

    def test_missing_base_capability_fails_before_output_creation(self):
        (self.base / 'tools/inventory.py').unlink()
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.out.exists())

    def test_unknown_format_does_not_mutate_inputs(self):
        unknown = self.root / 'fake.zip'
        unknown.write_text('synthetic archive')
        before = unknown.stat().st_mode
        result = self.invoke('--pkg', str(unknown))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(unknown.stat().st_mode, before)
        self.assertFalse(self.out.exists())

    def test_xci_and_compressed_formats_are_passed_to_extractor(self):
        for suffix in ('.xci', '.nsz'):
            with self.subTest(suffix=suffix):
                package = self.root / f'fake game{suffix}'
                package.write_bytes(b'synthetic package')
                before = (package.read_bytes(), package.stat().st_mode)
                out = self.root / f'project{suffix}'
                result = subprocess.run(['bash', str(SCRIPT), '--pkg', str(package), '--keys', str(self.keys),
                                         '--out', str(out), '--base', str(self.base), '--no-extract'],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(before, (package.read_bytes(), package.stat().st_mode))

    def test_extractor_info_failure_stops_before_extraction(self):
        self.scaffold()
        self.interpreter()
        (self.out / 'tools/nca_extract.py').write_text('raise SystemExit("unsupported container")\n')
        result = self.invoke('--no-copy')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.out / 'extracted/exefs').exists())

    def test_inputs_in_ignored_input_folder_are_accepted(self):
        inputs = self.out / 'input'
        inputs.mkdir(parents=True)
        package, keys = inputs / 'game.nsp', inputs / 'prod.keys'
        package.write_bytes(b'synthetic package')
        keys.write_bytes(b'synthetic keys')
        result = self.invoke('--pkg', str(package), '--keys', str(keys), '--no-extract')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('input/', (self.out / '.gitignore').read_text().splitlines())
        self.assertEqual(package.read_bytes(), b'synthetic package')

    def test_inputs_elsewhere_in_project_are_rejected(self):
        self.out.mkdir()
        package = self.out / 'game.nsp'
        package.write_bytes(b'synthetic package')
        result = self.invoke('--pkg', str(package), '--no-copy', '--no-extract')
        self.assertNotEqual(result.returncode, 0)

    def test_nonempty_output_requires_explicit_resume(self):
        self.out.mkdir()
        (self.out / 'keep').write_text('unchanged')
        result = self.invoke('--no-extract')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.out / 'keep').read_text(), 'unchanged')

    def test_resume_appends_ignore_rules_without_replacing_user_files(self):
        self.out.mkdir()
        (self.out / '.gitignore').write_text('user-rule\n')
        (self.out / 'AGENTS.md').write_text('user rules')
        first = self.invoke('--no-copy', '--no-extract')
        second = self.invoke('--no-copy', '--no-extract')
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        ignore = (self.out / '.gitignore').read_text()
        self.assertTrue(ignore.startswith('user-rule\n'))
        self.assertEqual(ignore.count('# ---- Nintendo files:'), 1)
        self.assertEqual((self.out / 'AGENTS.md').read_text(), 'user rules')

    def test_resume_rejects_output_symlink(self):
        self.out.mkdir()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        (self.out / 'docs').symlink_to(elsewhere)
        result = self.invoke('--no-copy', '--no-extract')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_source_symlink_rejected_before_mutation(self):
        (self.base / 'tools/nso.py').unlink()
        (self.base / 'tools/nso.py').symlink_to(self.keys)
        result = self.invoke('--no-extract')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.out.exists())

    def test_readme_symlink_cannot_copy_external_file_as_attribution(self):
        (self.base / 'README.md').unlink()
        (self.base / 'README.md').symlink_to(self.keys)
        result = self.invoke('--no-extract')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.out.exists())

    def test_repeated_extraction_does_not_mix_builds(self):
        self.scaffold()
        self.interpreter()
        (self.out / 'extracted').mkdir()
        (self.out / 'extracted/prior').write_text('keep')
        result = self.invoke('--no-copy')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.out / 'extracted/prior').read_text(), 'keep')

    def test_missing_argument_is_usage_error(self):
        result = self.invoke('--name')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)

    def test_tracked_extracted_files_are_rejected(self):
        self.scaffold()
        self.interpreter()
        subprocess.run(['git', 'init', '-q', str(self.out)], check=True)
        (self.out / 'extracted').mkdir()
        p = self.out / 'extracted/prior'
        p.write_text('synthetic')
        subprocess.run(['git', '-C', str(self.out), 'add', '-f', str(p)], check=True)
        p.unlink()  # Empty on disk, but remains in the index.
        result = self.invoke('--no-copy')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already tracked', result.stderr)

    def test_failed_dependency_install_is_retried(self):
        self.scaffold()
        venv = self.out / 'tools/venv/bin'
        venv.mkdir(parents=True)
        # Stand-in interpreter whose pip always fails, as when offline.
        fake = venv / 'python'
        fake.write_text('#!/bin/sh\nexit 7\n')
        fake.chmod(0o700)
        for _ in range(2):
            result = self.invoke('--no-copy')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.out / 'tools/venv/.recomp-deps-installed').exists())
            self.assertFalse((self.out / 'extracted/exefs').exists())

    def test_scaffold_only_needs_no_package_or_keys(self):
        result = subprocess.run(['bash', str(SCRIPT), '--out', str(self.out), '--base', str(self.base),
                                 '--no-extract'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        missing = subprocess.run(['bash', str(SCRIPT), '--out', str(self.root / 'other'),
                                  '--base', str(self.base)], capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)

    def test_invalid_name_is_usage_error(self):
        result = self.invoke('--no-extract', '--name', '../x')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.out.exists())

    def test_non_git_base_reports_clearly(self):
        plain = self.root / 'plain'
        plain.mkdir()
        result = self.invoke('--no-extract', '--base', str(plain))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('not a Git checkout', result.stderr)
        self.assertFalse(self.out.exists())

    def test_rules_are_single_source_with_project_name(self):
        result = self.invoke('--no-extract', '--name', 'mygame')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.out / 'CLAUDE.md').read_text(), '@AGENTS.md\n')
        agents = (self.out / 'AGENTS.md').read_text()
        self.assertTrue(agents.startswith('# mygame'))
        self.assertNotIn('<PROJECT>', agents)
        self.assertIn('/mygame.ini', (self.out / '.gitignore').read_text())

    def add_generator_files(self):
        for name in ('tools/gen.py', 'tools/lifter.py'):
            (self.base / name).write_text('# synthetic\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'gen')
        return self.git('rev-parse', 'HEAD').stdout.decode().strip()

    def fetch(self, *extra):
        return subprocess.run(['bash', str(FETCH), *extra], capture_output=True, text=True)

    def test_fetch_base_pins_commit_and_is_idempotent(self):
        rev = self.add_generator_files()
        dest = self.root / 'fetched'
        args = ('--url', self.base.as_uri(), '--rev', rev, '--dest', str(dest))
        first = self.fetch(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), str(dest))
        self.assertEqual(subprocess.run(['git', '-C', str(dest), 'rev-parse', 'HEAD'], capture_output=True,
                                        text=True).stdout.strip(), rev)
        self.assertFalse(dest.with_name('fetched.partial').exists())
        second = self.fetch(*args)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('reusing', second.stderr)

    def test_fetch_base_rejects_other_commit_and_short_rev(self):
        rev = self.add_generator_files()
        dest = self.root / 'fetched'
        self.assertEqual(self.fetch('--url', self.base.as_uri(), '--rev', rev, '--dest', str(dest)).returncode, 0)
        other = self.git('rev-parse', 'HEAD~1').stdout.decode().strip()
        clash = self.fetch('--url', self.base.as_uri(), '--rev', other, '--dest', str(dest))
        self.assertNotEqual(clash.returncode, 0)
        self.assertEqual(self.fetch('--url', self.base.as_uri(), '--rev', rev[:7],
                                    '--dest', str(self.root / 'x')).returncode, 2)

    def test_init_falls_back_to_fetched_default_base(self):
        sys.path.insert(0, str(SCRIPT.parent))
        self.addCleanup(sys.path.remove, str(SCRIPT.parent))
        from fetch_base import default_dest
        rev = self.add_generator_files()
        fetched = self.fetch('--url', self.base.as_uri(), '--rev', rev, '--dest', str(default_dest()))
        self.assertEqual(fetched.returncode, 0, fetched.stderr)
        result = subprocess.run(['bash', str(SCRIPT), '--out', str(self.out), '--no-extract'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('using pinned base', result.stderr)
        self.assertTrue((self.out / 'tools/gen.py').is_file())

    def test_missing_base_names_fetch_command(self):
        result = subprocess.run(['bash', str(SCRIPT), '--out', str(self.out), '--no-extract'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('fetch_base.sh', result.stderr)


if __name__ == '__main__':
    unittest.main()
