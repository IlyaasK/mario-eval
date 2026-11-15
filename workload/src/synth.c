// synth.c - per-sample software synthesizer (CPU), MEV_AUDIO_SAMPLES per frame.
#include <math.h>
#include <string.h>
#include "game.h"

void synth_init(void)
{
    memset(world.voices, 0, sizeof(world.voices));
}

void synth_trigger(int wave, float freq, float amp, float decay, float pan, float sweep)
{
    // Steal the quietest voice when all are busy.
    int best = 0;
    for (int i = 0; i < MAX_VOICES; i++) {
        if (!world.voices[i].active) { best = i; break; }
        if (world.voices[i].amp < world.voices[best].amp) best = i;
    }
    voice_t *v = &world.voices[best];
    v->active = 1;
    v->wave = wave;
    v->freq = freq;
    v->phase = 0.0f;
    v->amp = amp;
    v->decay = decay;
    v->pan = pan;
    v->sweep = sweep;
}

static float oscillator(voice_t *v)
{
    const float two_pi = 6.2831853f;
    switch (v->wave) {
    case WAVE_SINE:
        return sinf(v->phase * two_pi);
    case WAVE_SQUARE:
        return sinf(v->phase * two_pi) >= 0.0f ? 0.6f : -0.6f;
    case WAVE_TRIANGLE:
        return asinf(sinf(v->phase * two_pi)) * 0.63661977f;
    default: {
        world.noise = world.noise * 1103515245u + 12345u;
        return (float)((world.noise >> 16) & 0x7fff) / 16384.0f - 1.0f;
    }
    }
}

void synth_frame(int16_t *out)
{
    for (int s = 0; s < MEV_AUDIO_SAMPLES; s++) {
        float left = 0.0f, right = 0.0f;
        for (int i = 0; i < MAX_VOICES; i++) {
            voice_t *v = &world.voices[i];
            if (!v->active) continue;
            float x = oscillator(v) * v->amp;
            left += x * (0.5f - 0.5f * v->pan);
            right += x * (0.5f + 0.5f * v->pan);
            v->phase = fmodf(v->phase + v->freq / (float)MEV_AUDIO_RATE, 1.0f);
            v->freq *= v->sweep;
            v->amp *= v->decay;
            if (v->amp < 0.001f) v->active = 0;
        }
        int l = (int)(left * 32767.0f), r = (int)(right * 32767.0f);
        out[s * 2 + 0] = (int16_t)(l > 32767 ? 32767 : (l < -32768 ? -32768 : l));
        out[s * 2 + 1] = (int16_t)(r > 32767 ? 32767 : (r < -32768 ? -32768 : r));
    }
}
