# <PROJECT> — permanent rules

Static recompilation of *<GAME TITLE>* (Nintendo Switch) to PC. Derived from <BASE REPO — e.g.
EoWRecomp / LASRecomp (MIT, https://github.com/peiikai/LASRecomp)>. Not an emulator: the game's
ARM64 becomes C at build time; the runtime replaces Horizon and the NVN graphics API.
Architecture/plan: `docs/ARCHITECTURE.md`; current state and next step: `docs/STATUS.md`
(read before starting).

## Nintendo files
- **No Nintendo file ever enters the repository**: no `extracted/`, `generated/`, keys,
  XCI/NSP/NCA/NSO, system fonts, textures, models, music, text or any other asset — not even
  "one file for a test". `.gitignore` covers this; check `git status --ignored` before every commit.
  Exception: screenshots of the running game (`docs/screenshots/`) to document progress —
  never extracted files.
- The user's files (package, `prod.keys`) live in their own folder **outside** the repository —
  **read-only**. Never copy them into the repo. Never ask for, look for, or suggest sources for
  them. (`extracted/romfs.src` contains the package path + keys: another reason `extracted/`
  stays untracked and machine-local.)
- Extraction: `tools/nca_extract.py` → `extracted/` (`exefs/`, `romfs*`).
- Pinned version: **title <TITLE ID>, v<VERSION>** — build IDs in `docs/STATUS.md`. Patch and HLE
  addresses are valid only for that build.

## Code
- Generated code (`generated/`) is never edited by hand: changes go in `tools/lifter.py`,
  `tools/gen.py` or `tools/patches.py`.
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
