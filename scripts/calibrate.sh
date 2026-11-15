#!/usr/bin/env bash
# Apply each calibration/*.patch to a fresh copy of workload/ and grade it.
#   scripts/calibrate.sh [--heldout DIR] [PATCH_NAME ...]
# Writes results/calibration/<name>/summary.json and prints a table.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"
HELDOUT=""
if [ "${1:-}" = "--heldout" ]; then HELDOUT=$(realpath "$2"); shift 2; fi
NAMES=("$@")
if [ ${#NAMES[@]} -eq 0 ]; then
  NAMES=(r0-unchanged)
  for p in calibration/*.patch; do NAMES+=("$(basename "$p" .patch)"); done
fi
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
for name in "${NAMES[@]}"; do
  rm -rf "$WORK/base" "$WORK/$name"
  cp -r workload "$WORK/base"
  rm -rf "$WORK/base/build" "$WORK/base"/*.z64
  cp -r "$WORK/base" "$WORK/$name"
  if [ "$name" != r0-unchanged ]; then
    (cd "$WORK/$name" && patch -s -p1 < "$REPO/calibration/$name.patch")
  fi
  out="results/calibration/$name"
  rm -rf "$out"; mkdir -p "$out"
  args=(); mounts=()
  if [ -n "$HELDOUT" ]; then args=(--split all --heldout /heldout); mounts=(-v "$HELDOUT":/heldout:ro); fi
  docker run --rm -u "$(id -u):$(id -g)" -v "$REPO":/repo:ro -v "$WORK/$name":/submission:ro \
    -v "$REPO/$out":/out "${mounts[@]}" -w /repo mario-eval \
    python3 -m grader.grade grade /submission --corpus corpus --cache cache/reference --out /out "${args[@]}" \
    >/dev/null 2>&1 || true
done
python3 - "${NAMES[@]}" <<'EOF'
import json, sys
print(f"{'patch':18s} {'status':8s} {'speed':>7s} {'rsp':>7s} {'traffic':>8s} {'memory':>7s}  failed gates / profile notes")
for name in sys.argv[1:]:
    s = json.load(open(f"results/calibration/{name}/summary.json"))
    r = s.get("rewards", {})
    note = [g for g, v in s.get("gates", {}).items() if not v["pass"]]
    note += [f"{p}: {v['reason']}" for p, v in s.get("profiles", {}).items() if not v["valid"]]
    if s["status"] == "grader_error":
        note = [s.get("reason", "")]
    print(f"{name:18s} {s['status']:8s} " + " ".join(f"{r.get(k, float('nan')):7.3f}" for k in ("speed", "rsp")) +
          f" {r.get('traffic', float('nan')):8.3f} {r.get('memory', float('nan')):7.3f}  " + "; ".join(note))
EOF
