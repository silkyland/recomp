---
name: recomp
description: >-
  Bootstrap or continue a Nintendo Switch static-recompilation project for a NEW game: the game's
  ARM64 is lifted to C at build time and a runtime replaces Horizon OS (SVCs, IPC services) and the
  NVN graphics API — the EoWRecomp/LASRecomp pipeline. Use when the user runs /recomp <package>,
  says "recomp <game file>", or asks to recompile a Switch game / start a new recomp project from
  an NSP/XCI/NCZ/NCA dump. Requires the user's own legally dumped package and prod.keys — they stay
  OUTSIDE the repo and are never committed, copied, or fetched.
argument-hint: "<game.nsp|xci|nca> [new-project-dir]"
---

# /recomp — Switch static recompilation pipeline

Not an emulator: `game NSO (AArch64) -> tools/gen.py + lifter.py -> generated/*.c -> <game>lib.so`
plus a runtime (`runtime/`) that emulates Horizon kernel SVCs, HIPC/TIPC services and reimplements
NVN on Vulkan/Metal. This skill walks a new game through the same stages EoWRecomp uses.

## Usage

```
/recomp <game.nsp|game.xci|program.nca> [new-project-dir] [--keys <prod.keys>] [--base <recomp-repo>]
```

On invocation, the agent:
1. Confirms the legal prerequisites below (ask if keys/package location is unknown — never search
   the web for them).
2. Picks or confirms a **base recomp repo** to copy tools+runtime from (see "Base repo" below).
3. Runs `scripts/init_project.sh` to scaffold the project, extract, and inventory the dump.
4. Walks the milestone gates in `references/pipeline.md` one at a time, updating `docs/STATUS.md`.

## Legal rules — non-negotiable, recite to the user once

- The game package and `prod.keys` must come from the user's own console/dump. They live in a
  folder **outside the repository**, opened **read-only**. Never copy them into the repo.
- Never commit: packages, keys, `extracted/`, `generated/`, or any game asset/code — not even one
  file "for a test". Install `templates/gitignore` first; verify with `git status --ignored`.
- `extracted/romfs.src` embeds the package path **and decryption keys** — `extracted/` must stay
  untracked and machine-local.
- Do not provide or suggest sources for obtaining dumps or keys. Screenshots of the running game
  (for docs) are the only game-derived files allowed in the repo.

## Prerequisites checklist (gate — stop and ask if missing)

- [ ] A dump of the user's own game: `.nsp` (read in place), `.nsz` (decompress with `nsz -D` first),
      program `.nca`, or `.xci` (needs hactool to extract the program NCA first).
- [ ] The user's own `prod.keys` (needs `header_key`, `key_area_key_application_XX`, `aes_kek`/… —
      `nca_extract.py` errors name what's missing).
- [ ] A base recomp repo to copy from: EoWRecomp or LASRecomp (both MIT). `silkyland/recomp` was
      checked on 2026-11 and **does not exist** — if the user created it since, prefer it as base.
- [ ] Python 3 + venv deps: capstone, unicorn, lz4, cryptography, pillow (`scripts/init_project.sh`
      creates `tools/venv`). Host deps for the runtime: clang, SDL3, FFmpeg, shaderc, Vulkan.
- [ ] ~20–80 GB free disk (RomFS trees and generated C are large; generated code ~900 MB for a
      40 MB .text game).

## Pipeline — one gate at a time (detail: `references/pipeline.md`)

| Stage | Gate to pass before moving on |
|---|---|
| 0. Legal setup | dumps/keys outside repo; `.gitignore` installed; `git status --ignored` clean |
| 1. Pin one build | one title ID + version recorded; module **build IDs** in STATUS.md — all patch/HLE addresses are per-build-ID |
| 2. Extract | `nca_extract.py --info` shows NCA3 / content type 0; `extracted/exefs/` has `main`, `sdk`, `subsdk*`, `rtld`, `main.npdm`. **Stop if the package is truncated or the NSO won't decompress** |
| 3. Inventory | `inventory.py extracted/exefs [--lift]` → `docs/GAP.md`: module sizes, imports by exporting module, NVN coverage, services, SVCs, unsupported instructions |
| 4. M1 generate | `make gen` finishes with **0 `Unsupported`** — never work around: implement in `lifter.py`, test against Unicorn |
| 5. M2/M3 boot | runtime loads modules, `nn::init::Start` runs, services answer, **first frame presented** |
| 6. M4 image | first **correct** image — verified by screenshot, never by "should work" |
| 7. M5–M7 | title/input/first playable scene → full playthrough+saves → PC features |

## Working rules (from the reference project's CLAUDE.md)

- **Generated code is never edited by hand** — fix `gen.py`/`lifter.py`/`patches.py` and regenerate.
- Every patch checks the original instruction word first (`expect()` in `patches.py`); a mismatch
  means wrong build, not a patch to force.
- A fix is only verified when **seen working** (screenshot, log line, or test). Measure with tools
  (`nso.py`, `analyze.py --census`, `inventory.py`), don't estimate.
- Debug env vars use a per-project prefix (`EOWRECOMP_*` in the reference). Watchdog +
  symbolized guest stacks are the deadlock/freeze toolkit — see `references/hard-parts.md`.
- Advance by milestones; the current milestone must be proven before starting the next.

## Bundled files

- `scripts/init_project.sh` — scaffolds a project: copies tools+runtime from a base repo, builds
  the venv, runs extraction + inventory, writes `docs/STATUS.md`/`GAP.md` skeletons.
- `references/pipeline.md` — detailed stage-by-stage walkthrough with commands and decision gates.
- `references/tools.md` — which tools/runtime files to copy verbatim vs adapt per game, and where
  they came from (LASRecomp → EoWRecomp).
- `references/hard-parts.md` — known hard parts: Horizon mutex/condvar semantics, guest deadlocks,
  Maxwell shader translation, memory layout/GUEST_SHIFT, per-build versioning.
- `templates/` — `CLAUDE.md` (project rules), `STATUS.md` (M1–M7 tracker), `gitignore` (dumps/keys/
  extracted/generated) for the new project.
