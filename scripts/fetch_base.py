#!/usr/bin/env python3
"""Fetch the pinned recomp base checkout to a known location and print its path.

The default is EoWRecomp (MIT, a LASRecomp derivative) at a verified revision: it provides the
lifter, generator, runtime and the package extractor/inventory tools. The upstream LASRecomp
(--url https://github.com/peiikai/LASRecomp.git --rev d23597d6cba13f0e3b4797a0c813c14ef86c684c)
lacks the extractor, so pair it with `init_project --no-extract`.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

URL = 'https://github.com/Nycolazs/EoWRecomp.git'
REV = 'dd9c79d6c01d9eaddafc1fc5a07b6658bfc56505'
NAME = 'EoWRecomp'
REQUIRED = ('tools/nso.py', 'tools/gen.py', 'tools/lifter.py', 'runtime/rt.h', 'Makefile', 'LICENSE')
EXTRACTION = ('tools/nca_extract.py', 'tools/inventory.py')


def cache_root():
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'recomp' / 'bases'


def default_dest(rev=REV):
    """Where the pinned base lives; init_project falls back to it when --base is absent."""
    return cache_root() / f'{NAME}-{rev[:12]}'


def git(*args, **kwargs):
    return subprocess.run(['git', *map(str, args)], check=True, **kwargs)


def head(dest):
    return git('-C', dest, 'rev-parse', 'HEAD', stdout=subprocess.PIPE, text=True).stdout.strip()


def fetch(url, rev, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + '.partial')
    if partial.exists():
        raise ValueError(f'leftover partial fetch at {partial}; remove it and retry')
    git('init', '-q', partial)
    git('-C', partial, 'remote', 'add', 'origin', url)
    # Shallow fetch of the exact commit; fall back to a full fetch for servers that refuse SHA wants.
    if subprocess.run(['git', '-C', str(partial), 'fetch', '-q', '--depth', '1', 'origin', rev],
                      stderr=subprocess.DEVNULL).returncode != 0:
        git('-C', partial, 'fetch', '-q', 'origin')
    git('-C', partial, '-c', 'advice.detachedHead=false', 'checkout', '-q', '--detach', rev)
    git('-C', partial, 'submodule', 'update', '--init', '--recursive', '-q')
    # Rename only once complete, so an interrupted fetch never looks like a usable base.
    partial.rename(dest)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=URL, help=f'base repository (default: {URL})')
    parser.add_argument('--rev', default=REV, help='full commit to check out (default: verified pin)')
    parser.add_argument('--dest', type=Path, help='checkout directory (default: under $XDG_CACHE_HOME/recomp/bases)')
    args = parser.parse_args()
    if len(args.rev) != 40 or any(c not in '0123456789abcdef' for c in args.rev.lower()):
        parser.error('--rev must be a full 40-character commit hash, so the base stays pinned')
    rev = args.rev.lower()
    if args.dest:
        dest = args.dest.expanduser().resolve()
    elif args.url == URL:
        dest = default_dest(rev)
    else:
        parser.error('--dest is required with a custom --url')
    if dest.exists():
        # Reuse an existing checkout only if it is exactly the requested commit.
        if head(dest) != rev:
            raise ValueError(f'{dest} exists at another commit; choose a different --dest')
        print(f'fetch_base: reusing {dest}', file=sys.stderr)
    else:
        fetch(args.url, rev, dest)
    missing = [name for name in REQUIRED if not (dest / name).is_file()]
    if missing:
        raise ValueError(f'{dest} lacks required base files: {", ".join(missing)}')
    lacking = [name for name in EXTRACTION if not (dest / name).is_file()]
    if lacking:
        print('fetch_base: base lacks ' + ', '.join(lacking) +
              '; use init_project --no-extract, or an extended base via --url/--rev', file=sys.stderr)
    print(dest)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'fetch_base: {error}', file=sys.stderr)
        sys.exit(1)
