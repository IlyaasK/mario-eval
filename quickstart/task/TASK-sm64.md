# Super-optimize Super Mario 64 for real Nintendo 64 hardware

`/task/game` is the complete US decompilation of **Super Mario 64** (`n64decomp/sm64`),
wired to the `mario-eval` deterministic frame harness (`src/game/mev.c`,
`src/game/mev.h`). By default it builds with SGI IDO at `-g`/`-O1`, triple-buffers
three 150 KB framebuffers, thrashes the 8 KB D-cache with 64 KB trig lookup
tables and pointer-chasing `SurfaceNode` collision lists, uploads unculled
skybox tiles and unbatched TMEM blocks, uses naive matrix math and scene-graph
traversal, and leaves massive VR4300 CPU, I/D-cache, RSP, RDP, RDRAM bus, and
4 MB RAM wins on the table.

Your job over this 24-hour run is to super-optimize Super Mario 64 for the
original 4 MB Nintendo 64 hardware — the kind of deep hardware-aware engineering
pioneered by Kaze Emanuar and cracked N64 systems programmers — **without
changing the game the player experiences**.

The GCC `-O2 -fno-fast-math` reference is about **1.38×** vanilla on the six
public routes. Grading builds `/task/game` with `make VERSION=us COMPARE=0 NOEXTRACT=1`:
you may edit `Makefile` (including `COMPILER`, `OPT_FLAGS`, and `GRUCODE`), linker
scripts, C source, and MIPS assembly — everything except the protected harness
files (`src/game/mev.c`, `src/game/mev.h`). Vanilla starts CPU-bound, but once CPU time drops (even at
`-O2` or after early CPU wins), Fast3D RSP (`bob`, `rr`) and RDP fillrate
(`jrb`) become active bottlenecks, and RCP RDRAM traffic directly contends
with CPU cache refills. Start with CPU and cache profiling; remeasure after
each milestone and optimize whichever subsystem limits the resulting frame
time. This model is not a hardware measurement.

## Objective

Your submission is scored **solely** on one primary resource profile, named in
`/task/PROFILE` (default: `console`). All seven profiles are measured and reported
for diagnostics; another profile's budget (such as `memory`'s 0% footprint limit)
never fails your primary profile:

For `console`, maximize the game's capacity to render frames at unchanged
quality, simulation cadence, and controls. Aim for a frame budget of **6.94 ms
(144 FPS equivalent)** or better across courses, including busy scenes. That
is a work budget, not a claim that actual N64 video output can display 144 FPS.
Optimize the limiting subsystem and report sustained and slow-frame timing.

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
- Replacing D-cache-thrashing trig lookup tables (`gSineTable`, `gArctanTable`)
  with register-only minimax/folded polynomials that return the tables' exact
  values (one ULP off is not enough: it drifts Mario, the camera and sound
  panning until unscripted input fails a gate);
- Rewriting `surface_collision.c` / `surface_load.c` with flat cache-friendly
  structures, Y-bounds/AABB pre-filtering, finer spatial grids, and stationary
  floor caching that return the same winning surfaces;
- Hibernating physics/floor raycasts on distant off-screen objects far outside
  Mario's interaction radius and Lakitu's camera view *(careful: some actors rest
  in `oAction == 0` for 100+ frames before moving, so only hibernate genuinely
  distant actors and verify with `mev stress`)*;
- Balancing `-Os` vs `-O2` per file (GCC's `libgcc` is linked automatically) so
  hot code fits the 16 KB direct-mapped I-cache instead of blindly unrolling
  loops *(note: 16 KB direct-mapped I-cache set collisions can cause ±1–2% layout
  variance when code addresses shift; use `mev profile` I-cache conflict pairs to
  diagnose set collisions rather than misattributing them)*;
- Using VR4300 `CACHE 0x0d` (`Create Dirty Exclusive`) on 16-byte-aligned cached
  KSEG0 addresses (`0x80000000..0x9FFFFFFF` only — never KSEG1), optimizing
  `math_util`, `rendering_graph_node`, `audio`, Fast3D/RSP, RDP render
  modes/syncs/TMEM, and compacting RDRAM pools and framebuffers *(always keep
  CPU D-cache writebacks coherent before SP/DP DMA reads)*.

## Verification Gates (Player Equivalence)

Grading replays recorded controller inputs across courses and checks these gates:

- **Integrity & Playable Build** — `src/game/mev.c` and `src/game/mev.h` must
  be byte-identical, and **both** the graded build (`make VERSION=us COMPARE=0 NOEXTRACT=1`)
  and the real-time console ROM (`make VERSION=us COMPARE=0 NOEXTRACT=1 check-play`)
  must build and link. This does not validate physical-console behavior.
- **Execution & Hardware** — every course must complete all 240 frames within
  the 4 MB RDRAM ceiling (`0x00400000` bytes, no Expansion Pak).
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
  more than ±2/31 per channel from their best 3×3 neighbor. Do not extrapolate beyond
  those exact accepted policies (for example, `ra-zb-opa` covers `OPA_SURF` only, not
  `OPA_DECAL` or `OPA_INTER`). Watch the `vid%` column in `mev check`: a non-zero
  pixel drift that stays under 0.2% on the 6 public courses often exceeds 0.2% on
  held-out routes.
- **Audio** — overall SNR ≥ 40 dB against baseline, ≥ 20 dB on every
  non-silent frame (with a 40-band log-mel spectral + loudness fallback for tiny
  sub-millisecond phase shifts); a frame the baseline renders silent (RMS ≤ 64 of
  32768) must stay silent (candidate samples there ≤ 256).

Host grading also runs private held-out routes, unseen courses, and randomized
controller inputs. Never special-case public course IDs or remove subsystem
support (such as snow, desert, or lava effects) used in other courses.

## Tools

Your working directory is `/task/game` (the SM64 git repository).

```
mev build [--clean]       build /task/game (prints ROM sha256; use --clean after Makefile flag changes)
mev run jrb               run a public course; prints CPU/RSP/RDP/RDRAM breakdowns & vs-baseline speedups
mev run --all             run all 6 public courses in parallel (~10s; defaults to 120 frames — pass --frames 240 to match check)
mev profile bob           per-function CPU busy profile (idle excluded) with function sizes, D/I-cache misses,
                          data-symbol miss & writeback attribution, 16 KB I-cache conflicts, and RDP/RDRAM map
mev check                 full clean + PLAY=1 grader on all 6 public courses; prints per-course timings,
                          vid% drift, Δcon vs last check, and updates /tmp/mev-last-check/summary.json
mev check --play-smoke    full clean check + boots and verifies controller response on the PLAY=1 console ROM
mev check jrb --fast      fast incremental gate check on 1+ courses (~5s, skips PLAY=1 rebuild)
mev stress                local seeded button-mash stress test across all 6 courses (checks crashes, RAM, DMA coherence)
mev workloads             bob, wf, jrb, ddd, bitfs, rr
mev restore-assets        restore missing extracted SM64 assets offline without overwriting edits
```

Workflow tips:
- Use `mev check <course> --fast` or `mev run --all` for rapid iteration, and reserve plain `mev check` for verifying milestone commits.
- Always run `mev build --clean` (or `make clean`) after changing `COMPILER`, `GRUCODE`, or `OPT_FLAGS` in `Makefile`. Use `VERBOSE=1` (not `V=1`) to inspect compiler invocations.
- Keep a short scratch log at `/task/OPTIMIZATION_LOG.md` (outside `/task/game`) summarizing tried ideas, measured deltas, and confirmed invariants so context compactions never cause duplicate work.
- Always wait for `mev check` to finish before ending your turn — ending a turn with a backgrounded job kills the job. Never run overlapping `make`/`mev` jobs simultaneously.
- `make distclean` keeps extracted assets when `baserom.us.z64` is absent; if extracted assets are ever removed, run `mev restore-assets` before rebuilding. The task image does not contain the original ROM.

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
