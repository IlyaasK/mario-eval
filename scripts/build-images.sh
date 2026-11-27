#!/usr/bin/env bash
# Build every Mario Eval image in dependency order with content-hash skipping,
# timestamp-preserving <1 MB leaf contexts, and zero-spawn rootfs staging so
# editing grader/, tools/, spec/, grader.json, or TASK.md rebuilds in ~1s
# (and no-op checks finish in ~0.3s).
#
# Usage:
#   ./scripts/build-images.sh [--no-task] [--force]
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
NO_TASK=0
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --game)
      [ "${2:-}" = "sm64" ] || { echo "error: mario-eval v4 is Super Mario 64 only (--game sm64)" >&2; exit 2; }
      shift 2
      ;;
    --no-task) NO_TASK=1; shift ;;
    --force) FORCE=1; shift ;;
    *) echo "usage: $0 [--no-task] [--force]" >&2; exit 2 ;;
  esac
done

dir_hash() {
  find "$@" -type f ! -name '*.so' ! -path '*/__pycache__/*' -print0 \
    | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1
}

img_label() {
  docker image inspect -f "{{ index .Config.Labels \"$2\" }}" "$1:latest" 2>/dev/null || true
}

TC_HASH="$(dir_hash toolchain)"
if [ "$FORCE" -eq 1 ] || ! docker image inspect mario-eval-toolchain:latest >/dev/null 2>&1 || { [ -n "$(img_label mario-eval-toolchain mev.src_hash)" ] && [ "$(img_label mario-eval-toolchain mev.src_hash)" != "$TC_HASH" ]; }; then
  docker build --provenance=false --label "mev.src_hash=$TC_HASH" -t mario-eval-toolchain toolchain
elif [ -z "$(img_label mario-eval-toolchain mev.src_hash)" ]; then
  printf 'FROM mario-eval-toolchain:latest\nLABEL mev.src_hash="%s"\n' "$TC_HASH" | docker build --provenance=false -q -t mario-eval-toolchain - >/dev/null
fi

RN_HASH="$(dir_hash runner)"
if [ "$FORCE" -eq 1 ] || ! docker image inspect mario-eval-runner:latest >/dev/null 2>&1 || { [ -n "$(img_label mario-eval-runner mev.src_hash)" ] && [ "$(img_label mario-eval-runner mev.src_hash)" != "$RN_HASH" ]; }; then
  docker build --provenance=false --label "mev.src_hash=$RN_HASH" -t mario-eval-runner runner
elif [ -z "$(img_label mario-eval-runner mev.src_hash)" ]; then
  printf 'FROM mario-eval-runner:latest\nLABEL mev.src_hash="%s"\n' "$RN_HASH" | docker build --provenance=false -q -t mario-eval-runner - >/dev/null
fi

# Grader image (<1 MB context: fast_video.cpp layer cached separately from *.py)
TC_ID="$(docker image inspect -f '{{.Id}}' mario-eval-toolchain:latest)"
RN_ID="$(docker image inspect -f '{{.Id}}' mario-eval-runner:latest)"
GR_HASH="$(dir_hash Dockerfile grader tools):$TC_ID:$RN_ID"
if [ "$FORCE" -eq 1 ] || [ "$(img_label mario-eval mev.src_hash)" != "$GR_HASH" ]; then
  CTX_GR="$(mktemp -d)"
  cp -a Dockerfile "$CTX_GR/Dockerfile"
  mkdir -p "$CTX_GR/grader" "$CTX_GR/tools"
  cp -a grader/fast_video.cpp grader/*.py "$CTX_GR/grader/"
  cp -a tools/*.py "$CTX_GR/tools/"
  docker build --provenance=false --label "mev.src_hash=$GR_HASH" -t mario-eval "$CTX_GR"
  rm -rf "$CTX_GR"
fi

if [ "$NO_TASK" -eq 0 ]; then
  CORPUS_DIR="sm64/corpus"
  GAME_DIR="sm64/decomp"
  REF_DIR="cache/sm64-reference"
  TASK_DOC="quickstart/task/TASK.md"
  GAME_TITLE="Super Mario 64 US baseline"

  [ -f "$REF_DIR/index.json" ] || {
    echo "$REF_DIR missing: run ./scripts/precompute.sh first" >&2; exit 1; }
  [ -d "$GAME_DIR" ] || {
    echo "$GAME_DIR missing: run ./sm64/setup.sh first" >&2; exit 1; }

  # Heavy base image (rebuilt ONLY if sm64/harness, sm64/patches, Dockerfile.base, or reference cache changed!)
  BASE_HASH="$(dir_hash quickstart/task/Dockerfile.base sm64/harness sm64/patches "$REF_DIR/index.json")"
  if [ "$FORCE" -eq 1 ] || [ "$(img_label mario-eval-task-base mev.src_hash)" != "$BASE_HASH" ]; then
    STAGE="$REPO/cache/public-stage"
    chmod -R u+w "$STAGE" 2>/dev/null || true
    rm -rf "$STAGE"
    docker run --rm -u "$(id -u):$(id -g)" -v "$REPO":/repo -w /repo mario-eval \
      python3 -m grader.grade export-public --corpus "$CORPUS_DIR" --cache "$REF_DIR" --out cache/public-stage
    find "$STAGE" -exec touch -t 202601010000 {} +
    chmod -R a-w,a+rX "$STAGE"
    docker build --provenance=false --label "mev.src_hash=$BASE_HASH" -t mario-eval-task-base \
      --build-arg GAME_DIR="$GAME_DIR" \
      --build-arg GAME_TITLE="$GAME_TITLE" \
      -f quickstart/task/Dockerfile.base .
    chmod -R u+w "$STAGE"
    rm -rf "$STAGE"
  fi

  # Leaf task image (~600 KB context, single rootfs COPY, 0 container spawns -> ~1s rebuild!)
  GR_ID="$(docker image inspect -f '{{.Id}}' mario-eval:latest)"
  TB_ID="$(docker image inspect -f '{{.Id}}' mario-eval-task-base:latest)"
  LEAF_HASH="$(dir_hash quickstart/task/Dockerfile "$TASK_DOC" "$CORPUS_DIR/grader.json" "$CORPUS_DIR/replays/public" spec tools/mev.py):$GR_ID:$TB_ID"
  if [ "$FORCE" -eq 1 ] || [ "$(img_label mario-eval-task mev.src_hash)" != "$LEAF_HASH" ]; then
    (cd spec/n64brew && sha256sum -c SHA256SUMS >/dev/null)
    CTX_LF="$(mktemp -d)"
    cp -a quickstart/task/Dockerfile "$CTX_LF/Dockerfile"
    mkdir -p "$CTX_LF/rootfs/opt/mario-eval/corpus/replays" \
             "$CTX_LF/rootfs/task/spec" \
             "$CTX_LF/rootfs/usr/local/bin"
    chmod 0755 "$CTX_LF/rootfs/task" "$CTX_LF/rootfs/task/spec"
    cp -a "$CORPUS_DIR/replays/public" "$CTX_LF/rootfs/opt/mario-eval/corpus/replays/public"
    python3 -c 'import json, pathlib, sys; d = json.loads(pathlib.Path(sys.argv[1]).read_text()); d.pop("o2_reference_patch", None); d.pop("accepted_visual_variants", None); pathlib.Path(sys.argv[2]).write_text(json.dumps(d, indent=2) + "\n")' \
      "$CORPUS_DIR/grader.json" "$CTX_LF/rootfs/opt/mario-eval/corpus/grader.json"
    chmod -R a-w,a+rX "$CTX_LF/rootfs/opt/mario-eval/corpus"
    cp -a spec/n64brew "$CTX_LF/rootfs/task/spec/n64brew"
    cp -a spec/MEASUREMENT.md "$CTX_LF/rootfs/task/spec/MEASUREMENT.md"
    chmod -R a-w,a+rX "$CTX_LF/rootfs/task/spec"
    cp -a "$TASK_DOC" "$CTX_LF/rootfs/task/TASK.md"
    chmod 0444 "$CTX_LF/rootfs/task/TASK.md" "$CTX_LF/rootfs/task/spec/MEASUREMENT.md"
    cp -a tools/mev.py "$CTX_LF/rootfs/usr/local/bin/mev"
    chmod 0755 "$CTX_LF/rootfs/usr/local/bin/mev"
    docker build --provenance=false --label "mev.src_hash=$LEAF_HASH" -t mario-eval-task "$CTX_LF"
    chmod -R u+w "$CTX_LF"
    rm -rf "$CTX_LF"
  fi

  PX_HASH="$(dir_hash quickstart/proxy)"
  if [ "$FORCE" -eq 1 ] || ! docker image inspect mario-eval-proxy:latest >/dev/null 2>&1 || { [ -n "$(img_label mario-eval-proxy mev.src_hash)" ] && [ "$(img_label mario-eval-proxy mev.src_hash)" != "$PX_HASH" ]; }; then
    docker build --provenance=false --label "mev.src_hash=$PX_HASH" -t mario-eval-proxy quickstart/proxy
  elif [ -z "$(img_label mario-eval-proxy mev.src_hash)" ]; then
    printf 'FROM mario-eval-proxy:latest\nLABEL mev.src_hash="%s"\n' "$PX_HASH" | docker build --provenance=false -q -t mario-eval-proxy - >/dev/null
  fi
fi
