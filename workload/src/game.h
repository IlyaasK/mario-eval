// game.h - Pip's Garden: the stand-in workload for mario-eval.
//
// A small fixed-timestep 3D game written the way a 1990s console game engine
// often was: correct, readable, and not tuned. Everything an optimizer may
// change lives in this directory except mev.c / mev.h (the harness contract).
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "mev.h"

#define SCREEN_W 320
#define SCREEN_H 240

#define FRAME_DT     (1.0f / 30.0f)
#define SUBSTEPS     4
#define ARENA        40.0f
#define GRAVITY      -25.0f

#define MAX_BOXES     48
#define MAX_ENEMIES   MEV_MAX_ENEMIES
#define MAX_GEMS      MEV_MAX_GEMS
#define MAX_PARTICLES 1024
#define MAX_VOICES    16

enum { SCENE_MEADOW, SCENE_FORTRESS, SCENE_STORM, SCENE_CONCERT, SCENE_COUNT };

enum { PLAYER_GROUND, PLAYER_AIR, PLAYER_DASH, PLAYER_HURT };
enum { ENEMY_WANDER, ENEMY_CHASE, ENEMY_STUNNED };
enum { PART_DUST, PART_RAIN, PART_SPARK };
enum { WAVE_SINE, WAVE_SQUARE, WAVE_TRIANGLE, WAVE_NOISE };

typedef struct { float x, y, z; } vec3_t;
typedef struct { float m[4][4]; } mat4_t;

typedef struct {
    vec3_t center;
    vec3_t half;
    float  yaw;          // visual only; collision is axis-aligned
    float  color[3];
} box_t;

typedef struct {
    vec3_t pos;
    vec3_t vel;
    float  yaw;
    int    state;
    int    timer;
    int    jump_held;
} player_t;

typedef struct {
    vec3_t pos;
    float  heading;
    int    state;
    int    timer;
    float  color[3];
} enemy_t;

typedef struct {
    vec3_t pos;
    float  spin;
    int    taken;
} gem_t;

typedef struct {
    vec3_t pos;
    vec3_t vel;
    float  life;
    float  size;
    float  color[4];
    int    kind;
    int    alive;
    int    pad[3];
} particle_t;

typedef struct {
    int   active;
    int   wave;
    float freq;
    float phase;
    float amp;
    float decay;
    float pan;
    float sweep;
} voice_t;

typedef struct {
    int       scene;
    uint32_t  frame;
    uint32_t  rng;
    int       gems_taken;
    int       score;
    int       hits;

    player_t  player;
    vec3_t    cam_pos;
    vec3_t    cam_target;
    float     cam_yaw;

    int       box_count;
    box_t     boxes[MAX_BOXES];
    int       enemy_count;
    enemy_t   enemies[MAX_ENEMIES];
    int       gem_count;
    gem_t     gems[MAX_GEMS];
    particle_t particles[MAX_PARTICLES];

    voice_t   voices[MAX_VOICES];
    uint32_t  noise;
    int       music_step;
} world_t;

extern world_t world;

// math3d.c
float  terrain_height(float x, float z);
vec3_t vec3(float x, float y, float z);
vec3_t vadd(vec3_t a, vec3_t b);
vec3_t vsub(vec3_t a, vec3_t b);
vec3_t vscale(vec3_t a, float s);
float  vdot(vec3_t a, vec3_t b);
vec3_t vcross(vec3_t a, vec3_t b);
float  vlength(vec3_t a);
vec3_t vnormalize(vec3_t a);
mat4_t mat_identity(void);
mat4_t mat_mul(mat4_t a, mat4_t b);
mat4_t mat_translate(float x, float y, float z);
mat4_t mat_scale(float x, float y, float z);
mat4_t mat_rotate_y(float a);
mat4_t mat_perspective(float fovy, float aspect, float znear, float zfar);
mat4_t mat_look_at(vec3_t eye, vec3_t target, vec3_t up);
void   mat_transform(const mat4_t *m, const float in[4], float out[4]);

// world.c
uint32_t rng_next(void);
float    rng_float(void);
void     world_init(int scene);
void     world_update(mev_pad_t pad);
void     world_observe(mev_obs_t *obs);

// render.c
void render_init(void);
void render_frame(void);

// synth.c
void synth_init(void);
void synth_trigger(int wave, float freq, float amp, float decay, float pan, float sweep);
void synth_frame(int16_t *out);
