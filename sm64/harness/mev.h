/* mev.h - mario-eval Super Mario 64 harness contract.
 * PROTECTED: the grader rejects any submission that modifies mev.h or mev.c.
 */
#ifndef SM64_MEV_H
#define SM64_MEV_H

#include <ultra64.h>
#include "types.h"

/* Every active object in the six gameplay object lists is recorded up to this
 * many; the public routes peak at 81 (Bob-omb Battlefield), the vanilla cap of
 * 64 made the grader skip the actor gate on every such frame. */
#define MEV_MAX_ACTORS         256
#define MEV_AUDIO_SUBFRAMES    2
#define MEV_AUDIO_SUB_SAMPLES  544
#define MEV_AUDIO_SAMPLES      (MEV_AUDIO_SUBFRAMES * MEV_AUDIO_SUB_SAMPLES)
#define MEV_AUDIO_BYTES        (MEV_AUDIO_SAMPLES * 2 * (s32)sizeof(s16))

/* 1056 big-endian 32-bit words (4224 bytes); matches grader/contract.py. */
typedef struct {
    u32 frame;
    u32 level_area;
    u32 rng;
    u32 timer;
    u32 mario_action;
    u32 mario_prev_action;
    u32 mario_flags;
    u32 mario_action_state;
    f32 mario_pos[3];
    f32 mario_vel[3];
    f32 mario_fvel;
    f32 mario_floor_height;
    f32 mario_ceil_height;
    s32 mario_angles[3];
    s32 mario_stats[4];
    f32 cam_pos[3];
    f32 cam_focus[3];
    u32 cam_yaw_mode;
    u32 actor_count;
    f32 actor_pos[MEV_MAX_ACTORS][3];
    u32 actor_state[MEV_MAX_ACTORS];
} mev_obs_t;

void mev_init(void);
struct LevelCommand *mev_entry_script(void);
s32 mev_select_boot_level(s16 arg, s32 prev);
void mev_read_pad_sync(void);
void mev_step_audio(void);
void mev_observe_and_end_frame(uintptr_t fb_paddr);

#endif /* SM64_MEV_H */
