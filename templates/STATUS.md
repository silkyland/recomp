# Status

Updated: <date> (session N: <machine/OS>).

## Pinned game build (the ONLY build patch/HLE addresses are valid for)

| | |
|---|---|
| Title | <GAME TITLE> |
| Title ID | <0100…> |
| Version | <v? (0x?), display version ?.?.?> |
| System requirement (CNMT) | <…> |
| SDK | <NintendoSDK ?.?.? from program NCA / module strings> |
| Program NCA | `<hash>.nca` (<size> bytes) |

Module build IDs (from `tools/nso.py extracted/exefs/*`):

| Module | Build ID | File size | Guest base (modules.h) |
|---|---|---|---|
| main | `<…>` | | |
| sdk | `<…>` | | |
| subsdk* | `<…>` | | |
| rtld | `<…>` | | |

RomFS: <n> files, <bytes> bytes (served via `romfs.src` / `romfs.bin` / extracted tree — pick one).

## Current milestone

M?<n> — <state>. Backend tested: <Vulkan/Metal> on <GPU/driver>. **Say which backend each fix was
verified on.**

## Milestones

- [ ] M1 — all game code recompiles to C (<n> modules, <n> functions, **0 unsupported**)
- [ ] M2 — the runtime links and boots into the game (`nn::init::Start`, init callbacks)
- [ ] M3 — first frame presented
- [ ] M4 — first correct image (screenshot-proven)
- [ ] M5 — title screen, audio, input, first playable scene
- [ ] M6 — playable start to finish, saves round-trip
- [ ] M7 — PC features: resolution, free aspect, unlocked fps, remapping, button icons

## Works (each item verified — screenshot / log / test, not "should work")

-

## Fixed this session (each with the root cause found in game/SDK code)

-

## Open problems (priority order)

1.

## How to test

- `<PREFIX>` env vars: `<PREFIX>_SHOT_AT=<frames>` screenshots → `build/frames/`;
  `<PREFIX>_INPUT="frame:BTN:dur,…"` scripted input; `<PREFIX>_WATCHDOG=<ms>` deadlock dump;
  `<PREFIX>_SAVE_DIR`, `<PREFIX>_HIDDEN`, `<PREFIX>_NO_AUDIO`.
- `tools/run.sh` — timed run, log `build/run.log`, symbolized guest stack (`tools/symgame.py`).
- Tests: `test_lift.py` (vs Unicorn; `--synth` without game files), `test_translate.sh`,
  `test_simd.py`, `test_shaders.*`, `test_astc.*`, `test_vk_pipelines.*`, `test_nxpkg.sh`.

## How to build

- `tools/venv` (capstone, unicorn, lz4, cryptography, pillow) → `make gen` → `make -j$(nproc)`
- Host deps: clang, SDL3, FFmpeg, shaderc, Vulkan (see base repo's per-OS docs).

## Next step

-
