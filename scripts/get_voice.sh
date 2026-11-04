#!/usr/bin/env bash
# Download the default German Piper voice into ./voices
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p voices
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high"
for f in de_DE-thorsten-high.onnx de_DE-thorsten-high.onnx.json; do
  if [[ -f "voices/$f" ]]; then echo "voices/$f exists"; continue; fi
  echo "Downloading $f ..."
  curl -fL --retry 3 -o "voices/$f" "$BASE/$f"
done
echo "Voice ready in ./voices"
