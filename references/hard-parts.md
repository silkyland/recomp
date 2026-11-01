# Known hard parts

Distilled from EoWRecomp's `docs/STATUS.md` and `docs/HANDOFF-freeze.md` — the bugs that cost real
sessions, and the tools reported to have cracked them. Sections 8–13 come from a 2026-11-01 web
survey of nxnative, Ryujinx and yuzu/Eden sources (search excerpts, not fetched code). The source
revision for these local reports was not supplied: treat them as investigation leads, not verified
universal behavior. Confirm constants, flags, structures and semantics in the pinned base and
relevant source. Substitute your env-var prefix for `EOWRECOMP_`.

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

## 8. Reference codebases — clone before you need them

- **[nxnative](https://github.com/seedds/nxnative)** (MIT) — ARM64→ARM64 rewriter + Horizon HLE +
  NVN→Metal; 100+ playable games. Not our lineage, but its documented bug list transfers directly.
  Highest-value reads: `docs/reference/{nvn-objects,rendering}.md`, `dm/games/*/README.md`,
  `dm/gfx/nvn/{hle_nvn.c,nvn_mtl.m}`, and `nxnative:`-marked patches in its vendored Ryujinx
  shader translator.
- **A Ryujinx mirror** — `src/Ryujinx.Graphics.Vulkan/` (`PipelineBase.cs`, `TextureView.cs`,
  `DescriptorSetUpdater.cs`, `BarrierBatch.cs`) for feedback loops and barriers; `OpCodeTable` /
  `InstEmitTexture.cs` for battle-tested Maxwell decode+emit; `BindlessElimination.cs` for
  bindless rewriting.
- **yuzu/Eden** — `shader_recompiler/frontend/maxwell` (opcode table + per-op impl);
  Eden `docs/NvidiaGpu.md` (SASS bit-pattern table: TEX.B `1101 1110 10--`, TLD4.B `…11--`,
  TLD4S `1101 1111 -0--`, TMML `1101 1111 0101 1---`, TXA `1101 1111 0100 0---`,
  TXD `1101 1110 00--`, VMAD `0101 1111`); `tools/maxwell-disas` / `tools/maxwell-spirv`.
- **envytools** `envydis -m gm107` — definitive encoding tables; NVIDIA's CUDA Binary Utilities
  doc for the mnemonic list.
- Same-lineage recomps worth diffing when stuck: totk-pc-recomp, totk-recomp, SavageWindRecomp,
  SkyRecomp (LASRecomp-derived, Vulkan); kirikae (generic NSO/NRO→obj lifter, Rust/Cranelift).
  Aggregators: recomp.gg/c/switch, fangamesdb.com/recomps.html, decompdex.com.

## 9. Texture feedback / self-sampling — Switch semantics are *pre-draw*

`NV_texture_barrier` ground truth: same-attachment read+write is defined only for disjoint texel
sets or draws separated by `TextureBarrierNV()`; hardware observed to return the content from
**before** the draw. Three documented host strategies:

- **`VK_EXT_attachment_feedback_loop_layout`** (Ryujinx PR #7226): all renderable images get
  `ATTACHMENT_FEEDBACK_LOOP_BIT`; detected bound-feedback → `FeedbackLoopAspects` +
  `VkPipelineAttachmentFeedbackLoopCreateInfoEXT`/dynamic state. Cheap and correct on the API
  level, but yields raster-ordered (newer) content — **wrong semantics** when the shader expects
  pre-draw data.
- **yuzu/Eden**: `TextureCache::CheckFeedbackLoop` — any bound-for-sampling view whose `image_id`
  equals a bound attachment → `RequestOutsideRenderPassOperationContext` (end pass, barrier,
  resume). Detection lives in `GraphicsPipeline::ConfigureImpl`.
- **Snapshot copy** (nxnative `fb_prepare`): for listed shaders, end the pass, copy the attachment
  level+layer into a snapshot texture, bind the snapshot. Binding scan covers combined slots
  0–127 and separate slots 128–255.

Verdict: keep cheap per-draw *detection* (sampler image ∈ attachments, yuzu-style), and resolve
with snapshot-copy or pass-split for faithful pre-draw content. Profile-list the shaders that
actually self-sample rather than paying a barrier for all.

## 10. Bindless textures (TIC/TSC)

- Handle packing (yuzu `texture.h`): `tic_id` bits 0–19 | `tsc_id` bits 20–31 →
  `(tex & 0xFFFFF) | ((samp & 0xFFF) << 20)`. `nvnDeviceGetTextureHandle` returns the packed u32;
  `nvnDeviceGetSeparateTextureHandle`/`…SamplerHandle` return the halves.
- `nvnTexturePool`/`nvnSamplerPool` are GPU-memory buffers bound per command buffer; a TIC entry
  is 0x20 bytes. Emulators translate `tic_base + index * sizeof(TICEntry)` → host view+sampler;
  a recomp can do the same or keep a host-side handle→slot LUT.
- SASS side: non-bindless `TEX imm` uses a ~13-bit word offset into the texture-handle cbuf (CB2);
  bindless `TEX.B` takes the handle in a register — computed via ISCADD/LOP3/SULD chains, vertex
  attributes or SSBO loads, which is the case naive translators miss.
- Ryujinx's three-tier strategy, cheapest→general:
  1. **BindlessElimination** — pattern-match `LDC cbuf2` + `OR` combine → rewrite to a bound
     `(cbufSlot, wordOffset)` access; fallback zero dest + delete.
  2. **BindlessToArray** — handle = `LDC cbuf2[constOffset + i*4]` → indexed sampler array backed
     by a host `ITextureArray` sized `min(ArrayLength, pool.MaximumId+1)`.
  3. **True bindless** — only when the handle arrives via shader input: separate texture+sampler
     descriptor arrays indexed by TIC/TSC id, combined via `nonuniformEXT` indices.
- nxnative's translator patches carry these further: bindless handles through **phi nodes**, and
  non-constant TLD4.PTP gather offsets must be `OpCompositeConstruct`ed — same constraint as a
  GLSL const-offset workaround.
- Rule: an unknown handle → diagnostic color, never a silent black/white sample. A `btbl[]`+`bmap[]`
  SSBO plan ≈ Ryujinx tier-3 and is sound; add tier-1 pattern matching for the common `LDC` case.

## 11. NVN command-buffer semantics

- **Per-stage programs**: `NVNshaderStageBits` = VS 0x1, FS 0x2, GS 0x4, TCS 0x8, TES 0x10,
  CS 0x20, ALL_GRAPHICS 0x1F. `nvnCmdBufBindProgram(cmd, prog, mask)` merges prog's stages into
  the masked slots; `NULL` **unbinds** them. Games do bind `vertex|fragment` then `null,fragment`
  to issue VS-only draws — a "no program bound" draw drop once silently lost ~140 draws in
  nxnative. Composite state across binds (a mask→slot map plus a composite-pipeline cache keyed
  on per-stage program pointers), and log dropped draws as their own diagnostic.
- **Recorded-memory patching**: some engines rewrite texture handles *inside recorded command
  memory* before submit (observed in an NLG-engine title patching a 32-bit handle from a job
  worker). Harmless if commands execute eagerly at record time; a record-and-replay design must
  re-read the patched memory at replay.

## 12. Maxwell texture-op semantics (extends §3)

| Op | Meaning | Host mapping |
|---|---|---|
| TEX / TEX.B | fetch, implicit LOD / bindless (handle in reg) | `texture()` / bindless LUT |
| TXD | explicit gradients (aoffi bit 35, nodep bit 49) | `textureGrad()` |
| TLD | texel fetch | `texelFetch()` |
| TLD4/B/S | gather4 incl. `.DC` depth-compare; `.PTP` per-texel reg offsets | `textureGather()`; non-const offsets → 4 single-offset gathers taking `.w` |
| TXQ(.B) | query dimension/type/samples/lod/wrap/border | `textureSize`, `textureSamples`, … |
| TMML(.B) | mip-map level (LOD query) | `textureQueryLOD()` → vec2 |
| TXA (0xdf40) | texture-access family; **unimplemented in yuzu AND Ryujinx**, semantics undocumented | approximate ≈ TEX; verify against captures |
| VMAD (0x5F) | video multiply-add: `(a*b)+c` on byte/half/word lanes, `.po`, `.shr7/.shr15`, sat | rare; often sits in never-bound GS/TCS/TES stages |

Integer render targets: a deferred-renderer FS writes **bit-packed integers** — host shader
outputs must be typed `ivec4`/`uvec4`/`vec4` *per attachment format* (one table keyed on render-
target kind). nxnative typed everything float → Metal rejected every pipeline → every scene draw
skipped. Same failure mode on Vulkan, quieter: wrong output type → wrong bytes, not a compile error.

## 13. Color/gamma — triaging "washed/pastel"

Two independent places to get gamma wrong, with opposite symptoms:

1. **Render**: `nvnTextureViewSetFormat` overrides (e.g. RGBA8 texture + RGBA8_SRGB view → GPU
   encodes linear→sRGB on write). Ignoring overrides → darker/oversaturated. Encoding twice →
   lifted midtones = washed/pastel. Create images `MUTABLE_FORMAT`-capable and honor the view
   format, not just the base format.
2. **Present**: the window texture was stored via the sRGB view, so scanout must sample it
   **byte-verbatim through a non-sRGB view** into a UNORM swapchain image (Ryujinx uses UNORM +
   SRGB_NONLINEAR). A `_SRGB` present view or blit target double-converts → washed out.

Suspect order for "pastel": `_SRGB` swapchain/blit → ignored `TextureViewSetFormat` overrides →
sRGB sources sampled via UNORM views (milky lit scenes) → PNG readback byte order → premultiplied
vs straight alpha → int-vs-float output packing (a hue shift like gold→green is *not* gamma) →
vertex attributes flagged sRGB.

Instrumentation: dump the presented texture's raw bytes through a UNORM view, and compare against
a window photo and the PNG frame dump — that separates "the game wrote wrong bytes" from
"readback/present mangled them" without theorizing.
