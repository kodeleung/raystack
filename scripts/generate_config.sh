#!/usr/bin/env bash
# Render to a staging directory only. The deployment transaction owns activation.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE=""
OUTPUT_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) [[ $# -ge 2 ]] || exit 1; MODE="$2"; shift 2 ;;
    --output-dir) [[ $# -ge 2 ]] || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help) printf 'Usage: generate_config.sh --mode <ws|reality|hy2> --output-dir DIR < values.json\n'; exit 0 ;;
    *) printf 'Unsupported argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done
[[ -n "$MODE" && -n "$OUTPUT_DIR" ]] || { echo 'Mode and staging output directory are required' >&2; exit 1; }
python3 "${SCRIPT_DIR}/render_config.py" --mode "$MODE" --output-dir "$OUTPUT_DIR"
