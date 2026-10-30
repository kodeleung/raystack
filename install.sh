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
TRAFFIC_ENABLED="no"
TRAFFIC_CONFIG=""
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

prompt_traffic() {
  local answer quota reset timezone choice iface direction default_iface node_address
  read -r -p "Enable traffic subscription? [Y/n]: " answer
  [[ "${answer}" != [nN]* ]] || return
  TRAFFIC_ENABLED="yes"
  while true; do
    read -r -p "Monthly quota in GB: " quota
    python3 -c 'import sys; sys.path.insert(0,sys.argv[1]); from traffic import quota_bytes; quota_bytes(sys.argv[2])' "${SCRIPTS_DIR}" "${quota}" 2>/dev/null && break
    echo "Enter a positive quota in GB."
  done
  while true; do
    read -r -p "Monthly reset day [1]: " reset
    reset="${reset:-1}"
    [[ "${reset}" =~ ^([1-9]|[12][0-9]|3[01])$ ]] && break
    echo "Enter a day from 1 to 31."
  done
  while true; do
    read -r -p "Timezone: 1) Beijing  2) UTC  3) Custom [1]: " choice
    case "${choice:-1}" in
      1) timezone="Asia/Shanghai";; 2) timezone="UTC";; 3) read -r -p "IANA timezone: " timezone;; *) continue;;
    esac
    python3 -c 'import sys; from zoneinfo import ZoneInfo; ZoneInfo(sys.argv[1])' "${timezone}" 2>/dev/null && break
    echo "Invalid timezone."
  done
  default_iface="$(ip -4 route show default | awk 'NR == 1 {for(i=1;i<=NF;i++) if ($i == "dev") {print $(i+1); exit}}')"
  while true; do
    read -r -p "Public network interface [${default_iface}]: " iface
    iface="${iface:-${default_iface}}"
    [[ "${iface}" =~ ^[a-zA-Z0-9_.-]+$ && "${iface}" != lo && -d "/sys/class/net/${iface}" ]] && break
    echo "Enter an existing non-loopback interface."
  done
  read -r -p "Count traffic: 1) outbound  2) inbound and outbound [1]: " choice
  case "${choice:-1}" in 1) direction=outbound;; 2) direction=both;; *) fail "Invalid accounting selection";; esac
  if [[ "${MODE}" == reality ]]; then
    while true; do
      read -r -p "Domain pointing to this VPS for HTTPS subscription: " DOMAIN
      [[ "${DOMAIN}" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]$ ]] && break
      echo "Enter a valid domain."
    done
    HTTPS_PORT=8443
  fi
  node_address="${DOMAIN}"
  TRAFFIC_CONFIG="$(mktemp)"
  chmod 600 "${TRAFFIC_CONFIG}"
  if ${SUDO} test -f /etc/raystack/traffic.json; then
    ${SUDO} cat /etc/raystack/traffic.json > "${TRAFFIC_CONFIG}"
  fi
  python3 - "${TRAFFIC_CONFIG}" "${SCRIPTS_DIR}" "${quota}" "${reset}" "${timezone}" "${iface}" "${direction}" "${DOMAIN}" "${HTTPS_PORT}" "${MODE}" "${node_address}" <<'PYCONFIG'
import json, os, secrets, sys
path, scripts, quota, day, tz, interface, accounting, domain, port, mode, address = sys.argv[1:]
sys.path.insert(0, scripts)
from traffic import quota_bytes
old = {}
try:
    with open(path) as f: old = json.load(f)
except (OSError, ValueError): pass
if old and (old.get('traffic', {}).get('timezone') != tz or old.get('traffic', {}).get('interface') != interface):
    raise SystemExit('Changing timezone or interface requires a fresh statistics database; aborting to preserve existing data.')
config = {'token': old.get('token') or secrets.token_hex(32), 'traffic': {'quota_bytes': quota_bytes(quota), 'reset_day': int(day), 'timezone': tz, 'interface': interface, 'accounting': accounting}, 'nodes': {'mode': mode, 'domain': domain, 'https_port': int(port), 'node_address': address}}
with open(path, 'w') as f: json.dump(config, f)
PYCONFIG
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
      run ${SUDO} apt-get install -y curl unzip tar uuid-runtime openssl ca-certificates gnupg debian-keyring debian-archive-keyring apt-transport-https python3 tzdata iproute2
      ;;
    dnf)
      run ${SUDO} dnf install -y curl unzip tar util-linux openssl ca-certificates dnf-plugins-core python3 tzdata iproute
      ;;
    yum)
      run ${SUDO} yum install -y curl unzip tar util-linux openssl ca-certificates python3 tzdata iproute
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
  prompt_traffic
  run bash "${SCRIPTS_DIR}/install_xray.sh"
  if [[ "${MODE}" == "ws" || "${MODE}" == "both" ]]; then
    run bash "${SCRIPTS_DIR}/install_caddy.sh"
  fi
  if [[ "${TRAFFIC_ENABLED}" == yes ]]; then
    case "$(detect_package_manager)" in
      apt) run ${SUDO} apt-get install -y python3 tzdata iproute2 vnstat;;
      dnf) run ${SUDO} dnf install -y python3 tzdata iproute vnstat;;
      yum) run ${SUDO} yum install -y python3 tzdata iproute vnstat;;
    esac
    if [[ "${MODE}" == reality ]]; then run bash "${SCRIPTS_DIR}/install_caddy.sh"; fi
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
  if [[ "${TRAFFIC_ENABLED}" == yes ]]; then
    python3 - "${TRAFFIC_CONFIG}" "${UUID}" "${REALITY_SNI}" "${REALITY_PUBLIC_KEY}" "${REALITY_SHORT_ID}" <<'PYCONFIG'
import json, sys
path, uuid, sni, key, short = sys.argv[1:]
with open(path) as f: config = json.load(f)
config['nodes'].update(uuid=uuid, reality_sni=sni, reality_public_key=key, reality_short_id=short)
with open(path, 'w') as f: json.dump(config, f)
PYCONFIG
    run bash "${SCRIPTS_DIR}/install_traffic.sh" "${TRAFFIC_CONFIG}" "${PROJECT_DIR}"
    if [[ "${MODE}" == reality ]]; then
      printf '{\n  https_port 8443\n}\n%s {\n  handle /subscription/* {\n    reverse_proxy 127.0.0.1:8765\n  }\n  handle {\n    respond "OK"\n  }\n}\n' "${DOMAIN}" | ${SUDO} tee /etc/caddy/Caddyfile >/dev/null
    else
      ${SUDO} python3 -c 'p="/etc/caddy/Caddyfile"; s=open(p).read(); s=s.replace("  handle /ray* {", "  handle /subscription/* {\n    reverse_proxy 127.0.0.1:8765\n  }\n\n  handle /ray* {"); open(p,"w").write(s)'
    fi
    run ${SUDO} caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
    run ${SUDO} systemctl enable --now caddy
    run ${SUDO} systemctl reload caddy
  fi
  validate_configs
  start_services

  print_client_summary
  print_clash_config
  if [[ "${TRAFFIC_ENABLED}" == yes ]]; then
    python3 - "${TRAFFIC_CONFIG}" <<'PYCONFIG'
import json, sys
with open(sys.argv[1]) as f: c = json.load(f)
t, n = c['traffic'], c['nodes']
print('Subscription URL: https://%s:%s/subscription/%s' % (n['domain'], n['https_port'], c['token']))
print('Traffic: %s; reset day %s at midnight %s; 1 GB = 1,000,000,000 bytes.' % (t['accounting'], t['reset_day'], t['timezone']))
print('Only traffic observed after installation is included. Allow HTTPS and HTTP port 80 for certificates.')
PYCONFIG
    rm "${TRAFFIC_CONFIG}"
  fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
