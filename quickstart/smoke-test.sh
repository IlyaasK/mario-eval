#!/usr/bin/env bash
# Preflight check — verifies the repo, reference caches, and Docker images are
# ready to run or grade (<30s, modeled on gba-eval/quickstart/smoke-test.sh).
#
# Usage:
#   ./quickstart/smoke-test.sh [--game sm64|pips-garden]
set -euo pipefail
cd "$(dirname "$0")/.."

pass() { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n     %s\n" "$1" "$2"; }
fail() { printf "  \033[31m✗\033[0m %s\n     %s\n" "$1" "$2"; exit 1; }

GAME="sm64"
while [ $# -gt 0 ]; do
  case "$1" in
    --game) GAME="$2"; shift 2 ;;
    *) fail "unknown arg $1" "usage: $0 [--game sm64|pips-garden]" ;;
  esac
done

case "$GAME" in
  pips-garden) CORPUS="corpus"; CACHE="cache/reference"; SRC="workload" ;;
  sm64)        CORPUS="sm64/corpus"; CACHE="cache/sm64-reference"; SRC="sm64/decomp" ;;
  *) fail "game=$GAME" "expected 'sm64' or 'pips-garden'" ;;
esac

echo "── mario-eval smoke test (game=$GAME) ──"

[ -f grader/grade.py ]         || fail "grader/grade.py" "are you in the mario-eval repo root?"
[ -f "$CORPUS/grader.json" ]   || fail "$CORPUS/grader.json" "corpus config missing"
pass "repo layout ($CORPUS)"

if [ "$GAME" = "sm64" ]; then
  [ -d "$SRC/src/game" ] || fail "sm64/decomp prepared" "run: ./sm64/setup.sh '/path/to/Super Mario 64 (USA).z64'"
  [ ! -f "$SRC/baserom.us.z64" ] || fail "no retail ROM inside sm64/decomp" "remove baserom.us.z64"
  pass "SM64 decompilation source prepared (zero retail ROMs in tree)"
else
  [ -f "$SRC/Makefile" ] || fail "workload/Makefile" "Pip's Garden source missing"
  pass "Pip's Garden source present"
fi

if [ -f "$CACHE/index.json" ]; then
  pass "reference cache present ($CACHE/index.json)"
else
  warn "$CACHE/index.json not yet precomputed" "run: ./scripts/precompute.sh --game $GAME"
fi

command -v docker >/dev/null 2>&1 || fail "docker on PATH" "install docker"
docker info >/dev/null 2>&1        || fail "docker daemon reachable" "start docker daemon"
pass "docker reachable"

for img in mario-eval-toolchain mario-eval-runner mario-eval mario-eval-task mario-eval-proxy; do
  if docker image inspect "$img:latest" >/dev/null 2>&1; then
    pass "image $img:latest built"
  else
    warn "image $img:latest not built" "run: ./scripts/build-images.sh --game $GAME"
  fi
done

if docker image inspect mario-eval:latest >/dev/null 2>&1; then
  out="$(docker run --rm mario-eval:latest python3 -m grader.grade --help 2>&1 || true)"
  echo "$out" | grep -q "export-public" || fail "grader CLI in mario-eval:latest" "unexpected grader --help output"
  pass "grader CLI functional in mario-eval:latest"
fi

if docker image inspect mario-eval-task:latest >/dev/null 2>&1; then
  docker run --rm --network=none mario-eval-task:latest python3 -c '
import json, pathlib
ref = pathlib.Path("/opt/mario-eval/reference")
idx = json.loads((ref / "index.json").read_text())
assert all(not k.startswith("heldout") for k in idx.get("workloads", {})), "heldout leaked"
assert not list(ref.rglob("heldout*")), "heldout file leaked"
assert not list(pathlib.Path("/task/game").rglob("*.z64")), "ROM leaked"
' || fail "container zero-leak audit" "mario-eval-task failed zero-leak assertion"
  pass "mario-eval-task zero-leak & offline check passed"
fi

echo
echo "✓ all preflight checks passed. next steps:"
echo "    ./scripts/grade.sh --game $GAME $SRC results/smoke-baseline"
echo "    (cd quickstart && docker compose up -d && ./shell.sh mev workloads)"
