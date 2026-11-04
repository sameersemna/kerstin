#!/usr/bin/env bash
# Create a project-local CA and a server certificate for HTTPS on the LAN.
# The CA is reused on later runs so clients only have to trust it once.
set -euo pipefail

cd "$(dirname "$0")/.."

HOST_SHORT="$(hostname -s)"
CERT_DIR="certs"
CA_KEY="$CERT_DIR/kerstin-ca.key"
CA_CRT="$CERT_DIR/kerstin-ca.crt"
SRV_KEY="$CERT_DIR/kerstin.key"
SRV_CRT="$CERT_DIR/kerstin.crt"

NEW_CA=0
EXTRA_IPS=()
EXTRA_DNS=()

usage() {
  cat <<EOF
Usage: bash scripts/make_certs.sh [--new-ca] [--ip ADDRESS]... [--dns NAME]...

  --new-ca     replace the existing local CA (clients must trust it again)
  --ip IP      add another IP SAN (repeatable)
  --dns NAME   add another DNS SAN, e.g. promaxgb10-6116.fritz.box (repeatable)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --new-ca)
      NEW_CA=1
      shift
      ;;
    --ip)
      if [[ $# -lt 2 ]]; then
        echo "error: --ip needs an address" >&2
        exit 2
      fi
      EXTRA_IPS+=("$2")
      shift 2
      ;;
    --dns)
      if [[ $# -lt 2 ]]; then
        echo "error: --dns needs a name" >&2
        exit 2
      fi
      EXTRA_DNS+=("$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# --- pick the LAN address -------------------------------------------------

DEFAULT_DEV="$(ip -4 route show default 2>/dev/null \
  | awk '$1 == "default" { for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }')"
DEFAULT_IP=""
if [[ -n "$DEFAULT_DEV" ]]; then
  case "$DEFAULT_DEV" in
    nordlynx|tun*|tap*|wg*|tailscale*|vpn*|ppp*) ;;  # VPN: fall back to a physical interface
    *)
      DEFAULT_IP="$(ip -4 -o addr show dev "$DEFAULT_DEV" scope global 2>/dev/null \
        | awk '{ split($4, a, "/"); print a[1]; exit }')"
      ;;
  esac
fi

if [[ -z "$DEFAULT_IP" ]]; then
  while read -r iface addr; do
    case "$iface" in
      lo|docker*|br-*|veth*|virbr*|lxcbr*|nordlynx|tun*|tap*|wg*|tailscale*|vpn*|ppp*)
        continue
        ;;
    esac
    case "$addr" in
      192.168.*|10.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*)
        DEFAULT_IP="$addr"
        break
        ;;
    esac
  done < <(ip -4 -o addr show scope global 2>/dev/null \
    | awk '{ split($4, a, "/"); print $2, a[1] }')
fi

# --- SANs -----------------------------------------------------------------

SAN_ENTRIES=("DNS:localhost" "DNS:${HOST_SHORT}" "DNS:${HOST_SHORT}.local" "IP:127.0.0.1")
add_san() {
  local entry="$1" existing
  for existing in "${SAN_ENTRIES[@]}"; do
    [[ "$existing" == "$entry" ]] && return 0
  done
  SAN_ENTRIES+=("$entry")
}
if [[ -n "$DEFAULT_IP" ]]; then
  add_san "IP:${DEFAULT_IP}"
fi
for extra in "${EXTRA_IPS[@]}"; do
  add_san "IP:${extra}"
done
for extra in "${EXTRA_DNS[@]}"; do
  add_san "DNS:${extra}"
done
SAN_STRING=$(printf '%s,' "${SAN_ENTRIES[@]}")
SAN_STRING=${SAN_STRING%,}

echo "Hostname: ${HOST_SHORT}"
echo "SANs:"
printf '  %s\n' "${SAN_ENTRIES[@]}"

# --- CA -------------------------------------------------------------------

umask 077
mkdir -p "$CERT_DIR"

if [[ "$NEW_CA" -eq 1 && ( -f "$CA_KEY" || -f "$CA_CRT" ) ]]; then
  echo "WARNING: --new-ca replaces the local CA; every client must trust it again." >&2
  rm -f "$CA_KEY" "$CA_CRT" "$CERT_DIR/kerstin-ca.srl"
fi

if [[ -f "$CA_KEY" && -f "$CA_CRT" ]]; then
  echo "Reusing existing CA: $CA_CRT"
else
  echo "Creating local CA ..."
  openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
    -keyout "$CA_KEY" -out "$CA_CRT" \
    -subj "/CN=Kerstin Local CA ($HOST_SHORT)" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
fi

# --- server certificate ---------------------------------------------------

TMP_CSR="$(mktemp)"
TMP_EXT="$(mktemp)"
trap 'rm -f "$TMP_CSR" "$TMP_EXT"' EXIT

echo "Creating server certificate ..."
openssl genrsa -out "$SRV_KEY" 3072
openssl req -new -key "$SRV_KEY" -out "$TMP_CSR" -subj "/CN=${HOST_SHORT}.local"

cat >"$TMP_EXT" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=${SAN_STRING}
EOF

openssl x509 -req -in "$TMP_CSR" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
  -days 397 -sha256 -extfile "$TMP_EXT" -out "$SRV_CRT"

chmod 600 "$CA_KEY" "$SRV_KEY"
chmod 644 "$CA_CRT" "$SRV_CRT"

echo
openssl verify -CAfile "$CA_CRT" "$SRV_CRT"
openssl x509 -in "$SRV_CRT" -noout -subject -dates -ext subjectAltName

PORT="${KERSTIN_PORT:-8770}"
cat <<EOF

Next steps:
  Add to .env:
    KERSTIN_HOST=0.0.0.0
    KERSTIN_TLS_CERTFILE=certs/kerstin.crt
    KERSTIN_TLS_KEYFILE=certs/kerstin.key
    KERSTIN_TLS_CA_CERTFILE=certs/kerstin-ca.crt

  Start Kerstin:
    make run

  Open on the Mac/phone:
    https://${HOST_SHORT}.local:${PORT}

  Trust the CA once (download it at):
    https://${HOST_SHORT}.local:${PORT}/kerstin-ca.crt
EOF
