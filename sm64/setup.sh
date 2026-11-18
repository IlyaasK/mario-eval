#!/usr/bin/env bash
# Prepare the Super Mario 64 evaluation target from a legally dumped US ROM.
#
#   ./sm64/setup.sh "/path/to/Super Mario 64 (USA).z64"
#
# Verifies the ROM SHA-1 (US big-endian .z64), checks out n64decomp/sm64 at a
# pinned commit into sm64/decomp, extracts assets, deletes baserom.us.z64 so
# the retail ROM image never lingers in the source tree, applies the mario-eval
# deterministic harness patch, and builds tools + baseline ROM inside the
# mario-eval image. Nothing in sm64/decomp is ever committed to git.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SM64_DIR="$ROOT/sm64"
SM64_COMMIT=9921382a68bb0c865e5e45eb594d9c64db59b1af
US_SHA1=9bef1128717f958171a4afac3ed78ee2bb4e86ce
IMAGE="${MARIO_EVAL_IMAGE:-mario-eval:latest}"

ROM="${1:-}"
[ -n "$ROM" ] || { echo "usage: $0 /path/to/baserom.us.z64" >&2; exit 2; }
[ -f "$ROM" ] || { echo "error: $ROM not found" >&2; exit 2; }
ROM_ABS="$(realpath "$ROM")"
got=$(sha1sum "$ROM_ABS" | cut -d' ' -f1)
if [ "$got" != "$US_SHA1" ]; then
  echo "error: ROM SHA-1 is $got; expected US big-endian .z64 ($US_SHA1)" >&2
  exit 1
fi

cd "$SM64_DIR"
if [ ! -d decomp/.git ]; then
  git init -q decomp
  git -C decomp remote add origin https://github.com/n64decomp/sm64.git
fi
if ! git -C decomp cat-file -e "${SM64_COMMIT}^{commit}" 2>/dev/null; then
  git -C decomp fetch -q --depth 1 origin "$SM64_COMMIT"
fi
git -C decomp checkout -q -f "$SM64_COMMIT"
git -C decomp clean -fdq

cp "$ROM_ABS" decomp/baserom.us.z64
docker run --rm -u "$(id -u):$(id -g)" -v "$SM64_DIR/decomp":/work -w /work "$IMAGE" \
  python3 extract_assets.py us
rm -f decomp/baserom.us.z64

git -C decomp apply "$SM64_DIR/patches/0001-mario-eval-harness.patch"
cp "$SM64_DIR/harness/mev.c" "$SM64_DIR/harness/mev.h" decomp/src/game/

docker run --rm -u "$(id -u):$(id -g)" -v "$SM64_DIR/decomp":/work -w /work "$IMAGE" \
  make VERSION=us NOEXTRACT=1 -j"$(nproc)" check-play all

echo "prepared Super Mario 64 target: sm64/decomp/build/us/sm64.us.z64"
