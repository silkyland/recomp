# The recompilation pipeline, stage by stage

Adapted from EoWRecomp's `docs/ARCHITECTURE.md` + `docs/STATUS.md`. Commands assume the layout
`init_project.sh` produces (`tools/venv` created, `extracted/` untracked, project root = cwd).
Substitute your own env-var prefix for `EOWRECOMP_` and your binary name for `eowrecomp`.

Overall shape:

```
package (.nsp/.xci) ─extract─> extracted/exefs (NSOs + main.npdm) + extracted/romfs*
exefs/<module> ─tools/gen.py─> generated/<module>/*.c ─clang─> <game>.{so,dll,dylib}
runtime ─> reserves guest address window, loads NSOs, relocates, dlopen(<game>lib) ─> nn::init::Start
```

---

## Stage 0 — legal setup (do this before anything else)

- Ask the user where their package and `prod.keys` live. They must be **outside the new repo** —
  e.g. `~/Games/dumps/`, never `repo/dumps/`. Open read-only; never copy in.
- If you can't find them, **ask**. Do not search the web, do not suggest how to obtain them.
- Scaffold the repo and install the `.gitignore` (`templates/gitignore`) **before the first
  commit**. Verify with `git status --ignored` — dumps, keys, `extracted/`, `generated/` ignored.
- Package formats:
  - `.nsp` / `.nca` — `nca_extract.py` reads in place, nothing copied out.
  - `.nsz` — decompress first: `nsz -D --keys <prod.keys> game.nsz` (needs keys even to decompress).
  - `.xci` — `nca_extract.py` does **not** read XCI containers: extract the program NCA first
    (`hactool game.xci`, secure partition), then point the tool at the `.nca`. Note: program NCAs
    with a rights ID (titlekey crypto, e.g. digital/eShop-only titles) are **not supported** by the
    tool — cart XCI/NSP program NCAs use the key area and work.

## Stage 1 — pin exactly one build

A recomp is per-game-**per-version**: every patch address, HLE offset, struct size assumption is
valid for one set of module build IDs only.

- Pick the version you will support (usually base game v0/1.0.0, or a specific update). Record in
  `docs/STATUS.md`: title ID, display version, SDK version, program-NCA name/size.
- `nca_extract.py --info` prints `title <id>`, `content type`, `sdk`, `key generation`, and each
  section's fs/hash/encryption/compression. If the title ID isn't what you intended — stop.
- **Truncated packages fail late**: the ExeFS and the RomFS compression table sit at the *end* of
  the program NCA. Check the file size against expectations first; the extractor refuses short
  files, but an incomplete copy wastes hours. (Real case: a 5.64 GB copy of a 5.81 GB NSP.)

## Stage 2 — extract

```
tools/venv/bin/python -I tools/nca_extract.py <prod.keys> <game.nsp|program.nca> extracted \
    --no-romfs --romfs-src
```

- Writes `extracted/exefs/` (the NSOs + `main.npdm`) and `extracted/romfs.src` — a small descriptor
  that lets the runtime read/decrypt/decompress RomFS straight from the package. Alternatives:
  `--romfs-image` (one `romfs.bin`, can be 8+ GB) or a full `extracted/romfs/` tree (no flags).
- Gate: `exefs/` contains at least `main`, `main.npdm`, `rtld`; typically `sdk` and `subsdk*`.
  If an NSO's LZ4 segments won't decompress or the NCA isn't NCA3 — stop, fix extraction first.

## Stage 3 — module inventory (measure, don't guess)

```
tools/venv/bin/python -I tools/nso.py extracted/exefs/*        # per-module: build id, image size, imports/exports
tools/venv/bin/python -I tools/analyze.py extracted/exefs/main --census
tools/venv/bin/python -I tools/inventory.py extracted/exefs --lift > docs/GAP.md
```

You learn: each module's build ID and image size (→ guest base addresses and spans), which module
exports which imports (`main` imports from `sdk`, `subsdk*`, sometimes unresolved), how many `nvn*`
entry points the game names vs the runtime implements, which HOS service name strings appear, which
SVC wrappers exist in `sdk`, and (`--lift`) which instructions the lifter can't handle yet.

Then adapt the address layout in **`runtime/modules.h`** — order is rtld's load order
(`main, subsdk*, sdk`), bases are fixed guest addresses; each span must fit that module's image
(real case: a 64 MB+ `main` pushed `sdk` to a higher base). `runtime/rt.h` holds the whole guest
window (`0x7000000000`–`0x7320000000` in EoWRecomp) and heap region — size the heap for the game.
Android/ASLR-constrained ports may need `GUEST_SHIFT` / `gen.py --shift`.

Write the module table (name / build ID / file size) into `docs/STATUS.md` — it is the authority
for "which build these addresses are for".

## Stage 4 — M1: all game code recompiles to C

```
make gen        # per module: gen.py <name> extracted/exefs/<name> <base> generated/<name> \
                #          --hle runtime/hle/hle_symbols.txt --simd c|asm
```

- `gen.py` discovers functions (`.eh_frame_hdr`, `STT_FUNC` syms, `R_AARCH64_RELATIVE` targets,
  `BL`/`ADR`/`ADRP` targets, iterated to a fixpoint), resolves `br xN` jump tables by Unicorn
  emulation per index (fallthrough + taken forms), and emits chunked C (`<module>_NNN.c` +
  `<module>_table.c`). Functions are `void f_<addr>(Cpu *c)`; direct calls are C calls, external
  jumps `musttail`, indirects go through `rt_dispatch`.
- `lifter.py` turns AArch64 into C: integers/memory/flags become C; FP/SIMD becomes host ARM64
  inline asm (`--simd asm`) or portable C requiring AVX2+FMA (`--simd c`, compile generated code
  with `-march=x86-64-v3` — with zig's clang spell it `-mcpu=x86_64_v3`).
- **Gate: 0 `Unsupported`.** Every unsupported encoding is implemented in `lifter.py` — not stubbed
  — and tested: `tools/test_lift.py <nso> <base>` (differential vs Unicorn) or `--synth` on machines
  without the game files. Common gaps on newer SDKs: exclusive **pairs** (LDXP/STXP/LDAXP/STLXP) and
  LSE atomics (CAS/CASP/SWP/LDADD…) — the `sdk` uses them even when `main` doesn't. Cross-check
  against real hardware when Unicorn itself is wrong (it miscompares LDSMAX/LDSMIN unsigned on
  ≤32-bit sizes; `test_lse.c`).
- `--hle hle_symbols.txt` lets host HLE replace *internal* sdk functions at generation time.

## Stage 5 — M2/M3: boot, services, first frame

- **Loader**: `loader.c` decompresses each NSO into its guest base, applies RELA/JMPREL relocs.
  Imports resolve host-HLE first (`HLE_FUNC("symbol")` registered via a linker section in
  `dispatch.c`), then guest exports; leftovers become "UNIMPLEMENTED" stubs that log and return 0.
- **Start**: `main.c` does rtld's job — calls `nn::init::Start` in `sdk` with callbacks that run
  each module's `DT_INIT`/`init_array`. **The `Start` signature varies by SDK version** (EoWRecomp:
  3 callbacks on SDK 16.2). Main-thread priority/stack come from `main.npdm`.
- **Kernel** (`kernel.c`): ~43 SVCs — threads on pthreads (priority/affinity recorded only),
  Horizon mutex/condvar (`ArbitrateLock`, `WaitProcessWideKey`), `WaitForAddress`/
  `SignalToAddress`, events, `WaitSynchronization`, memory ops, `GetInfo` (patch title ID there),
  `QueryMemory`, 19.2 MHz ticks. Unimplemented SVCs abort loudly — implement as the game hits them.
- **IPC** (`ipc.c` + `services/`): CMIF domains + **TIPC** (`sm:` has used TIPC since SDK 12 —
  confirm on your SDK). Services get HLE as the game opens them; unknown ones hit a stub that logs
  `[ipc] no HLE implementation` — the log is your roadmap.
- **NVN bootstrap**: `hle/nvn_boot.c` implements `nvnBootstrapLoader`/`nvnDeviceGetProcAddress`.
- Gate: a presented frame (any pixels) — use the hidden-window + screenshot env vars, don't stare
  at a black screen and guess.

## Stage 6 — M4: first *correct* image

The classic bugs, all seen in EoWRecomp: builder structs sized differently per NVN version (an
oversized `NVNsamplerBuilder` scribbled over the game's stack — check the SDK's real sizes), Z-cull
with size 0, command-memory shadow sizing, 0x100-byte header on newer compute shaders, Tegra
block-linear texture layout (`tegra.c`), ASTC software decode, and **Maxwell shader translation**
bugs (`nvn/maxwell/translate.c`) — each miscompile looks like a *rendering* artifact, not a crash.
Verify with frame captures and the Maxwell fuzz harness (`test_translate.sh`); see
`references/hard-parts.md`.

## Stage 7 — M5…M7

- **M5**: title screen, audio, input, first controllable scene. Input via `hid`/`hid:sys` services
  backed by SDL; verify with **scripted input** (`<PREFIX>_INPUT="frame:BTN:duration,..."`) so the
  game drives itself to the scene you're checking.
- **M6**: playable start-to-finish, saves round-trip, audio verified by ear, performance measured
  (`<PREFIX>_VK_PROF`, `<PREFIX>_GPUPROF_AT`, `<PREFIX>_SKIP_FSHASH` for shader cost bisection).
- **M7**: PC features — free resolution/aspect, unlocked fps, remapping, platform button icons.
  Engine-specific HLE (heaps, frame pacing) is per-game work: find addresses, patch via
  `patches.py` + `expect()`.

## The verification loop (use constantly)

- `tools/run.sh` — timed run (SECS=N), scratch save dir, log to `build/run.log`, then prints a
  **symbolized guest stack** via `symgame.py` (`<game>lib.so+<off>` → `f_<addr>` → `nm`/`sym.py`
  demangled name). Keep `game_slot.sh`'s memory gate if you run parallel copies — each instance
  can take ~2 GB+.
- Screenshots: `<PREFIX>_SHOT_AT=300,600,900` → `build/frames/`; `tools/shot.sh <frame>` grabs one
  window shot and exits.
- Freezes: run under `gdb` from the start (ptrace_scope may block late attaches), send SIGINT; the
  **watchdog** (`<PREFIX>_WATCHDOG=<ms>`) dumps every guest thread's wait state, mutex words, x29
  chain and sync handles when no frame presents — `<PREFIX>_WATCHDOG_STOP=1` raises SIGINT for the
  supervisor. `references/hard-parts.md` has the full deadlocked-state field guide.
- Tests to keep green: `test_lift.py` (lifter vs Unicorn), `test_translate.sh` (Maxwell→GLSL fuzz),
  `test_simd.py`, `test_shaders.*`, `test_astc.*`, `test_vk_pipelines.*`, `test_nxpkg.sh` (package
  crypto/LZ4 vectors).
- Every fix: find the root cause (Capstone, logs, Switchbrew, envytools, Atmosphere source) — never
  paper over. Say which GPU backend you verified on.
- **Stale-build trap**: a failed `make` can leave `gamelib`/`gamebuild` objects with an old
  `GAMELIB_ID` → "game library was built for another version" — delete those objects and rebuild.

## Per-game adaptation checklist (what `init_project.sh` cannot do for you)

- `runtime/modules.h` bases/spans (from the inventory), `runtime/rt.h` window/heap sizes.
- `GetInfo` title ID, `main.npdm` handling if the game needs different thread config.
- `tools/patches.py` — starts **empty**; add sites only after root-causing, always via `expect()`.
- `runtime/hle/` engine specifics (heaps/input/framepace/bindings) — addresses differ per game.
- Services/NVN gaps from `docs/GAP.md`, in the order the game's log actually hits them.
- Rename pass: binary name, game-lib name, `.ini` name, and the env-var prefix — mechanical but
  broad; do it deliberately early, then grep for leftovers.
