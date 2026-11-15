#!/usr/bin/env bash
# Prepare the Super Mario 64 workload from a ROM you supply.
#
#   sm64/setup.sh /path/to/your/baserom.us.z64
#
# Verifies the ROM is the US release (SHA-1 below), checks out the
# n64decomp/sm64 decompilation at a pinned commit into sm64/decomp, and builds
# the matching baseline with the decompilation's own Docker image. Nothing
# from the ROM is ever committed or published: sm64/decomp is git-ignored.
#
# This prepares the baseline only. Wiring the mario-eval harness (mev_read_pad /
# mev_end_frame, an unthrottled benchmark build, and the observation record)
# into SM64's game loop is the next step; see sm64/README.md.
set -euo pipefail
cd "$(dirname "$0")"
SM64_COMMIT=9921382a68bb0c865e5e45eb594d9c64db59b1af
US_SHA1=9bef1128717f958171a4afac3ed78ee2bb4e86ce

ROM="${1:-}"
[ -n "$ROM" ] || { echo "usage: $0 /path/to/baserom.us.z64" >&2; exit 2; }
[ -f "$ROM" ] || { echo "error: $ROM not found" >&2; exit 2; }
got=$(sha1sum "$ROM" | cut -d' ' -f1)
if [ "$got" != "$US_SHA1" ]; then
  echo "error: ROM SHA-1 is $got; the US release (big-endian .z64) is $US_SHA1" >&2
  exit 1
fi

if [ ! -d decomp/.git ]; then
  git init -q decomp
  git -C decomp remote add origin https://github.com/n64decomp/sm64.git
fi
git -C decomp fetch -q --depth 1 origin "$SM64_COMMIT"
git -C decomp checkout -q FETCH_HEAD
cp "$ROM" decomp/baserom.us.z64

docker build -q -t mario-eval-sm64 decomp
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/decomp":/sm64 -w /sm64 mario-eval-sm64 \
  make VERSION=us -j"$(nproc)"
echo "built matching baseline: sm64/decomp/build/us/sm64.us.z64"
