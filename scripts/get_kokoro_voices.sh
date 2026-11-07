#!/usr/bin/env bash
# Download pinned Kokoro German voices into ./voices/kokoro.
# Usage: bash scripts/get_kokoro_voices.sh [--force]
set -euo pipefail
cd "$(dirname "$0")/.."

FORCE=0
EVAL_VOICES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --eval-voices) EVAL_VOICES=1; shift ;;
    *) echo "usage: $0 [--force] [--eval-voices]" >&2; exit 2 ;;
  esac
done

ROOT="voices/kokoro"
TMP=""
cleanup() { if [[ -n "$TMP" ]]; then rm -rf "$TMP"; fi; }
trap cleanup EXIT

fetch() {
  local url="$1" dest="$2" expected="$3"
  if [[ -f "$dest" ]] && (( ! FORCE )); then
    echo "$dest exists"
    return
  fi
  mkdir -p "$(dirname "$dest")"
  TMP="$(mktemp -d)"
  local temp="$TMP/file"
  echo "Downloading $(basename "$dest") ..."
  curl -fL --retry 3 -o "$temp" "$url"
  local actual
  actual="$(sha256sum "$temp" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    rm -f "$temp"
    rm -rf "$TMP"
    TMP=""
    echo "ERROR: SHA-256 mismatch for $dest" >&2
    exit 1
  fi
  mv "$temp" "$dest"
  rm -rf "$TMP"
  TMP=""
}

# Revisions pinned to the model cards / package files used in T012.
THORSTEN_REV=734e593d320a3d876bede7020f773dfd481a0cc7
KERSTIN_REV=1979d9ef12aff18b3c77cd19a52926ae85c661d3
VICTORIA_REV=ce81e200ff9203e1a3b042cd678c48e3ffb85cef
BASE_REV=f3ff3571791e39611d31c381e3a41a3af07b4987

THORSTEN="https://huggingface.co/Thorsten-Voice/Kokoro/resolve/$THORSTEN_REV"
KERSTIN="https://huggingface.co/cryptomilk/kokoro-german-kerstin/resolve/$KERSTIN_REV"
VICTORIA="https://huggingface.co/kikiri-tts/kikiri-german-victoria/resolve/$VICTORIA_REV"
BASE="https://huggingface.co/hexgrad/Kokoro-82M/resolve/$BASE_REV"

fetch "$THORSTEN/config.json" "$ROOT/thorsten/config.json" "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f"
fetch "$THORSTEN/model.pth" "$ROOT/thorsten/model.pth" "36dde15c4a800cfd1ab540ccb4476dbab604fe03ff7c937d976ebbf3b49e59ce"
fetch "$THORSTEN/voices/thorsten.pt" "$ROOT/thorsten/voice.pt" "9d98b775ebce1cfc369e8f9a3ee8ee260cd612dffb477cba85749112362306d7"
fetch "$THORSTEN/README.md" "$ROOT/thorsten/README.md" "a2ffa2aca2c321d4bb49ef552e23e8e9f3cff8c03f918f77fcfc6fc4bd2a275b"

fetch "$BASE/config.json" "$ROOT/kerstin/config.json" "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f"
fetch "$BASE/kokoro-v1_0.pth" "$ROOT/kerstin/model.pth" "496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4"
fetch "$KERSTIN/voices/df_kerstin.pt" "$ROOT/kerstin/voice.pt" "4f77aed240aaad3eace1b0e9c10394ee4c4774997f729816b39944534656b988"
fetch "$KERSTIN/LICENSE" "$ROOT/kerstin/LICENSE" "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
fetch "$KERSTIN/README.md" "$ROOT/kerstin/README.md" "8ba9bd9f9db064c6f30ee8544b682732c81aded131c94b61895d60e24dfc9bda"

if (( EVAL_VOICES )); then
  fetch "$BASE/config.json" "$ROOT/victoria/config.json" "5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f"
  fetch "$VICTORIA/kikiri_german_victoria_ep10.pth" "$ROOT/victoria/model.pth" "128d1c4a4184a459f23cb307a6cbbb8e9c076c2526f86e18594c1b320a81e00c"
  fetch "$VICTORIA/voices/victoria.pt" "$ROOT/victoria/voice.pt" "18dbcf0afa7b737e450e6ba769ee898a5aae1d90218265ff4c95422f4693da50"
  fetch "$VICTORIA/README.md" "$ROOT/victoria/README.md" "05eb9070a975754d0bc0034787288a2f53c89b5884b72458c61c3a59eb09f69b"
fi

echo "Kokoro voices ready in ./$ROOT"
du -sh "$ROOT"
