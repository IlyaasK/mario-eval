// mev.h - mario-eval harness contract. PROTECTED: the grader rejects any
// submission that modifies mev.h or mev.c (their hashes are checked).
//
// A workload ROM runs a fixed-timestep game loop. Each logical frame it must:
//   1. call mev_read_pad() exactly once, before simulating the frame;
//   2. simulate and render the frame;
//   3. call mev_end_frame() once the frame's picture is complete in RDRAM and
//      its audio block has been written back to RDRAM.
// The grader keys all input, video, audio and state comparison to these
// calls, never to video-interface timing, so a faster program sees exactly
// the same inputs as a slower one.
#pragma once
#include <stdint.h>
#include <surface.h>

// Controller state for one logical frame (N64 controller layout).
typedef struct {
    uint16_t buttons;   // N64 button mask (A = 0x8000, B = 0x4000, Z = 0x2000, START = 0x1000, ...)
    int8_t   x, y;      // analog stick, -85..85
} mev_pad_t;

#define MEV_A      0x8000
#define MEV_B      0x4000
#define MEV_Z      0x2000
#define MEV_START  0x1000
#define MEV_DUP    0x0800
#define MEV_DDOWN  0x0400
#define MEV_DLEFT  0x0200
#define MEV_DRIGHT 0x0100
#define MEV_L      0x0020
#define MEV_R      0x0010
#define MEV_CUP    0x0008
#define MEV_CDOWN  0x0004
#define MEV_CLEFT  0x0002
#define MEV_CRIGHT 0x0001

#define MEV_MAX_ENEMIES 16
#define MEV_MAX_GEMS    64

// Gameplay observation. Compared bit-for-bit against the baseline every frame.
// Layout is part of the contract and must not change.
typedef struct {
    uint32_t frame;
    uint32_t scene;
    uint32_t rng;
    int32_t  gems;
    int32_t  score;
    int32_t  hits;
    float    player_pos[3];
    float    player_vel[3];
    float    player_yaw;
    uint32_t player_state;
    float    cam_pos[3];
    float    cam_target[3];
    float    enemy_pos[MEV_MAX_ENEMIES][3];
    uint32_t enemy_state[MEV_MAX_ENEMIES];
    uint32_t gem_mask[MEV_MAX_GEMS / 32];
    uint32_t particles;
    uint32_t voices;
} mev_obs_t;

// Audio: each logical frame produces exactly MEV_AUDIO_SAMPLES stereo int16
// sample pairs at MEV_AUDIO_RATE Hz.
#define MEV_AUDIO_RATE    32000
#define MEV_AUDIO_SAMPLES 512

void mev_init(void);
mev_pad_t mev_read_pad(void);
// fb must be the completed frame (RDP finished). audio must hold
// MEV_AUDIO_SAMPLES*2 int16 values and be written back from the data cache.
void mev_end_frame(const mev_obs_t *obs, const surface_t *fb, const int16_t *audio);
