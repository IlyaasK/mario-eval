// mev.c - mario-eval harness contract. PROTECTED (see mev.h).
#include "mev.h"
#include <libdragon.h>
#include <string.h>

static uint32_t mev_frame;

// IS-Viewer (development cartridge debug port): text buffer at 0x13FF0020,
// byte count written to 0x13FF0014. Retail cartridges ignore these writes.
#define ISV_BUFFER 0x13FF0020
#define ISV_LENGTH 0x13FF0014

static void isv_write(const char *text, int len)
{
    for (int i = 0; i < len; i += 4) {
        uint32_t word = 0;
        for (int b = 0; b < 4; b++) {
            word <<= 8;
            if (i + b < len) word |= (uint8_t)text[i + b];
        }
        io_write(ISV_BUFFER + i, word);
    }
    io_write(ISV_LENGTH, len);
}

void mev_init(void)
{
    mev_frame = 0;
}

// Synchronous controller read through the PIF (one joybus transaction), so
// the grader can answer it with the input for the current logical frame.
mev_pad_t mev_read_pad(void)
{
    uint8_t in[64] __attribute__((aligned(16)));
    uint8_t out[64] __attribute__((aligned(16)));
    memset(in, 0, sizeof(in));
    in[0] = 0x01;   // tx bytes
    in[1] = 0x04;   // rx bytes
    in[2] = 0x01;   // command: read buttons
    in[3] = 0xff; in[4] = 0xff; in[5] = 0xff; in[6] = 0xff;
    in[7] = 0xfe;   // end of commands
    in[63] = 0x01;  // PIF: execute joybus commands
    joybus_exec(in, out);
    mev_pad_t pad;
    pad.buttons = (uint16_t)(out[3] << 8 | out[4]);
    pad.x = (int8_t)out[5];
    pad.y = (int8_t)out[6];
    return pad;
}

static char *put_hex(char *p, uint32_t v)
{
    static const char digits[] = "0123456789abcdef";
    for (int shift = 28; shift >= 0; shift -= 4) *p++ = digits[(v >> shift) & 15];
    return p;
}

static char *put_dec(char *p, uint32_t v)
{
    char tmp[10];
    int n = 0;
    do { tmp[n++] = '0' + v % 10; v /= 10; } while (v);
    while (n) *p++ = tmp[--n];
    return p;
}

void mev_end_frame(const mev_obs_t *obs, const surface_t *fb, const int16_t *audio)
{
    // "@mev <frame> <obs_vaddr> <obs_len> <fb_paddr> <w> <h> <bpp> <au_paddr> <au_len>\n"
    char line[128];
    char *p = line;
    memcpy(p, "@mev ", 5); p += 5;
    p = put_dec(p, mev_frame); *p++ = ' ';
    p = put_hex(p, (uint32_t)obs); *p++ = ' ';
    p = put_dec(p, sizeof(mev_obs_t)); *p++ = ' ';
    p = put_hex(p, PhysicalAddr(fb->buffer)); *p++ = ' ';
    p = put_dec(p, fb->width); *p++ = ' ';
    p = put_dec(p, fb->height); *p++ = ' ';
    p = put_dec(p, TEX_FORMAT_BITDEPTH(surface_get_format(fb))); *p++ = ' ';
    p = put_hex(p, PhysicalAddr(audio)); *p++ = ' ';
    p = put_dec(p, MEV_AUDIO_SAMPLES * 2 * sizeof(int16_t));
    *p++ = '\n';
    isv_write(line, p - line);
    mev_frame++;
}
