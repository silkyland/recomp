---
name: recomp
description: >-
  Bootstrap or continue a Nintendo Switch static-recompilation project using a local
  LASRecomp-derived toolchain and Horizon/NVN runtime. Use for /recomp, recompiling a
  user's Switch game dump, or continuing an existing recomp project. Works from the user's
  own package and keys, kept outside the repository or in its ignored input/ folder.
---

# Switch static recompilation

Goal: lift one pinned game's AArch64 modules to C at build time and adapt a native runtime
that replaces Horizon services and NVN. This is a per-game engineering project, not an
automatic converter; a successful scaffold does not establish playability.

## Start or continue

For a **new project**, obtain the paths to the user's own package, keys, target directory,
and a trusted local base checkout. Ask for any missing paths (paths only; keys stay in their file).

```sh
bash scripts/init_project.sh --pkg /external/game.nsp --keys /external/prod.keys \
  --out /work/new-game --base /work/compatible-base --name newgame
```

Resolve the script relative to this skill's directory. It accepts `.nsp`, program `.nca`, `.xci`
and compressed `.nsz`/`.xcz`/`.ncz`, handing each to the base extractor, whose `--info` pass
confirms support before anything is extracted. Check the extractor's `--help` for its formats; if
it lacks one, convert the package with a tool that has it. `--romfs` accepts `src` (default),
`image`, `tree`, or `none`. Package and keys may sit outside the project or in its ignored `input/`.

- `--no-extract`: scaffold only; no venv, pip, extraction or inventory, and `--pkg`/`--keys` become
  optional. Useful to inspect a base that lacks the extraction extensions.
- `--no-copy`: retain existing project sources/templates; append missing ignore rules. Extraction
  requires an empty `extracted/` directory to avoid mixing builds. Never erase it automatically.
- `RECOMP_BASE` supplies the base when `--base` is absent. There is no automatic base search.
- Dependencies come from the base's `tools/requirements.txt` when present (prefer a pinned one),
  else an unpinned default set. Installation needs network access; a failed install is retried
  on the next run rather than silently skipped.

For an **existing project**, read its agent rules, `docs/STATUS.md`, build configuration and
current changes first. Continue the next unproven milestone. Do not rerun initialization,
replace its runtime, discard patches, or reinstall dependencies just because this skill loaded.

## Data boundaries

- Use the user's own dumps and keys. Keep them outside the repository or in its ignored `input/`
  folder, opened read-only with their permissions unchanged.
- Extraction and generation outputs are machine-local and ignored. They contain game code/assets,
  so keep them out of commits and releases. `extracted/romfs.src` embeds keys and absolute package
  paths: keep it private, and log key names rather than values.
- Install ignore rules before extraction. `.gitignore` does not protect already tracked files;
  inspect `git ls-files` and use `git check-ignore` on actual output paths before a commit.
  Screenshots of the running game may be committed to document progress.
- Preserve the base's license and third-party notices.

## Verify the base before executing its tools

Use [references/tools.md](references/tools.md) to classify copied versus game-specific files.
Record the base revision and local modifications (`docs/BASE.md` from the initializer), inspect
its license, CLI help and build rules. Local scripts and Makefiles execute with user permissions.
The initializer copies tracked source files from a Git checkout; it rejects selected symlinks,
missing tracked files and submodule entries. Untracked additions are not copied.

**LASRecomp is a lineage reference, not a guaranteed extraction-capable base.** At verified
revision `d23597d6cba13f0e3b4797a0c813c14ef86c684c`, it has `nso.py`, `gen.py` and the runtime,
but lacks `nca_extract.py` and `inventory.py`. The package workflow below needs a compatible
extended checkout providing both. No public EoWRecomp source revision was supplied with this
skill; treat its detailed commands, diagnostic variables and failure stories as examples until
confirmed in the selected checkout. Do not invent a repository URL or missing tool.

## Milestone gates

Read [references/pipeline.md](references/pipeline.md) for commands and adaptation details.

| Stage | Evidence required |
|---|---|
| Setup | External inputs; ignored, private outputs; trusted compatible base pinned |
| Pin build | Title/version and **full module build IDs** recorded; never mix base/update files without verified support |
| Extract | Correct program NCA selected; required modules and metadata present; NSO parsing/decompression succeeds |
| Inventory | Measured image spans, imports, NVN/service/SVC gaps; census every loaded module |
| M1 | All required modules generated and compiled; zero unsupported encodings; lifter tests pass |
| M2/M3 | Runtime initializes modules and services; first frame presented |
| M4 | First correct image checked against a known reference |
| M5 | Title, audio, input and first controllable scene verified |
| M6 | Full playthrough, save/load round-trip and performance evidence |
| M7 | Only requested PC features, verified independently |

Before generation, reconcile **both** Makefile generation/link module lists and runtime module
layout; remove or disable inherited game-specific patch/HLE registrations deliberately. A copied
`patches.py` is not empty, and matching an instruction word alone does not validate a foreign patch.

## Working rules

- Never hand-edit generated C; fix the generator, lifter or source patch definitions.
- Bind patches/HLE addresses to full build IDs and check original instruction bytes (`expect()` or
  equivalent). Stop on mismatch. Add differential lifter tests; compare hardware where the oracle
  itself is uncertain. Zero unsupported encodings is necessary, not proof of correct lifting.
- An unresolved import or service stub returning success can hide incorrect behavior. Track stubs,
  and implement or explicitly justify those on the exercised path before advancing a milestone.
- Use measured evidence: command exit status, tests, logs, screenshots and save round-trips.
  State which host/GPU backend was tested. Never infer playability from generation or a black frame.
- Consult [references/hard-parts.md](references/hard-parts.md) when investigating synchronization,
  shader or memory-layout failures; verify each proposed mechanism against the selected code.
- Update `docs/STATUS.md` with evidence, blockers and the next step. If blocked, report the exact
  missing input/capability rather than claiming a milestone passed.

The initializer also installs `templates/gitignore`, `templates/STATUS.md`, and the project rules
as `AGENTS.md` (with `<PROJECT>` filled from `--name`) plus a `CLAUDE.md` that imports it, each
only when absent. Fill the remaining placeholders after pinning the build.
