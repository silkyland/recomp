# Known hard parts

Distilled from EoWRecomp's `docs/STATUS.md` and `docs/HANDOFF-freeze.md` — the bugs that cost real
sessions, and the tools reported to have cracked them. The source revision for these local
reports was not supplied: treat them as investigation leads, not verified universal behavior.
Confirm constants, flags, structures and semantics in the pinned base and relevant source. Substitute your env-var prefix for `EOWRECOMP_`.

## 1. Horizon mutex/condvar semantics (SVC layer) — the #1 source of freezes

Horizon's arbitration is *not* pthreads semantics. `kernel.c` implements `ArbitrateLock`,
`WaitProcessWideKey(Atomic)`, `SignalProcessWideKey`, `WaitForAddress`/`SignalToAddress` on top of
host primitives, and getting the edge cases wrong produces rare, racing deadlocks — not crashes.

- `WaitProcessWideKeyAtomic` on **timeout must re-acquire the mutex** the way Horizon does; the
  EoWRecomp bug where it didn't re-acquire froze the main thread after ~1200 frames.
- The CONDVAR→WAIT_MUTEX waiter conversion is the subtle case: a waiter whose signal was consumed
  but that then **times out waiting on the mutex queue** can lose the wakeup entirely → an enqueued
  task nobody runs. Compare against Atmosphere's kernel source, not pthread intuition.
- `svc_signal_process_wide_key(count)`: a "woken" waiter that fails to grab the mutex may still
  count toward `count` — count=1 + a lost timeout = stranded work.
- Symptom signature of a *guest* deadlock: every guest thread parked (cv waits, event waits,
  `std::future::get`), **all mutex words = 0** (nobody holds a lock), host threads alive and idle
  (vsync ticking, GPU workers idle, zero threads inside a host call). If a future's
  `__assoc_sub_state.__state_` = 1 (constructed, not ready) the task was never delivered.

## 2. Debugging a guest deadlock

- `<PREFIX>_WATCHDOG=<ms>` — when no frame presents, dumps per-thread: wait kind + address, the
  mutex word, guest x29 frame chain, sync handles with type/signaled, last cv/event signals
  matched to waited keys. `<PREFIX>_WATCHDOG_STOP=1` raises SIGINT for a supervising gdb.
- Start the game **under gdb** — `ptrace_scope` often prevents attaching later; SIGINT it.
- `<PREFIX>_TRACE_HND` (handle alloc/close), `TRACE_SIG` (signal/wait svcs), `TRACE_MAIN` (main
  thread svcs) — gate them behind env vars and *keep them*; races escape heavy logging sometimes.
- Heavier logging changing the outcome is itself diagnostic: it serializes the race.
- Rule out before theorizing: handle-slot reuse, signal-vs-timeout windows, tasks queued to exited
  threads, event handles consumed normally (check the live object, not just the number).

## 3. Maxwell shader translation (`runtime/nvn/maxwell/`)

NVN shaders ship as Maxwell binaries (NVN header + SPH + code) → translated to MSL, then rewritten
to GLSL, then compiled to SPIR-V with shaderc (disk-cached). Each miscompile is a *visual* artifact.

- **Register-index clobbering**: `LDC.64 c[idx][Ra+imm]` emitted two loads re-reading `Ra`; when
  `Rd == Ra` the first write corrupted the index → garbage offset → stretched triangles (a dark
  vertical band from a skinned character — the second bone's matrix row). Save the index first.
- **`FLO` semantics** (`.SH`/`.INV` forms): verify bit-scan direction, result encoding
  and signed/inverted edge cases from the instruction implementation; do not infer them from
  the mnemonic. A wrong result made a per-light loop
  over-iterate → the dominant fullscreen pass cost. FLO's edge cases (no bit set) matter.
- Structured loops in shader control flow need real structuring, not naive labels.
- Newer NVN compute shaders have a **0x100-byte header** before code — check before decoding.
- Missing ops seen: BFE.BREV, HSETP2/HSET2 immediates, VOTE, RED (incl. signed min/max → CAS loop
  in GLSL), LEA.HI, SUST storage images, `INC/DEC`.
- **Fuzz, don't sample**: `tools/test_translate.sh` diffs every shader's translation against a REF
  build (e.g. `REF=HEAD`) and compiles/validates the GLSL — it caught a regression class that
  looked fine on the one tested shader. MoltenVK adds a wrinkle: helper names colliding with Metal
  builtins (`popcount`, `clz`, `fmin`) — prefix helpers (`mw_*`).

## 4. Memory layout / `GUEST_SHIFT`

- Guest addresses **are** host addresses: the example runtime reserves a fixed window
  (`0x7000000000`–`0x7320000000` in EoWRecomp) at process start and re-execs if it's taken. `LD64`
  is a plain pointer dereference — fast, but means layout bugs are immediate memory corruption.
- `main`'s image can exceed its slot: pick `modules.h` spans from *measured* image sizes
  (`nso.py`), and size the game heap (`rt.h`) for the game, not the previous one.
- Android/some drivers need `gen.py --shift` + `GUEST_SHIFT` — all generated address math shifts;
  keep it consistent across generator, loader, dispatcher.
- `NvNsamplerBuilder`/`NVN*Builder` sizes are **per-NVN-version** — an oversized host struct
  overwrote the game's own stack bytes. Check the SDK version's real sizes, don't trust fields.

## 5. Versioning — everything is per build ID

- Patch addresses, HLE overrides, `GetInfo` results, hard-coded struct offsets: valid **only** for
  the pinned module build IDs recorded in STATUS.md. A game update invalidates all of them.
- `patches.py`'s `expect()` asserting the original instruction word is what saves you: a wrong
  address or wrong build **fails generation loudly** instead of silently miscompiling. Never remove
  or weaken `expect()` — fix the address.
- `hle_symbols.txt` and address-based overrides in `dispatch.c` have the same exposure.

## 6. Generation/lifting subtleties

- **Jump tables** (`br xN`): `gen.py` emulates the sequence with Unicorn per index; tables it can't
  resolve fall back to a `switch` over *every* instruction in the function — correct but huge and
  slow. Count the fallbacks (`main` in EoW: 71 resolved vs 1832 fallback) and improve patterns.
- Function splitting: branches out of a function become new functions; jump tables inside *split*
  functions need the same treatment or `VFormatString`-style code miscompiles.
- Exclusive pairs/LSE atomics appear in `sdk` on newer SDKs even when `main` is clean — check the
  census of every module. Unicorn itself has bugs (unsigned compare on 8/16/32-bit LDSMAX/LDSMIN):
  verify against real ARM64 hardware (`test_lse.c`).
- `GAMELIB_ID` staleness after a failed build → "built for another version" — delete the stale
  objects (`build/rt/gamebuild.o`, `gamelib*.o`), don't chase the runtime check.

## 7. Extraction gotchas

- `nca_extract.py` exists because the local extension reportedly needed to read RomFS sections stored through the BucketTree
  compression layer (LZ4 blocks, firmware 12+). Layout: AES-CTR section → IVFC/SHA-256 hash layers →
  CompressedStorage → RomFS/PFS0; compression table offsets are relative to the hash layers' data
  region. Atmosphere's `fssystem` + Switchbrew's NCA page are the references.
- Check container bounds, section sizes, hashes and decompression results. Truncation may fail
  at different stages; ExeFS/RomFS placement is container-specific.
- Rights-ID/titlekey crypto support depends on the extractor. Determine it from the selected
  implementation; the package format alone does not establish the encryption mode.
- `romfs.src` embeds the absolute package path + section keys → `extracted/` is machine-local and
  must never be committed (also why it can't be shared between machines).
