# Mario Eval

A 24-hour RLVR systems-engineering benchmark and evaluation environment for coding agents:
**super-optimize Super Mario 64 for an unexpanded 4 MB Nintendo 64 without changing the player experience.**

The agent receives the complete C/assembly US decompilation (`n64decomp/sm64`), pinned N64 toolchains (SGI IDO + `mips64-elf-gcc`), offline community N64 hardware specifications ([N64brew Wiki](https://n64brew.dev/), CC BY-SA 4.0), an instrumented cycle-, cache-, RSP-, and 62.5 MHz RDP-accurate N64 emulator ([ares](https://github.com/ares-emulator/ares)), and a clock-weighted per-function/cache-line profiler. Every optimization is verified against player-equivalent gameplay (preserving 1996 SM64 physics and speedrun quirks while permitting engine UB fixes), whole-frame pixel-level video + 16×16 block-SSIM (with accepted quality-improving visual variants), stereo audio SNR + log-mel similarity, unexpanded 4 MB RDRAM hardware & cache/DMA coherence invariants, playable real-time console builds (`PLAY=1` cold-boot runtime smoke), and **private held-out multi-course/multi-act trajectories**.

Site, leaderboard, uncapped N64 FPS curves, calibration results, and write-ups:
**<https://ilya.as/mario-eval/>**. Modeled on Mechanize's
[GBA Eval](https://github.com/mechanize-work/gba-eval) and calibrated against a
26-video hardware optimization audit of [Kaze Emanuar](https://www.youtube.com/@KazeN64)'s
Super Mario 64 work.

This repository contains **no Nintendo code, ROMs, or assets** (`sm64/decomp/`, `cache/`, and `*.z64` are git-ignored).

## Quick start

Requires Docker and a legally dumped US Super Mario 64 `.z64` ROM (`SHA-1: 9bef1128717f958171a4afac3ed78ee2bb4e86ce`).

```sh
# 1. Build toolchain, instrumented ares runner, and grader image
./scripts/build-images.sh --no-task

# 2. Prepare Super Mario 64 decompilation source (deletes baserom.us.z64 after asset extraction)
./sm64/setup.sh "/path/to/Super Mario 64 (USA).z64"

# 3. Precompute public dev reference + build agent container + smoke test
./scripts/precompute.sh
./scripts/build-images.sh
./quickstart/smoke-test.sh

# 4. (Host evaluation) Generate private seeded held-out replays & reference outside the repo
python3 sm64/corpus/make_replays.py --heldout /private/replays --heldout-seed "$PRIVATE_SEED"
./scripts/precompute.sh --heldout /private/replays --cache /private/reference
MEV_REFERENCE_DIR=/private/reference ./scripts/calibrate.sh --heldout /private/replays
```

## How grading works (v4)

1. **Zero-Spoiler Contract & Real Hardware Docs**: Inside the task container, `/task/TASK.md` states only the behavioral contract, gates, and tools (`~50` lines, zero codebase spoilers), accompanied by read-only `/task/spec/MEASUREMENT.md` and 20 SHA-256-verified [N64brew Wiki](https://n64brew.dev/) hardware reference pages in `/task/spec/n64brew/`.
2. **Integrity & Playable Console Check (`PLAY=1`)**: Harness files (`mev.c`, `mev.h`) and `#ifdef PLAY` glue must preserve parity between the benchmark build and the real-time 60 Hz VBlank console build (`PLAY=1`). Host grading builds both cleanly in an isolated, network-disabled container with a scrubbed environment and boots the linked `PLAY=1` ROM twice in parallel (`idle` + `controller`), verifying changing VI video, controller response, 4 MB RAM safety, DMA coherence, and active RSP audio (`play_rsp_aud_cycles > 0`).
3. **100% Held-Out Final Score Weight**:
   - **Public dev courses (`0%` final score weight)**: `bob`, `wf`, `jrb`, `ddd`, `bitfs`, `rr` — available locally via `mev run`, `mev profile`, `mev check`, and `mev stress`, plus `mev diff <replay.txt>` for arbitrary custom replays across all valid SM64 levels (`4..36`) and acts (`1..6`).
   - **Private held-out routes (`100%` final score weight: `75%` scripted + `25%` random-input mash)**: 20 private trajectories synthesized from `--heldout-seed` across **18 SM64 courses and multiple acts** (`bbh`, `ccm`, `hmc`, `ssl`, `bob`, `sl`, `wdw`, `jrb`, `thi`, `ttc`, `rr`, `lll`, `ddd`, `wf`, `ttm`, `bitdw`, `bitfs`, `bits`).
4. **Correctness Gates**:
   - **Execution & Hardware**: 240 completed frames, `0` synchronous CPU fault/trap exceptions, `highest_byte <= 4,194,304` (4 MB RDRAM), `oob_rdram_accesses == 0` (`0x00400000..0x03EFFFFF`), `cache_uncached_ops == 0`, `cache_cde_unaligned_ops == 0`, `cache_kseg1_dirty_synonyms == 0`, `rdram_dma_coherence_errors == 0`, and `sp_dmem_coherence_errors <= 1.05 * frames`.
   - **Gameplay (Player Equivalence)**: Exact `frame`, `level_area`, `mario_stats`, `mario_action`, and `actor_count`; `mario_pos`, `mario_vel`, `mario_floor_height` within `±0.01`; `cam_pos`, `cam_focus` within `±0.02`; unordered bipartite match of every actor within `2000` units of Mario (`±0.1` position, exact action/state).
   - **Video**: Every frame matches baseline or one consistent accepted visual variant (`full-detail`, `no-lod`, `f3dex2`, `ra-zb-opa`, `rr-statics`) with `<= 0.2%` pixels exceeding `±2/31` in a `3×3` neighborhood **and** GBA-Eval 16×16 block-SSIM `>= 0.98` (worst frame `>= 0.85`).
   - **Audio**: Stereo 32 kHz SNR `>= 40 dB` (worst frame `>= 20 dB`) or 40-band log-mel similarity `>= 0.95` (worst frame `>= 0.75`, RMS ratio within `±15%`); silent frames remain silent.
5. **Profiles, Speedups & Uncapped FPS**:

| profile | role | measured per frame | route regression cap | cross-subsystem cap |
|---------|------|--------------------|----------------------|---------------------|
| `console` | **Headline** | `est_console_ms = max(cpu_ms, rsp_ms, rdp_ms, mem_ms)` (`est_fps = 1000 / est_console_ms`) | `<= 5%` | None (`<= 4.00 MB` RDRAM gate) |
| `stutter` | Worst frames | `est_console_p99_ms` (99th-percentile bottleneck) | `<= 5%` | None (`<= 4.00 MB` RDRAM gate) |
| `speed` | CPU time | `cpu_effective_cycles` (VR4300 cycles + cache/bus stalls) | `<= 5%` | `rdp_busy <= 5%` |
| `rdp` | RDP busy | `rdp_busy` (62.5 MHz raster/fill/Z/TMEM/page-miss/sync) | `<= 5%` | `cpu_effective_cycles <= 5%` |
| `rsp` | RSP busy | `rsp_busy` (non-halted RSP cycles) | `<= 5%` | `cpu_effective_cycles <= 5%` |
| `traffic` | RDRAM traffic | `rdram_bytes` across all bus masters | `<= 5%` | `cpu_effective_cycles <= 5%` |
| `memory` | RAM footprint | `footprint_bytes` (distinct 16B RDRAM lines touched) | `0%` | `cpu_effective_cycles <= 5%` |

Each valid submission emits unbounded `speedup = 1 / geomean_weighted(cand / base)`, `est_fps`, `cost_saved = 1 - 1/speedup`, `vs_o2_speedup`, and `reward = log2(speedup) / 4.0` (while `fidelity.effective_speedups` also records per-route gated speedup on invalid checkpoints).

## Running a 24-hour agent evaluation

```sh
cd quickstart && cp -n .env.example .env && docker compose up -d
MEV_REFERENCE_DIR=/private/reference \
AGENT_CMD='claude -p --dangerously-skip-permissions' \
  ./run-agent.sh --hours 24 --profile console --heldout /private/replays

# Grade a live or stopped container directly from the host at any time:
MEV_REFERENCE_DIR=/private/reference \
  ../scripts/grade.sh --from-container ../results/live-check --heldout /private/replays
```

## Layout

| path | what |
|------|------|
| `sm64/` | Super Mario 64 setup, deterministic harness (`mev.c`/`mev.h`), seeded multi-course/act replay generator, 17-patch Kaze calibration suite |
| `spec/` | `MEASUREMENT.md` counter spec + `vendor-n64brew.sh` & SHA-256-verified offline N64brew Wiki hardware docs (`spec/n64brew/`) |
| `runner/` | Pinned `ares` commit, CPU/RSP/RDP/RDRAM instrumentation patch, `n64run` frontend |
| `toolchain/` | Hash-pinned MIPS64 GCC cross-compiler image |
| `grader/` | SM64 grader (`precompute`, `grade`, `export-public`) + `-O3` C++ gate & ELF verifier (`fast_video.cpp`) |
| `quickstart/` | Leak-hardened agent container (`TASK.md`, read-only `/task/spec`), smoke test, egress proxy, 24-hour supervisor |
| `tools/` | `mev` in-container CLI (`build`, `run`, `profile`, `check`, `stress`, `diff`), PC/cache-line symbolizer |
| `site/` | Static website & FPS/speedup chart generator (`python3 site/build.py site/dist`) |
