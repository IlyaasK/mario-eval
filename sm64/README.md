# Super Mario 64 evaluation target

Super Mario 64 (`us`, `n64decomp/sm64`) is the flagship 24-hour evaluation
target in Mario Eval alongside Pip's Garden (`workload/`). Because this
repository never distributes Nintendo code or assets (`sm64/decomp/`, `cache/`,
and `*.z64` are git-ignored), you prepare the target once from a legally dumped
US ROM you own.

## 1. Prepare `sm64/decomp`

```sh
./sm64/setup.sh "/path/to/Super Mario 64 (USA).z64"
```

`sm64/setup.sh`:
1. Verifies the US big-endian `.z64` SHA-1 (`9bef1128717f958171a4afac3ed78ee2bb4e86ce`).
2. Checks out [`n64decomp/sm64`](https://github.com/n64decomp/sm64) at pinned
   commit `9921382a68bb0c865e5e45eb594d9c64db59b1af` into `sm64/decomp/`.
3. Extracts assets inside `mario-eval` and **deletes `baserom.us.z64`** so the
   retail ROM binary never lingers in the workspace or task container.
4. Applies [`sm64/patches/0001-mario-eval-harness.patch`](patches/0001-mario-eval-harness.patch)
   and copies the protected harness files [`sm64/harness/mev.c`](harness/mev.c)
   and [`sm64/harness/mev.h`](harness/mev.h) into `sm64/decomp/src/game/`.
5. Builds the host tools (including `ido-static-recomp`) and verifies both the
   playable `#ifdef PLAY` check (`make check-play`) and the baseline ROM.

## 2. Precompute and calibrate

```sh
python3 sm64/corpus/make_replays.py --heldout /path/to/private-heldout-sm64
./scripts/precompute.sh --game sm64 --heldout /path/to/private-heldout-sm64
./scripts/calibrate.sh  --game sm64 --heldout /path/to/private-heldout-sm64
```

The SM64 calibration ladder (`sm64/calibration/`) spans 12 valid rungs plus 5
invalid shortcut traps (`i0-gcc-fastmath` through `i4-tamper`):

- `r0-unchanged` to `r9-kaze-partial`: compiler flags and a growing subset of
  Kaze Emanuar's techniques.
- **`r10-kaze-master`, the human-expert reference (1.65x console speedup)**:
  a reconstruction of applicable optimizations from Kaze's public videos,
  on-screen code, and two code downloads (the "How Optimizations made Mario 64
  SLOWER" repository and the audio code from "Revolutionizing N64 programming!").
  It is not Kaze's own engine, which rewrites physics and assets in ways that
  change the game.
  Techniques that change gameplay or audio (one-raycast walls, his sound engine)
  are left out. His table-free trig is kept, with a 512-byte correction map so
  every sine and cosine equals the vanilla table bit for bit, and his vertical
  object culling skips objects whose drawing moves other objects (held Spiny,
  collision children). With both, gameplay and audio are bit-identical to
  vanilla on the public routes and on seeded button mashing, except that the
  accepted Rainbow Ride decoration variant itself changes 54 PCM samples on the
  public RR route (99 dB SNR). Visual changes he
  ships are accepted as precomputed variants (full-detail Mario, no LOD, F3DEX2,
  reduced-aliasing opaque modes, Rainbow Ride decoration baked into the level).
- `r11-beyond-kaze` (1.62x, an earlier and smaller build): adds techniques Kaze
  never described (object fields ordered for the 16-byte D-cache lines, skipped
  unchanged stores, audio struct reorder, double buffering), to check that the
  reward keeps rising past the human reference.

## 3. Smoke test & run a 24-hour SM64 optimization agent

```sh
./scripts/build-images.sh --game sm64
./quickstart/smoke-test.sh --game sm64

cd quickstart && cp -n .env.example .env && docker compose up -d
AGENT_CMD='claude -p --dangerously-skip-permissions' \
  ./run-agent.sh --game sm64 --hours 24 --profile console --heldout /path/to/private-heldout-sm64
```

`scripts/build-images.sh --game sm64` runs `python3 -m grader.grade export-public`
to stage only the 6 public reference baselines into `/opt/mario-eval/reference`
inside `mario-eval-task`, asserting at Docker build time that zero `heldout`
files, zero `calibration` patches, and zero `.z64` ROM binaries exist inside the
container.

## Harness, 12-Course Suite & Gate Design

- **12-course lag torture + generalization suite**:
  - **Public (6)**: `bob` (Bob-omb Battlefield), `wf` (Whomp's Fortress), `jrb`
    (Jolly Roger Bay fog/water fillrate wall), `ddd` (Dire, Dire Docks Area 2 —
    Bowser's Sub room, SM64's most infamous retail lag spot), `bitfs` (Bowser in
    the Fire Sea dynamic platforms & lava), and `rr` (Rainbow Ride).
  - **Held-out (6)**: `ccm` (Cool, Cool Mountain snow & cabin), `lll` (Lethal
    Lava Land), `ssl` (Shifting Sand Land), plus alternate trajectories `bob2`,
    `jrb2`, and `ddd2`.
- **Deterministic logical frames (`#ifndef PLAY`)**: `thread5_game_loop` reads
  controller input synchronously per logical frame (`mev_read_pad_sync()`),
  waits for both `MESG_SP_COMPLETE` and `MESG_DP_COMPLETE` on `M_GFXTASK`, runs
  two deterministic 544-sample `M_AUDTASK` subframes (`1088` stereo samples /
  30 Hz frame) on `rspAspMain`, and emits `@mev` over IS-Viewer. Building with
  `PLAY=1` (`make check-play`, verified on every submission) restores normal
  60 Hz VBlank pacing and asynchronous `thread4_sound` console execution.
- **Player Equivalence + Hyrum's Law**: Gates on what the player sees, hears,
  and controls (`level_area`, `mario_stats`, `mario_action`, sub-pixel
  `mario_pos`, `mario_floor_height`, `cam_pos`, `cam_focus`, every actor within
  2000 units of Mario, whole-frame video, and audio SNR). Fixing engine C/memory
  undefined behavior (`AVOID_UB`, uninitialized locals, out-of-bounds reads) and
  hibernating distant off-screen objects is rewarded; altering 1996 SM64
  gameplay/physics quirks (quarter-step counts, wall-kick timing, BLJs) fails
  the gameplay gate.
- **Accepted visual variants (`full-detail`, `ra-zb-opa`, `f3dex2`, `no-lod`,
  `rr-statics`, and every combination)**: Always drawing high-polygon Mario (`actors/mario/geo.inc.c`),
  switching to Nintendo's F3DEX2 microcode, and/or using
  SGI's `G_RM_RA_ZB_OPA_SURF` / `G_RM_RA_OPA_SURF` reduced-aliasing opaque
  modes (preserving `AA_EN` VI coverage while dropping `IM_RD` framebuffer
  reads, as used by Kaze Emanuar and later N64 first-party games) are
  precomputed (every combination) and accepted as whole frames by the video gate.
