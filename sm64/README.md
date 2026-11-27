# Super Mario 64 Evaluation Target

Mario Eval evaluates long-horizon systems engineering on the complete US Super Mario 64 decompilation (`n64decomp/sm64`). Because this repository never distributes Nintendo code, ROMs, or assets (`sm64/decomp/`, `cache/`, and `*.z64` are git-ignored), you prepare the target once from a legally dumped US `.z64` ROM you own.

## 1. Prepare `sm64/decomp`

```sh
./sm64/setup.sh "/path/to/Super Mario 64 (USA).z64"
```

`sm64/setup.sh`:
1. Verifies the US big-endian `.z64` SHA-1 (`9bef1128717f958171a4afac3ed78ee2bb4e86ce`).
2. Checks out [`n64decomp/sm64`](https://github.com/n64decomp/sm64) at pinned commit `9921382a68bb0c865e5e45eb594d9c64db59b1af` into `sm64/decomp/`.
3. Extracts assets inside `mario-eval` and **deletes `baserom.us.z64`** so the retail ROM binary never lingers in the workspace or task container.
4. Applies [`sm64/patches/0001-mario-eval-harness.patch`](patches/0001-mario-eval-harness.patch) and copies the protected harness files [`sm64/harness/mev.c`](harness/mev.c) and [`sm64/harness/mev.h`](harness/mev.h) into `sm64/decomp/src/game/`.
5. Builds the host tools (including `ido-static-recomp`) and verifies both `make check-play` (`PLAY=1`) and the benchmark ROM.

## 2. Precompute & Calibrate

```sh
# Public dev cache (staged into mario-eval-task alongside baseline.z64 for mev diff / mev stress)
./scripts/precompute.sh

# Private held-out replays + host reference cache (keep PRIVATE_SEED outside git)
python3 sm64/corpus/make_replays.py --heldout /private/replays --heldout-seed "$PRIVATE_SEED"
./scripts/precompute.sh --heldout /private/replays --cache /private/reference
MEV_REFERENCE_DIR=/private/reference ./scripts/calibrate.sh --heldout /private/replays
```

The SM64 calibration ladder (`sm64/calibration/`) spans 12 valid hardware optimization rungs (`r0-unchanged` through `r10-kaze-master` and `r11-beyond-kaze`) plus 5 invalid shortcut traps (`i0-gcc-fastmath` through `i4-tamper`). See [`calibration/r10-trials.md`](calibration/r10-trials.md) for the technique-by-technique record of Kaze Emanuar's and ultrasm64's optimizations.

## 3. Build Task Container, Smoke Test & Run

```sh
./scripts/build-images.sh
./quickstart/smoke-test.sh

cd quickstart && cp -n .env.example .env && docker compose up -d
MEV_REFERENCE_DIR=/private/reference \
AGENT_CMD='claude -p --dangerously-skip-permissions' \
  ./run-agent.sh --hours 24 --profile console --heldout /private/replays
```

## v4 Harness & Suite Design

- **Generic `(level, act)` boot selector (`mev_select_boot_level`)**: Holding `S` (`START_BUTTON`) on Frame 0 decodes any valid SM64 `level` (`4..36` excluding stubs `{25, 32, 35}`) from `{6:1, 4:2, 2:4, 8:8, B:16, A:32}` and `act` (`1..6`) from `1 + {Z:1, L:2, u:4}`, without leaking which courses or acts are in the private held-out set. Without `S`, the 6 public single-button shortcuts (`.`=`bob`, `L`=`wf`, `R`=`jrb`, `u`=`ddd`, `d`=`bitfs`, `Z`=`rr`) boot Act 1.
- **0% Public / 100% Held-Out Weight**: The 6 public courses are purely for local profiling and `mev check`; 100% of the final score comes from 20 private held-out trajectories (`75%` scripted multi-course/multi-act routes + `25%` seeded random-input mash routes across 18 SM64 courses).
- **Differential Oracle (`mev diff` & `mev stress`)**: `export-public` stages `baseline.z64` into `/opt/mario-eval/reference/`, allowing agents to differentially test arbitrary custom replays (`mev diff <replay.txt>`) and random-input stress tests (`mev stress`) against the unmodified baseline ROM offline.
- **Accepted Visual Variants**: `full-detail`, `no-lod`, `f3dex2`, `ra-zb-opa`, and `rr-statics` (individually or combined) are precomputed and verified with whole-frame `3×3` `±2/31` pixel tolerance (`<= 0.2%`) and 16×16 block-SSIM (`>= 0.98`).
