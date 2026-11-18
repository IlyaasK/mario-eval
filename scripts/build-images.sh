#!/usr/bin/env bash
# Build every image, in dependency order:
#   mario-eval-toolchain  N64 cross-compilers + libdragon (pinned)
#   mario-eval-runner     ares + CPU/RSP/RDP/RDRAM instrumentation + n64run
#   mario-eval            toolchain + n64run + grader (grading image)
#   mario-eval-task       agent container (game source, public corpus,
#                         sanitized public-only reference; zero held-out data)
#   mario-eval-proxy      egress allowlist proxy
#
# Usage:
#   ./scripts/build-images.sh [--game pips-garden|sm64] [--no-task]
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
GAME="pips-garden"
NO_TASK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --game) GAME="$2"; shift 2 ;;
    --no-task) NO_TASK=1; shift ;;
    *) echo "usage: $0 [--game pips-garden|sm64] [--no-task]" >&2; exit 2 ;;
  esac
done

case "$GAME" in
  pips-garden)
    CORPUS_DIR="corpus"; GAME_DIR="workload"; REF_DIR="cache/reference"
    TASK_DOC="quickstart/task/TASK.md"; GAME_TITLE="Pip's Garden baseline"
    ;;
  sm64)
    CORPUS_DIR="sm64/corpus"; GAME_DIR="sm64/decomp"; REF_DIR="cache/sm64-reference"
    TASK_DOC="quickstart/task/TASK-sm64.md"; GAME_TITLE="Super Mario 64 US baseline"
    ;;
  *) echo "unknown --game $GAME (expected pips-garden or sm64)" >&2; exit 2 ;;
esac

docker build -t mario-eval-toolchain toolchain
docker build -t mario-eval-runner runner
docker build -t mario-eval .

if [ "$NO_TASK" -eq 0 ]; then
  [ -f "$REF_DIR/index.json" ] || {
    echo "$REF_DIR missing: run ./scripts/precompute.sh --game $GAME first" >&2; exit 1; }
  [ -d "$GAME_DIR" ] || {
    echo "$GAME_DIR missing: run ./sm64/setup.sh first" >&2; exit 1; }

  STAGE="$REPO/cache/public-stage"
  rm -rf "$STAGE"
  trap 'rm -rf "$STAGE"' EXIT
  docker run --rm -u "$(id -u):$(id -g)" -v "$REPO":/repo -w /repo mario-eval \
    python3 -m grader.grade export-public --corpus "$CORPUS_DIR" --cache "$REF_DIR" --out cache/public-stage

  docker build -t mario-eval-task \
    --build-arg CORPUS_DIR="$CORPUS_DIR" \
    --build-arg GAME_DIR="$GAME_DIR" \
    --build-arg TASK_DOC="$TASK_DOC" \
    --build-arg GAME_TITLE="$GAME_TITLE" \
    -f quickstart/task/Dockerfile .
  docker build -t mario-eval-proxy quickstart/proxy
fi
