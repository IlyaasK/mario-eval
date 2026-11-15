# Mario Eval

An RLVR environment for coding agents: **make a Nintendo 64 game cheaper to run
on the original hardware without changing it.** The agent gets the game's
source, a pinned toolchain, an accurate emulator and a profiler; the reward is
measured by the emulator, gated on bit-exact gameplay and on picture and sound
matching the original.

Site, calibration results and write-ups: **<https://ilya.as/mario-eval/>**.
Modelled on Mechanize's [GBA Eval](https://github.com/mechanize-work/gba-eval).

The harness is built and calibrated on **Pip's Garden** (`workload/`), an
original stand-in game. Super Mario 64 plugs into the same pipeline once you
supply a legally dumped ROM; see [`sm64/README.md`](sm64/README.md). This
repository contains no Nintendo code or assets.

## Quick start

Requires Docker.

```sh
scripts/build-images.sh --no-task      # toolchain, emulator, grader (~5 min)
scripts/precompute.sh                  # build the baseline, record its reference outputs
scripts/grade.sh workload out/r0       # grade the unchanged game: valid, reward 0
scripts/calibrate.sh                   # grade every calibration patch
```

`out/<name>/summary.json` has the status (`valid`, `invalid`, or
`grader_error` for infrastructure failures, which carry no reward), every gate
with the first divergent frame and field, per-workload metrics, and one reward
per profile.

## How grading works

1. **Integrity**: `src/mev.c` and `src/mev.h` (the harness) must be unchanged.
2. **Trusted rebuild** of the submitted source with the pinned toolchain.
3. **Run** each workload (240 logical frames of recorded controller input)
   under `n64run`: [ares](https://github.com/ares-emulator/ares) at a pinned
   commit with [one patch](runner/patches/0001-mario-eval-instrumentation.patch)
   (RDRAM footprint tracking, PC sampling), CPU interpreter so the VR4300's
   I- and D-cache models apply to every instruction, Vulkan via lavapipe.
   The game runs unthrottled and reports each finished frame through the
   IS-Viewer port; input is served per *logical* frame, so a faster build plays
   the same game.
4. **Gates**: gameplay observation record bit-exact on every frame; video
   within a one-pixel-neighbourhood tolerance (≤ 0.2% failing pixels per
   frame); audio ≥ 40 dB SNR (≥ 20 dB per non-silent frame); stays within 4 MB.
   Any failure: reward −1 on every profile.
5. **Reward** per profile = clip(1 − geomean(candidate / baseline), −1, 1):

| profile   | cost                                             |
|-----------|--------------------------------------------------|
| `speed`   | CPU COUNT ticks per frame (cache stalls included) |
| `rsp`     | RSP busy cycles per frame                         |
| `traffic` | RDRAM bytes per frame, all bus devices            |
| `memory`  | distinct RDRAM bytes touched after boot           |

Non-speed profiles carry a 5% frame-time budget; every profile rejects a >5%
regression on any single workload (0% for `memory`). Thresholds live in
[`corpus/grader.json`](corpus/grader.json).

What the model does **not** include: RDP rasterization time and CPU/RCP bus
contention. See [`quickstart/task/docs/n64-cost-model.md`](quickstart/task/docs/n64-cost-model.md).

## Calibration

`calibration/*.patch` are known changes with known expected outcomes:
IEEE-preserving `-O2`, algorithmic changes, Create Dirty Exclusive, a memory
saving, two tolerance probes (reassociated math, a sine table), and five
shortcuts that must fail (fast-math, muted audio, skipped particles, changed
physics, harness tampering). `scripts/calibrate.sh` reproduces the table on
the site.

## Running an agent

```sh
scripts/precompute.sh --heldout DIR   # reference for public + held-out routes
scripts/build-images.sh               # + task container and egress proxy
cd quickstart && cp .env.example .env && docker compose up -d
./shell.sh                            # look around: /task/TASK.md, mev --help
AGENT_CMD='claude -p --dangerously-skip-permissions' ./run-agent.sh --hours 8 --profile speed --heldout DIR
```

The task container has no route to the internet: it sits on an internal
Docker network whose only exit is a proxy that admits model-API hosts
([`quickstart/proxy/allowlist.txt`](quickstart/proxy/allowlist.txt)) and
refuses everything else. Inside, `mev build|run|profile|check` builds the game,
reports costs against the baseline, gives a clock-weighted per-function
profile, and runs the real grader on the public routes. Held-out routes stay on
the host (generate them with `corpus/make_replays.py DIR --seed-file SEEDS`,
keeping the seeds private) and are used only when checkpoints are graded.

## Layout

| path | what |
|------|------|
| `workload/` | Pip's Garden source (the baseline) |
| `runner/` | ares pin, instrumentation patch, `n64run` headless frontend |
| `toolchain/` | pinned libdragon toolchain image |
| `grader/` | grader (gates, metrics, rewards) |
| `corpus/` | grader config, public routes, route generator |
| `calibration/` | calibration patches |
| `quickstart/` | agent container, egress proxy, supervisor |
| `tools/` | `mev` CLI, PC-sample symbolizer |
| `sm64/` | Super Mario 64 setup (bring your own ROM) |
| `site/` | website generator and posts |

## Third-party components

ares (ISC-style license) and libdragon (Unlicense) are fetched at pinned
commits during the image builds, not vendored. Pip's Garden, its music and
its character are original to this project.
