# recomp — agent skill for Nintendo Switch static recompilation

An [agent skill](https://agentskills.io) (`/recomp <package>`) that walks an AI coding agent
through bootstrapping a **static recompilation** project for a new Nintendo Switch game:
the game's ARM64 is lifted to C at build time, and a runtime replaces Horizon OS (SVCs, IPC
services) and the NVN graphics API. The methodology is distilled from
[LASRecomp](https://github.com/peiikai/LASRecomp) (MIT) and an EoW recomp project built on it.

## Usage

```
/recomp <game.nsp|game.xci|program.nca|game.nsz> [new-project-dir] [--keys <prod.keys>] [--base <recomp-repo>]
```

Every package format is handed to the base's extractor, whose `--info` pass confirms support
before extraction. The package and keys can live outside the project or in its git-ignored
`input/` folder.

## Legal

- Use the game package and `prod.keys` from **your own console/dump**. The skill opens them
  read-only and keeps them out of commits.
- Game-derived files (packages, keys, extracted code/assets) stay local and out of every repo,
  including this one. The bundled `.gitignore` template covers the standard directories.

## Contents

- `SKILL.md` — entry point: prerequisites checklist, pipeline stages with go/no-go gates
- `references/` — `pipeline.md` (stage-by-stage walkthrough), `tools.md` (tool inventory and
  what to copy vs adapt per game), `hard-parts.md` (Horizon mutex/condvar semantics,
  Maxwell shader translation, per-build-ID versioning, guest-deadlock debugging)
- `scripts/init_project.sh` (wrapper for `init_project.py`) — scaffolds a project: canonical-path
  checks, explicit base selection, copies tracked source, installs ignore rules, extracts and
  inventories with failure propagation. `--no-extract` scaffolds without a package or keys.
- `templates/` — project rules (installed as `AGENTS.md`, with `CLAUDE.md` importing it),
  `STATUS.md`, `.gitignore` for the new project
- `tests/` — offline regression tests for the bootstrap (synthetic fixtures only)

Not affiliated with Nintendo. Requires a base repo providing `tools/` + `runtime/` (e.g. a
LASRecomp-derived tree); `init_project.sh --base` or `RECOMP_BASE` selects it.

The public LASRecomp revision documented in this skill lacks the package extractor and
inventory extensions. Select a compatible local Git base explicitly, or use `--no-extract`
for scaffolding without dependency installation. Existing projects should continue from
STATUS.md rather than rerun initialization. See SKILL.md for the capability checks.

Validate the bootstrap without game data or network access:

```sh
python3 -m unittest discover -s tests -v
shellcheck scripts/init_project.sh
```
