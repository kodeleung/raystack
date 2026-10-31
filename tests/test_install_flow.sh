#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_DIR}/install.sh"
[[ "$(printf '1\n' | { prompt_mode >/dev/null; echo "$MODE"; })" == ws ]]
[[ "$(printf '2\n' | { prompt_mode >/dev/null; echo "$MODE"; })" == reality ]]
[[ "$(printf '3\n' | { prompt_mode >/dev/null; echo "$MODE"; })" == hy2 ]]
[[ "$(printf '4\n' | { prompt_mode >/dev/null; echo "$MODE"; })" == 3x-ui ]]
if prompt_mode </dev/null >/dev/null; then
  echo 'Canceled input must stop installation' >&2
  exit 1
fi
[[ ! -e "${PROJECT_DIR}/config/xray-both.json" ]]
if bash "${PROJECT_DIR}/scripts/generate_config.sh" --mode both --uuid test --project-dir "$PROJECT_DIR" 2>/dev/null; then
  echo 'Removed both mode was accepted' >&2
  exit 1
fi
