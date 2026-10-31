#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_DIR}/install.sh"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TEST_DIR"' EXIT

# Replace only the download: run the downloaded fixture with real Bash/stdin.
curl() {
  [[ "$*" == *https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh* ]]
  local output=''
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == --output ]]; then output="$2"; break; fi
    shift
  done
  [[ -n "$output" ]]
  printf '%s' "$output" > "$TEST_DIR/download-path"
  if [[ "${DOWNLOAD_FAIL:-0}" == 1 ]]; then
    printf 'exit 99\n' > "$output"
    return 22
  fi
  cat > "$output" <<'INSTALLER'
read -r answer
[[ "$answer" == panel-setup ]] || exit 98
exit 42
INSTALLER
}

status=0
install_3x_ui <<< 'panel-setup' > /dev/null || status=$?
[[ "$status" == 42 ]] # Preserve upstream exit status and interactive stdin.
[[ ! -e "$(cat "$TEST_DIR/download-path")" ]]

status=0
DOWNLOAD_FAIL=1 install_3x_ui > /dev/null || status=$?
[[ "$status" == 1 ]] # Do not execute a partial download.
[[ ! -e "$(cat "$TEST_DIR/download-path")" ]]
