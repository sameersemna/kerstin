#!/usr/bin/env bash
# Download the pinned browser VAD/ONNX assets into ./frontend/vendor.
# Usage: bash scripts/get_frontend_vendor.sh [--force]
set -euo pipefail
cd "$(dirname "$0")/.."

FORCE=0
if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
  shift
fi
if [[ $# -gt 0 ]]; then
  echo "usage: $0 [--force]" >&2
  exit 2
fi

VENDOR="frontend/vendor"
VAD_VERSION="0.0.22"
ORT_VERSION="1.14.0"
VAD_URL="https://registry.npmjs.org/@ricky0123/vad-web/-/vad-web-${VAD_VERSION}.tgz"
VAD_SHA512="sha512-679R6sfwXx4jkquK+FJ9RC2W29oulWC+9ZINK6LVpuy90IBV7UaTGNN79oQXufpJTJs5z4X/22nw1DQ4+Rh8CA=="
VAD_LICENSE_URL="https://raw.githubusercontent.com/ricky0123/vad/3fc4ef1cfad060e99d4194e8653e60cbdcfe5287/LICENSE"
VAD_LICENSE_SHA256="239ebca4207803d3507124517c0dd6324c0d5cf73e1c486ade16bac1788f4a79"
ORT_URL="https://registry.npmjs.org/onnxruntime-web/-/onnxruntime-web-${ORT_VERSION}.tgz"
ORT_SHA512="sha512-Kcqf43UMfW8mCydVGcX9OMXI2VN17c0p6XvR7IPSZzBf/6lteBzXHvcEVWDPmCKuGombl997HgLqj91F11DzXw=="
ORT_LICENSE_URL="https://raw.githubusercontent.com/microsoft/onnxruntime/v1.14.0/LICENSE"
ORT_LICENSE_SHA256="2f07c72751aed99790b8a4869cf2311df85a860b22ded05fa22803587a48922c"

TMP=""
cleanup() {
  if [[ -n "$TMP" ]]; then rm -rf "$TMP"; fi
}
trap cleanup EXIT

all_present() {
  local dest="$1"
  shift
  local file
  for file in "$@"; do
    [[ -f "$dest/$file" ]] || return 1
  done
}

install_package() {
  local name="$1" version="$2" url="$3" integrity="$4" license_url="$5" license_sha256="$6" dest="$7"
  shift 7
  local sources=() outputs=()
  while [[ $# -gt 0 ]]; do
    sources+=("$1")
    outputs+=("$2")
    shift 2
  done

  if (( ! FORCE )) && all_present "$dest" "${outputs[@]}" "LICENSE"; then
    echo "vendor/$name exists"
    return
  fi

  TMP="$(mktemp -d)"
  local archive="$TMP/$name.tgz"
  echo "Downloading $name-$version ..."
  curl -fL --retry 3 -o "$archive" "$url"

  local actual
  actual="sha512-$(openssl dgst -sha512 -binary "$archive" | base64 -w0)"
  if [[ "$actual" != "$integrity" ]]; then
    rm -f "$archive"
    echo "ERROR: SHA-512 mismatch for $name-$version" >&2
    exit 1
  fi

  mkdir -p "$TMP/extract"
  tar -xzf "$archive" -C "$TMP/extract" "${sources[@]}"
  curl -fL --retry 3 -o "$TMP/LICENSE" "$license_url"
  # The npm tarballs ship no LICENSE; the upstream text is pinned by SHA-256.
  if [[ "$(sha256sum "$TMP/LICENSE" | cut -d' ' -f1)" != "$license_sha256" ]]; then
    echo "ERROR: SHA-256 mismatch for $name LICENSE" >&2
    exit 1
  fi

  rm -rf "$dest"
  mkdir -p "$dest"
  local index
  for index in "${!sources[@]}"; do
    cp "$TMP/extract/${sources[$index]}" "$dest/${outputs[$index]}"
  done
  cp "$TMP/LICENSE" "$dest/LICENSE"
  rm -rf "$TMP"
  TMP=""
  echo "vendor/$name ready"
}

install_package \
  "vad-web" "$VAD_VERSION" "$VAD_URL" "$VAD_SHA512" "$VAD_LICENSE_URL" "$VAD_LICENSE_SHA256" "$VENDOR/vad-web" \
  "package/dist/bundle.min.js" "bundle.min.js" \
  "package/dist/vad.worklet.bundle.min.js" "vad.worklet.bundle.min.js" \
  "package/dist/silero_vad_legacy.onnx" "silero_vad_legacy.onnx"

install_package \
  "onnxruntime-web" "$ORT_VERSION" "$ORT_URL" "$ORT_SHA512" "$ORT_LICENSE_URL" "$ORT_LICENSE_SHA256" "$VENDOR/onnxruntime-web" \
  "package/dist/ort.js" "ort.js" \
  "package/dist/ort-wasm-simd.wasm" "ort-wasm-simd.wasm"
