#!/usr/bin/env bash
# Pre-flight checks for Kerstin on the GB10. Read-only: changes nothing.
set -uo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] && set -a && source .env && set +a

OLLAMA="${KERSTIN_OLLAMA_URL:-http://127.0.0.1:11434}"
MODEL="${KERSTIN_OLLAMA_MODEL:-qwen3:14b}"
STT="${KERSTIN_STT_URL:-http://127.0.0.1:8000}"
VOICE="${KERSTIN_PIPER_VOICE_PATH:-voices/de_DE-thorsten-medium.onnx}"
ok()   { echo "  [ok]   $*"; }
bad()  { echo "  [FAIL] $*"; }
warn() { echo "  [warn] $*"; }

echo "Ollama ($OLLAMA)"
if tags=$(curl -fsS -m 3 "$OLLAMA/api/tags"); then
  ok "reachable"
  if echo "$tags" | grep -q "\"$MODEL\""; then ok "model $MODEL present"; else bad "model $MODEL not pulled  ->  ollama pull $MODEL"; fi
else bad "not reachable"; fi

echo "STT (${KERSTIN_STT_BACKEND:-http})"
if [[ "${KERSTIN_STT_BACKEND:-http}" == "whispercpp" ]]; then
  # whisper.cpp server: GET / is its HTML page (never POST /load here)
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 3 "$STT/" || true)
  if [[ "$code" == "200" ]]; then ok "$STT/ answers"; else bad "$STT/ -> HTTP $code"; fi
elif [[ "${KERSTIN_STT_BACKEND:-http}" == "http" ]]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 3 "$STT/v1/models" || true)
  if [[ "$code" == "200" ]]; then ok "$STT/v1/models answers"; else warn "$STT/v1/models -> HTTP $code (server may use another path; see docs/STATUS.md)"; fi
else
  python3 -c "import faster_whisper" 2>/dev/null && ok "faster-whisper importable" || bad "faster-whisper not installed"
fi

echo "TTS (${KERSTIN_TTS_BACKEND:-piper})"
if [[ "${KERSTIN_TTS_BACKEND:-piper}" == "piper" ]]; then
  [[ -f "$VOICE" ]] && ok "voice $VOICE" || bad "voice missing -> make voice"
fi

if [[ -n "${KERSTIN_TLS_CERTFILE:-}" ]]; then
  echo "TLS"
  TLS_KEY="${KERSTIN_TLS_KEYFILE:-}"
  if [[ -f "$KERSTIN_TLS_CERTFILE" ]]; then
    ok "cert $KERSTIN_TLS_CERTFILE"
  else
    bad "cert missing: $KERSTIN_TLS_CERTFILE"
  fi
  if [[ -z "$TLS_KEY" ]]; then
    bad "KERSTIN_TLS_KEYFILE not set"
  elif [[ -f "$TLS_KEY" ]]; then
    ok "key $TLS_KEY"
    mode=$(stat -c '%a' "$TLS_KEY" 2>/dev/null || true)
    if [[ "$mode" == "600" ]]; then
      ok "key mode 600"
    else
      warn "key mode ${mode:-unknown}, expected 600"
    fi
  else
    bad "key missing: $TLS_KEY"
  fi
  if [[ -f "$KERSTIN_TLS_CERTFILE" ]]; then
    if openssl x509 -checkend 2592000 -noout -in "$KERSTIN_TLS_CERTFILE" >/dev/null 2>&1; then
      ok "cert valid for more than 30 days"
    else
      warn "cert expires within 30 days (or cannot be parsed)"
    fi
    echo "         SANs:"
    openssl x509 -noout -ext subjectAltName -in "$KERSTIN_TLS_CERTFILE" 2>/dev/null \
      | tail -n +2 | tr ',' '\n' | sed 's/^ */           /' || true
  fi
fi

echo "GPU"
if command -v nvidia-smi >/dev/null; then
  t=$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
  if [[ -n "$t" ]]; then
    if (( t >= 80 )); then warn "GPU at ${t} °C — close to the 84 °C shutdown limit"; else ok "GPU at ${t} °C"; fi
  fi
  nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/         /'
else warn "nvidia-smi not found"; fi
