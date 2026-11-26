# Mario Eval

A 24-hour RLVR benchmark and evaluation environment for coding agents:
**super-optimize a Nintendo 64 game for the original 4 MB hardware without
changing the player experience.**

The agent gets the complete C/assembly source tree (**Super Mario 64** or
**Pip's Garden**), pinned N64 toolchains (SGI IDO + `mips64-elf-gcc`), an
instrumented cycle-, cache-, RSP-, and 62.5 MHz RDP-accurate N64 emulator
([ares](https://github.com/ares-emulator/ares)), and a clock-weighted
per-function profiler. Every optimization is verified against player-equivalent
gameplay (preserving 1996 SM64 physics and speedrun quirks while permitting
engine UB fixes), whole-frame pixel-level video (with accepted quality-improving
visual variants), audio SNR, 4 MB RDRAM hardware limits, playable real-time
console builds (`PLAY=1`), and private held-out controller routes.

Site, leaderboard/reference ceiling, calibration results and write-ups:
**<https://ilya.as/mario-eval/>**. Modeled on Mechanize's
[GBA Eval](https://github.com/mechanize-work/gba-eval) and calibrated against a
26-video hardware optimization audit of [Kaze Emanuar](https://www.youtube.com/@KazeEmanuar)'s
Super Mario 64 work.

This repository contains **no Nintendo code or assets** (`sm64/decomp/`,
`cache/`, and ROM files are git-ignored).

## Evaluation targets

1. **Super Mario 64 (`--game sm64`, default 24h target)** — Full US
   decompilation (`n64decomp/sm64`) evaluated across a **25-route suite**:
   6 public courses (`bob` Bob-omb Battlefield, `wf` Whomp's Fortress, `jrb`
   Jolly Roger Bay, `ddd` Dire, Dire Docks Area 2 / Bowser's Sub lag room,
   `bitfs` Bowser in the Fire Sea, `rr` Rainbow Ride) and 19 private held-out
   routes: 8 scripted courses (`ccm` Cool, Cool Mountain, `lll` Lethal Lava
   Land, `ssl` Shifting Sand Land, `hmc` Hazy Maze Cave, `wdw` Wet-Dry World,
   `bob2`, `jrb2`, `ddd2`) plus, with
   `--mash-seed S`, seeded random button mashing on all 11 courses
   (`mash-<course>`), which catches route-specific special cases and crashes
   on unscripted input. Prepared locally from a legally dumped US
   `.z64` ROM via [`sm64/setup.sh`](sm64/setup.sh). See
   [`sm64/README.md`](sm64/README.md).
2. **Pip's Garden (`--game pips-garden`)** — Self-contained 3D libdragon N64
   game (`workload/`) with DragonFS textures, double-buffered 16bpp VI
   framebuffers, cartridge PI DMA asset streaming, 2-cycle RDP combiners, alpha
   particles, and 12-voice software audio synthesis across 8 routes (4 public +
   4 held-out). Runs out of the box with zero external ROMs.

## Quick start

Requires Docker.

```sh
# 1. Build toolchain, instrumented ares runner, and grader image
./scripts/build-images.sh --no-task

# 2a. Super Mario 64 (bring your own legally dumped US .z64 ROM)
./sm64/setup.sh "/path/to/Super Mario 64 (USA).z64"
python3 sm64/corpus/make_replays.py --heldout /path/to/heldout-sm64 --mash-seed "$PRIVATE_SEED"
./scripts/precompute.sh --game sm64 --heldout /path/to/heldout-sm64
./scripts/calibrate.sh  --game sm64 --heldout /path/to/heldout-sm64
./scripts/build-images.sh --game sm64
./quickstart/smoke-test.sh --game sm64

# 2b. Pip's Garden (out of the box, no ROM needed)
./scripts/precompute.sh --game pips-garden
./scripts/calibrate.sh  --game pips-garden
```

## How grading works

1. **Integrity & Playable Console Check**: Harness files (`mev.c`, `mev.h`) must
   be byte-identical, and **both** the unthrottled benchmark build and the
   real-time VBlank console build (`PLAY=1` / `check-play`) must build and link.
   To also require a playable-ROM runtime smoke, add `--play-smoke` to
   `scripts/grade.sh --game sm64 SUBMISSION_DIR OUT_DIR`. It boots the linked
   `PLAY=1` ROM twice in ares, with idle and scripted controller input, and
   requires changing VI output and an observable response to input. This
   does not verify gameplay equivalence or physical FPS; grading runs
   without the flag are unchanged.
2. **Run**: Each public and private held-out workload (240 logical frames) runs
   under `n64run`: [ares](https://github.com/ares-emulator/ares) at a pinned
   commit with [`0001-mario-eval-instrumentation.patch`](runner/patches/0001-mario-eval-instrumentation.patch)
   modelling the VR4300 CPU interpreter, direct-mapped 16 KB I-cache and 8 KB
   D-cache (including `CACHE 0x0d` Create Dirty Exclusive), RSP scalar+SIMD
   microcode cycles, **deterministic 62.5 MHz RDP raster/combiner/Z/TMEM/sync
   cycles**, per-device RDRAM bus bytes (CPU, SP DMA, PI DMA, SI DMA, **DP DMA**,
   **DP Draw**), and 4 MB RDRAM cacheline footprint.

   Host grading via `scripts/grade.sh` builds the submission in a separate,
   network-disabled container with no corpus, reference cache or private replay
   mounts. The build gets a scrubbed environment, scratch `HOME`/`TMPDIR`, and
   its own process group. Measurement starts only after the build container
   exits, with a read-only handoff containing the built ROM and its ELF-derived
   idle ranges. Local `mev check` only uses public data and checks that the
   in-container build did not modify its measurement inputs.
3. **Correctness Gates**:
   - **Gameplay (Player Equivalence + Hyrum's Law)**: On SM64, `level_area`,
     `mario_stats` (health, coins, stars, lives), `mario_action` and the actor
     count must match on every frame; `mario_pos`, `mario_vel` and
     `mario_floor_height` must stay within `0.01` world units and `cam_pos` /
     `cam_focus` within `0.02` (L-infinity). Every actor within `2000` units of
     Mario must exist in the candidate with the same action/state and a position
     within `0.1` units (matched as an unordered set, so object-list order is
     free). Internal PRNG state and actors farther away are unconstrained, so
     Kaze-style distant object hibernation and math/cache optimizations pass,
     while any change to 1996 SM64 physics/collision quirks (quarter-steps, wall
     seam geometry, BLJs) fails. On Pip's Garden, `mev_obs_t` is checked bit-exact.
   - **Video**: Every frame across a workload must match either the baseline
     reference or one consistent **accepted visual variant** (`full-detail`,
     `ra-zb-opa`, `f3dex2`, `no-lod`, `rr-statics`, or combinations thereof),
     with ≤ 0.2% pixels exceeding ±2/31 channel difference in a 3×3 neighborhood
     **and** GBA-Eval single-scale 16×16 block-SSIM ≥ 0.98 (worst frame ≥ 0.85).
   - **Audio**: Overall SNR ≥ 40 dB and worst-frame SNR ≥ 20 dB (or 40-band
     stereo log-mel spectrogram cosine similarity ≥ 0.95 with RMS loudness ratio
     within ±15% for timing-preserving audio rewrites); silent baseline frames
     must remain silent.
   - **Hardware & Cache Coherence**: Highest RDRAM byte ≤ 4,194,304 (4 MB retail
     N64 RAM, no Expansion Pak), zero `CACHE` ops on uncached addresses, zero
     non-16-byte-aligned `CACHE 0x0d` (`Create_Dirty_Exclusive`) ops, zero
     uncached `KSEG1` accesses aliasing dirty `KSEG0` D-cache lines, coherent
     SP/DP DMA writebacks, and (with `--play-smoke`) cold-boot `PLAY=1` video
     progress, controller response, and active RSP audio (`play_rsp_aud_cycles > 0`).
   Any gate failure yields reward **−1.0** on every profile. Every `summary.json`
   also emits bounded `cost_saved` (`1 - geomean_ratio`), continuous 5-axis
   `fidelity`, `capability_ruler` (subsystem speedups across CPU, graphics RSP,
   audio RSP, effective RDP, RDRAM traffic, and memory footprint, plus
   `generalization_ratio`), and automatic `failure_attribution`.
4. **Profiles, Rewards & Unbounded Speedups**:

| profile | role | measured per frame | profile budget | cross-subsystem budget |
|---------|------|--------------------|----------------|------------------------|
| `console` | **Headline** | `est_console_ms` = `max(cpu_ms, rsp_ms, rdp_ms, mem_ms)` (`est_fps = 1000 / est_console_ms`) | ≤ 5% regression | `footprint_bytes` ≤ 5% |
| `stutter` | Worst frames | `est_console_p99_ms`, the 99th percentile of the same per-frame bottleneck (the hitches a player feels) | ≤ 5% regression | `footprint_bytes` ≤ 5% |
| `speed` | CPU time to simulate and build a frame | `cpu_effective_cycles` (VR4300 cycles including cache/bus stalls) | ≤ 5% regression | `rdp_busy` ≤ 5% |
| `rdp` | RDP hardware busy time | `rdp_busy` (62.5 MHz raster/fill/Z/TMEM/sync cycles) | ≤ 5% regression | `cpu_effective_cycles` ≤ 5% |
| `rsp` | RSP microcode busy time | `rsp_busy` (non-halted 62.5 MHz cycles) | ≤ 5% regression | `cpu_effective_cycles` ≤ 5% |
| `traffic` | RDRAM bus traffic | `rdram_bytes` read + written by every bus master | ≤ 5% regression | `cpu_effective_cycles` ≤ 5% |
| `memory` | Console RAM footprint | `footprint_bytes` (distinct 16-byte RDRAM lines touched after boot) | 0% regression | `cpu_effective_cycles` ≤ 5% |

A profile is scored valid only if no course regresses its own metric past the
profile budget *and* no course regresses the cross-subsystem metric past the
cross budget (e.g. `speed` refuses a CPU win bought with RDP work, `console`
refuses one bought with RAM); an over-budget profile scores −1.

Each profile reports:
- `reward = max(-1, log2(speedup) / reward_log2_scale)` with
  `reward_log2_scale = 4.0`: 2× scores 0.25, 16× scores 1.0, no upper cap; any
  failed gate (or that profile's budget) scores −1,
- `speedup = 1 / geomean(cand / base)` and `log2_speedup` (unbounded improvement),
- `vs_o2_speedup` (speedup relative to a pure `-O2 -fno-fast-math` compiler build,
  isolating genuine algorithmic & hardware engineering beyond compiler flags).

## Running a 24-hour agent evaluation

```sh
./scripts/precompute.sh --game sm64 --heldout /path/to/heldout-sm64
./scripts/build-images.sh --game sm64
./quickstart/smoke-test.sh --game sm64

cd quickstart && cp -n .env.example .env && docker compose up -d
AGENT_CMD='claude -p --dangerously-skip-permissions' \
  ./run-agent.sh --game sm64 --hours 24 --profile console --heldout /path/to/heldout-sm64

# Grade a live or stopped container directly from the host at any time:
../scripts/grade.sh --game sm64 --from-container ../out/live-check --heldout /path/to/heldout-sm64
```

`run-agent.sh` snapshots git checkpoints, records every in-container `mev check`
into `results/<run>/trajectory.json` for 24-hour scaling curves, and grades the
final submission on `public + heldout`. `scripts/build-images.sh` stages
`/opt/mario-eval/reference` via `python3 -m grader.grade export-public`, locks
`TASK.md`/`docs/` read-only, pins `core.hooksPath`, and runs on an isolated
Docker network whose only egress is [`quickstart/proxy/allowlist.txt`](quickstart/proxy/allowlist.txt)
(supporting Anthropic, OpenAI, Gemini/Google, and OpenRouter).

## Layout

| path | what |
|------|------|
| `sm64/` | Super Mario 64 setup, deterministic harness (`mev.c`/`mev.h`), 12-course replay generator, 15-patch Kaze calibration & ceiling suite |
| `workload/` | Pip's Garden libdragon N64 game source & DragonFS asset generator |
| `runner/` | Pinned ares commit, CPU/RSP/RDP/RDRAM instrumentation patch, `n64run` frontend |
| `toolchain/` | Pinned N64 cross-compilers + libdragon toolchain image |
| `grader/` | Multi-target grader (`precompute`, `grade`, `export-public`), Player Equivalence & variant gates, rewards |
| `corpus/` | Pip's Garden grader config, public routes, accepted variants |
| `calibration/` | Pip's Garden 16-patch calibration suite (CPU, cache, RSP, RDP, memory, shortcuts) |
| `quickstart/` | Leak-hardened agent container, smoke test, shell helper, egress proxy, 24-hour supervisor |
| `tools/` | `mev` in-container CLI, `.mev-history.jsonl` telemetry, clock-weighted PC symbolizer |
| `site/` | Static website & PNG/SVG generator (`python3 site/build.py <out_dir>`) |
