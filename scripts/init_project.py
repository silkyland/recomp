#!/usr/bin/env python3
"""Scaffold from an explicitly selected, trusted local Git checkout. Never builds it."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from fetch_base import default_dest

SKILL = Path(__file__).resolve().parent.parent
REQUIRED = ('tools/nso.py', 'runtime/rt.h', 'Makefile', 'LICENSE')
EXTRACTION = ('tools/nca_extract.py', 'tools/inventory.py')
# Fallback when the base provides no tools/requirements.txt.
PACKAGES = ('capstone', 'unicorn', 'lz4', 'cryptography', 'pillow')
# The one in-project location (git-ignored) where the user's package and keys may live.
INPUT_DIR = 'input'
# Extensions handed to the base extractor; its --info pass decides actual support.
FORMATS = ('.nsp', '.nca', '.xci', '.nsz', '.xcz', '.ncz')


def fail(message):
    raise ValueError(message)


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def git(base, *args):
    return run(['git', '-C', base, *args], stdout=subprocess.PIPE).stdout


def contained(path, root):
    return path == root or root in path.parents


def check_base(base, extract):
    try:
        toplevel = git(base, 'rev-parse', '--show-toplevel')
    except subprocess.CalledProcessError:
        fail(f'--base is not a Git checkout: {base}')
    if Path(os.fsdecode(toplevel).strip()).resolve() != base:
        fail('--base must be the root of a local Git checkout')
    required = REQUIRED + (EXTRACTION if extract else ())
    for name in required:
        if not (base / name).is_file():
            fail(f'base missing {name}; select a compatible base or use --no-extract to scaffold only')
    for name in ('tools', 'runtime', 'third_party'):
        if not (base / name).is_dir():
            fail(f'base missing {name}/ (initialize its dependencies first)')
    files = []
    for raw in git(base, 'ls-files', '-z').split(b'\0'):
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if relative.parts[0] not in ('tools', 'runtime', 'third_party') and str(relative) not in (*REQUIRED, 'README.md'):
            continue
        if any(p in ('venv', '__pycache__', '.git', 'build', 'extracted', 'generated') or
               p.startswith('generated-') for p in relative.parts):
            continue
        source = base / relative
        if not contained(source.resolve(), base) or any(p.is_symlink() for p in (source, *source.parents)):
            fail(f'base contains a symlink in selected source: {relative}')
        if not source.is_file():
            fail(f'base source missing or a submodule: {relative}; materialize dependencies before copying')
        files.append(relative)
    if not set(required).issubset({str(p) for p in files}):
        fail('required base files must be tracked in Git')
    revision = git(base, 'rev-parse', 'HEAD').decode().strip()
    dirty = bool(git(base, 'diff', 'HEAD', '--', 'tools', 'runtime', 'third_party', 'Makefile', 'LICENSE', 'README.md'))
    return files, revision, dirty


def prepare_output(out, name):
    # Resume may add missing templates but must not follow output symlinks elsewhere.
    for relative in ('tools', 'runtime', 'third_party', 'docs', 'extracted', '.gitignore',
                     'CLAUDE.md', 'AGENTS.md', 'docs/STATUS.md'):
        path = out / relative
        if path.is_symlink() or not contained(path.resolve(), out):
            fail(f'unsafe output path: {path}')
    for directory in ('tools', 'runtime', 'third_party', 'docs', 'extracted'):
        path = out / directory
        if path.exists() and not path.is_dir():
            fail(f'expected directory: {path}')
    (out / 'docs').mkdir(parents=True, exist_ok=True)
    ignore = out / '.gitignore'
    rules = (SKILL / 'templates/gitignore').read_text().replace('<PROJECT>', name)
    existing = ignore.read_text() if ignore.exists() else ''
    if rules not in existing:
        with ignore.open('a') as stream:
            stream.write(('\n' if existing else '') + rules)
    status = out / 'docs/STATUS.md'
    if not status.exists():
        shutil.copyfile(SKILL / 'templates/STATUS.md', status)
    # One rules file; CLAUDE.md imports it so the two never drift apart.
    agents = out / 'AGENTS.md'
    if not agents.exists():
        agents.write_text((SKILL / 'templates/CLAUDE.md').read_text().replace('<PROJECT>', name))
    claude = out / 'CLAUDE.md'
    if not claude.exists():
        claude.write_text('@AGENTS.md\n')


def report(args, cwd, destination, preamble=''):
    # Do not publish a partial successful-looking report or clobber a previous good one.
    if destination.is_symlink():
        fail(f'report must not be a symlink: {destination}')
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.recomp-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(preamble)
            stream.flush()
            run(args, cwd=cwd, stdout=stream)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def extract(out, package, keys, romfs):
    for name in EXTRACTION + ('tools/nso.py',):
        if not (out / name).is_file():
            fail(f'project missing {name}')
    extracted = out / 'extracted'
    if extracted.exists() and any(extracted.iterdir()):
        fail('extracted/ is not empty; use a fresh output directory to avoid mixing builds')
    extracted.mkdir(mode=0o700, exist_ok=True)
    if git_available(out):
        tracked = git(out, 'ls-files', '--', 'extracted', 'generated', 'generated-*', INPUT_DIR)
        if tracked:
            fail('game-derived output is already tracked; .gitignore cannot untrack it')
    python = ensure_venv(out)
    # -E -s ignores PYTHON* and user site packages while retaining sibling-tool imports.
    command = [python, '-E', '-s', 'tools/nca_extract.py', keys, package, 'extracted']
    run(command + ['--info'], cwd=out)
    flags = {'src': ['--no-romfs', '--romfs-src'], 'image': ['--no-romfs', '--romfs-image'],
             'none': ['--no-romfs'], 'tree': []}[romfs]
    run(command + flags, cwd=out)
    exefs = extracted / 'exefs'
    if not (exefs / 'main').is_file() or not (exefs / 'main.npdm').is_file():
        fail('extraction missing exefs/main or main.npdm')
    modules = []
    build_ids = []
    for path in sorted(exefs.iterdir()):
        if path.is_file():
            with path.open('rb') as stream:
                header = stream.read(0x60)
                if header[:4] == b'NSO0':
                    if len(header) < 0x60:
                        fail(f'truncated NSO header: {path.name}')
                    modules.append(path)
                    build_ids.append(f'{path.name}: {header[0x40:0x60].hex()}')
    if exefs / 'main' not in modules:
        fail('exefs/main is not an NSO0 module')
    report([python, '-E', '-s', 'tools/nso.py', *modules], out, out / 'docs/modules.txt',
           'Full 32-byte NSO build IDs (header bytes 0x40..0x5f):\n' + '\n'.join(build_ids) + '\n\n')
    report([python, '-E', '-s', 'tools/inventory.py', 'extracted/exefs'], out, out / 'docs/GAP.md')


def ensure_venv(out):
    venv = out / 'tools/venv'
    python = venv / 'bin/python'
    marker = venv / '.recomp-deps-installed'
    if not python.exists():
        run([sys.executable, '-m', 'venv', venv])
    # The marker is written only after pip succeeds, so an interrupted or offline install is
    # retried on the next run instead of extracting with missing dependencies.
    if not marker.exists():
        requirements = out / 'tools/requirements.txt'
        packages = ['-r', requirements] if requirements.is_file() else list(PACKAGES)
        run([python, '-m', 'pip', 'install', *packages])
        marker.write_text('dependencies installed by init_project\n')
    return python


def git_available(out):
    return subprocess.run(['git', '-C', str(out), 'rev-parse', '--show-toplevel'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pkg', type=Path, help='.nsp/.nca/.xci/.nsz/.xcz/.ncz package, outside the project or in its '
                        f'{INPUT_DIR}/ folder (required unless --no-extract)')
    parser.add_argument('--keys', type=Path, help=f'prod.keys, outside the project or in its {INPUT_DIR}/ folder; '
                        'never modified (required unless --no-extract)')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--base', type=Path, default=os.environ.get('RECOMP_BASE') or None)
    parser.add_argument('--name', default='game', help='short binary name: letters, digits, underscore, hyphen')
    parser.add_argument('--romfs', choices=('src', 'image', 'tree', 'none'), default='src')
    parser.add_argument('--no-copy', action='store_true', help='resume without replacing project source files')
    parser.add_argument('--no-extract', action='store_true', help='scaffold only; no venv or dependency installation')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.name):
        parser.error('invalid --name (letters, digits, underscore, hyphen)')
    if not args.no_extract and (args.pkg is None or args.keys is None):
        parser.error('--pkg and --keys are required unless --no-extract is given')
    out = args.out.expanduser().resolve()
    inputs = out / INPUT_DIR

    def misplaced(path):
        # Inputs may live outside the project or in its git-ignored input/ folder, nowhere else.
        return contained(path, out) and not contained(path, inputs)

    given = [p for p in (args.pkg, args.keys) if p is not None]
    resolved = [p.expanduser().resolve(strict=True) for p in given]
    for path in resolved:
        if not path.is_file() or misplaced(path):
            fail(f'package and keys must be regular files outside the project or in {INPUT_DIR}/')
    # Also check the given spelling, so an alias elsewhere in the project cannot hide the input.
    for path in given:
        if misplaced(Path(os.path.abspath(path.expanduser()))):
            fail(f'package/key aliases must also be outside the project or in {INPUT_DIR}/')
    package = resolved[0] if args.pkg is not None else None
    keys = resolved[-1] if args.keys is not None else None
    if package is not None and package.suffix.lower() not in FORMATS:
        fail(f'unrecognized package extension {package.suffix!r}; expected one of {", ".join(FORMATS)}')
    if out.exists() and not out.is_dir():
        fail('--out must be a directory')
    if not args.no_copy and out.exists() and any(p.name not in ('.git', INPUT_DIR) for p in out.iterdir()):
        fail(f'--out must be empty (apart from .git and {INPUT_DIR}/); use --no-copy to resume')
    files, base, revision, dirty = [], None, '', False
    if args.no_copy and args.base:
        print('init_project: --no-copy given; ignoring --base/RECOMP_BASE', file=sys.stderr)
    if not args.no_copy:
        if not args.base and default_dest().is_dir():
            args.base = default_dest()
            print(f'init_project: using pinned base {args.base}', file=sys.stderr)
        if not args.base:
            fail('no base: run `bash scripts/fetch_base.sh` first, or pass --base / set RECOMP_BASE')
        base = Path(args.base).expanduser().resolve(strict=True)
        if contained(out, base) or contained(base, out):
            fail('base and output must not overlap')
        files, revision, dirty = check_base(base, not args.no_extract)
    elif not args.no_extract:
        for relative in EXTRACTION + REQUIRED[:1]:
            if not (out / relative).is_file():
                fail(f'project missing {relative}')
    out.mkdir(parents=True, exist_ok=True)
    prepare_output(out, args.name)
    for relative in files:
        if str(relative) == 'README.md':
            continue  # Attribution is preserved separately, not used as the new project's README.
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base / relative, target)
    if base:
        # The base README often carries third-party attribution absent from LICENSE.
        if Path('README.md') in files:
            shutil.copyfile(base / 'README.md', out / 'docs/BASE-README.md')
        (out / 'docs/BASE.md').write_text(
            f'# Base provenance\n\nLocal checkout: `{base}`\n\nCommit: `{revision}`\n\n'
            f'Tracked source modifications: {dirty}\n\n'
            'Only tracked source directories and root build/license files were copied.\n'
            'Review inherited patches, HLE addresses and Makefile module lists before generation.\n'
            'Preserve third-party notices; BASE-README.md contains base attribution if available.\n')
    if not args.no_extract:
        extract(out, package, keys, args.romfs)
    print(f'Scaffold ready: {out}')
    print('Extraction/inventory skipped.' if args.no_extract else 'Extraction and inventory completed.')
    print('Next: pin module build IDs in docs/STATUS.md; review inherited patches/HLE and module lists.')
    print('No generation, runtime build, or game launch was performed.')


if __name__ == '__main__':
    # Private descriptors and partial extraction must not be world-readable by default.
    os.umask(0o077)
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'init_project: {error}', file=sys.stderr)
        sys.exit(1)
