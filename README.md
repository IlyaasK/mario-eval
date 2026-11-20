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
   decompilation (`n64decomp/sm64`) evaluated across a **12-course suite**:
   6 public courses (`bob` Bob-omb Battlefield, `wf` Whomp's Fortress, `jrb`
   Jolly Roger Bay, `ddd` Dire, Dire Docks Area 2 / Bowser's Sub lag room,
   `bitfs` Bowser in the Fire Sea, `rr` Rainbow Ride) and 6 private held-out
   courses (`ccm` Cool, Cool Mountain, `lll` Lethal Lava Land, `ssl` Shifting
   Sand Land, `bob2`, `jrb2`, `ddd2`), prepared locally from a legally dumped US
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
python3 sm64/corpus/make_replays.py --heldout /path/to/heldout-sm64
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
   real-time VBlank console build (`PLAY=1` / `check-play`) must compile cleanly.
2. **Run**: Each public and private held-out workload (240 logical frames) runs
   under `n64run`: [ares](https://github.com/ares-emulator/ares) at a pinned
   commit with [`0001-mario-eval-instrumentation.patch`](runner/patches/0001-mario-eval-instrumentation.patch)
   modelling the VR4300 CPU interpreter, direct-mapped 16 KB I-cache and 8 KB
   D-cache (including `CACHE 0x0d` Create Dirty Exclusive), RSP scalar+SIMD
   microcode cycles, **deterministic 62.5 MHz RDP raster/combiner/Z/TMEM/sync
   cycles**, per-device RDRAM bus bytes (CPU, SP DMA, PI DMA, SI DMA, **DP DMA**,
   **DP Draw**), and 4 MB RDRAM cacheline footprint.
3. **Correctness Gates**:
   - **Gameplay (Player Equivalence + Hyrum's Law)**: On SM64, `level_area` must
     match frame-by-frame, `mario_stats` (health, coins, stars, lives) and
     `mario_action` must match within ±1 frame (and exact at episode end), and
     `mario_pos`, `mario_floor_height`, `cam_pos`, and `cam_focus` must stay
     within tight sub-pixel L-infinity tolerances (`2.0`–`4.0` world units).
     Internal PRNG state and off-screen actor slots are intentionally unconstrained
     so Kaze-style distant object hibernation and math/cache optimizations pass,
     while any change to 1996 SM64 physics/collision quirks (quarter-steps, wall
     seam geometry, BLJs) fails. On Pip's Garden, `mev_obs_t` is checked bit-exact.
   - **Video**: Every frame as a whole must match either the baseline reference
     or an **accepted visual variant**: any combination of `full-detail`,
     `ra-zb-opa` and `f3dex2` (precomputed), with ≤ 0.2% pixels exceeding ±2/31 channel
     difference in a 3×3 neighborhood.
   - **Audio**: Overall SNR ≥ 40 dB and worst-frame SNR ≥ 20 dB.
   - **Hardware**: Highest RDRAM byte ≤ 4,194,304 (4 MB retail N64 RAM, no
     Expansion Pak).
   Any gate failure yields reward **−1.0** on every profile.
4. **Profiles, Rewards & Unbounded Speedups**:

| profile | role | measured hardware cost | cross-budget |
|---------|------|------------------------|--------------|
| `console` | **Headline** | Per-frame `max(CPU_ms, RSP_ms, RDP_ms)` bottleneck time (`est_fps = 1000 / est_console_ms`) | ≤ 5% per-course regression, ≤ 5% `footprint_bytes` |
| `speed` | Diagnostic | VR4300 `COUNT` ticks per frame (46.875 MHz, incl. cache stalls) | ≤ 5% `rdp_busy` regression |
| `rdp` | Diagnostic | RDP 62.5 MHz cycles per frame (1-cycle vs 2-cycle/fill/copy, Z/blend RMW, TMEM, syncs) | ≤ 5% `frame_ticks` regression |
| `rsp` | Diagnostic | RSP non-halted microcode cycles per frame | ≤ 5% `frame_ticks` regression |
| `traffic` | Diagnostic | Total RDRAM bytes read+written per frame across all bus masters | ≤ 5% `frame_ticks` regression |
| `memory` | Diagnostic | Distinct 16-byte RDRAM cachelines touched after boot | 0% footprint regression, ≤ 5% `frame_ticks` |

Each profile reports:
- `reward = clip(1 - geomean(cand / base), -1, 1)` (bounded RLVR signal),
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
./scripts/grade.sh --from-container mario-eval-task out/live-check --game sm64 --heldout /path/to/heldout-sm64
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
