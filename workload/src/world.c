// world.c - scene setup and fixed-timestep simulation.
#include <math.h>
#include <string.h>
#include "game.h"

world_t world;

// Unused "level streaming" cache, kept from an earlier design. It is cleared
// at startup, so it occupies RDRAM for the whole run.
static uint8_t level_cache[256 * 1024];

uint32_t rng_next(void)
{
    uint32_t x = world.rng;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    world.rng = x;
    return x;
}

float rng_float(void)
{
    return (float)(rng_next() & 0xffff) / 65536.0f;
}

typedef struct {
    int   boxes, enemies, gems;
    float box_size;
    float enemy_speed;
    uint32_t seed;
} scene_def_t;

static const scene_def_t scene_defs[SCENE_COUNT] = {
    [SCENE_MEADOW]   = { 10,  6, 20, 2.0f, 4.0f, 0x1234567u },
    [SCENE_FORTRESS] = { 24, 10, 14, 2.5f, 5.0f, 0x2468aceu },
    [SCENE_STORM]    = { 10,  6, 12, 2.0f, 4.5f, 0x13579bdu },
    [SCENE_CONCERT]  = {  6,  4, 10, 1.5f, 3.0f, 0x0f1e2d3u },
};

void world_init(int scene)
{
    memset(&world, 0, sizeof(world));
    memset(level_cache, 0, sizeof(level_cache));
    const scene_def_t *def = &scene_defs[scene];
    world.scene = scene;
    world.rng = def->seed;
    world.noise = 0xace1u;

    world.box_count = def->boxes;
    for (int i = 0; i < def->boxes; i++) {
        box_t *b = &world.boxes[i];
        float x = (rng_float() * 2.0f - 1.0f) * (ARENA - 6.0f);
        float z = (rng_float() * 2.0f - 1.0f) * (ARENA - 6.0f);
        if (fabsf(x) < 5.0f && fabsf(z) < 5.0f) x += 10.0f;
        float hx = def->box_size * (0.6f + rng_float());
        float hy = def->box_size * (0.4f + rng_float() * 1.2f);
        float hz = def->box_size * (0.6f + rng_float());
        b->center = vec3(x, terrain_height(x, z) + hy, z);
        b->half = vec3(hx, hy, hz);
        b->yaw = 0.0f;
        b->color[0] = 0.55f + 0.3f * rng_float();
        b->color[1] = 0.45f + 0.2f * rng_float();
        b->color[2] = 0.35f + 0.2f * rng_float();
    }

    world.enemy_count = def->enemies;
    for (int i = 0; i < def->enemies; i++) {
        enemy_t *e = &world.enemies[i];
        float x = (rng_float() * 2.0f - 1.0f) * (ARENA - 4.0f);
        float z = (rng_float() * 2.0f - 1.0f) * (ARENA - 4.0f);
        e->pos = vec3(x, terrain_height(x, z) + 0.7f, z);
        e->heading = rng_float() * 6.2831853f;
        e->state = ENEMY_WANDER;
        e->timer = 30 + (int)(rng_next() % 60);
        e->color[0] = 0.8f; e->color[1] = 0.25f + 0.2f * rng_float(); e->color[2] = 0.3f;
    }

    world.gem_count = def->gems;
    for (int i = 0; i < def->gems; i++) {
        gem_t *g = &world.gems[i];
        float ring = 6.0f + (float)(i % 4) * 7.0f;
        float a = (float)i * 2.399963f + rng_float() * 0.3f;
        float x = cosf(a) * ring;
        float z = sinf(a) * ring;
        g->pos = vec3(x, terrain_height(x, z) + 1.2f, z);
        g->spin = rng_float() * 6.2831853f;
        g->taken = 0;
    }

    world.player.pos = vec3(0.0f, terrain_height(0.0f, 0.0f) + 0.8f, 0.0f);
    world.player.state = PLAYER_GROUND;
    world.cam_yaw = 0.0f;
    world.cam_target = vadd(world.player.pos, vec3(0, 1, 0));
    world.cam_pos = vadd(world.cam_target, vec3(0, 5, -10));
}

static void spawn_particle(int kind, vec3_t pos, vec3_t vel, float life, float size,
                           float r, float g, float b, float a)
{
    for (int i = 0; i < MAX_PARTICLES; i++) {
        particle_t *p = &world.particles[i];
        if (p->alive) continue;
        p->alive = 1;
        p->kind = kind;
        p->pos = pos;
        p->vel = vel;
        p->life = life;
        p->size = size;
        p->color[0] = r; p->color[1] = g; p->color[2] = b; p->color[3] = a;
        return;
    }
}

// Push a sphere of the given radius out of every box it overlaps.
static vec3_t collide_boxes(vec3_t p, float radius, vec3_t *vel)
{
    for (int i = 0; i < world.box_count; i++) {
        const box_t *b = &world.boxes[i];
        float dx = p.x - b->center.x;
        float dy = p.y - b->center.y;
        float dz = p.z - b->center.z;
        float ox = b->half.x + radius - fabsf(dx);
        float oy = b->half.y + radius - fabsf(dy);
        float oz = b->half.z + radius - fabsf(dz);
        if (ox <= 0.0f || oy <= 0.0f || oz <= 0.0f) continue;
        if (oy < ox && oy < oz) {
            p.y += dy > 0.0f ? oy : -oy;
            if (vel && ((dy > 0.0f && vel->y < 0.0f) || (dy < 0.0f && vel->y > 0.0f))) vel->y = 0.0f;
        } else if (ox < oz) {
            p.x += dx > 0.0f ? ox : -ox;
            if (vel) vel->x = 0.0f;
        } else {
            p.z += dz > 0.0f ? oz : -oz;
            if (vel) vel->z = 0.0f;
        }
    }
    return p;
}

// Highest walkable surface (terrain or box top) under a point.
static float floor_height(float x, float z, float y)
{
    float h = terrain_height(x, z);
    for (int i = 0; i < world.box_count; i++) {
        const box_t *b = &world.boxes[i];
        if (fabsf(x - b->center.x) > b->half.x || fabsf(z - b->center.z) > b->half.z) continue;
        float top = b->center.y + b->half.y;
        if (top <= y + 0.25f && top > h) h = top;
    }
    return h;
}

static float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

static void update_player(mev_pad_t pad)
{
    player_t *pl = &world.player;
    const float radius = 0.8f;

    float sx = (float)pad.x / 80.0f;
    float sy = (float)pad.y / 80.0f;
    if (fabsf(sx) < 0.1f) sx = 0.0f;
    if (fabsf(sy) < 0.1f) sy = 0.0f;
    float cs = cosf(world.cam_yaw), sn = sinf(world.cam_yaw);
    vec3_t want = vec3(sx * cs + sy * sn, 0.0f, -sx * sn + sy * cs);
    float speed = pl->state == PLAYER_DASH ? 14.0f : 8.0f;

    if (pl->state == PLAYER_HURT) {
        if (--pl->timer <= 0) pl->state = PLAYER_AIR;
        want = vec3(0, 0, 0);
    }
    if (pl->state == PLAYER_DASH && --pl->timer <= 0) pl->state = PLAYER_GROUND;

    bool grounded = pl->state == PLAYER_GROUND || pl->state == PLAYER_DASH;
    float accel = grounded ? 40.0f : 14.0f;
    pl->vel.x += clampf(want.x * speed - pl->vel.x, -accel * FRAME_DT, accel * FRAME_DT);
    pl->vel.z += clampf(want.z * speed - pl->vel.z, -accel * FRAME_DT, accel * FRAME_DT);
    if (want.x != 0.0f || want.z != 0.0f) pl->yaw = atan2f(want.x, want.z);

    if ((pad.buttons & MEV_A) && !pl->jump_held && grounded) {
        pl->vel.y = 9.0f;
        pl->state = PLAYER_AIR;
        synth_trigger(WAVE_SQUARE, 330.0f, 0.18f, 0.9994f, 0.0f, 1.0006f);
    }
    pl->jump_held = (pad.buttons & MEV_A) != 0;
    if ((pad.buttons & MEV_B) && pl->state == PLAYER_GROUND) {
        pl->state = PLAYER_DASH;
        pl->timer = 12;
        synth_trigger(WAVE_NOISE, 1000.0f, 0.10f, 0.9990f, 0.0f, 1.0f);
    }

    float h = FRAME_DT / SUBSTEPS;
    for (int step = 0; step < SUBSTEPS; step++) {
        pl->vel.y += GRAVITY * h;
        pl->pos = vadd(pl->pos, vscale(pl->vel, h));
        pl->pos.x = clampf(pl->pos.x, -ARENA, ARENA);
        pl->pos.z = clampf(pl->pos.z, -ARENA, ARENA);
        pl->pos = collide_boxes(pl->pos, radius, &pl->vel);

        float ground = floor_height(pl->pos.x, pl->pos.z, pl->pos.y - radius);
        if (pl->pos.y - radius <= ground) {
            pl->pos.y = ground + radius;
            if (pl->vel.y < 0.0f) pl->vel.y = 0.0f;
            if (pl->state == PLAYER_AIR) pl->state = PLAYER_GROUND;
        } else if (pl->state == PLAYER_GROUND || pl->state == PLAYER_DASH) {
            if (pl->pos.y - radius > ground + 0.3f) pl->state = PLAYER_AIR;
        }

        for (int i = 0; i < world.gem_count; i++) {
            gem_t *g = &world.gems[i];
            if (g->taken) continue;
            if (vlength(vsub(g->pos, pl->pos)) < 1.5f) {
                g->taken = 1;
                world.gems_taken++;
                world.score += 100;
                synth_trigger(WAVE_SINE, 1318.5f, 0.22f, 0.9992f, 0.3f, 1.0f);
                synth_trigger(WAVE_SINE, 1975.5f, 0.12f, 0.9990f, -0.3f, 1.0f);
                for (int s = 0; s < 12; s++) {
                    float a = (float)s * 0.5235988f;
                    spawn_particle(PART_SPARK, g->pos, vec3(cosf(a) * 3.0f, 4.0f, sinf(a) * 3.0f),
                                   0.6f, 0.25f, 1.0f, 0.9f, 0.3f, 1.0f);
                }
            }
        }
    }

    if (grounded && vlength(vec3(pl->vel.x, 0, pl->vel.z)) > 6.0f) {
        vec3_t at = vsub(pl->pos, vec3(0, 0.7f, 0));
        spawn_particle(PART_DUST, at, vec3(rng_float() - 0.5f, 1.0f, rng_float() - 0.5f),
                       0.5f, 0.35f, 0.7f, 0.65f, 0.5f, 0.8f);
    }
}

static void update_enemies(void)
{
    player_t *pl = &world.player;
    const scene_def_t *def = &scene_defs[world.scene];
    for (int i = 0; i < world.enemy_count; i++) {
        enemy_t *e = &world.enemies[i];
        vec3_t to_player = vsub(pl->pos, e->pos);
        float dist = vlength(to_player);

        if (e->state == ENEMY_STUNNED) {
            if (--e->timer <= 0) { e->state = ENEMY_WANDER; e->timer = 40; }
            continue;
        }
        if (dist < 10.0f) {
            e->state = ENEMY_CHASE;
            e->heading = atan2f(to_player.x, to_player.z);
        } else {
            e->state = ENEMY_WANDER;
            if (--e->timer <= 0) {
                e->heading += (rng_float() - 0.5f) * 2.5f;
                e->timer = 30 + (int)(rng_next() % 60);
            }
        }

        float speed = def->enemy_speed * (e->state == ENEMY_CHASE ? 1.4f : 1.0f);
        vec3_t step = vec3(sinf(e->heading) * speed * FRAME_DT, 0.0f, cosf(e->heading) * speed * FRAME_DT);
        vec3_t next = vadd(e->pos, step);
        if (fabsf(next.x) > ARENA - 1.0f || fabsf(next.z) > ARENA - 1.0f) {
            e->heading += 3.14159265f;
            next = e->pos;
        }
        next = collide_boxes(next, 0.7f, 0);
        next.y = floor_height(next.x, next.z, next.y - 0.7f) + 0.7f;
        e->pos = next;

        if (dist < 1.6f && pl->state != PLAYER_HURT) {
            world.hits++;
            world.score = world.score > 50 ? world.score - 50 : 0;
            vec3_t away = vnormalize(vec3(to_player.x, 0, to_player.z));
            pl->vel = vadd(vscale(away, 10.0f), vec3(0, 6.0f, 0));
            pl->state = PLAYER_HURT;
            pl->timer = 20;
            e->state = ENEMY_STUNNED;
            e->timer = 45;
            synth_trigger(WAVE_NOISE, 200.0f, 0.25f, 0.9993f, 0.0f, 0.9998f);
        }
    }
}

static void update_particles(void)
{
    if (world.scene == SCENE_STORM) {
        for (int s = 0; s < 3; s++) {
            float x = world.player.pos.x + (rng_float() - 0.5f) * 40.0f;
            float z = world.player.pos.z + (rng_float() - 0.5f) * 40.0f;
            spawn_particle(PART_RAIN, vec3(x, 18.0f + rng_float() * 4.0f, z), vec3(0.6f, -22.0f, 0.2f),
                           2.0f, 0.12f, 0.6f, 0.7f, 0.9f, 0.7f);
        }
    }
    for (int i = 0; i < MAX_PARTICLES; i++) {
        particle_t *p = &world.particles[i];
        if (!p->alive) continue;
        p->life -= FRAME_DT;
        if (p->kind != PART_RAIN) p->vel.y += GRAVITY * 0.3f * FRAME_DT;
        p->pos = vadd(p->pos, vscale(p->vel, FRAME_DT));
        if (p->life <= 0.0f || p->pos.y < terrain_height(p->pos.x, p->pos.z)) p->alive = 0;
    }
}

static void update_camera(mev_pad_t pad)
{
    if (pad.buttons & MEV_CLEFT) world.cam_yaw += 2.5f * FRAME_DT;
    if (pad.buttons & MEV_CRIGHT) world.cam_yaw -= 2.5f * FRAME_DT;
    float dist = (pad.buttons & MEV_CDOWN) ? 15.0f : 10.0f;
    vec3_t target = vadd(world.player.pos, vec3(0, 1.0f, 0));
    vec3_t want = vadd(target, vec3(-sinf(world.cam_yaw) * dist, 5.0f, -cosf(world.cam_yaw) * dist));
    float floor_y = terrain_height(want.x, want.z) + 1.0f;
    if (want.y < floor_y) want.y = floor_y;
    world.cam_pos = vadd(world.cam_pos, vscale(vsub(want, world.cam_pos), 0.2f));
    world.cam_target = vadd(world.cam_target, vscale(vsub(target, world.cam_target), 0.3f));
}

static void update_music(void)
{
    // Generated pentatonic arpeggio over a four-chord loop; one step every
    // 8 frames. The concert scene layers extra voices on every step.
    static const float roots[4] = { 220.0f, 174.61f, 196.0f, 146.83f };
    static const float scale[5] = { 1.0f, 1.125f, 1.25f, 1.5f, 1.6667f };
    if (world.frame % 8 != 0) return;
    int step = world.music_step++;
    float root = roots[(step / 16) % 4];
    float note = root * scale[(step * 3 + step / 5) % 5] * ((step & 4) ? 2.0f : 1.0f);
    synth_trigger(WAVE_TRIANGLE, note, 0.12f, 0.9990f, ((step & 1) ? 0.4f : -0.4f), 1.0f);
    if (step % 4 == 0) synth_trigger(WAVE_SINE, root * 0.5f, 0.16f, 0.9994f, 0.0f, 1.0f);
    if (world.scene == SCENE_CONCERT) {
        synth_trigger(WAVE_SQUARE, note * 1.5f, 0.05f, 0.9990f, 0.6f, 1.0f);
        synth_trigger(WAVE_TRIANGLE, note * 2.0f, 0.06f, 0.9988f, -0.6f, 1.0f);
        synth_trigger(WAVE_SINE, root * 1.25f, 0.07f, 0.9992f, 0.2f, 1.0f);
    }
}

void world_update(mev_pad_t pad)
{
    update_music();
    update_player(pad);
    update_enemies();
    update_particles();
    update_camera(pad);
    for (int i = 0; i < world.gem_count; i++) world.gems[i].spin += 2.0f * FRAME_DT;
    world.frame++;
}

void world_observe(mev_obs_t *obs)
{
    memset(obs, 0, sizeof(*obs));
    obs->frame = world.frame;
    obs->scene = world.scene;
    obs->rng = world.rng;
    obs->gems = world.gems_taken;
    obs->score = world.score;
    obs->hits = world.hits;
    obs->player_pos[0] = world.player.pos.x;
    obs->player_pos[1] = world.player.pos.y;
    obs->player_pos[2] = world.player.pos.z;
    obs->player_vel[0] = world.player.vel.x;
    obs->player_vel[1] = world.player.vel.y;
    obs->player_vel[2] = world.player.vel.z;
    obs->player_yaw = world.player.yaw;
    obs->player_state = world.player.state;
    obs->cam_pos[0] = world.cam_pos.x;
    obs->cam_pos[1] = world.cam_pos.y;
    obs->cam_pos[2] = world.cam_pos.z;
    obs->cam_target[0] = world.cam_target.x;
    obs->cam_target[1] = world.cam_target.y;
    obs->cam_target[2] = world.cam_target.z;
    for (int i = 0; i < world.enemy_count; i++) {
        obs->enemy_pos[i][0] = world.enemies[i].pos.x;
        obs->enemy_pos[i][1] = world.enemies[i].pos.y;
        obs->enemy_pos[i][2] = world.enemies[i].pos.z;
        obs->enemy_state[i] = world.enemies[i].state;
    }
    for (int i = 0; i < world.gem_count; i++)
        if (world.gems[i].taken) obs->gem_mask[i / 32] |= 1u << (i % 32);
    for (int i = 0; i < MAX_PARTICLES; i++) obs->particles += world.particles[i].alive;
    for (int i = 0; i < MAX_VOICES; i++) obs->voices += world.voices[i].active;
}
