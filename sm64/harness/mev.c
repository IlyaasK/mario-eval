/* mev.c - mario-eval Super Mario 64 harness contract.
 * PROTECTED: the grader rejects any submission that modifies mev.h or mev.c.
 */
#include <ultra64.h>

#include "sm64.h"
#include "mev.h"
#include "area.h"
#include "camera.h"
#include "game_init.h"
#include "level_update.h"
#include "main.h"
#include "memory.h"
#include "object_fields.h"
#include "object_list_processor.h"
#include "save_file.h"
#include "segment_symbols.h"
#include "audio/external.h"
#include "engine/behavior_script.h"
#include "engine/level_script.h"
#include "level_commands.h"
#include "levels/scripts.h"

typedef char mev_obs_size_check[(sizeof(mev_obs_t) == 4224) ? 1 : -1];

#define ISV_BUFFER_K1     0xB3FF0020U
#define ISV_LENGTH_K1     0xB3FF0014U
#define PI_STATUS_K1      0xA4600010U
#define MEV_PI_BUSY_MASK  0x00000003U
#define MEV_K0_TO_K1(ptr) ((void *) (((uintptr_t) (ptr)) | 0xA0000000U))

extern u16 mev_peek_random_u16(void);
extern struct SPTask *mev_create_audio_frame_task(s16 *outBuf, s32 samples, OSMesgQueue *doneQueue);
extern s32 exec_audio_sptask_sync(struct SPTask *spTask);

static u32 sMevFrame = 0;
static mev_obs_t sMevObs;
static OSMesgQueue sMevAudioDoneQueue;
static OSMesg sMevAudioDoneBuf[2];
static u64 sMevAudioStorage[(MEV_AUDIO_BYTES + 31) / 8];

static const s32 sMevActorLists[6] = {
    OBJ_LIST_DESTRUCTIVE,
    OBJ_LIST_GENACTOR,
    OBJ_LIST_PUSHABLE,
    OBJ_LIST_LEVEL,
    OBJ_LIST_POLELIKE,
    OBJ_LIST_SURFACE
};

static const LevelScript sMevEntryScript[] = {
    INIT_LEVEL(),
    BLACKOUT(/*active*/ FALSE),
    CALL(/*arg*/ 0, /*func*/ mev_select_boot_level),
    EXECUTE(/*seg*/ 0x15, /*script*/ _scriptsSegmentRomStart, /*scriptEnd*/ _scriptsSegmentRomEnd, /*entry*/ level_main_scripts_entry),
    JUMP(/*target*/ level_script_entry),
};

static s16 *mev_audio_buffer(void) {
    uintptr_t raw = (uintptr_t) sMevAudioStorage;
    return (s16 *) ((raw + 15U) & ~(uintptr_t) 15U);
}

static void mev_pi_wait(void) {
    while ((*(vu32 *) PI_STATUS_K1) & MEV_PI_BUSY_MASK) {
        ;
    }
}

static void mev_isv_write(const char *text, s32 len) {
    s32 i;
    s32 b;
    u32 word;

    for (i = 0; i < len; i += 4) {
        word = 0;
        for (b = 0; b < 4; b++) {
            word <<= 8;
            if (i + b < len) {
                word |= (u8) text[i + b];
            }
        }
        mev_pi_wait();
        *(vu32 *) (ISV_BUFFER_K1 + (u32) i) = word;
    }
    mev_pi_wait();
    *(vu32 *) ISV_LENGTH_K1 = (u32) len;
    mev_pi_wait();
}

static char *mev_put_hex(char *p, u32 v) {
    static const char digits[] = "0123456789abcdef";
    s32 shift;

    for (shift = 28; shift >= 0; shift -= 4) {
        *p++ = digits[(v >> shift) & 15U];
    }
    return p;
}

static char *mev_put_dec(char *p, u32 v) {
    char tmp[12];
    s32 n = 0;

    do {
        tmp[n++] = (char) ('0' + (v % 10U));
        v /= 10U;
    } while (v != 0U);
    while (n > 0) {
        *p++ = tmp[--n];
    }
    return p;
}

static void mev_zero_words_uncached(void *kseg0_ptr, s32 nbytes) {
    vu32 *dst = (vu32 *) MEV_K0_TO_K1(kseg0_ptr);
    s32 words = nbytes >> 2;
    s32 i;

    for (i = 0; i < words; i++) {
        dst[i] = 0;
    }
}

void mev_init(void) {
    sMevFrame = 0;
    osCreateMesgQueue(&sMevAudioDoneQueue, sMevAudioDoneBuf, ARRAY_COUNT(sMevAudioDoneBuf));
}

struct LevelCommand *mev_entry_script(void) {
    return (struct LevelCommand *) sMevEntryScript;
}

static s32 mev_is_valid_boot_level(s32 level) {
    if (level < 4 || level > 36) {
        return FALSE;
    }
    if (level == 25 || level == 32 || level == 35) {
        return FALSE;
    }
    return TRUE;
}

s32 mev_select_boot_level(UNUSED s16 arg, UNUSED s32 prev) {
    u16 btn = gControllerPads[0].button;
    s32 level = LEVEL_BOB;
    s32 act = 1;

    if (btn & START_BUTTON) {
        s32 raw_level = ((btn & R_CBUTTONS) ? 1 : 0)
                      | ((btn & L_CBUTTONS) ? 2 : 0)
                      | ((btn & D_CBUTTONS) ? 4 : 0)
                      | ((btn & U_CBUTTONS) ? 8 : 0)
                      | ((btn & B_BUTTON) ? 16 : 0)
                      | ((btn & A_BUTTON) ? 32 : 0);
        s32 raw_act = 1
                    + ((btn & Z_TRIG) ? 1 : 0)
                    + ((btn & L_TRIG) ? 2 : 0)
                    + ((btn & U_JPAD) ? 4 : 0);
        if (mev_is_valid_boot_level(raw_level)) {
            level = raw_level;
        }
        if (raw_act < 1) {
            act = 1;
        } else if (raw_act > 6) {
            act = 6;
        } else {
            act = raw_act;
        }
        /* Consume the digital boot-selector chord so buttons like U_CBUTTONS ('8')
         * or Z_TRIG ('Z') do not leak into Mario's Frame-0 gameplay state. */
        gControllerPads[0].button = 0;
        gControllerPads[0].stick_x = 0;
        gControllerPads[0].stick_y = 0;
        gControllers[0].buttonDown = 0;
        gControllers[0].buttonPressed = 0;
        gControllers[0].rawStickX = 0;
        gControllers[0].rawStickY = 0;
        gControllers[0].stickX = 0;
        gControllers[0].stickY = 0;
        gControllers[0].stickMag = 0;
    } else if (btn & L_TRIG) {
        level = LEVEL_WF;
    } else if (btn & R_TRIG) {
        level = LEVEL_JRB;
    } else if (btn & Z_TRIG) {
        level = LEVEL_RR;
    } else if (btn & U_JPAD) {
        level = LEVEL_DDD;
    } else if (btn & D_JPAD) {
        level = LEVEL_BITFS;
    }

    gCurrSaveFileNum = 1;
    gCurrActNum = act;
    gDebugLevelSelect = FALSE;
    save_file_erase(0);
    save_file_set_flags(SAVE_FLAG_FILE_EXISTS);
    return level;
}

void mev_read_pad_sync(void) {
    if (gControllerBits) {
        osContStartReadData(&gSIEventMesgQueue);
        osRecvMesg(&gSIEventMesgQueue, &gMainReceivedMesg, OS_MESG_BLOCK);
        osContGetReadData(&gControllerPads[0]);
    }
}

void mev_step_audio(void) {
    s16 *base = mev_audio_buffer();
    s32 sub;
    OSMesg msg;

    for (sub = 0; sub < MEV_AUDIO_SUBFRAMES; sub++) {
        s16 *subBuf = base + (sub * MEV_AUDIO_SUB_SAMPLES * 2);
        struct SPTask *spTask = mev_create_audio_frame_task(
            subBuf, MEV_AUDIO_SUB_SAMPLES, &sMevAudioDoneQueue
        );
        if (spTask != NULL && exec_audio_sptask_sync(spTask)) {
            osRecvMesg(&sMevAudioDoneQueue, &msg, OS_MESG_BLOCK);
        } else {
            mev_zero_words_uncached(subBuf, MEV_AUDIO_SUB_SAMPLES * 2 * (s32) sizeof(s16));
        }
    }
}

static void mev_observe(mev_obs_t *obs) {
    struct MarioState *m = gMarioState;
    s32 i;
    s32 li;
    u32 total = 0;

    bzero(obs, sizeof(*obs));
    obs->frame = sMevFrame;
    obs->level_area = (((u32) (u16) gCurrLevelNum) << 16) | ((u32) (u16) gCurrAreaIndex);
    obs->rng = (((u32) mev_peek_random_u16()) << 16) | (gAudioRandom & 0xFFFFU);
    obs->timer = gGlobalTimer;

    if (m != NULL) {
        obs->mario_action = m->action;
        obs->mario_prev_action = m->prevAction;
        obs->mario_flags = m->flags;
        obs->mario_action_state = (((u32) m->actionState) << 16) | ((u32) m->actionTimer);
        for (i = 0; i < 3; i++) {
            obs->mario_pos[i] = m->pos[i];
            obs->mario_vel[i] = m->vel[i];
            obs->mario_angles[i] = (s32) m->faceAngle[i];
        }
        obs->mario_fvel = m->forwardVel;
        obs->mario_floor_height = m->floorHeight;
        obs->mario_ceil_height = m->ceilHeight;
        obs->mario_stats[0] = (s32) m->health;
        obs->mario_stats[1] = (s32) m->numCoins;
        obs->mario_stats[2] = (s32) m->numStars;
        obs->mario_stats[3] = (s32) m->numLives;
    }

    for (i = 0; i < 3; i++) {
        obs->cam_pos[i] = gLakituState.pos[i];
        obs->cam_focus[i] = gLakituState.focus[i];
    }
    obs->cam_yaw_mode = (((u32) (u16) gLakituState.yaw) << 16)
                      | (((u32) gLakituState.mode) << 8)
                      | ((u32) gLakituState.defMode);

    if (gObjectLists != NULL) {
        for (li = 0; li < 6; li++) {
            struct ObjectNode *head = &gObjectLists[sMevActorLists[li]];
            struct ObjectNode *node = head->next;
            while (node != NULL && node != head) {
                struct Object *obj = (struct Object *) node;
                if (obj->activeFlags != ACTIVE_FLAG_DEACTIVATED) {
                    if (total < MEV_MAX_ACTORS) {
                        obs->actor_pos[total][0] = obj->oPosX;
                        obs->actor_pos[total][1] = obj->oPosY;
                        obs->actor_pos[total][2] = obj->oPosZ;
                        obs->actor_state[total] =
                            (((u32) obj->oAction & 0xFFU) << 24)
                            | (((u32) obj->oSubAction & 0xFFU) << 16)
                            | ((u32) ((u16) obj->activeFlags));
                    }
                    total++;
                }
                node = node->next;
            }
        }
    }
    obs->actor_count = total;
}

void mev_observe_and_end_frame(uintptr_t fb_paddr) {
    char line[128];
    char *p = line;
    s16 *au = mev_audio_buffer();

    mev_observe(&sMevObs);

    p[0] = '@'; p[1] = 'm'; p[2] = 'e'; p[3] = 'v'; p[4] = ' ';
    p += 5;
    p = mev_put_dec(p, sMevFrame); *p++ = ' ';
    p = mev_put_hex(p, (u32) (uintptr_t) &sMevObs); *p++ = ' ';
    p = mev_put_dec(p, (u32) sizeof(mev_obs_t)); *p++ = ' ';
    p = mev_put_hex(p, (u32) fb_paddr); *p++ = ' ';
    p = mev_put_dec(p, (u32) SCREEN_WIDTH); *p++ = ' ';
    p = mev_put_dec(p, (u32) SCREEN_HEIGHT); *p++ = ' ';
    p = mev_put_dec(p, 16U); *p++ = ' ';
    p = mev_put_hex(p, (u32) VIRTUAL_TO_PHYSICAL(au)); *p++ = ' ';
    p = mev_put_dec(p, (u32) MEV_AUDIO_BYTES);
    *p++ = '\n';

    mev_isv_write(line, (s32) (p - line));
    sMevFrame++;
}
