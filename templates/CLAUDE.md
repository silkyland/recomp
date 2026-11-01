# <PROJECT> — permanent rules

Static recompilation of *<GAME TITLE>* (Nintendo Switch) to PC. Derived from <BASE REPO — e.g.
EoWRecomp / LASRecomp (MIT, https://github.com/peiikai/LASRecomp)>. Not an emulator: the game's
ARM64 becomes C at build time; the runtime replaces Horizon and the NVN graphics API.
Base provenance: `docs/BASE.md`; current state and next step: `docs/STATUS.md`
(read before starting).

## Nintendo files
- **Game files stay local and untracked**: `input/`, `extracted/`, `generated/`, keys,
  XCI/NSP/NCA/NSO, system fonts, textures, models, music, text and other assets live only on this
  machine, test files included. `.gitignore` covers this; check `git ls-files` and
  `git check-ignore` on actual output paths before a commit. Screenshots of the running game
  (`docs/screenshots/`) may be committed to document progress.
- The user's files (package, `prod.keys`) come from their own console and live outside the
  repository or in its ignored `input/` folder, opened **read-only** with permissions unchanged.
  Ask for missing local paths; keys stay in their file. (`extracted/romfs.src` contains the
  package path + keys, which is why `extracted/` stays untracked and machine-local.)
- Extraction: `tools/nca_extract.py` → `extracted/` (`exefs/`, `romfs*`).
- Pinned version: **title <TITLE ID>, v<VERSION>** — build IDs in `docs/STATUS.md`. Patch and HLE
  addresses are valid only for that build.

## Code
- Generated code (`generated/`) is never edited by hand: changes go in `tools/lifter.py`,
  `tools/gen.py` or `tools/patches.py`.
- Audit inherited patches/HLE registrations before generation. Bind them to full build IDs.
- Every patch checks the original instruction word first (`expect()` in `tools/patches.py`) —
  a mismatch means wrong build/address, never force it.
- Match the surrounding code style (names, structure, comment density). Comments explain the
  *why* — what the game does, what an address is, which log/test revealed the problem.
- For every failure find the root cause (Capstone, logs, Switchbrew, envytools, Atmosphere source)
  instead of working around it. Missing NVN feature or Maxwell instruction: implement it properly
  and add a test (`test_translate`, `test_shaders`, `test_simd`, `test_lift`).
- Debug environment variables use the `<PREFIX>_` prefix.

## Verification
- A fix is verified only once *seen* working (screenshot, log or test) — never declare success
  from "it should work".
- A change in the shared renderer: say which backend was tested (Vulkan / Metal).
- Measure instead of estimating — run the tools (`tools/nso.py`, `tools/analyze.py --census`,
  `tools/inventory.py`, logs).
- Advance by milestones (M1–M7, `docs/STATUS.md`); move to the next only when the current one is
  proven.

## Git
- Small, descriptive commits; one subject per commit.
- README: fan project, no Nintendo affiliation, no game files included, requires the user's own
  legal copy; credit the base project and every library used, with their licenses.

## End of session
- Update `docs/STATUS.md`: current milestone, what works, what broke, next step, and what the user
  should test and watch for.
