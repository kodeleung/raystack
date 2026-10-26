#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="${PROJECT_DIR}/scripts"

DOMAIN=""
UUID_FILE="/etc/raystack/uuid"
REALITY_PRIVATE_KEY_FILE="/etc/raystack/reality-private-key"
REALITY_PUBLIC_KEY_FILE="/etc/raystack/reality-public-key"
REALITY_SHORT_ID_FILE="/etc/raystack/reality-short-id"
MODE=""
HTTPS_PORT=""
REALITY_DEST="swscan.apple.com:443"
REALITY_SNI="swscan.apple.com"
REALITY_PRIVATE_KEY=""
REALITY_PUBLIC_KEY=""
REALITY_SHORT_ID=""

if [[ ${EUID} -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

log() {
  printf '[raystack] %s\n' "$*"
}

fail() {
  printf '[raystack] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  ./install.sh
EOF
}

run() {
  log "$*"
  "$@"
}

require_command() {
  local command_name="$1"

  if ! command -v "${command_name}" >/dev/null 2>&1; then
    fail "Missing required command: ${command_name}"
  fi
}

parse_args() {
  [[ $# -eq 0 ]] || {
    if [[ "$1" == "-h" || "$1" == "--help" ]]; then
      usage
      exit 0
    fi
    fail "This installer is interactive and does not accept arguments"
  }
}

prompt_mode() {
  while true; do
    printf '%s\n' "Select installation mode:"
    printf '%s\n' "  1) VLESS + WebSocket + TLS"
    printf '%s\n' "  2) VLESS + TCP + REALITY"
    printf '%s\n' "  3) Install both modes"
    read -r -p "Choice [1-3]: " selection

    case "${selection}" in
      1)
        MODE="ws"
        HTTPS_PORT="443"
        return
        ;;
      2)
        MODE="reality"
        return
        ;;
      3)
        MODE="both"
        HTTPS_PORT="8443"
        return
        ;;
      *)
        printf '%s\n' "Please enter 1, 2, or 3."
        ;;
    esac
  done
}

prompt_domain() {
  while [[ -z "${DOMAIN}" ]]; do
    read -r -p "Domain for WebSocket + TLS: " DOMAIN
    [[ -n "${DOMAIN}" ]] || printf '%s\n' "A domain is required for WebSocket + TLS."
  done
}

prompt_reality_value() {
  local label="$1"
  local default_value="$2"
  local input=""

  read -r -p "${label} [${default_value}]: " input
  printf '%s' "${input:-${default_value}}"
}

prompt_mode_parameters() {
  if [[ "${MODE}" == "ws" || "${MODE}" == "both" ]]; then
    prompt_domain
  fi

  if [[ "${MODE}" == "reality" || "${MODE}" == "both" ]]; then
    printf '%s\n' "Press Enter to accept each REALITY default."
    REALITY_DEST="$(prompt_reality_value "REALITY destination" "${REALITY_DEST}")"
    REALITY_SNI="$(prompt_reality_value "REALITY SNI" "${REALITY_SNI}")"
  fi
}

detect_package_manager() {
  if command -v apt-get >/dev/null 2>&1; then
    echo "apt"
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    echo "dnf"
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    echo "yum"
    return
  fi

  fail "Supported package manager not found (apt, dnf, yum)"
}

install_dependencies() {
  local package_manager
  package_manager="$(detect_package_manager)"

  log "Installing dependencies with ${package_manager}"

  case "${package_manager}" in
    apt)
      run ${SUDO} apt-get update -y
      run ${SUDO} apt-get install -y curl unzip tar uuid-runtime openssl ca-certificates gnupg debian-keyring debian-archive-keyring apt-transport-https
      ;;
    dnf)
      run ${SUDO} dnf install -y curl unzip tar util-linux openssl ca-certificates dnf-plugins-core
      ;;
    yum)
      run ${SUDO} yum install -y curl unzip tar util-linux openssl ca-certificates
      ;;
  esac
}

load_or_create_uuid() {
  if [[ -f "${UUID_FILE}" ]]; then
    UUID="$(tr -d '[:space:]' < "${UUID_FILE}")"
    log "Using existing UUID"
    return
  fi

  require_command uuidgen
  UUID="$(uuidgen)"
  run ${SUDO} mkdir -p "$(dirname "${UUID_FILE}")"
  log "Generating UUID"
  printf '%s\n' "${UUID}" | ${SUDO} tee "${UUID_FILE}" >/dev/null
}

parse_reality_key_pair() {
  local key_pair="$1"

  REALITY_PRIVATE_KEY="$(awk -F': *' '$1 == "PrivateKey" { print $2; exit }' <<<"${key_pair}" | tr -d '[:space:]')"
  REALITY_PUBLIC_KEY="$(awk -F': *' '$1 ~ /^Password/ { print $2; exit }' <<<"${key_pair}" | tr -d '[:space:]')"
}

load_or_create_reality_credentials() {
  if [[ -f "${REALITY_PRIVATE_KEY_FILE}" && -f "${REALITY_PUBLIC_KEY_FILE}" && -f "${REALITY_SHORT_ID_FILE}" ]]; then
    REALITY_PRIVATE_KEY="$(tr -d '[:space:]' < "${REALITY_PRIVATE_KEY_FILE}")"
    REALITY_PUBLIC_KEY="$(tr -d '[:space:]' < "${REALITY_PUBLIC_KEY_FILE}")"
    REALITY_SHORT_ID="$(tr -d '[:space:]' < "${REALITY_SHORT_ID_FILE}")"
    log "Using existing REALITY credentials"
    return
  fi

  require_command xray
  require_command openssl

  local key_pair
  key_pair="$(xray x25519)"
  parse_reality_key_pair "${key_pair}"
  REALITY_SHORT_ID="$(openssl rand -hex 8)"

  [[ -n "${REALITY_PRIVATE_KEY}" && -n "${REALITY_PUBLIC_KEY}" ]] || fail "Unable to generate REALITY key pair"

  run ${SUDO} mkdir -p /etc/raystack
  log "Generating REALITY credentials"
  printf '%s\n' "${REALITY_PRIVATE_KEY}" | ${SUDO} tee "${REALITY_PRIVATE_KEY_FILE}" >/dev/null
  printf '%s\n' "${REALITY_PUBLIC_KEY}" | ${SUDO} tee "${REALITY_PUBLIC_KEY_FILE}" >/dev/null
  printf '%s\n' "${REALITY_SHORT_ID}" | ${SUDO} tee "${REALITY_SHORT_ID_FILE}" >/dev/null
}

validate_configs() {
  log "Validating Xray config"
  run ${SUDO} xray run -test -config /usr/local/etc/xray/config.json

  if [[ "${MODE}" == "ws" || "${MODE}" == "both" ]]; then
    log "Validating Caddy config"
    run ${SUDO} caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
  fi
}

start_services() {
  log "Starting services"
  run ${SUDO} systemctl daemon-reload

  if [[ "${MODE}" == "ws" || "${MODE}" == "both" ]]; then
    run ${SUDO} systemctl enable --now caddy
    # In combined mode this releases Caddy's former port 443 before Xray binds it.
    run ${SUDO} systemctl reload caddy
  fi

  run ${SUDO} systemctl enable --now xray
  run ${SUDO} systemctl restart xray
}

print_client_summary() {
  printf '\n%s\n' "Installation complete"
  printf '%s\n' "UUID: ${UUID}"

  if [[ "${MODE}" == "ws" || "${MODE}" == "both" ]]; then
    printf '%s\n' "WebSocket + TLS: address=${DOMAIN}, port=${HTTPS_PORT}, path=/ray, security=tls"
  fi

  if [[ "${MODE}" == "reality" || "${MODE}" == "both" ]]; then
    printf '%s\n' "TCP + REALITY: address=<your-server-ip-or-domain>, port=443, flow=xtls-rprx-vision"
    printf '%s\n' "REALITY SNI: ${REALITY_SNI}"
    printf '%s\n' "REALITY public key: ${REALITY_PUBLIC_KEY}"
    printf '%s\n' "REALITY short ID: ${REALITY_SHORT_ID}"
  fi
}

print_clash_config() {
  printf '\n%s\n' "----- BEGIN MIHOMO / CLASH META PROXIES -----"
  printf '%s\n' "# Paste this block into your Mihomo / Clash Meta configuration."
  printf '%s\n' "proxies:"

  if [[ "${MODE}" == "ws" || "${MODE}" == "both" ]]; then
    printf '%s\n' '  - name: "raystack-ws"'
    printf '%s\n' '    type: vless'
    printf '%s\n' "    server: \"${DOMAIN}\""
    printf '%s\n' "    port: ${HTTPS_PORT}"
    printf '%s\n' "    uuid: \"${UUID}\""
    printf '%s\n' '    udp: true'
    printf '%s\n' '    tls: true'
    printf '%s\n' '    servername: "'"${DOMAIN}"'"'
    printf '%s\n' '    network: ws'
    printf '%s\n' '    ws-opts:'
    printf '%s\n' '      path: "/ray"'
    printf '%s\n' '    encryption: ""'
  fi

  if [[ "${MODE}" == "reality" || "${MODE}" == "both" ]]; then
    printf '%s\n' '  - name: "raystack-reality"'
    printf '%s\n' '    type: vless'
    printf '%s\n' '    server: "YOUR_SERVER_ADDRESS"'
    printf '%s\n' '    port: 443'
    printf '%s\n' "    uuid: \"${UUID}\""
    printf '%s\n' '    udp: true'
    printf '%s\n' '    flow: xtls-rprx-vision'
    printf '%s\n' '    tls: true'
    printf '%s\n' "    servername: \"${REALITY_SNI}\""
    printf '%s\n' '    client-fingerprint: chrome'
    printf '%s\n' '    network: tcp'
    printf '%s\n' '    reality-opts:'
    printf '%s\n' '      support-x25519mlkem768: true'
    printf '%s\n' "      public-key: \"${REALITY_PUBLIC_KEY}\""
    printf '%s\n' "      short-id: \"${REALITY_SHORT_ID}\""
    printf '%s\n' '    encryption: ""'
  fi

  printf '%s\n' "----- END MIHOMO / CLASH META PROXIES -----"
}

main() {
  parse_args "$@"

  require_command bash
  require_command systemctl

  prompt_mode
  prompt_mode_parameters

  install_dependencies
  run bash "${SCRIPTS_DIR}/install_xray.sh"
  if [[ "${MODE}" == "ws" || "${MODE}" == "both" ]]; then
    run bash "${SCRIPTS_DIR}/install_caddy.sh"
  fi
  load_or_create_uuid
  if [[ "${MODE}" == "reality" || "${MODE}" == "both" ]]; then
    load_or_create_reality_credentials
  fi
  run bash "${SCRIPTS_DIR}/generate_config.sh" \
    --mode "${MODE}" \
    --domain "${DOMAIN}" \
    --uuid "${UUID}" \
    --project-dir "${PROJECT_DIR}" \
    --https-port "${HTTPS_PORT}" \
    --reality-dest "${REALITY_DEST}" \
    --reality-sni "${REALITY_SNI}" \
    --reality-private-key "${REALITY_PRIVATE_KEY}" \
    --reality-short-id "${REALITY_SHORT_ID}"
  validate_configs
  start_services

  print_client_summary
  print_clash_config
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
