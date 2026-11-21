# SM64 engine trials against r10-kaze-master

Apply each trial independently to a clean checkout with `sm64/calibration/r10-kaze-master.patch` already applied (local reference `d2c1fa6`). Build with the existing `mario-eval` image and US assets. Captures use the six public replays (`bob wf jrb ddd bitfs rr`), 240 frames each, with the ELF's `thread1_idle` range passed to `n64run`. Compare against captures from the unchanged r10 build. No ROMs or regenerated meshes are included.

**Revision (re-check of the first pass).** The first pass compared each trial at one code layout. An unchanged control build, padded by 0x10–0x2000 bytes after `main.o(.text)`, moves the modeled frame time by up to 1.75% purely through I-cache aliasing — larger than most measured deltas. Every CPU-side trial was therefore re-run at seven paddings (`padded-results.jsonl`, `padded-summary.py`); the table reports the median and range against the control at the same padding. The first-pass F3DEX3 port also had a lighting bug (fixed below), and one rerun reused stale output (the runner now deletes prior output and fails on incomplete replays).

| Trial | Source | Evidence | Disposition |
| --- | --- | --- | --- |
| F3DEX3 | `f3dex3.patch`, `f3dex3-header.patch`, `f3dex3-lights.py`; Sauraen's HackerN64/F3DEX3 `91a85284821181af627d838e47d245718804f388` | `f3dex3-results.json`, `f3dex3-lightfix-*.png` | First pass rendered surfaces dark: F3DEX3 only re-transforms directional lights on `G_MW_NUMLIGHT`, which SM64 sets once per frame. With `f3dex3-lights.py` (1,455 paired uploads → `gsSPSetLights1`), BoB/WF/DDD/BitFS are within 0.25–1.1% bad pixels of F3DEX2 (borderline, not passing). JRB and RR still fail: JRB water/fog and an RR near-plane triangle render differently (F3DEX2's own NoN build shows the same RR frame difference). Obs/PCM exact. RSP −6% to −22% per route; console frame time unchanged because every route is CPU-bound (CPU 17–22 ms vs RSP 8–13 ms). No adoption; viable after JRB fog/water is resolved. |
| Shared renderer node tail | `renderer-outline.patch`; adapted from Kaze's outline, already partly present in r10 | `padded-results.jsonl` | Exact obs, PCM, framebuffer. Median +1.13% (range −0.25% to +1.86%). Consistently not faster. No adoption. |
| Actor vertex repack | `actor-repack.patch`, `actor-repack.py`; new analogue, not Kaze's exports or rigs | `padded-results.jsonl`, `actor-repack-bob.mp4` | Exact. Median +0.10% (−0.15% to +0.24%): neutral. Its savings are RSP-side, which does not set frame time on these routes. No Bowser-fight replay. No adoption. |
| Whole audio TU | `audio-unity.patch`; retail loader and synth, not Kaze's stripped audio release | `padded-results.jsonl` | Exact. Median +1.25% (+0.27% to +2.03%): slower at every layout. No adoption. |
| Shadow below-plane skip | `shadow-cull.patch`; exact-plane adaptation of FazanaJ/ultrasm64 `c4fb9633` | `padded-results.jsonl` | Exact. Median +0.51% (−0.86% to +2.42%): noise. Few shadows on these routes are viewed from below. No adoption. |
| `gSPLookAt` once per master list | `lookat-hoist.patch`; FazanaJ/ultrasm64 `a946464b` lineage | `padded-results.jsonl` | Exact; RSP −0.05 to −0.19 ms. Median +0.19% (+0.01% to +2.19%): the first-pass +2.19% was one layout. Neutral on CPU. No adoption. |
| Published collision replacement | [Kaze's demo/published ASM](https://youtu.be/jp35ihdSefM) and public source drop | Source audit only | ASM shifts all nine vertex coordinates right by two with no corresponding scale in the published transform path. The separately released permanent-loader change alters collision persistence/partition. Excluded from same-game benchmark; r10 already implements a replay-tested cache that preserves per-frame dynamic insertion. |

Model deltas are geometric means of trial/reference ratios across routes, not N64 hardware times. Public replay parity is not a general equivalence proof. ultrasm64 survey notes: `/tmp/me/ultra/report-fazana.md`, `/tmp/me/ultra/report-base-getreal.md` (not committed).

## F3DEX3 build

1. Build `F3DEX3_BrW_NOC` from the pinned upstream checkout with `make ARMIPS=/path/to/armips F3DEX3_BrW_NOC`. Copy the resulting `.code` and `.data` from `build/F3DEX3_BrW_NOC/` to the SM64 checkout's `rsp/`. Copy upstream `gbi.h` to `include/PR/f3dex3_gbi.h`.
2. In the r10 build tree, apply `patch -p1 < f3dex3.patch` and `patch -p1 < f3dex3-header.patch` (resolve artifact paths relative to your lab folder).
3. Build with `make GRUCODE=f3dex3 VERSION=us COMPARE=0 NOEXTRACT=1`. Confirm `F3DEX3_BrW_NOC_B` is embedded. The trial does not include the upstream matrix-stack migration or Fast64 re-exports. No deliberate fog, dither or filtering edits.

## Actor repack build

Apply `actor-repack.patch`. For each of `goomba bobomb bowser`, run `python3 /path/to/actor-repack.py actors/$actor/model.inc.c actors/$actor/model.repacked.inc.c`. It leaves rigs, animation, textures, triangle sequence, and draw state alone. In eligible static runs ending at `gsSPEndDisplayList`, vertex loads went 32→15, 6→3, and 128→66 respectively. Build `GRUCODE=f3dex2` for this, the renderer outline, and the audio trial.
