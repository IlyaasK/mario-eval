// main.c - Pip's Garden main loop.
//
// Default build (graded): runs unthrottled, renders into double-buffered
// framebuffers and reports every frame to the harness. PLAY=1 build: shows
// frames on the TV and plays audio, for running on real hardware or by hand.
#include <libdragon.h>
#include "game.h"

static int16_t audio_block[MEV_AUDIO_SAMPLES * 2] __attribute__((aligned(16)));
static mev_obs_t obs;

static int scene_from_pad(mev_pad_t pad)
{
    if (pad.buttons & MEV_L) return SCENE_FORTRESS;
    if (pad.buttons & MEV_R) return SCENE_STORM;
    if (pad.buttons & MEV_Z) return SCENE_CONCERT;
    return SCENE_MEADOW;
}

int main(void)
{
    mev_init();
    dfs_init(DFS_DEFAULT_LOCATION);
    rdpq_init();
    render_init();

#ifdef PLAY
    display_init(RESOLUTION_320x240, DEPTH_16_BPP, 3, GAMMA_NONE, FILTERS_RESAMPLE);
    surface_t zbuf = surface_alloc(FMT_RGBA16, SCREEN_W, SCREEN_H);
    audio_init(MEV_AUDIO_RATE, 4);
    audio_set_buffer_granularity(MEV_AUDIO_SAMPLES);
#else
    surface_t fbs[2] = {
        surface_alloc(FMT_RGBA16, SCREEN_W, SCREEN_H),
        surface_alloc(FMT_RGBA16, SCREEN_W, SCREEN_H),
    };
    surface_t zbuf = surface_alloc(FMT_RGBA16, SCREEN_W, SCREEN_H);
    int fb_idx = 0;
#endif

    bool started = false;
    while (1) {
        mev_pad_t pad = mev_read_pad();
        if (!started) {
            world_init(scene_from_pad(pad));
            synth_init();
            started = true;
        }

        world_update(pad);
        synth_frame(audio_block);
        data_cache_hit_writeback(audio_block, sizeof(audio_block));

#ifdef PLAY
        surface_t *fb = display_get();
        rdpq_attach_clear(fb, &zbuf);
        render_frame();
        rdpq_detach_wait();
        world_observe(&obs);
        mev_end_frame(&obs, fb, audio_block);
        display_show(fb);
        while (!audio_can_write()) {}
        short *dst = audio_write_begin();
        for (int i = 0; i < MEV_AUDIO_SAMPLES * 2; i++) dst[i] = audio_block[i];
        audio_write_end();
#else
        surface_t *fb = &fbs[fb_idx];
        fb_idx ^= 1;
        rdpq_attach_clear(fb, &zbuf);
        render_frame();
        rdpq_detach_wait();
        world_observe(&obs);
        mev_end_frame(&obs, fb, audio_block);
#endif
    }
}
