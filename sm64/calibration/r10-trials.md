# r10-kaze-master: every remaining technique, measured

Each row is r10 (as of trig fix `1d6a3bc`) plus one change, measured with the same
battery:

- **speed**: modeled console frame time vs r10, geometric mean over the six public
  routes, at 7 code-layout pads (main.o padded by 0x0 to 0x2000). Unchanged code moves
  up to 1.75% across pads, so only the median and whether min and max share a sign mean
  anything. Negative is faster.
- **units**: change in mean CPU / RSP / RDP ms at pad 0. All six routes are CPU-bound
  (CPU 17-23 ms, RSP 8-13, RDP 5-18), so RSP/RDP savings do not move console time.
- **exact**: gameplay observations bit-identical to vanilla (object-list order ignored)
  and audio PCM equal, on the six public routes and 24 seeded button-mash runs. r10
  itself differs only in Rainbow Ride's public-route PCM (54 samples, from the accepted
  `rr-statics` variant).
- **video**: grader video gate against vanilla plus accepted variants, and the number of
  frames (of 6 x 240) that differ from r10.
- **RAM**: mean change in touched RDRAM (`footprint_bytes`) per route.

Sources: Kaze Emanuar's videos and code releases, FazanaJ/ultrasm64 (branches master,
getreal) and CrashOveride95/ultrasm64.

## Adopted (r10 commits b476ef9..e59eca1; graded 1.651x -> 1.671x)

| trial | change | speed vs r10 | units (cpu/rsp/rdp ms) | RAM |
|---|---|---|---|---|
| `cc-libultra-os` | libultra compiled `-Os` (r10's per-file libultra flags were IDO-only, dead under gcc); FazanaJ 8a20ba05 | -1.36 [-2.80, +0.40] | -0.255 / 0 / 0 | -208 |
| `mtx-4x3-factored` | Kaze's 4x3 matrices: never store the constant column; shared rotation products (DUbR8C6svHs 6:41, r-2iIBmXULI 5:46) | -0.37 [-1.69, -0.17] | -0.064 / 0 / 0 | +416 |
| `coll-5fe1a69f5-exact` | flat surfaces (nx = nz = 0) return v1y in find_floor/ceil; exact form of FazanaJ getreal 5fe1a69f5 | -0.19 [-0.36, -0.10] | -0.070 / 0 / 0 | +363 |
| `ram-fb-overlap` | adjacent framebuffers share their never-drawn 8-line borders | +0.00 [0.00, 0.00] | 0 / 0 / 0 | -10240 |
| (cleanup) | delete `KAZE_GCC_FLAGS`, defined after use and never applied | output identical | | |
| **combined** | all of the above | **-2.11 [-3.14, -1.20]**, p99 -2.42 | -0.237 / 0 / 0 | -10592 |

All exact, all pictures identical to r10.

## Exact, not adopted

| trial | change | speed vs r10 | units | RAM | why not |
|---|---|---|---|---|---|
| `ro-dispatch` | graph-node handler table instead of r10's compare ladder | -1.03 [-3.16, +1.55] | -0.084 / 0 / 0 | -957 | mixed sign; on top of the adopted set -0.43 median [-1.62, +0.64], and audio then differs in 4 WF mash runs (63-64 dB) while gameplay stays exact: it reaches code that reads the matrix column the 4x3 change no longer writes |
| `cc-spc` | `-fsingle-precision-constant` | -0.83 [-2.10, +0.39] | -0.083 / 0 / 0 | +243 | mixed sign; combined with the adopted set it is slower (-0.87 vs -1.74); changes float evaluation by design (2 JRB frames differ sub-LSB) |
| `ro-early-out` | model-less objects skip matrix build (FazanaJ 2872a7f3, keeping draw-time state writers) | -0.23 [-1.79, +1.14] | +0.212 / 0 / 0 | +133 | noise |
| `dead-camera` | unused camera globals/modes/spline tail (FazanaJ aad3ab05) | -0.20 [-1.24, +0.61] | -0.043 / 0 / 0 | +96 | noise |
| `dead-actors` | 26 unreachable scripts, 7 dead behavior files | +0.30 [-1.42, +0.88] | +0.055 / 0 / 0 | -624 | noise |
| `dead-resident` | 61 proven-unreferenced resident symbols | +3.67 [-0.77, +4.88] | +0.939 / 0 / 0 | -4675 | slower (layout) |
| `mtx-4x3` | constant-column stores only | -0.06 [-1.82, +0.51] | -0.011 / 0 / 0 | +384 | noise alone; adopted combined |
| `mtx-factored` | shared products only | +0.12 [-1.06, +0.74] | +0.018 / 0 / 0 | +315 | noise alone; adopted combined |
| `cc-case20` | case-values-threshold 20 | +0.12 [-1.08, +0.71] | +0.128 / 0 / 0 | +411 | noise |
| `cc-fipa-pta` | `-fipa-pta` | +0.21 [-1.94, +0.74] | +0.065 / 0 / 0 | +504 | noise |
| `cc-kaze-rest` | Kaze's flag set minus no-zero-division | +0.09 [-0.75, +1.79] | +0.313 / 0 / 0 | +72 | noise |
| `cc-kaze-flags` | Kaze's 11 flags actually applied | +0.73 [-0.88, +2.11] | +0.133 / 0 / 0 | +888 | noise/slower |
| `cc-nozero-all` | `-mno-check-zero-division` everywhere | +0.27 [-0.89, +5.51] | +0.186 / 0 / 0 | +117 | noise |
| `cc-os-load` | `-Os` for surface_load.o | +1.13 [+0.05, +2.69] | +0.221 / 0 / 0 | -381 | slower |
| `coll-5fe1a69f5` | as committed upstream (ny > 0.99999) | -0.18 [-0.35, -0.08] | -0.070 / 0 / 0 | +165 | exactness unproven; exact form adopted |
| `coll-9059813bc` | s32 bufferY | -0.02 [-0.18, +0.35] | -0.029 / 0 / 0 | +85 | noise |
| `coll-e954899da` | hoisted rejections | +0.01 [-0.12, +0.44] | -0.025 / 0 / 0 | 0 | noise |
| `coll-f59f0d892` | oFloor reuse + wrapper inlining | +0.16 [-1.39, +0.47] | +0.090 / 0 / 0 | -160 | noise |
| `coll-d17c9247a` | single-pass min/max in the loader | +0.10 [-1.36, +1.22] | +0.176 / 0 / 0 | +411 | noise |
| `coll-690720805` | zero-vertex shortcut | -0.04 [-0.20, +0.31] | -0.039 / 0 / 0 | +107 | noise |
| `coll-combined` | exact forms of the collision commits | +0.02 [-0.88, +0.57] | +0.091 / 0 / 0 | +411 | noise |
| `farcall-actors` | 66 behavior files linked into per-level segments (FazanaJ farcall) | +0.07 [-1.27, +1.36] | +0.137 / 0 / 0 | +12029 | resident image -106 KB, but the 4 MB layout cannot reuse it; touched RAM rises |
| `ram-fill-gaps` | pack the default link layout | +0.61 [-0.87, +0.85] | +0.131 / 0 / 0 | 0 | highest used byte -608 KB; noise in speed |
| `ram-music-zero-regions` | audio heap -4 KB to measured high water | +2.44 [-1.55, +4.38] | +0.875 / 0 / 0 | -3995 | slower (layout) |
| `ram-memory-pool-trim` | gfx pool 6400 -> 5120, object pool 0x800 -> 0x100 | +1.53 [+0.53, +2.11] | +0.336 / 0 / 0 | +160 | slower |
| `ram-zbuffer-rim` | z-buffer stops at the unwritten bottom strip | +0.46 [+0.28, +0.61] | +0.111 / 0 / 0 | +187 | slower |
| `ram-sample-dma-buffers` | 3 -> 2 sample DMA windows per note | +0.02 [-1.22, +0.54] | +0.021 / 0 / 0 | +549 | noise |
| `ram-engine-dead-code` | 4 unreferenced engine functions | +0.31 [-0.49, +0.79] | +0.099 / 0 / 0 | -165 | noise |
| `rdp-dedupe-state` | 184 redundant state commands removed | +0.10 [-0.13, +0.32] | +0.060 / -0.002 / 0 | +85 | data has nothing left to remove (16 RR frames differ by noise-floor pixels) |
| `rdp-culldl8b` | `G_CULLDL` over all 8 AABB corners, inserted before each list's first draw (1514 lists) | +0.30 [-0.07, +0.51] | +0.103 / -0.164 / 0 | +27411 | RSP-only saving (RR -1.15 ms); console unchanged |
| `rig-goomba-deadmodel` | delete two unreferenced Goomba display lists | +0.29 [-0.02, +0.34] | +0.064 / 0 / 0 | -4965 | noise; -5 KB data |
| `rig-goomba-bones` | fold eyes into the billboard node | +0.03 [-0.10, +0.14] | -0.003 / 0 / 0 | +64 | noise; no Goomba bone is droppable without re-export |
| `rig-bobomb-bones` | Bob-omb 13 -> 8 bones | +0.03 [-0.19, +0.18] | +0.002 / 0 / 0 | -219 | noise |
| `rig-bobomb-tex` | eye textures RGBA16 -> IA8 (lossless here) | +0.10 [-0.07, +0.14] | +0.015 / 0 / 0 | -1888 | noise |
| `rig-bowser-static` | 27 inert Bowser bones removed | -0.00 [-0.01, +0.01] | -0.002 / 0 / 0 | -5 | Bowser is on no public route |

## Picture changes (visual variants, not adopted)

| trial | change | speed vs r10 | units | video | look |
|---|---|---|---|---|---|
| `vis-dither-off` | color and alpha dither off | +0.15 [-1.05, +0.58] | +0.029 / 0 / 0 | fails JRB only (0.0073) | same by eye; water and dirt lose the speckle. The RDP model charges nothing for dither |
| `vis-point-filter` | point texture filtering | -0.00 | 0 / 0 / 0 | fails all routes | clearly worse: jagged HUD text, staircased edges |
| `vis-dither-off-point` | both | +0.15 [-1.05, +0.58] | +0.029 / 0 / 0 | fails all routes | aliasing dominates |
| `vis-detail-tex` | procedural detail texture over BoB grass (2-cycle, no new art) | -0.02 [-0.08, +0.01] | 0 / +0.001 / 0 | passes | same, about 1% darker |
| `rdp-onecycle-nofog2` | fog materials drawn 1-cycle without fog | +0.16 [-0.09, +0.21] | +0.036 / -0.003 / **-0.701** | fails BoB, JRB | distant haze gone (JRB pillars at full contrast); RDP -1.5 ms BoB, -2.7 ms JRB |
| `rdp-front-to-back` | opaque layer sorted near to far | +0.09 [-1.89, +0.82] | +0.166 / 0 / 0 | fails 5 routes | same by eye; anti-aliased edges depend on draw order; no RDP gain (model has no early-Z) |
| `ro-bg-cull` | FazanaJ background switch (with a fixed camera test) | -0.05 [-2.66, +0.19] | -0.012 / -0.136 / -0.445 | fails DDD (193 frames) | culls a visible sky band in DDD |
| `f3dex3-base` | F3DEX3 microcode (light fix, F3DEX3 viewport) | +1.01 (pad 0) | +0.200 / **-1.479** / -0.214 | fails WF, JRB, DDD, RR | JRB water/fog and RR near clipping differ; RR cannot pass (NoN is mandatory in F3DEX3) |

Superseded or broken attempts, kept for the record: `rdp-culldl`, `rdp-culldl-big`,
`rdp-culldl8`, `rdp-culldl8-big` (culled lists also dropped their trailing state, so later
draws lost texture/shading setup), `rdp-onecycle`, `rdp-onecycle-nofog` (second combine
cycle read COMBINED, erasing geometry), `f3dex3-noskip` (identical to `f3dex3-base` in a
clean build).

## Already done or not applicable

- `rdp-nofbclear`: vanilla clears the framebuffer only for the ending letterbox, and every
  level draws its background without Z.
- `cc-libgcc-nozero`, `cc-libz-ofast`: the US build compiles no libgcc and contains no libz.
- Kaze's Goomba rig rework (144 -> 107 triangles, 12 -> 7 bones): every Goomba bone is
  animated or carries a static rotation; it needs a re-export from the original model.

## v2 Exhaustive Kaze & ultrasm64 completion pass (2026-11-22)

Following a full audit of all 424 Kaze Emanuar videos (309 transcripts + 115 visual-screened), both Kaze code releases, `FazanaJ/ultrasm64`, and `CrashOveride95/ultrasm64` under Mario Eval v2's updated cost model (4-bank RDP page misses, early-Z write rejection, bus-coupled CPU contention, 60 Hz VI scanout, `cache_uncached_ops == 0`, and `PLAY=1` runtime smoke) and US `TOOLCHAIN_LIBGCC` linking, the remaining 8 unimplemented Kaze/`ultrasm64` candidates were tested on top of `r10-kaze-master` (v2 baseline `1.6745x` on 6 public routes / `1.6463x` on 25 private routes):

### Adopted (graded `1.6745x -> 1.7328x` public, `1.6463x -> 1.6930x` across all 25 private routes; `PLAY=1` pass)

| trial | source & change | pad-0 console vs r10 | key hardware deltas (mean/frame, 6 public) |
|---|---|---|---|
| `k1d-wb-all-plus-lookat` | Kaze `g5u3zW4SLow [12:37-13:52]` targeted `osWritebackDCache` in `main.c` (`spTask`, `data_ptr`, `&lookAt`, live `gGfxPool` head/tail) + NMI-only guard on `game_init.c:320` + Goddard flush in `PLAY=1` | `+1.55%` (`1.7004x`) | D$ misses `-344`, writebacks `-161`, `coh == 1408` (identical to base) |
| `k2b-cde-bzero-bcopy` | Kaze `cache 0x0d` (Create Dirty Exclusive) in `lib/asm/bzero.s` & `lib/asm/bcopy.s`, strictly KSEG0 (`(addr >> 29) == 4`) and 16-byte aligned | `+0.38%` (`1.6809x`) | D$ misses `-271`, `cache_uncached_ops == 0` |
| `k3-shadow-exact` | Kaze `3We_ZGOwmik [10:36]` `find_floor_height` instead of `find_floor_height_and_data` in `shadow.c` | `+0.05%` (`1.6753x`) | CPU eff `-859` cyc, exact |
| `k4-lookat-hoist` | `FazanaJ/ultrasm64` `a946464b` hoist `gSPLookAt` once into `geo_process_master_list_sub` | `-0.37%` alone (I$ shift), `+0.33%` in combo | RSP busy `-20,238` cyc/frame (`-1.0%`) |
| `k7-shadow-above-cam` | `FazanaJ/ultrasm64` `588d06bb` cull shadows whose floor is above `gCurGraphNodeCamera->pos[1]` | `+0.93%` (`1.6900x`) | CPU eff `-13,773` cyc, RSP busy `-9,410` cyc |
| `area-play-null-fix` | Guard `load_obj_warp_nodes()` in `src/game/area.c` when `gObjParentGraphNode.children == NULL` | correctness fix | Fixes real-N64 `PLAY=1` boot hang in 0-object `levels/intro` caught by `--play-smoke` |
| **combined (`k1d+k2b+k3+k4+k7`)** | **All adopted changes** | **`+3.48%` pad-0 (`1.7328x` pub / `1.6930x` 25-route)** | **5-pad sweep (`0x0..0x1800`): median `+2.71%` (`[+1.48%, +3.12%]`), strictly faster on all 5 pads and on 25/25 private routes; `PLAY=1` pass, `unc == 0`, zero extra `coh`** |

### Not adopted (v2 pass)

| trial | source & change | console vs r10 | why not |
|---|---|---|---|
| `k5-os-remaining` | Kaze `oZcbgNdWL7w` / `FazanaJ` `91ce5e84` `-Os` on 9 remaining `-O2` game-loop TUs (`mario.o`, `mario_step.o`, `object_list_processor.o`, `object_collision.o`, `spawn_object.o`, `level_update.o`, `memory.o`, `game_init.o`, `behavior_script.o`) | `-3.53%` (`1.6155x`) | Slower: I$ misses `+511`, CPU busy `+48.4k` cyc/frame |
| `k6-inline-f32` | Kaze `U2K44nC8c8g` / `t_rzYnXEQlE` / `20s9hWDx0Io` (`f32` `round_float`, inline `absf`/`absi`/`signum_positive`, `__restrict__` in `mtxf_to_mtx`) | `-0.16%` (`1.6718x`) | Neutral/slower (`+70` D$ misses, `+1.8k` CPU busy) |
| `k8-frustratio2` | `FazanaJ/ultrasm64` `a9630cf7` `FRUSTRATIO_1` -> `FRUSTRATIO_2` in `sInitRdpRspDl` | invalid (video gate) | Cuts RSP busy `-13.7%` and RDP `-3.8%`, but 3 frames reach `0.23%` bad edge pixels (`> 0.20%` video gate) |

## Model gaps these results expose

- All six routes are CPU-bound, so RSP/RDP work (F3DEX3, culling, 1-cycle fog) cannot
  move the console score; RDP/RSP-bound scenes are needed to reward it.
- The RDP model has no early-Z credit and charges nothing for dither or texture filtering,
  so front-to-back drawing and dither-off cannot register even where the RDP is the
  bottleneck. Calibrating against real hardware should come before adding such scenes.
