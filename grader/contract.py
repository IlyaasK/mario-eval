"""Layout of mev_obs_t (workload/src/mev.h), for naming divergent fields.

The grader compares observation records byte-for-byte; this module only turns
a byte offset into a field name for diagnostics.
"""
import struct

MAX_ENEMIES = 16
MAX_GEMS = 64

# (name, struct format, count) in declaration order; big-endian MIPS.
FIELDS = [
    ("frame", "I", 1), ("scene", "I", 1), ("rng", "I", 1),
    ("gems", "i", 1), ("score", "i", 1), ("hits", "i", 1),
    ("player_pos", "f", 3), ("player_vel", "f", 3), ("player_yaw", "f", 1),
    ("player_state", "I", 1), ("cam_pos", "f", 3), ("cam_target", "f", 3),
    ("enemy_pos", "f", MAX_ENEMIES * 3), ("enemy_state", "I", MAX_ENEMIES),
    ("gem_mask", "I", MAX_GEMS // 32), ("particles", "I", 1), ("voices", "I", 1),
]
SIZE = sum(4 * n for _, _, n in FIELDS)


def decode(raw):
    out, offset = {}, 0
    for name, fmt, n in FIELDS:
        values = struct.unpack_from(f">{n}{fmt}", raw, offset)
        out[name] = values[0] if n == 1 else list(values)
        offset += 4 * n
    return out


def field_at(offset):
    start = 0
    for name, _, n in FIELDS:
        if offset < start + 4 * n:
            index = (offset - start) // 4
            return name if n == 1 else f"{name}[{index}]"
        start += 4 * n
    return f"byte {offset}"


def first_difference(ref, cand):
    """Return (field, ref_value, cand_value) for the first differing word."""
    for offset in range(0, min(len(ref), len(cand)), 4):
        if ref[offset:offset + 4] != cand[offset:offset + 4]:
            name = field_at(offset)
            fmt = next(f for n, f, _ in FIELDS if name.split("[")[0] == n)
            r = struct.unpack(f">{fmt}", ref[offset:offset + 4])[0]
            c = struct.unpack(f">{fmt}", cand[offset:offset + 4])[0]
            return name, r, c
    if len(ref) != len(cand):
        return "length", len(ref), len(cand)
    return None
