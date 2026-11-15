# Super Mario 64 workload

Mario Eval's harness, grader and agent environment were built and calibrated
on Pip's Garden (`workload/`). Super Mario 64 uses the same pipeline; what it
needs from you is a ROM dumped from a cartridge you own. No Nintendo code or
assets are distributed by this repository.

## Done

- `sm64/setup.sh ROM` verifies the ROM (US release, SHA-1
  `9bef1128717f958171a4afac3ed78ee2bb4e86ce`), checks out
  [n64decomp/sm64](https://github.com/n64decomp/sm64) at a pinned commit into
  `sm64/decomp/` (git-ignored) and builds the matching baseline.
- Everything downstream of "a ROM that speaks the harness protocol" is
  game-independent: `n64run`, the grader's gates and metrics, the reward
  profiles, the agent container and the supervisor.

## Remaining (needs a ROM to build and verify)

1. **Harness calls in the game loop** (`src/game/game_init.c`, `thread5_game_loop`):
   call `mev_read_pad()` in place of the per-frame controller read
   (`osContStartReadData` / `osContGetReadData`), so input is served per logical
   frame; call `mev_end_frame()` once the frame's graphics task has completed
   and its audio has been produced.
2. **Unthrottled benchmark build**: remove the wait for the video interface
   retrace in the game loop under a build flag, as the decomp community's
   profiling builds do, so frame cost is pure work.
3. **Observation record**: an SM64 `mev_obs_t` with Mario's position, velocity,
   action, health, coins and stars, the camera, the RNG state
   (`gRandomSeed16`) and the positions of active objects, compared bit-for-bit.
4. **Routes**: per-course controller routes (Bob-omb Battlefield, Whomp's
   Fortress, Jolly Roger Bay for water, Big Boo's Haunt, the castle grounds),
   public and held-out, starting from a portable state (a replayed path from
   the file-select screen, not an emulator savestate, which would pin one
   build's memory layout).
5. **Calibration**: the same discipline as Pip's Garden: the unchanged rebuild
   scores 0; `-O2` with IEEE semantics, a Create Dirty Exclusive patch and a
   memory patch score positive; shortcuts (muted audio, skipped objects,
   changed physics) score −1.

The decompilation builds with IDO by default (matching); the agent may switch
to GCC and change flags, as long as gameplay stays bit-exact.
