#!/usr/bin/env bash
# Install, uninstall or inspect Kerstin as a systemd user service.
# Usage: scripts/install_service.sh [install|uninstall|status] [--unit app|tts] [--name NAME] [--port PORT] [--env KEY=VALUE]... [--enable] [--dry-run]
set -euo pipefail
cd "$(dirname "$0")/.."

ACTION="install"
UNIT_KIND="app"
NAME=""
PORT=""
ENABLE=0
DRY_RUN=0
ENVS=()
USAGE="usage: $0 [install|uninstall|status] [--unit app|tts] [--name NAME] [--port PORT] [--env KEY=VALUE]... [--enable] [--dry-run]"
MARKER="# Managed by Kerstin scripts/install_service.sh — do not edit; re-run the installer."
UNIT_DIR="$HOME/.config/systemd/user"

usage_error() {
  echo "$USAGE" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    install|uninstall|status)
      ACTION="$1"
      shift
      ;;
    --unit)
      [[ $# -ge 2 ]] || usage_error
      UNIT_KIND="$2"
      [[ "$UNIT_KIND" == "app" || "$UNIT_KIND" == "tts" ]] || usage_error
      shift 2
      ;;
    --name)
      [[ $# -ge 2 ]] || usage_error
      NAME="$2"
      shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || usage_error
      PORT="$2"
      shift 2
      ;;
    --env)
      [[ $# -ge 2 ]] || usage_error
      ENVS+=("$2")
      shift 2
      ;;
    --enable)
      ENABLE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      usage_error
      ;;
  esac
done

if [[ -z "$NAME" ]]; then
  NAME="kerstin-tts"
  [[ "$UNIT_KIND" == "app" ]] && NAME="kerstin"
fi
if [[ ! "$NAME" =~ ^kerstin[a-z0-9-]*$ ]]; then
  echo "error: --name must match ^kerstin[a-z0-9-]*$" >&2
  exit 2
fi
if [[ -n "$PORT" && ! "$PORT" =~ ^[0-9]+$ ]]; then
  echo "error: --port must be numeric" >&2
  exit 2
fi
if [[ -n "$PORT" ]] && (( PORT < 1 || PORT > 65535 )); then
  echo "error: --port must be between 1 and 65535" >&2
  exit 2
fi
ENV_LINES=""
for pair in "${ENVS[@]}"; do
  key="${pair%%=*}"
  value="${pair#*=}"
  if [[ "$pair" != *=* || ! "$key" =~ ^(KERSTIN|KOKORO)_[A-Z0-9_]+$ ]]; then
    echo "error: --env must be KERSTIN_* or KOKORO_* KEY=VALUE" >&2
    exit 2
  fi
  if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
    echo "error: --env values must not contain newlines" >&2
    exit 2
  fi
  ENV_LINES+="Environment=${key}=${value}"$'\n'
done

REPO="$(pwd -P)"
UNIT="$UNIT_DIR/$NAME.service"
TTS_NAME="${NAME/kerstin/kerstin-tts}"

env_value() {
  local key="$1"
  if [[ -f .env ]]; then
    sed -n "s/^${key}=//p" .env | tail -n 1 | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
  fi
}

target_port() {
  if [[ -n "$PORT" ]]; then
    printf '%s\n' "$PORT"
  elif [[ "$UNIT_KIND" == "tts" ]]; then
    local value
    value="$(env_value KOKORO_PORT)"
    printf '%s\n' "${value:-8880}"
  else
    local value
    value="$(env_value KERSTIN_PORT)"
    printf '%s\n' "${value:-8770}"
  fi
}

render_unit() {
  local port_env="" wants="" template line
  if [[ -n "$PORT" ]]; then
    if [[ "$UNIT_KIND" == "tts" ]]; then
      port_env="Environment=KOKORO_PORT=$PORT"
    else
      port_env="Environment=KERSTIN_PORT=$PORT"
    fi
  fi
  template="deploy/kerstin.service.in"
  if [[ "$UNIT_KIND" == "tts" ]]; then
    template="deploy/kerstin-tts.service.in"
  elif [[ -x ".venv-kokoro/bin/python" && -d "voices/kokoro/kerstin" ]]; then
    wants="Wants=${TTS_NAME}.service"$'\n'"After=${TTS_NAME}.service"$'\n'
  fi
  while IFS= read -r line; do
    if [[ "$line" == "@ENV_LINES@" ]]; then
      printf '%s' "$ENV_LINES"
      continue
    fi
    if [[ "$line" == "@WANTS_TTS@" ]]; then
      printf '%s' "$wants"
      continue
    fi
    line="${line//@NAME@/$NAME}"
    line="${line//@REPO@/$REPO}"
    line="${line//@PORT_ENV@/$port_env}"
    printf '%s\n' "$line"
  done < "$template"
}

unit_is_managed() {
  [[ -f "$UNIT" ]] && [[ "$(head -n 1 "$UNIT")" == "$MARKER" ]]
}

print_commands() {
  case "$ACTION" in
    install)
      echo "# would run: systemctl --user daemon-reload"
      echo "# would run: systemctl --user reset-failed $NAME"
      echo "# would run: systemctl --user restart $NAME"
      if (( ENABLE )); then
        echo "# would run: systemctl --user enable $NAME"
        echo "# would run: loginctl show-user $USER -p Linger"
      fi
      echo "# logs: journalctl --user -u $NAME -f"
      ;;
    uninstall)
      echo "# would run: systemctl --user disable --now $NAME"
      echo "# would remove: $UNIT"
      echo "# would run: systemctl --user daemon-reload"
      ;;
    status)
      echo "# would run: systemctl --user status $NAME --no-pager"
      ;;
  esac
}

if (( DRY_RUN )); then
  if [[ "$ACTION" == "install" ]]; then
    render_unit
  fi
  echo "# unit: $UNIT"
  print_commands
  exit 0
fi

case "$ACTION" in
  install)
    if [[ "$UNIT_KIND" == "tts" ]]; then
      if [[ ! -x ".venv-kokoro/bin/python" ]]; then
        echo "error: .venv-kokoro/bin/python not found; run make kokoro-setup first" >&2
        exit 1
      fi
    elif [[ ! -x ".venv/bin/python" ]]; then
      echo "error: .venv/bin/python not found; run make setup first" >&2
      exit 1
    fi
    if [[ -f "$UNIT" ]] && ! unit_is_managed; then
      echo "error: refusing to overwrite an unmanaged unit: $UNIT" >&2
      exit 1
    fi

    mkdir -p "$UNIT_DIR"
    tmp_unit="$(mktemp "$UNIT_DIR/.${NAME}.service.XXXXXX")"
    trap 'rm -f "$tmp_unit"' EXIT
    render_unit > "$tmp_unit"
    mv "$tmp_unit" "$UNIT"
    trap - EXIT
    echo "Installed $UNIT"

    systemctl --user daemon-reload
    port="$(target_port)"
    if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "([.:])${port}$"; then
      echo "warning: port $port is already listening (stop a manual make run first)" >&2
    fi
    # Clear a previous start-limit failure so restart is not refused.
    systemctl --user reset-failed "$NAME" 2>/dev/null || true
    systemctl --user restart "$NAME"
    if (( ENABLE )); then
      systemctl --user enable "$NAME"
      linger="$(loginctl show-user "$USER" -p Linger 2>/dev/null || true)"
      echo "$linger"
      if [[ "$linger" == "Linger=no" ]]; then
        echo "hint: sudo loginctl enable-linger $USER"
      fi
    fi
    echo "Logs: journalctl --user -u $NAME -f"
    ;;
  uninstall)
    if [[ ! -f "$UNIT" ]]; then
      echo "Unit not installed: $UNIT"
      exit 0
    fi
    if ! unit_is_managed; then
      echo "error: refusing to remove an unmanaged unit: $UNIT" >&2
      exit 1
    fi
    systemctl --user disable --now "$NAME" || true
    rm -f "$UNIT"
    systemctl --user daemon-reload
    systemctl --user reset-failed "$NAME" 2>/dev/null || true
    echo "Uninstalled $UNIT"
    ;;
  status)
    systemctl --user status "$NAME" --no-pager || true
    port="$(target_port)"
    scheme="http"
    if [[ "$UNIT_KIND" == "app" && -n "$(env_value KERSTIN_TLS_CERTFILE)" ]]; then
      scheme="https"
    fi
    echo
    echo "GET $scheme://localhost:$port/health"
    curl -sk "$scheme://localhost:$port/health" || true
    echo
    ;;
esac
