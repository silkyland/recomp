# recomp — agent skill for Nintendo Switch static recompilation

An [agent skill](https://agentskills.io) (`/recomp <package>`) that walks an AI coding agent
through bootstrapping a **static recompilation** project for a new Nintendo Switch game:
the game's ARM64 is lifted to C at build time, and a runtime replaces Horizon OS (SVCs, IPC
services) and the NVN graphics API. The methodology is distilled from
[LASRecomp](https://github.com/peiikai/LASRecomp) (MIT) and an EoW recomp project built on it.

## Usage

```
/recomp <game.nsp|game.xci|program.nca> [new-project-dir] [--keys <prod.keys>] [--base <recomp-repo>]
```

## Legal

- The game package and `prod.keys` must come from **your own console/dump**. They live outside
  the repository, read-only — never committed, copied, or fetched by the skill.
- No Nintendo files (packages, keys, extracted code/assets) belong in any repo — including this
  one. The bundled `.gitignore` template covers the standard directories.

## Contents

- `SKILL.md` — entry point: prerequisites checklist, pipeline stages with go/no-go gates
- `references/` — `pipeline.md` (stage-by-stage walkthrough), `tools.md` (tool inventory and
  what to copy vs adapt per game), `hard-parts.md` (Horizon mutex/condvar semantics,
  Maxwell shader translation, per-build-ID versioning, guest-deadlock debugging)
- `scripts/init_project.sh` — scaffolds a project: legal guard, format gates, copies the
  recomp tool+runtime base, extracts (`--romfs-src`), installs templates
- `templates/` — `CLAUDE.md`, `STATUS.md`, `.gitignore` for the new project

Not affiliated with Nintendo. Requires a base repo providing `tools/` + `runtime/` (e.g. a
LASRecomp-derived tree); `init_project.sh --base` or `RECOMP_BASE` selects it.
