#!/usr/bin/env bash
# Apply each calibration patch to a fresh copy of the baseline and grade it.
#   scripts/calibrate.sh [--game pips-garden|sm64] [--heldout DIR] [PATCH_NAME ...]
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
GAME="pips-garden"
HELDOUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --game) GAME="$2"; shift 2 ;;
    --heldout) HELDOUT=$(realpath "$2"); shift 2 ;;
    *) break ;;
  esac
done

case "$GAME" in
  pips-garden)
    SRC_DIR="workload"; CORPUS="corpus"; CACHE="cache/reference"
    CAL_DIR="calibration"; OUT_BASE="results/calibration"
    ;;
  sm64)
    SRC_DIR="sm64/decomp"; CORPUS="sm64/corpus"; CACHE="cache/sm64-reference"
    CAL_DIR="sm64/calibration"; OUT_BASE="results/sm64-calibration"
    ;;
  *) echo "unknown --game $GAME" >&2; exit 2 ;;
esac
OUT_BASE=$(realpath -m "${MEV_CALIBRATION_DIR:-$OUT_BASE}")

NAMES=("$@")
if [ ${#NAMES[@]} -eq 0 ]; then
  NAMES=(r0-unchanged)
  for p in "$CAL_DIR"/*.patch; do NAMES+=("$(basename "$p" .patch)"); done
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

python3 - "$SRC_DIR" "$WORK/base" <<'PY'
import pathlib, shutil, sys
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
root = str(src.resolve())
def _ignore(cur, names):
    ig = {n for n in names if n == ".git" or n.endswith((".z64", ".n64", ".v64"))}
    if str(pathlib.Path(cur).resolve()) == root:
        ig |= {n for n in names if n == "build" or n.startswith("build_")}
    return ig
shutil.copytree(src, dst, ignore=_ignore)
PY

for name in "${NAMES[@]}"; do
  rm -rf "$WORK/$name"
  cp -al "$WORK/base" "$WORK/$name" 2>/dev/null || cp -r "$WORK/base" "$WORK/$name"
  if [ "$name" != r0-unchanged ]; then
    # Break hardlinks on files modified by patch (`patch` in-place safe with --backup-if-mismatch off,
    # so copy modified files first via python or --remove-empty-files; safest is a clean copy of patched files):
    python3 - "$WORK/base" "$WORK/$name" "$REPO/$CAL_DIR/$name.patch" <<'PY'
import pathlib, re, shutil, subprocess, sys
base, target, patch_file = map(pathlib.Path, sys.argv[1:4])
for line in patch_file.read_text(errors="replace").splitlines():
    m = re.match(r"^\+\+\+\s+[^/\s]+/(\S+)", line)
    if m and m.group(1) != "dev/null":
        rel = m.group(1)
        p = target / rel
        if p.exists():
            data = p.read_bytes()
            p.unlink()
            p.write_bytes(data)
subprocess.run(["patch", "-s", "-p1", "-i", str(patch_file)], cwd=target, check=True)
PY
  fi
  out="$OUT_BASE/$name"
  rm -rf "$out"; mkdir -p "$out"
  args=()
  if [ -n "$HELDOUT" ]; then args=(--heldout "$HELDOUT"); fi
  "$REPO/scripts/grade.sh" --game "$GAME" "$WORK/$name" "$out" "${args[@]}" \
    >/dev/null 2>&1 || true
done

python3 - "$OUT_BASE" "${NAMES[@]}" <<'EOF'
import json, sys
out_base = sys.argv[1]
cols = ("console", "stutter", "speed", "rdp", "rsp", "traffic", "memory")
print(f"{'patch':28s} {'status':8s} " + " ".join(f"{c:>7s}" for c in cols) + f" {'con_x':>7s} {'spd_x':>7s}  failed gates / notes")
for name in sys.argv[2:]:
    s = json.load(open(f"{out_base}/{name}/summary.json"))
    r = s.get("rewards", {})
    cx = s.get("speedups", {}).get("console", 0.0)
    sp = s.get("speedups", {}).get("speed", 0.0)
    note = [g for g, v in s.get("gates", {}).items() if not v["pass"]]
    note += [f"{p}: {v['reason']}" for p, v in s.get("profiles", {}).items() if not v["valid"]]
    if s["status"] == "grader_error":
        note = [s.get("reason", "")]
    cx_str = f"{cx:6.2f}x" if cx else "     - "
    sp_str = f"{sp:6.2f}x" if sp else "     - "
    print(f"{name:28s} {s['status']:8s} " + " ".join(f"{r.get(k, float('nan')):7.3f}" for k in cols) +
          f" {cx_str} {sp_str}  " + "; ".join(note))
EOF
