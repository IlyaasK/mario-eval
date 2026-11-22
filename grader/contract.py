"""Layouts of mev_obs_t per workload target, for naming divergent fields.

The grader compares observation records byte-for-byte; this module turns a
byte offset into a human-readable field name for diagnostics.
"""
import struct

SCHEMAS = {
    "pips-garden": [
        ("frame", "I", 1), ("scene", "I", 1), ("rng", "I", 1),
        ("gems", "i", 1), ("score", "i", 1), ("hits", "i", 1),
        ("player_pos", "f", 3), ("player_vel", "f", 3), ("player_yaw", "f", 1),
        ("player_state", "I", 1), ("cam_pos", "f", 3), ("cam_target", "f", 3),
        ("enemy_pos", "f", 16 * 3), ("enemy_state", "I", 16),
        ("gem_mask", "I", 64 // 32), ("particles", "I", 1), ("voices", "I", 1),
    ],
    "sm64": [
        ("frame", "I", 1), ("level_area", "I", 1), ("rng", "I", 1), ("timer", "I", 1),
        ("mario_action", "I", 1), ("mario_prev_action", "I", 1),
        ("mario_flags", "I", 1), ("mario_action_state", "I", 1),
        ("mario_pos", "f", 3), ("mario_vel", "f", 3), ("mario_fvel", "f", 1),
        ("mario_floor_height", "f", 1), ("mario_ceil_height", "f", 1),
        ("mario_angles", "i", 3), ("mario_stats", "i", 4),
        ("cam_pos", "f", 3), ("cam_focus", "f", 3), ("cam_yaw_mode", "I", 1),
        ("actor_count", "I", 1),
        ("actor_pos", "f", 256 * 3), ("actor_state", "I", 256),
    ],
}

# Backwards-compatible aliases for Pip's Garden.
FIELDS = SCHEMAS["pips-garden"]
SIZE = sum(4 * n for _, _, n in FIELDS)


def size_of(schema_name="pips-garden"):
    fields = SCHEMAS[schema_name]
    return sum(4 * n for _, _, n in fields)


def decode(raw, schema_name="pips-garden"):
    fields = SCHEMAS[schema_name]
    out, offset = {}, 0
    for name, fmt, n in fields:
        values = struct.unpack_from(f">{n}{fmt}", raw, offset)
        out[name] = values[0] if n == 1 else list(values)
        offset += 4 * n
    return out


def field_at(offset, schema_name="pips-garden"):
    fields = SCHEMAS.get(schema_name, [])
    start = 0
    for name, _, n in fields:
        if offset < start + 4 * n:
            index = (offset - start) // 4
            return name if n == 1 else f"{name}[{index}]"
        start += 4 * n
    return f"word_{offset // 4}"


def first_difference(ref, cand, schema_name="pips-garden"):
    """Return (field, ref_value, cand_value) for the first differing word."""
    fields = SCHEMAS.get(schema_name, [])
    for offset in range(0, min(len(ref), len(cand)), 4):
        if ref[offset:offset + 4] != cand[offset:offset + 4]:
            name = field_at(offset, schema_name)
            base_name = name.split("[")[0]
            fmt = next((f for n, f, _ in fields if n == base_name), "I")
            r = struct.unpack(f">{fmt}", ref[offset:offset + 4])[0]
            c = struct.unpack(f">{fmt}", cand[offset:offset + 4])[0]
            return name, r, c
    if len(ref) != len(cand):
        return "length", len(ref), len(cand)
    return None
