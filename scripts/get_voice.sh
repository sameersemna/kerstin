#!/usr/bin/env bash
# Download a German Piper voice (thorsten) into ./voices.
# Usage: bash scripts/get_voice.sh [high|medium]   (default: high)
set -euo pipefail
cd "$(dirname "$0")/.."

QUALITY="${1:-high}"
case "$QUALITY" in
  high|medium) ;;
  *)
    echo "usage: $0 [high|medium]" >&2
    exit 2
    ;;
esac

mkdir -p voices
NAME="de_DE-thorsten-${QUALITY}"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/${QUALITY}"
for f in "${NAME}.onnx" "${NAME}.onnx.json"; do
  if [[ -f "voices/$f" ]]; then echo "voices/$f exists"; continue; fi
  echo "Downloading $f ..."
  curl -fL --retry 3 -o "voices/$f" "$BASE/$f"
done
echo "Voice ready in ./voices"
