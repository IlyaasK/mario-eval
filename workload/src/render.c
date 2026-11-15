// render.c - CPU transform and lighting, RDP rasterization (rdpq triangles).
#include <math.h>
#include <libdragon.h>
#include "game.h"

#define TERRAIN_CELLS 8
#define NEAR_W        0.5f
#define PIP_LOD_MEDIUM 12.0f   // camera distance beyond which Pip loses the visor
#define PIP_LOD_LOW    14.0f   // ... and the head

static mat4_t proj;
static mat4_t view;
static vec3_t light_dir;

// Unit cube, 12 triangles, counter-clockwise when seen from outside.
static const float cube_pos[8][3] = {
    {-1,-1,-1}, { 1,-1,-1}, { 1, 1,-1}, {-1, 1,-1},
    {-1,-1, 1}, { 1,-1, 1}, { 1, 1, 1}, {-1, 1, 1},
};
static const int cube_tri[12][3] = {
    {4,5,6}, {4,6,7}, {1,0,3}, {1,3,2}, {5,1,2}, {5,2,6},
    {0,4,7}, {0,7,3}, {7,6,2}, {7,2,3}, {0,1,5}, {0,5,4},
};

// Octahedron for gems.
static const float octa_pos[6][3] = {
    { 0, 1, 0}, { 0,-1, 0}, { 1, 0, 0}, {-1, 0, 0}, { 0, 0, 1}, { 0, 0,-1},
};
static const int octa_tri[8][3] = {
    {0,4,2}, {0,3,4}, {0,5,3}, {0,2,5}, {1,2,4}, {1,4,3}, {1,3,5}, {1,5,2},
};

void render_init(void)
{
    proj = mat_perspective(1.0471976f, (float)SCREEN_W / (float)SCREEN_H, 0.5f, 200.0f);
    light_dir = vnormalize(vec3(0.4f, 1.0f, 0.3f));
}

// Build an object's model matrix from its placement.
static mat4_t model_matrix(vec3_t pos, float yaw, vec3_t scale)
{
    mat4_t t = mat_translate(pos.x, pos.y, pos.z);
    mat4_t r = mat_rotate_y(yaw);
    mat4_t s = mat_scale(scale.x, scale.y, scale.z);
    return mat_mul(t, mat_mul(r, s));
}

// Project one vertex through a model-view-projection matrix to an rdpq
// vertex {X, Y, Z, R, G, B, A}. Returns false if behind the near plane.
static bool project_vertex(const mat4_t *mvp, const float local[3],
                           float shade, const float color[4], float out[7])
{
    float in[4] = { local[0], local[1], local[2], 1.0f };
    float clip[4];
    mat_transform(mvp, in, clip);
    if (clip[3] < NEAR_W) return false;
    float inv_w = 1.0f / clip[3];
    out[0] = (clip[0] * inv_w * 0.5f + 0.5f) * SCREEN_W;
    out[1] = (1.0f - (clip[1] * inv_w * 0.5f + 0.5f)) * SCREEN_H;
    float z = clip[2] * inv_w * 0.5f + 0.5f;
    out[2] = z < 0.0f ? 0.0f : (z > 1.0f ? 1.0f : z);
    out[3] = color[0] * shade;
    out[4] = color[1] * shade;
    out[5] = color[2] * shade;
    out[6] = color[3];
    return true;
}

// Project a world-space point for a billboard (rebuilds view-projection).
static bool project_world(const float world_pos[3], float shade, const float color[4], float out[7])
{
    mat4_t vp = mat_mul(proj, view);
    return project_vertex(&vp, world_pos, shade, color, out);
}

static float face_shade(vec3_t a, vec3_t b, vec3_t c)
{
    vec3_t n = vnormalize(vcross(vsub(b, a), vsub(c, a)));
    float d = vdot(n, light_dir);
    if (d < 0.0f) d = 0.0f;
    return 0.35f + 0.65f * d;
}

static void draw_triangle(const float a[7], const float b[7], const float c[7])
{
    float area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
    if (area >= 0.0f) return;  // back-facing (screen y points down)
    rdpq_triangle(&TRIFMT_ZBUF_SHADE, a, b, c);
}

// Draw an indexed mesh with flat per-face lighting. Shared vertices are
// transformed once per triangle that uses them.
static void draw_mesh(const float (*verts)[3], const int (*tris)[3], int ntris,
                      vec3_t pos, float yaw, vec3_t scale, const float color[4])
{
    mat4_t model = model_matrix(pos, yaw, scale);
    mat4_t mvp = mat_mul(proj, mat_mul(view, model));
    mat4_t rot = mat_rotate_y(yaw);
    for (int t = 0; t < ntris; t++) {
        // Face normal in model space, rotated into the world for lighting.
        const float *a = verts[tris[t][0]], *b = verts[tris[t][1]], *c = verts[tris[t][2]];
        vec3_t n = vnormalize(vcross(vec3(b[0] - a[0], b[1] - a[1], b[2] - a[2]),
                                     vec3(c[0] - a[0], c[1] - a[1], c[2] - a[2])));
        float in[4] = { n.x, n.y, n.z, 0.0f }, out[4];
        mat_transform(&rot, in, out);
        float d = vdot(vec3(out[0], out[1], out[2]), light_dir);
        float shade = 0.35f + 0.65f * (d < 0.0f ? 0.0f : d);
        float v[3][7];
        bool ok = true;
        for (int k = 0; k < 3; k++)
            ok = ok && project_vertex(&mvp, verts[tris[t][k]], shade, color, v[k]);
        if (ok) draw_triangle(v[0], v[1], v[2]);
    }
}

static void draw_terrain(void)
{
    const float cell = (2.0f * ARENA) / TERRAIN_CELLS;
    const float green[4] = { 0.35f, 0.62f, 0.30f, 1.0f };
    const float dark[4] = { 0.30f, 0.54f, 0.27f, 1.0f };
    mat4_t vp = mat_mul(proj, view);
    // Heights are recomputed for every triangle corner that uses them.
    for (int i = 0; i < TERRAIN_CELLS; i++) {
        for (int j = 0; j < TERRAIN_CELLS; j++) {
            float x0 = -ARENA + i * cell, x1 = x0 + cell;
            float z0 = -ARENA + j * cell, z1 = z0 + cell;
            vec3_t p00 = vec3(x0, terrain_height(x0, z0), z0);
            vec3_t p10 = vec3(x1, terrain_height(x1, z0), z0);
            vec3_t p11 = vec3(x1, terrain_height(x1, z1), z1);
            vec3_t p01 = vec3(x0, terrain_height(x0, z1), z1);
            const float *col = ((i + j) & 1) ? green : dark;
            vec3_t quad[2][3] = { { p00, p11, p10 }, { p00, p01, p11 } };
            for (int t = 0; t < 2; t++) {
                float shade = face_shade(quad[t][0], quad[t][1], quad[t][2]);
                float v[3][7];
                bool ok = true;
                for (int k = 0; k < 3; k++) {
                    float local[3] = { quad[t][k].x, quad[t][k].y, quad[t][k].z };
                    ok = ok && project_vertex(&vp, local, shade, col, v[k]);
                }
                if (ok) draw_triangle(v[0], v[1], v[2]);
            }
        }
    }
}

// Camera-facing quad, built from the view matrix for each billboard.
static void draw_billboard(vec3_t pos, float size, const float color[4])
{
    mat4_t inv_rot = mat_identity();
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            inv_rot.m[i][j] = view.m[j][i];
    vec3_t right = vec3(inv_rot.m[0][0], inv_rot.m[1][0], inv_rot.m[2][0]);
    vec3_t up = vec3(inv_rot.m[0][1], inv_rot.m[1][1], inv_rot.m[2][1]);
    vec3_t corners[4] = {
        vadd(pos, vadd(vscale(right, -size), vscale(up, -size))),
        vadd(pos, vadd(vscale(right,  size), vscale(up, -size))),
        vadd(pos, vadd(vscale(right,  size), vscale(up,  size))),
        vadd(pos, vadd(vscale(right, -size), vscale(up,  size))),
    };
    float v[4][7];
    for (int k = 0; k < 4; k++) {
        float local[3] = { corners[k].x, corners[k].y, corners[k].z };
        if (!project_world(local, 1.0f, color, v[k])) return;
    }
    rdpq_triangle(&TRIFMT_ZBUF_SHADE, v[0], v[1], v[2]);
    rdpq_triangle(&TRIFMT_ZBUF_SHADE, v[0], v[2], v[3]);
}

// Blob shadow: sample the floor at five points under the object.
static void draw_shadow(vec3_t pos, float radius)
{
    float h = -1e9f;
    const float off[5][2] = { {0,0}, {radius,0}, {-radius,0}, {0,radius}, {0,-radius} };
    for (int s = 0; s < 5; s++) {
        float x = pos.x + off[s][0], z = pos.z + off[s][1];
        float fh = terrain_height(x, z);
        for (int i = 0; i < world.box_count; i++) {
            const box_t *b = &world.boxes[i];
            if (fabsf(x - b->center.x) > b->half.x || fabsf(z - b->center.z) > b->half.z) continue;
            float top = b->center.y + b->half.y;
            if (top <= pos.y && top > fh) fh = top;
        }
        if (fh > h) h = fh;
    }
    const float col[4] = { 0.1f, 0.1f, 0.1f, 1.0f };
    mat4_t vp = mat_mul(proj, view);
    float v[4][7];
    float local[4][3] = {
        { pos.x - radius, h + 0.05f, pos.z - radius }, { pos.x + radius, h + 0.05f, pos.z - radius },
        { pos.x + radius, h + 0.05f, pos.z + radius }, { pos.x - radius, h + 0.05f, pos.z + radius },
    };
    for (int k = 0; k < 4; k++)
        if (!project_vertex(&vp, local[k], 1.0f, col, v[k])) return;
    draw_triangle(v[0], v[2], v[1]);
    draw_triangle(v[0], v[3], v[2]);
}

void render_frame(void)
{
    view = mat_look_at(world.cam_pos, world.cam_target, vec3(0, 1, 0));

    rdpq_set_mode_standard();
    rdpq_mode_combiner(RDPQ_COMBINER_SHADE);
    rdpq_mode_zbuf(true, true);

    draw_terrain();

    for (int i = 0; i < world.box_count; i++) {
        const box_t *b = &world.boxes[i];
        const float col[4] = { b->color[0], b->color[1], b->color[2], 1.0f };
        draw_mesh(cube_pos, cube_tri, 12, b->center, b->yaw, b->half, col);
    }

    for (int i = 0; i < world.enemy_count; i++) {
        const enemy_t *e = &world.enemies[i];
        const float col[4] = { e->color[0], e->color[1], e->color[2], 1.0f };
        float squash = e->state == ENEMY_STUNNED ? 0.35f : 0.6f;
        draw_mesh(cube_pos, cube_tri, 12, e->pos, e->heading, vec3(0.7f, squash, 0.7f), col);
        draw_shadow(e->pos, 0.7f);
    }

    for (int i = 0; i < world.gem_count; i++) {
        const gem_t *g = &world.gems[i];
        if (g->taken) continue;
        const float col[4] = { 0.3f, 0.85f, 1.0f, 1.0f };
        draw_mesh(octa_pos, octa_tri, 8, g->pos, g->spin, vec3(0.5f, 0.7f, 0.5f), col);
    }

    // Pip: a round-ish robot (body, head, eye visor). Like Mario in SM64, Pip
    // has detail levels: the visor, then the head, are dropped when the camera
    // is far away.
    const player_t *pl = &world.player;
    const float body[4] = { 0.95f, 0.75f, 0.2f, 1.0f };
    const float head[4] = { 0.9f, 0.9f, 0.85f, 1.0f };
    const float visor[4] = { 0.15f, 0.2f, 0.35f, 1.0f };
    float cam_dist = vlength(vsub(world.cam_pos, pl->pos));
    int lod = cam_dist < PIP_LOD_MEDIUM ? 0 : (cam_dist < PIP_LOD_LOW ? 1 : 2);
    bool blink = pl->state == PLAYER_HURT && (pl->timer & 2);
    if (!blink) {
        draw_mesh(cube_pos, cube_tri, 12, pl->pos, pl->yaw, vec3(0.6f, 0.45f, 0.6f), body);
        vec3_t head_pos = vadd(pl->pos, vec3(0, 0.75f, 0));
        if (lod <= 1)
            draw_mesh(cube_pos, cube_tri, 12, head_pos, pl->yaw, vec3(0.45f, 0.35f, 0.45f), head);
        vec3_t eye_pos = vadd(head_pos, vec3(sinf(pl->yaw) * 0.42f, 0.05f, cosf(pl->yaw) * 0.42f));
        if (lod == 0)
            draw_mesh(cube_pos, cube_tri, 12, eye_pos, pl->yaw, vec3(0.32f, 0.1f, 0.06f), visor);
    }
    draw_shadow(pl->pos, 0.8f);

    for (int i = 0; i < MAX_PARTICLES; i++) {
        const particle_t *p = &world.particles[i];
        if (!p->alive) continue;
        draw_billboard(p->pos, p->size, p->color);
    }
}
