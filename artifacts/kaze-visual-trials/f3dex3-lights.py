"""Convert SM64's per-light uploads to F3DEX3-safe light commands.

F3DEX3 caches directional lights transformed into model space and only
invalidates that cache on G_MW_NUMLIGHT, not on a G_MOVEMEM light upload.
Retail SM64 uploads lights with paired gsSPLight(&x.l, 1) / gsSPLight(&x.a, 2)
and sets the light count once per frame, so under F3DEX3 every later model
is shaded with the first model's transformed light direction (visibly dark).

gsSPSetLights1(x) emits the light count plus both uploads, which matches the
F3DEX2 result. Three retail models (amp, koopa, bully) upload lights from
other data; they get an explicit gsSPNumLights(NUMLIGHTS_1) after the upload.

Run from the root of an SM64 tree that already has f3dex3.patch applied:
    python3 f3dex3-lights.py
"""
import re
from pathlib import Path

PAIR = re.compile(r'gsSPLight\(&(\w+)\.l,\s*1\),\s*\n(\s*)gsSPLight\(&\1\.a,\s*2\),')
ODD = {
    'actors/amp/model.inc.c': r'(gsSPLight\(\(const u8\*\)dAmpUnused3DVtx01, 2\),)',
    'actors/koopa/model.inc.c': r'(gsSPLight\(\(u8\*\)koopa_seg6_texture_06002648 \+ 0x18, 2\),[^\n]*)',
    'actors/bully/model.inc.c': r'(gsSPLight\(bully_seg5_texture_05000468, 2\),[^\n]*)',
}

converted = 0
for path in (p for d in ('actors', 'levels', 'bin') for p in Path(d).rglob('*.c')):
    text = path.read_text(errors='replace')
    text, n = PAIR.subn(lambda m: f'gsSPSetLights1({m[1]}),', text)
    pattern = ODD.get(str(path))
    if pattern:
        text, k = re.subn(pattern, lambda m: m[1] + '\n    gsSPNumLights(NUMLIGHTS_1),', text)
        assert k, path
    if n or pattern:
        path.write_text(text)
        converted += n
print(f'converted {converted} paired light uploads')
