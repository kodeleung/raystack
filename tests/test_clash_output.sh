#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_DIR}/install.sh"

UUID="11111111-1111-4111-8111-111111111111"
DOMAIN="example.com"
HTTPS_PORT="443"
REALITY_SNI="www.bing.com"
REALITY_PUBLIC_KEY="public-key"
REALITY_PRIVATE_KEY="private-key-must-not-appear"
REALITY_SHORT_ID="a1b2c3d4e5f60708"

assert_contains() {
  local haystack="$1"
  local needle="$2"
  [[ "${haystack}" == *"${needle}"* ]] || {
    printf 'Expected output to contain: %s\n' "${needle}" >&2
    exit 1
  }
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  [[ "${haystack}" != *"${needle}"* ]] || {
    printf 'Output must not contain: %s\n' "${needle}" >&2
    exit 1
  }
}

MODE="ws"
ws_output="$(print_clash_config)"
assert_contains "${ws_output}" 'name: "raystack-ws"'
assert_contains "${ws_output}" 'network: ws'
assert_contains "${ws_output}" 'path: "/ray"'

MODE="reality"
reality_output="$(print_clash_config)"
assert_contains "${reality_output}" 'name: "raystack-reality"'
assert_contains "${reality_output}" 'flow: xtls-rprx-vision'
assert_contains "${reality_output}" 'public-key: "public-key"'
assert_contains "${reality_output}" 'support-x25519mlkem768: true'
assert_not_contains "${reality_output}" "${REALITY_PRIVATE_KEY}"

MODE="hy2"
HY2_PASSWORD="test-password"
hy2_output="$(print_clash_config)"
assert_contains "${hy2_output}" 'type: hysteria2'
assert_contains "${hy2_output}" 'password: "test-password"'
assert_contains "${hy2_output}" 'sni: "example.com"'
assert_contains "${hy2_output}" 'skip-cert-verify: false'
assert_not_contains "${hy2_output}" 'uuid:'
assert_not_contains "${hy2_output}" 'raystack-reality'
