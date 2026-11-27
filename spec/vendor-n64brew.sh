#!/usr/bin/env bash
# Vendor community Nintendo 64 hardware documentation from the N64brew Wiki
# (https://n64brew.dev/, licensed under Creative Commons Attribution-ShareAlike 4.0
# International, CC BY-SA 4.0) into spec/n64brew/ with SHA-256 verification.
#
# Usage:
#   ./spec/vendor-n64brew.sh           # fetch pages and write SHA256SUMS
#   ./spec/vendor-n64brew.sh --verify  # verify existing files against SHA256SUMS
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/spec/n64brew"

if [ "${1:-}" = "--verify" ]; then
  cd "$OUT_DIR"
  sha256sum -c SHA256SUMS
  exit 0
fi

mkdir -p "$OUT_DIR"

cat > "$OUT_DIR/LICENSE-CC-BY-SA-4.0.txt" <<'EOF'
N64brew Wiki Hardware Documentation Snapshot
Source: https://n64brew.dev/
License: Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)
License URL: https://creativecommons.org/licenses/by-sa/4.0/

Each file in this directory is a verbatim MediaWiki source snapshot from the
N64brew community hardware reference wiki, prefixed with its canonical page URL
and license attribution header for offline reference inside the evaluation
environment.
EOF

PAGES=(
  "VR4300:VR4300.md"
  "MIPS_III_instructions:MIPS_III_Instructions.md"
  "COP1:COP1_FPU.md"
  "Memory_map:Memory_Map.md"
  "RDRAM:RDRAM.md"
  "RDRAM_Interface:RDRAM_Interface.md"
  "Reality_Signal_Processor:RSP.md"
  "Reality_Signal_Processor/CPU_Core:RSP_CPU_Core.md"
  "Reality_Signal_Processor/CPU_Pipeline:RSP_CPU_Pipeline.md"
  "Reality_Signal_Processor/Interface:RSP_Interface.md"
  "Reality_Display_Processor:RDP.md"
  "Reality_Display_Processor/Commands:RDP_Commands.md"
  "Reality_Display_Processor/Pipeline:RDP_Pipeline.md"
  "Reality_Display_Processor/Hazards:RDP_Hazards.md"
  "Reality_Display_Processor/Interface:RDP_Interface.md"
  "MIPS_Interface:MIPS_Interface.md"
  "Parallel_Interface:Parallel_Interface_PI.md"
  "Video_Interface:Video_Interface.md"
  "Audio_Interface:Audio_Interface.md"
  "Serial_Interface:Serial_Interface.md"
)

{
  echo "# N64brew Hardware Reference (Offline Snapshot)"
  echo
  echo "Source: <https://n64brew.dev/> — licensed under **CC BY-SA 4.0** (see \`LICENSE-CC-BY-SA-4.0.txt\`)."
  echo
  echo "| File | N64brew Page |"
  echo "|------|--------------|"
} > "$OUT_DIR/INDEX.md"

for entry in "${PAGES[@]}"; do
  title="${entry%%:*}"
  fname="${entry##*:}"
  url="https://n64brew.dev/w/index.php?title=${title}&action=raw"
  canon="https://n64brew.dev/wiki/${title}"
  tmp="$(mktemp)"
  curl -fsSL "$url" -o "$tmp"
  if [ ! -s "$tmp" ]; then
    rm -f "$tmp"
    echo "error: empty response for $url" >&2
    exit 1
  fi
  {
    echo "<!--"
    echo "  Source: ${canon}"
    echo "  Authors: N64brew Wiki contributors"
    echo "  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)"
    echo "-->"
    echo
    cat "$tmp"
    echo
  } > "$OUT_DIR/$fname"
  rm -f "$tmp"
  echo "| \`$fname\` | \`${title}\` (<${canon}>) |" >> "$OUT_DIR/INDEX.md"
done

(
  cd "$OUT_DIR"
  sha256sum LICENSE-CC-BY-SA-4.0.txt INDEX.md *.md | LC_ALL=C sort -u -k2 > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

echo "vendored ${#PAGES[@]} N64brew pages into $OUT_DIR (verified SHA256SUMS)"
