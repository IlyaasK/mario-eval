#!/usr/bin/env bash
# Preflight check — verifies the repo, SM64 source, reference caches, N64brew
# specs, and Docker images are ready to run or grade (<30s).
#
# Usage:
#   ./quickstart/smoke-test.sh
set -euo pipefail
cd "$(dirname "$0")/.."

pass() { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n     %s\n" "$1" "$2"; }
fail() { printf "  \033[31m✗\033[0m %s\n     %s\n" "$1" "$2"; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --game)
      [ "${2:-}" = "sm64" ] || fail "game=${2:-}" "mario-eval v4 is Super Mario 64 only"
      shift 2
      ;;
    *) fail "unknown arg $1" "usage: $0" ;;
  esac
done

CORPUS="sm64/corpus"
CACHE="cache/sm64-reference"
SRC="sm64/decomp"

echo "── mario-eval v4 smoke test (Super Mario 64) ──"

[ -f grader/grade.py ]         || fail "grader/grade.py" "are you in the mario-eval repo root?"
[ -f "$CORPUS/grader.json" ]   || fail "$CORPUS/grader.json" "corpus config missing"
[ -f spec/MEASUREMENT.md ]     || fail "spec/MEASUREMENT.md" "measurement spec missing"
./spec/vendor-n64brew.sh --verify >/dev/null || fail "spec/n64brew/SHA256SUMS" "run ./spec/vendor-n64brew.sh"
pass "repo layout & SHA-256-verified N64brew hardware specs"

[ -d "$SRC/src/game" ] || fail "sm64/decomp prepared" "run: ./sm64/setup.sh '/path/to/Super Mario 64 (USA).z64'"
[ ! -f "$SRC/baserom.us.z64" ] || fail "no retail ROM inside sm64/decomp" "remove baserom.us.z64"
pass "SM64 decompilation source prepared (zero retail ROMs in tree)"

if [ -f "$CACHE/index.json" ] && [ -f "$CACHE/baseline.z64" ]; then
  pass "reference cache & baseline.z64 present ($CACHE)"
else
  warn "$CACHE not yet precomputed" "run: ./scripts/precompute.sh"
fi

command -v docker >/dev/null 2>&1 || fail "docker on PATH" "install docker"
docker info >/dev/null 2>&1        || fail "docker daemon reachable" "start docker daemon"
pass "docker reachable"

for img in mario-eval-toolchain mario-eval-runner mario-eval mario-eval-task mario-eval-proxy; do
  if docker image inspect "$img:latest" >/dev/null 2>&1; then
    pass "image $img:latest built"
  else
    warn "image $img:latest not built" "run: ./scripts/build-images.sh"
  fi
done

if docker image inspect mario-eval:latest >/dev/null 2>&1; then
  out="$(docker run --rm mario-eval:latest python3 -m grader.grade --help 2>&1 || true)"
  echo "$out" | grep -q "export-public" || fail "grader CLI in mario-eval:latest" "unexpected grader --help output"
  pass "grader CLI functional in mario-eval:latest"
fi

if docker image inspect mario-eval-task:latest >/dev/null 2>&1; then
  docker run --rm --network=none -u 1000:1000 mario-eval-task:latest python3 -c '
import json, os, pathlib
ref = pathlib.Path("/opt/mario-eval/reference")
idx = json.loads((ref / "index.json").read_text())
assert all(not k.startswith("heldout") for k in idx.get("workloads", {})), "heldout leaked"
assert not list(ref.rglob("heldout*")), "heldout file leaked"
vlist = idx.get("variants", [])
assert all(v.startswith("v") and v[1:].isdigit() for v in vlist), f"unredacted variant id leaked: {vlist}"
c_cfg = json.loads(pathlib.Path("/opt/mario-eval/corpus/grader.json").read_text())
assert "accepted_visual_variants" not in c_cfg and "o2_reference_patch" not in c_cfg, "spoiler keys leaked in container grader.json"
assert not os.access("/opt/mario-eval/corpus/grader.json", os.W_OK), "corpus grader.json writable"
assert not os.access("/opt/mario-eval/reference/index.json", os.W_OK), "reference index.json writable"
assert (ref / "baseline.z64").is_file(), "baseline.z64 missing"
assert not list(pathlib.Path("/task/game").rglob("*.z64")), "ROM leaked in /task/game"
assert pathlib.Path("/task/TASK.md").is_file(), "TASK.md missing"
assert pathlib.Path("/task/spec/MEASUREMENT.md").is_file(), "MEASUREMENT.md missing"
assert pathlib.Path("/task/spec/n64brew/INDEX.md").is_file(), "N64brew docs missing"
try:
    os.unlink("/task/TASK.md")
    raise AssertionError("/task/TASK.md was unlinkable by agent!")
except PermissionError:
    pass
' || fail "container zero-leak & immutability audit" "mario-eval-task failed assertion"
  pass "mario-eval-task zero-leak, N64brew spec, and read-only /task/TASK.md check passed"
fi

echo
echo "✓ all preflight checks passed. next steps:"
echo "    ./scripts/grade.sh $SRC results/smoke-baseline"
echo "    (cd quickstart && docker compose up -d && ./shell.sh mev workloads)"
