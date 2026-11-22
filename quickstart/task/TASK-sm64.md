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

The GCC `-O2 -fno-fast-math` reference is about **1.39×** vanilla on the six
public routes. In the current cost model, vanilla is CPU-bound on those
routes. Start with CPU and cache profiling; remeasure after each milestone
and optimize whichever subsystem limits the resulting frame time. This
model is not a hardware measurement.

## Objective

Your submission is scored on **one primary resource profile**, named in
`/task/PROFILE` (default: `console`). All seven profiles are measured and reported:

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
- `console` (`est_console_ms`) and `stutter` (`est_console_p99_ms`): ≤ **5%**; cross-subsystem `footprint_bytes` ≤ **5%**.
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
  Mario's interaction radius and Lakitu's camera view;
- Balancing `-Os` vs `-O2` per file so hot code fits the 16 KB direct-mapped
  I-cache instead of blindly unrolling loops;
- Using VR4300 `CACHE 0x0d` (`Create Dirty Exclusive`), optimizing `math_util`,
  `rendering_graph_node`, `audio`, Fast3D/RSP, RDP render modes/syncs/TMEM, and
  compacting RDRAM pools and framebuffers.

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
- **Video** — every frame as a whole must match either the baseline picture or
  an accepted visual variant in `/opt/mario-eval/corpus/variants/`
  (`full-detail`: always high-polygon Mario instead of medium/low LODs;
  `ra-zb-opa`: SGI's `G_RM_RA_ZB_OPA_SURF` / `G_RM_RA_OPA_SURF` reduced-aliasing
  opaque modes without `IM_RD`; `f3dex2`: Nintendo's later F3DEX2 microcode;
  `no-lod`: always the near full-detail branch of every level-of-detail node;
  `rr-statics`: Rainbow Ride's 14 static decoration pieces drawn as part of the
  level instead of as objects; or any combination of these): at most
  0.2% of pixels may differ by more than ±2/31 per channel from their best 3×3
  neighbor. Each frame is matched against the set of *distinct* reference
  frames for that frame index; identical combinations are stored once, and
  `no-lod` subsumes `full-detail` (Mario's LOD is the only thing `full-detail`
  changes), so the reference does not hold that combination separately.
- **Audio** — overall SNR ≥ 40 dB against baseline, ≥ 20 dB on every
  non-silent frame; a frame the baseline renders silent (RMS ≤ 64 of 32768)
  must stay silent (candidate samples there ≤ 256).

Host grading also runs private held-out routes, unseen courses, and randomized
controller inputs. Never special-case public course IDs or remove subsystem
support (such as snow, desert, or lava effects) used in other courses.

## Tools

```
mev build                 build /task/game
mev run jrb               run a public course; prints est_console_ms / est_console_p99_ms
                          (console & stutter), cpu/rsp/rdp/rdram ms and vs-baseline speedups
mev profile bob           per-function CPU profile plus D-cache misses, I-cache misses
                          and D-cache writebacks by function (stalls included)
mev check                 run the full grader on all 6 public courses
mev workloads             bob, wf, jrb, ddd, bitfs, rr
mev restore-assets        restore missing extracted SM64 assets offline without overwriting edits
```

Use `make clean` for ordinary rebuilds. If `make distclean` removes the
extracted assets, run `mev restore-assets` before rebuilding. The task image
does not contain the original ROM.

`mev run` and `mev check` measure CPU busy time the same way: the idle thread's
halt loop is excluded from CPU time and nothing else is, so an optimization
cannot buy free time by moving work into the idle function or renaming it.

Reference material: `/task/docs/n64-cost-model.md`. Both SGI IDO
(`tools/ido-static-recomp`) and `mips64-elf-gcc` / `mips-linux-gnu-gcc` are
installed locally; there is no internet access.

## Rules

- Do not attempt to detect the grader, replays, or emulator.
- Commit working milestones to the git repository in `/task/game` regularly so
  no progress is lost across checkpoints.
