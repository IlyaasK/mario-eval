// math3d.c - vectors, 4x4 matrices and the terrain height field.
#include <math.h>
#include "game.h"

float terrain_height(float x, float z)
{
    return 1.5f * sinf(x * 0.15f) * cosf(z * 0.12f)
         + 0.8f * sinf((x + z) * 0.07f)
         + 0.3f * cosf(x * 0.31f - z * 0.23f);
}

vec3_t vec3(float x, float y, float z) { vec3_t v = { x, y, z }; return v; }
vec3_t vadd(vec3_t a, vec3_t b) { return vec3(a.x + b.x, a.y + b.y, a.z + b.z); }
vec3_t vsub(vec3_t a, vec3_t b) { return vec3(a.x - b.x, a.y - b.y, a.z - b.z); }
vec3_t vscale(vec3_t a, float s) { return vec3(a.x * s, a.y * s, a.z * s); }
float  vdot(vec3_t a, vec3_t b) { return a.x * b.x + a.y * b.y + a.z * b.z; }

vec3_t vcross(vec3_t a, vec3_t b)
{
    return vec3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
}

float vlength(vec3_t a) { return sqrtf(vdot(a, a)); }

vec3_t vnormalize(vec3_t a)
{
    float len = vlength(a);
    if (len < 1e-6f) return vec3(0, 1, 0);
    return vscale(a, 1.0f / len);
}

mat4_t mat_identity(void)
{
    mat4_t r;
    for (int i = 0; i < 4; i++)
        for (int j = 0; j < 4; j++)
            r.m[i][j] = (i == j) ? 1.0f : 0.0f;
    return r;
}

mat4_t mat_mul(mat4_t a, mat4_t b)
{
    mat4_t r;
    for (int i = 0; i < 4; i++) {
        for (int j = 0; j < 4; j++) {
            float s = 0.0f;
            for (int k = 0; k < 4; k++) s += a.m[i][k] * b.m[k][j];
            r.m[i][j] = s;
        }
    }
    return r;
}

mat4_t mat_translate(float x, float y, float z)
{
    mat4_t r = mat_identity();
    r.m[0][3] = x; r.m[1][3] = y; r.m[2][3] = z;
    return r;
}

mat4_t mat_scale(float x, float y, float z)
{
    mat4_t r = mat_identity();
    r.m[0][0] = x; r.m[1][1] = y; r.m[2][2] = z;
    return r;
}

mat4_t mat_rotate_y(float a)
{
    mat4_t r = mat_identity();
    float c = cosf(a), s = sinf(a);
    r.m[0][0] = c;  r.m[0][2] = s;
    r.m[2][0] = -s; r.m[2][2] = c;
    return r;
}

mat4_t mat_perspective(float fovy, float aspect, float znear, float zfar)
{
    mat4_t r;
    for (int i = 0; i < 4; i++) for (int j = 0; j < 4; j++) r.m[i][j] = 0.0f;
    float f = 1.0f / tanf(fovy * 0.5f);
    r.m[0][0] = f / aspect;
    r.m[1][1] = f;
    r.m[2][2] = (zfar + znear) / (znear - zfar);
    r.m[2][3] = (2.0f * zfar * znear) / (znear - zfar);
    r.m[3][2] = -1.0f;
    return r;
}

mat4_t mat_look_at(vec3_t eye, vec3_t target, vec3_t up)
{
    vec3_t f = vnormalize(vsub(target, eye));
    vec3_t s = vnormalize(vcross(f, up));
    vec3_t u = vcross(s, f);
    mat4_t r = mat_identity();
    r.m[0][0] = s.x;  r.m[0][1] = s.y;  r.m[0][2] = s.z;  r.m[0][3] = -vdot(s, eye);
    r.m[1][0] = u.x;  r.m[1][1] = u.y;  r.m[1][2] = u.z;  r.m[1][3] = -vdot(u, eye);
    r.m[2][0] = -f.x; r.m[2][1] = -f.y; r.m[2][2] = -f.z; r.m[2][3] = vdot(f, eye);
    return r;
}

void mat_transform(const mat4_t *m, const float in[4], float out[4])
{
    for (int i = 0; i < 4; i++) {
        float s = 0.0f;
        for (int k = 0; k < 4; k++) s += m->m[i][k] * in[k];
        out[i] = s;
    }
}
