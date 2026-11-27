#!/usr/bin/env bash
# Apply each SM64 calibration patch to a fresh copy of the baseline and grade it in parallel.
# Skips unchanged patches in <0.1s via SHA-256 stamp (pass --force to re-grade unconditionally).
#   ./scripts/calibrate.sh [--heldout DIR] [--jobs N] [--force] [PATCH_NAME ...]
set -euo pipefail
main() {
  local REPO HELDOUT="" CAL_JOBS="${CALIBRATE_JOBS:-4}" FORCE=0
  REPO=$(cd "$(dirname "$0")/.." && pwd)
  cd "$REPO"
  while [ $# -gt 0 ]; do
    case "$1" in
      --game)
        [ "${2:-}" = "sm64" ] || { echo "error: mario-eval v4 is Super Mario 64 only" >&2; exit 2; }
        shift 2
        ;;
      --heldout) HELDOUT=$(realpath "$2"); shift 2 ;;
      --jobs) CAL_JOBS="$2"; shift 2 ;;
      --force) FORCE=1; shift ;;
      *) break ;;
    esac
  done

  local SRC_DIR="sm64/decomp" CAL_DIR="sm64/calibration"
  local OUT_BASE
  OUT_BASE=$(realpath -m "${MEV_CALIBRATION_DIR:-results/sm64-calibration}")
  local REF_DIR
  REF_DIR=$(realpath "${MEV_REFERENCE_DIR:-cache/sm64-reference}")

  local NAMES=("$@")
  if [ ${#NAMES[@]} -eq 0 ]; then
    NAMES=(r0-unchanged)
    for p in "$CAL_DIR"/*.patch; do NAMES+=("$(basename "$p" .patch)"); done
  fi

  local ENV_STAMP
  ENV_STAMP="$(
    {
      docker image inspect -f '{{.Id}}' mario-eval:latest
      sha256sum "$REF_DIR/index.json" sm64/corpus/grader.json
      find sm64/harness sm64/patches grader -type f ! -name '*.so' ! -path '*/__pycache__/*' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
      if [ -n "$HELDOUT" ]; then
        find "$HELDOUT" -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
      fi
    } | sha256sum | cut -d' ' -f1
  )"

  local NEED_RUN=()
  for name in "${NAMES[@]}"; do
    local p_hash="unchanged"
    if [ "$name" != r0-unchanged ]; then
      p_hash="$(sha256sum "$REPO/$CAL_DIR/$name.patch" | cut -d' ' -f1)"
    fi
    local want="${ENV_STAMP}:${p_hash}"
    local out="$OUT_BASE/$name"
    if [ "$FORCE" -eq 0 ] && [ -f "$out/summary.json" ] && [ -f "$out/.calibrate.stamp" ] && [ "$(cat "$out/.calibrate.stamp")" = "$want" ]; then
      continue
    fi
    NEED_RUN+=("$name")
  done

  if [ ${#NEED_RUN[@]} -gt 0 ]; then
    local WORK
    WORK=$(mktemp -d)
    trap "rm -rf '$WORK'" RETURN

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

    local NPROC_TOTAL PER_JOB_THREADS
    NPROC_TOTAL="$(nproc)"
    PER_JOB_THREADS=$(( NPROC_TOTAL / CAL_JOBS ))
    [ "$PER_JOB_THREADS" -lt 2 ] && PER_JOB_THREADS=2

    run_one_patch() {
      local name="$1"
      local p_hash="unchanged"
      if [ "$name" != r0-unchanged ]; then
        p_hash="$(sha256sum "$REPO/$CAL_DIR/$name.patch" | cut -d' ' -f1)"
      fi
      rm -rf "$WORK/$name"
      cp -al "$WORK/base" "$WORK/$name" 2>/dev/null || cp -r "$WORK/base" "$WORK/$name"
      if [ "$name" != r0-unchanged ]; then
        python3 - "$WORK/base" "$WORK/$name" "$REPO/$CAL_DIR/$name.patch" <<'PY'
import pathlib, re, subprocess, sys
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
subprocess.run(["patch", "--no-backup-if-mismatch", "-s", "-p1", "-i", str(patch_file)], cwd=target, check=True)
PY
      fi
      local out="$OUT_BASE/$name"
      rm -rf "$out"; mkdir -p "$out"
      local args=(--play-smoke)
      if [ -n "$HELDOUT" ]; then args+=(--heldout "$HELDOUT"); fi
      MEV_JOBS="$PER_JOB_THREADS" "$REPO/scripts/grade.sh" "$WORK/$name" "$out" "${args[@]}" \
        >/dev/null 2>&1 || true
      if [ -f "$out/summary.json" ]; then
        printf '%s\n' "${ENV_STAMP}:${p_hash}" > "$out/.calibrate.stamp"
      fi
    }

    local running=0
    for name in "${NEED_RUN[@]}"; do
      run_one_patch "$name" &
      running=$(( running + 1 ))
      if [ "$running" -ge "$CAL_JOBS" ]; then
        wait -n || true
        running=$(( running - 1 ))
      fi
    done
    wait
  fi

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
}
main "$@"
