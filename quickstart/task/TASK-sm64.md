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

A naive compiler switch (`COMPILER=gcc -O2 -fno-fast-math`) only gets ~1.18×
because `libultra` is already compiled with optimizations and Jolly Roger Bay /
Dire, Dire Docks are RDP fillrate-bound. If you believe you are done, you are
mistaken — keep profiling CPU, I-cache, D-cache, RSP, RDP, and RDRAM and keep
pushing further.

## Objective

Your submission is scored on **one primary resource profile**, named in
`/task/PROFILE` (default: `console`). All six profiles are measured and reported:

| profile   | what is reduced                                        | measured as |
|-----------|--------------------------------------------------------|-------------|
| `console` | **Real N64 frame bottleneck time (headline score)**    | Per-frame `max(CPU_ms, RSP_ms, RDP_ms)` within 4 MB RAM |
| `speed`   | CPU time to simulate and build a frame                 | VR4300 COUNT ticks per frame (46.875 MHz) |
| `rdp`     | Reality Display Processor hardware busy time           | RDP 62.5 MHz cycles per frame (raster/fill/Z/TMEM/sync) |
| `rsp`     | Reality Signal Processor microcode busy time           | RSP non-halted cycles per frame (`gspFast3D` + `rspAspMain`) |
| `traffic` | Total RDRAM bus traffic across all devices             | RDRAM bytes read+written per frame (CPU, SP, DP, PI, SI) |
| `memory`  | Console RAM footprint                                  | Distinct 16-byte RDRAM lines touched after boot |

For each profile, `geo = geomean(yours / baseline)` over all courses:
- **Bounded RL reward**: `reward = clip(1 - geo, -1, 1)` (`0.0` unchanged, `0.5` at 2×, `-1.0` if invalid or over budget).
- **Unbounded speedup**: `speedup = 1 / geo`, `log2_speedup = -log2(geo)`, and `vs_o2_speedup` (speedup beyond switching `COMPILER=gcc` `-O2 -fno-fast-math`, directly measuring genuine algorithmic & hardware optimization beyond the compiler).

Cross-subsystem budgets enforce honest hardware engineering:
- In `console`, no course may regress `est_console_ms` or `footprint_bytes` by more than **5%**.
- In `speed`, no course may regress `frame_ticks` or `rdp_busy` by more than **5%**.
- In `rdp`, `rsp`, and `traffic`, no course may regress the target metric or `frame_ticks` by more than **5%**.
- In `memory`, no course may regress `footprint_bytes` (`0%`) and `frame_ticks` may not regress by more than **5%**.

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
  with accurate register-only minimax/folded polynomials;
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

Grading replays recorded controller inputs across courses and checks six gates:

- **Integrity & Playable Build** — `src/game/mev.c` and `src/game/mev.h` must
  be byte-identical, and **both** the graded build (`make VERSION=us COMPARE=0 NOEXTRACT=1`)
  and the real-time console `#ifdef PLAY` check (`make VERSION=us COMPARE=0 NOEXTRACT=1 check-play`)
  must compile cleanly.
- **Execution & Hardware** — every course must complete all 240 frames within
  the 4 MB RDRAM ceiling (`0x00400000` bytes, no Expansion Pak).
- **Gameplay (Player Equivalence)** — `level_area` must match on every frame;
  `mario_stats` (health, coins, stars, lives) and `mario_action` must match
  (allowing ±1 frame boundary jitter during sub-pixel transitions, with exact
  final stats); `mario_pos` and `mario_floor_height` must stay within **2.0**
  world units (Mario is 160 units tall — <1 pixel on screen), and `cam_pos` /
  `cam_focus` within **4.0** world units. Internal PRNG state and off-screen
  actor lists are not locked bit-for-bit, while all visible actors are verified
  by the video gate.
- **Video** — every frame as a whole must match either the baseline picture or
  an accepted visual variant in `/opt/mario-eval/corpus/variants/`
  (`full-detail`: always high-polygon Mario instead of medium/low LODs;
  `ra-zb-opa`: SGI's `G_RM_RA_ZB_OPA_SURF` / `G_RM_RA_OPA_SURF` reduced-aliasing
  opaque modes without `IM_RD`; `f3dex2`: Nintendo's later F3DEX2 microcode;
  `no-lod`: always the near full-detail branch of every level-of-detail node;
  `rr-statics`: Rainbow Ride's 14 static decoration pieces drawn as part of the
  level instead of as objects; or any combination of these): at most
  0.2% of pixels may differ by more than ±2/31 per channel from their best 3×3
  neighbor.
- **Audio** — overall SNR ≥ 40 dB against baseline, ≥ 20 dB on every
  non-silent frame; silence must stay silent.

Grading on the host also runs **private held-out routes and unseen courses** you
cannot see — never special-case public course IDs or delete subsystem support
(such as snow/desert/lava effects) used in other SM64 courses.

## Tools

```
mev build                 build /task/game
mev run jrb               run a public course; prints console/CPU/RDP/RSP/RDRAM vs baseline
mev profile bob           per-function CPU profile (cache & uncached stalls included)
mev check                 run the full grader on all 6 public courses
mev workloads             bob, wf, jrb, ddd, bitfs, rr
```

Reference material: `/task/docs/n64-cost-model.md`. Both SGI IDO
(`tools/ido-static-recomp`) and `mips64-elf-gcc` / `mips-linux-gnu-gcc` are
installed locally; there is no internet access.

## Rules

- Do not attempt to detect the grader, replays, or emulator.
- Commit working milestones to the git repository in `/task/game` regularly so
  no progress is lost across checkpoints.
