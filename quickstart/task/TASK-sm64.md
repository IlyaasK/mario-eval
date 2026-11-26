# Super-optimize Super Mario 64 for real Nintendo 64 hardware

`/task/game` is the complete US decompilation of **Super Mario 64** (`n64decomp/sm64`),
wired to the `mario-eval` deterministic frame harness (`src/game/mev.c`,
`src/game/mev.h`). By default it builds with SGI IDO at `-g`/`-O1`, triple-buffers
three 150 KB framebuffers, thrashes the 8 KB D-cache with 22 KB trig lookup
tables (`gSineTable` 20 KB, `gArctanTable` 2 KB) and pointer-chasing `SurfaceNode` collision lists, uploads unculled
skybox tiles and unbatched TMEM blocks, uses naive matrix math and scene-graph
traversal, and leaves massive VR4300 CPU, I/D-cache, RSP, RDP, RDRAM bus, and
4 MB RAM wins on the table.

Your job over this 24-hour run is to super-optimize Super Mario 64 for the
original 4 MB Nintendo 64 hardware — the kind of deep hardware-aware engineering
pioneered by Kaze Emanuar and cracked N64 systems programmers — **without
changing the game the player experiences**.

The GCC `-O2 -fno-fast-math` reference is about **1.35×** vanilla on the six
public routes. Grading builds `/task/game` with `make VERSION=us COMPARE=0 NOEXTRACT=1`:
you may edit `Makefile` (including `COMPILER`, `OPT_FLAGS`, and `GRUCODE`), linker
scripts, C source, and MIPS assembly — everything except the protected harness
files (`src/game/mev.c`, `src/game/mev.h`). Vanilla starts CPU-bound, but once CPU time drops at
`-O2`, Fast3D RSP (`bob`) and RDP fillrate + RDRAM turnaround (`jrb` at ~31.4 ms RDP vs
27.2 ms CPU) immediately become active bottlenecks, and CPU/RCP RDRAM traffic
symmetrically contend on the shared RDRAM bus. Start with CPU and cache profiling; remeasure after
each milestone and optimize whichever subsystem limits the resulting frame
time. This model is not a hardware measurement.

## Objective

Your submission is scored **solely** on one primary resource profile, named in
`/task/PROFILE` (default: `console`). All seven profiles are measured and reported
for diagnostics; another profile's budget (such as `memory`'s 0% footprint limit)
never fails your primary profile:

For `console`, minimize `est_console_ms` across all courses, including busy
scenes, at unchanged quality, simulation cadence, and controls. **There is no
target cap or finish line**: `est_fps = 1000 / est_console_ms` is uncapped by
N64 30/60 Hz VI sync, so every microsecond of frame time you eliminate across
the full 24 hours directly increases your score. Re-profile after each win and
attack whichever subsystem (`CPU`, `RSP`, `RDP`, or `RDRAM`) limits frame time.

| profile   | what is reduced                                        | measured as |
|-----------|--------------------------------------------------------|-------------|
| `console` | **Real N64 frame bottleneck time (headline score)**    | Per-frame `est_console_ms` = `max(cpu_ms, rsp_ms, rdp_ms, mem_ms)` within 4 MB RAM |
| `stutter` | Worst frames (hitches the player feels)                | `est_console_p99_ms`, the 99th percentile of the same per-frame bottleneck |
| `speed`   | CPU time to simulate and build a frame                 | `cpu_effective_cycles` per frame (VR4300 cycles incl. cache/bus stalls) |
| `rdp`     | Reality Display Processor hardware busy time           | `rdp_busy` (RDP 62.5 MHz cycles: raster/fill/Z/TMEM/sync) |
| `rsp`     | Reality Signal Processor microcode busy time           | `rsp_busy` (RSP non-halted cycles per frame) |
| `traffic` | Total RDRAM bus traffic across all devices             | `rdram_bytes` read+written per frame (CPU, SP, DP, PI, SI) |
| `memory`  | Console RAM footprint                                  | `footprint_bytes` (distinct 16-byte RDRAM lines touched after boot) |

For each profile, `geo = geomean(yours / baseline)` over all courses:
- **Reward (log-scaled, unbounded above)**: `reward = max(-1, log2(1 / geo) / 4)` — 2× scores 0.25, 4× 0.5, 16× 1.0 (`0.0` unchanged); any failed gate, or an over-budget profile, scores `-1.0`.
- **Unbounded speedup**: `speedup = 1 / geo`, `log2_speedup = -log2(geo)`, and `vs_o2_speedup` (speedup beyond switching `COMPILER=gcc` `-O2 -fno-fast-math`, directly measuring genuine algorithmic & hardware optimization beyond the compiler).

Course budgets enforce honest hardware engineering. Each profile has a **profile budget** on its own metric (a course may not regress it) and a **cross-subsystem budget** (a course may not regress the other metric):
- `console` (`est_console_ms`) and `stutter` (`est_console_p99_ms`): ≤ **5%**; cross-subsystem `footprint_bytes` ≤ **5%** *(note: the 0% footprint cap applies ONLY to the `memory` profile, NOT `console`)*.
- `speed` (`cpu_effective_cycles`): ≤ **5%**; cross-subsystem `rdp_busy` ≤ **5%**.
- `rdp` (`rdp_busy`), `rsp` (`rsp_busy`), `traffic` (`rdram_bytes`): ≤ **5%**; cross-subsystem `cpu_effective_cycles` ≤ **5%**.
- `memory` (`footprint_bytes`): no course may regress it at all (**0%**); cross-subsystem `cpu_effective_cycles` ≤ **5%**.

## Hyrum's Law: Preserve 1996 Gameplay Quirks, Fix Engine UB

In Super Mario 64, movement quirks (Backwards Long Jumps, wall-kick angles,
quarter-step collision outcomes, slope physics) **are** the game. Do **not**
"bugfix" gameplay rules (such as replacing ray wall checks with rounded
cylinders or capping negative speed), because altering movement rules changes
where Mario lands on recorded controller replays and fails verification.

Conversely, internal engine rewrites that deliver the **exact same experience to
the player** are 100% encouraged (`NON_MATCHING=1` and `AVOID_UB=1` are enabled):
- Fixing C undefined behavior, uninitialized reads, or IDO workarounds;
- Hand-tuned MIPS III assembly (`__asm__` inline blocks, `.s` files under `src/` or
  `lib/rsp.s`, including 16-byte-aligned `CACHE 0x0d` `Create_Dirty_Exclusive` ops)
  and custom RSP scalar/vector microcode (`rsp/*.s`) — all fully permitted as long
  as real VR4300/RCP cache/DMA invariants and `PLAY=1` boot hold;
- Replacing D-cache-thrashing trig lookup tables (`gSineTable`, `gArctanTable`)
  with register-only minimax/folded polynomials (~1–3 ULP / `~1e-6` accuracy with
  exact cardinal quadrants `sins(0) == 0`, `coss(0) == 1`; SM64 grades
  player-equivalence tolerances rather than 0-ULP IEEE bit-identity to
  `trig_tables.inc.c`, though coarse `~1e-3` approximations drift Mario, Lakitu,
  and audio panning — verify with `mev check` and `mev stress`);
- Rewriting `surface_collision.c` / `surface_load.c` with flat cache-friendly
  structures, Y-bounds/AABB pre-filtering, finer spatial grids, and stationary
  floor caching that return the same winning surfaces *(watch memory limits:
  `sm64.ld` places `SEG_ENGINE` at `0x80378800` leaving <5 KB BSS before
  `0x8038F800` framebuffers while ~290 KB sits free below `0x80378800`,
  `alloc_surface_pools()` caps `sSurfaceNodePool` at `7,000` nodes, and growing
  `.bss` or `main_pool_alloc` by >32 KB can OOM larger held-out levels'
  `main_pool` even when `footprint_bytes < 3 MB`)*;
- Selectively skipping redundant per-frame work on distant off-screen objects
  *(warning: `ACTIVE_FLAG_FAR_AWAY` is a rendering draw-distance flag only — many
  actors, spawners, and ambient sound emitters sit stationary in `oAction == 0` or
  beyond 4,000–7,000 units and still affect gameplay, camera, or audio on other
  courses, so never blanket-skip `cur_obj_update` on `ACTIVE_FLAG_FAR_AWAY`)*;
- Shrinking cold/warm surrounding modules (`-Os` on `libultra`, menus, cold
  behaviors) while keeping hot inner loops at `-O2`/`-O3` (`libgcc` is linked
  automatically) so hot code fits the 16 KB direct-mapped I-cache instead of
  blindly unrolling loops *(notes: `Makefile` appends `-fno-inline-functions` by
  default, wraps its stock per-file `OPT_FLAGS` around line 745 inside
  `ifeq ($(COMPILER),ido)` and overrides `src/audio/*.o` later, and modern
  `mips64-elf-gcc` uses `--param max-inline-insns-*` rather than `-finline-limit`;
  use `mev profile` I-cache conflict pairs & set ranges to diagnose ±1–2% direct-mapped
  layout shifts)*;
- Using VR4300 `CACHE 0x0d` (`Create Dirty Exclusive`) on **16-byte-aligned** cached
  KSEG0 addresses (`0x80000000..0x9FFFFFFF` only, `(addr & 0xF) == 0` — never KSEG1
  and never unaligned `main_pool_alloc` / 8-byte pointers, both enforced by the
  hardware gate), optimizing `math_util` (`AVOID_UB=1` routes `mtxf_to_mtx` to
  `lib/src/guMtxF2L.c`), `rendering_graph_node`, `audio` (and `rsp/audio.s` via
  `armips`), Fast3D/`F3DEX2`, RDP render modes/syncs/TMEM, and compacting RDRAM
  pools and framebuffers *(note: Goddard's Mario head intro in `PLAY=1` boot smoke
  uses all three `gFramebuffers` in its intro heap; and `struct SPTask` only holds
  pointers to display lists/matrices/audio buffers, so replacing `osWritebackDCacheAll()`
  with `osWritebackDCache(spTask, sizeof(*spTask))` leaves the pointed-to buffers
  dirty in D-cache — always keep `PLAY=1` `dispatch_audio_sptask` / `send_sp_task_message`
  and `!PLAY` `exec_audio_sptask_sync` equally cache-coherent, and optimize shared
  functions like `synthesis_execute` rather than `#ifndef PLAY` glue)*.

## Verification Gates (Player Equivalence)

Grading replays recorded controller inputs across courses and checks these gates:

- **Integrity & Playable Build** — `src/game/mev.c` and `src/game/mev.h` must
  be byte-identical, baseline `#ifdef PLAY`/`#ifndef PLAY` benchmark glue blocks
  must not be modified, and **both** the graded build (`make VERSION=us COMPARE=0 NOEXTRACT=1`)
  and the real-time console ROM (`make VERSION=us COMPARE=0 NOEXTRACT=1 check-play`)
  must build, link, and pass boot smoke.
- **Execution & Hardware** — every course must complete all 240 frames within
  the 4 MB RDRAM ceiling (`0x00400000` bytes, no Expansion Pak), with zero
  uncached KSEG1 `CACHE` ops, zero unaligned `CACHE 0x0d` ops, zero KSEG1
  uncached reads/writes aliasing dirty D-cache lines, and ≤ 1.05 SP/DP DMA
  D-cache coherence errors per frame (vanilla has 0 RDRAM errors; stock `f3dex2`
  natively incurs 1.00 benign DMEM scratch read/frame — always write back dirty
  CPU D-cache lines before SP/DP DMA reads in both graded and `PLAY=1` builds).
- **Gameplay (Player Equivalence)** — `level_area`, `mario_stats` (health,
  coins, stars, lives), `mario_action` and the actor count must match on every
  frame; `mario_pos`, `mario_vel` and `mario_floor_height` must stay within
  **0.01** world units (Mario is 160 units tall), and `cam_pos` / `cam_focus`
  within **0.02**. Every actor within **2000** units of Mario must exist with
  the same action/state and a position within **0.1** units (order in the
  object lists does not matter). Internal PRNG state and farther actors are
  not checked, so hibernating distant objects is allowed; visible actors are
  also verified by the video gate. Drawing code must not change game state:
  some geo callbacks move objects (e.g. a held Spiny or a collision child), so
  culling an object vanilla draws can fail this gate.
- **Video** — every frame of a workload must match a single consistent reference
  (either the baseline picture or one accepted visual variant combination defined in
  `/opt/mario-eval/corpus/grader.json`: `full-detail`, `ra-zb-opa`, `f3dex2`, `no-lod`,
  `rr-statics`, or any combination of these): at most 0.2% of pixels may differ by
  more than ±2/31 per channel from their best 3×3 neighbor, AND motion-adaptive
  block-SSIM must stay ≥ 0.98 overall (≥ 0.85 worst frame). Do not extrapolate beyond
  those exact accepted policies (for example, `ra-zb-opa` covers `OPA_SURF` only, not
  `OPA_DECAL` or `OPA_INTER`; in `mev run`, `im_rd` measures RDP framebuffer
  read-modify-write cost eliminated on opaque surfaces by `G_RM_RA_ZB_OPA_SURF`).
  Watch `vid%` and `ssim` in `mev check`: a non-zero drift that stays under 0.2%
  on the 6 public courses often exceeds 0.2% on held-out routes.
- **Audio** — overall SNR ≥ 40 dB against baseline, ≥ 20 dB on every
  non-silent frame (with a 40-band log-mel spectral + loudness fallback for tiny
  sub-millisecond phase shifts); a frame the baseline renders silent (RMS ≤ 64 of
  32768) must stay silent (candidate samples there ≤ 256).

Host grading also runs private held-out routes, unseen courses, and randomized
controller inputs. Never special-case public course IDs, never assume static
world state (e.g. Wet-Dry World dynamically mutates `gEnvironmentRegions` water
levels at runtime, distant spawners/audio objects still matter, and draw
distances vary), and never remove subsystem support (such as snow, desert, or
lava effects) used in other courses.

## Tools

Your working directory is `/task/game` (the SM64 git repository).

```
mev build [--clean]       build /task/game (prints ROM sha256; use --clean after Makefile flag changes)
mev run jrb               run a public course; prints CPU/RSP/RDP/RDRAM breakdowns & vs-baseline speedups
mev run --all             run all 6 public courses in parallel (~10s; defaults to 120 frames — pass --frames 240 to match check)
mev profile bob           per-function CPU busy profile (idle excluded) with function sizes, D/I-cache misses,
                          data-symbol miss & writeback attribution, 16 KB I-cache conflicts, and RDP/RDRAM map
mev check                 full clean + PLAY=1 build + PLAY=1 boot smoke on all 6 public courses; prints per-course
                          timings, vid% drift, block-SSIM, Δcon vs last check, and updates /tmp/mev-last-check/summary.json
mev check --no-play-smoke full clean + PLAY=1 build check without PLAY=1 boot smoke
mev check jrb --fast      fast incremental gate check on 1+ courses (~5s, skips PLAY=1 rebuild)
mev stress                local seeded button-mash stress test across all 6 courses (checks crashes, RAM, DMA coherence)
mev workloads             bob, wf, jrb, ddd, bitfs, rr
mev restore-assets        restore missing extracted SM64 assets offline without overwriting edits
```

Workflow tips:
- Use `mev check <course> --fast` or `mev run --all` synchronously in the foreground (~5–10s) for rapid iteration, and reserve plain `mev check` for verifying milestone commits. Never background `mev` jobs or claim PASS before `Primary profile [...]: PASS` prints.
- **Never override `COMPILER`, `GRUCODE`, or `OPT_FLAGS` on the `make` command line or via exported env vars** — host grading always runs plain `make VERSION=us COMPARE=0 NOEXTRACT=1` with a clean environment. Edit `Makefile` directly and run `mev build --clean` (always run `mev build --clean` after editing `include/*.h` struct layouts or `sm64.ld`, and check `make -n VERBOSE=1 build/us/...o` when adding per-file rules). Legacy SGI `COMPILER=ido` is strict C90 and rejects `-Os`/`-O3`/`inline`; set `COMPILER := gcc` in `Makefile` to use modern GCC optimization flags.
- Keep a short scratch log at `/task/OPTIMIZATION_LOG.md` (outside `/task/game`) summarizing tried ideas, measured deltas, and confirmed invariants so context compactions never cause duplicate work.
- Always wait for `mev check` to finish before ending your turn — ending a turn with a backgrounded job kills the job. Never run overlapping `make`/`mev` jobs simultaneously.
- **`baserom.us.z64` is never present and never needed**: all US assets are pre-extracted in `/task/game` (`NOEXTRACT=1` is automatic; linker errors after switching compilers mean `build/` has mixed IDO/GCC `.o` files — run `mev build --clean`). If extracted assets are ever deleted, run `mev restore-assets` before rebuilding.

`mev run` and `mev check` measure CPU busy time the same way: the idle thread's
halt loop is excluded from CPU time and nothing else is, so an optimization
cannot buy free time by moving work into the idle function or renaming it.

Reference material: `/task/docs/n64-cost-model.md`. Both SGI IDO
(`tools/ido-static-recomp`) and `mips64-elf-gcc` are installed locally; there is
no internet access.

## Rules

- Do not attempt to detect the grader, replays, or emulator.
- Commit working milestones to the git repository in `/task/game` regularly so
  no progress is lost across checkpoints, and check `$MEV_DEADLINE_EPOCH`
  (seconds since epoch) so you leave a clean, `mev check`-passing tree before
  time runs out.
