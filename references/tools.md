# Tools & runtime: what to copy, what to adapt

Provenance: the base is **LASRecomp** (MIT, https://github.com/peiikai/LASRecomp, commit `d23597d`),
extended by **EoWRecomp** (MIT). Copy the whole `tools/` + `runtime/` + `Makefile` + `third_party/`
(imgui, smaa) from a base repo — do **not** rewrite them per game. `scripts/init_project.sh` does
the copy for you; this file explains what each piece is and which files are game-specific.

## tools/ — the recompiler (Python; venv deps: capstone, unicorn, lz4, cryptography, pillow)

| Tool | Role | Per game? |
|---|---|---|
| `nca_extract.py` | Program-NCA → ExeFS + RomFS extractor. Reads `.nsp` in place and bare `.nca`; handles the BucketTree/LZ4 compression layer hactool can't. Flags: `--info`, `--no-romfs`, `--romfs-image` (`romfs.bin`), `--romfs-src` (runtime streams RomFS from the package — **writes keys+package path into `extracted/romfs.src`**). Usage: `nca_extract.py <prod.keys> <nsp|nca> <outdir>` | copy as-is |
| `nso.py` | NSO parser: header, 3 LZ4 segments, MOD0, `.dynamic`, dynsym via `DT_HASH`, RELA/JMPREL relocs, build ID. `nso.py <files…>` prints the inventory table | copy as-is |
| `analyze.py` | Function discovery (.eh_frame_hdr + STT_FUNC + RELATIVE-relocs + BL targets); `--census` = instruction census | copy as-is |
| `inventory.py` | `inventory.py <exefs> [--lift] [--simd c|asm]` → the GAP report: segments, build IDs, SDK strings, imports by exporter, NVN names vs `HLE_FUNC`/`NVN(` coverage, HOS service strings, SVCs in kernel.c, unsupported-instruction census | copy as-is |
| `gen.py` | Code generator → `generated/<module>/<module>_NNN.c` + `_table.c`. Usage: `gen.py <name> <nso> <base-hex> <outdir> [--hle file] [--simd asm|c] [--shift N]` | copy as-is |
| `lifter.py` | AArch64 → C. Integer/mem/flags → C; FP/SIMD → host asm or `simd_c.py` portable (AVX2/FMA). Extend here for new instructions | copy, extend |
| `patches.py` | Address → C replacements applied at generation; **every site `expect()`s the original instruction word**. Starts empty — add only game-proven sites | adapt (empty→yours) |
| `passes.py`, `simd_c.py` | Codegen helpers + portable SIMD emitters | copy as-is |
| `sym.py`, `symgame.py` | Guest address → module+symbol (demangled); `symgame.py <log>` resolves `<gamelib>+<off>` crash frames to `f_<addr>` → names | copy; update lib name |
| `transients.py` | Flicker/twinkle finder across `build/frames/*.png` | copy as-is |
| `gamelib_entry.c` | Entry shim of the generated game library (`GAMELIB_ID` = hash of generator+headers+flags) | copy as-is |
| `run.sh`, `shot.sh`, `frames.sh`, `game_slot.sh` | Timed run + symbolized stack; window screenshot at frame N; frame dumps; memory/launch gating for parallel instances | copy; rename binary/prefix |
| `test_*.py/.c/.m/.sh` | `test_lift.py` (Unicorn diff; `--synth` needs no game files), `test_simd.py`, `test_translate.sh` (Maxwell fuzz vs REF), `test_shaders.*`, `test_astc.*`, `test_vk_pipelines.*`, `test_nxpkg.sh`, `test_lse.c`, `test_moltenvk.sh` | copy as-is |
| `fetch_zig.sh`, `*/dev_deps.*`, `eowgen.spec` | zig/clang fetch, per-OS dev deps, PyInstaller spec for the on-user-machine generator | copy; rename spec |
| `dbgfs.sh`, `bandmetric.py`, `sampletree.py`, `montage.sh` | Debug/analysis helpers | copy as-is |

## runtime/ — the Horizon + NVN replacement

Copy wholesale, then adapt the listed files:

| File | Role | Per game? |
|---|---|---|
| `rt.h` | Guest address-space window, TLS/HLE-heap/alias/game-heap layout | **adapt** (window, heap size) |
| `modules.h` | `GAME_MODULES(X)` name:base list — rtld load order = symbol lookup order | **adapt** (from inventory) |
| `loader.c` | NSO decompress + relocate + import binding (host HLE → guest syms → stub) | adapt (module list) |
| `main.c` | rtld's job: `nn::init::Start` + init callbacks; `main.npdm` thread config | adapt (Start signature/SDK) |
| `dispatch.c` | Guest addr → recompiled fn (binary search + per-thread cache), `HLE_FUNC` registry, `guest_call`, backtraces/watchpoints | copy as-is |
| `kernel.c` | ~43 SVCs: threads, Horizon mutex/condvar, events, sync waits, memory, GetInfo/QueryMemory, 19.2 MHz ticks | **adapt** (title ID, new SVCs) |
| `ipc.c`, `services/` | CMIF+TIPC codec, domains; `acc`, `fsp-srv`, `applet`, `apm`, `lm`, `audren/out`, `time`, `hid`, `set`, `pctl`, `aoc` + logging stub | extend per game log |
| `hle/` | `nn::vi`/`nv`, `hid`→SDL, `pl` fonts, `swkbd`, `movie` (FFmpeg), `nvn_boot`, engine heaps/frame pacing/input; `hle_symbols.txt` (generation-time sdk replacement list) | adapt (engine parts are per-game) |
| `nvn/` | High-level NVN reimplementation: `objects.c` (516 fns), `cmdbuf.c` (`CmdRec` in guest memory), `tegra.c` (block-linear), `astc.c`, `formats.c`, `maxwell/` (binary→MSL→GLSL), `vulkan/` backend, upscalers/SMAA | copy as-is, extend |
| `nxpkg.c` | Runtime package reader: NSP/XCI/NCA, AES-CTR/XTS, LZ4, BucketTree — powers `romfs.src` | copy as-is |
| `platform/`, `ui/` | Memory reserve, crash handler, backtrace per OS; ImGui menu, launcher, touch | copy as-is |
| `gamelib.c`, `gamebuild.c`, `cpu.h`, `simd*.h` | Game-lib load/id check; on-user-machine codegen+build; CPU state; SIMD backends | copy as-is |

## Mechanical renames (do early, deliberately)

Binary name (`eowrecomp`), game lib (`eowgame` → `<name>game`), settings ini (`eowrecomp.ini`),
env prefix (`EOWRECOMP_` → `<PREFIX>_` in runtime + tools scripts), `android/` app id if ported.
Grep for leftovers; keep `EOW_RUNTIME`/`EOW_METAL`-style internal defines consistent.

## Not to copy

`extracted/`, `generated*/`, `build/`, `save/`, `cache/`, `*.ini` with real settings,
`docs/screenshots/` of the old game, `tools/venv/`, `__pycache__/`.
