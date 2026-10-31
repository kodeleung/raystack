#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="${PROJECT_DIR}/scripts"
MODE=""
DOMAIN=""
EMAIL=""
UUID=""
HTTPS_PORT="443"
REALITY_DEST="www.bing.com:443"
REALITY_SNI="www.bing.com"
REALITY_PRIVATE_KEY=""
REALITY_PUBLIC_KEY=""
REALITY_SHORT_ID=""
HY2_PASSWORD=""

log() { printf '[raystack] %s\n' "$*"; }
fail() { printf '[raystack] ERROR: %s\n' "$*" >&2; return 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }
usage() { printf 'Usage: sudo bash ./install.sh\n'; }
parse_args() {
  if [[ $# -gt 0 ]]; then
    if [[ $# -eq 1 && ( "$1" == -h || "$1" == --help ) ]]; then usage; exit 0; fi
    fail 'This installer is interactive and does not accept arguments'
  fi
}

prompt_mode() {
  local selection
  while true; do
    printf '%s\n' 'Select installation mode:' \
      '  1) VLESS + WebSocket + TLS' \
      '  2) VLESS + TCP + REALITY' \
      '  3) Hysteria 2' \
      '  4) 3x-ui panel (official installer)'
    read -r -p 'Choice [1-4]: ' selection || return 1
    case "$selection" in
      1) MODE=ws; return ;;
      2) MODE=reality; return ;;
      3) MODE=hy2; return ;;
      4) MODE=3x-ui; return ;;
      *) printf '%s\n' 'Please enter 1, 2, 3, or 4.' ;;
    esac
  done
}

install_3x_ui() (
  local installer
  installer="$(mktemp)" || return 1
  trap 'rm -f -- "$installer"' EXIT
  log 'Existing raystack services remain running. Avoid port conflicts when creating nodes in 3x-ui.'
  log 'Starting the official 3x-ui installer; configure nodes and subscriptions in the panel afterward.'
  curl --fail --show-error --silent --location \
    https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh \
    --output "$installer" || return 1
  bash "$installer"
)

prompt_mode_parameters() {
  if [[ "$MODE" == ws || "$MODE" == hy2 ]]; then
    read -r -p 'Domain pointed directly to this server: ' DOMAIN || return 1
    [[ -n "$DOMAIN" ]] || { fail 'A domain is required'; return 1; }
    log 'Use DNS-only records (Cloudflare grey cloud), and only publish working IPv6 addresses.'
  fi
  if [[ "$MODE" == hy2 ]]; then
    read -r -p 'Email for automatic certificate management: ' EMAIL || return 1
    log 'Allow UDP 8443 for HY2 and TCP 80 for certificate issuance and renewal.'
  elif [[ "$MODE" == ws ]]; then
    log 'Allow TCP 80 and TCP 443 for Caddy.'
  elif [[ "$MODE" == reality ]]; then
    local input
    read -r -p "REALITY destination [${REALITY_DEST}]: " input || return 1
    REALITY_DEST="${input:-$REALITY_DEST}"
    read -r -p "REALITY SNI [${REALITY_SNI}]: " input || return 1
    REALITY_SNI="${input:-$REALITY_SNI}"
    log 'Allow TCP 8443 for REALITY.'
  fi
}

# Kept as a sourceable helper for older callers and its compatibility tests.
parse_reality_key_pair() {
  local key_pair="$1"
  REALITY_PRIVATE_KEY="$(awk -F': *' '$1 == "PrivateKey" { print $2; exit }' <<<"${key_pair}" | tr -d '[:space:]')"
  REALITY_PUBLIC_KEY="$(awk -F': *' '$1 ~ /^Password/ { print $2; exit }' <<<"${key_pair}" | tr -d '[:space:]')"
}

print_clash_config() (
  export MODE DOMAIN UUID REALITY_SNI REALITY_PUBLIC_KEY REALITY_SHORT_ID HY2_PASSWORD
  python3 "${SCRIPTS_DIR}/print_client_config.py"
)

main() {
  parse_args "$@"
  [[ "$(uname -s)" == Linux ]] || { fail 'Installation requires Linux with systemd'; return 1; }
  if [[ $EUID -ne 0 ]]; then exec sudo bash "${PROJECT_DIR}/install.sh" "$@"; fi
  require_command curl || return 1
  require_command systemctl || return 1
  prompt_mode || return 1
  if [[ "$MODE" == 3x-ui ]]; then
    install_3x_ui
    return $?
  fi
  local command_name
  for command_name in python3 curl openssl systemctl ss flock useradd; do
    require_command "$command_name" || return 1
  done
  prompt_mode_parameters
  # Do not start deployment when input preparation fails. Credentials stay in memory.
  local prepared options_file
  options_file="$(mktemp)"
  chmod 600 "$options_file"
  trap 'rm "${SUBSCRIPTION_OPTIONS_FILE}"' EXIT
  SUBSCRIPTION_OPTIONS_FILE="$options_file"
  python3 "${SCRIPTS_DIR}/subscription_prompts.py" "$MODE" "$DOMAIN" > "$options_file" || return 1
  prepared="$(python3 "${SCRIPTS_DIR}/installer_input.py" "$MODE" "$DOMAIN" "$EMAIL" "$REALITY_DEST" "$REALITY_SNI")" || return 1
  printf '%s\n' "$prepared" | python3 "${SCRIPTS_DIR}/deployment.py" --mode "$MODE" --subscription-options "$options_file"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then main "$@"; fi
