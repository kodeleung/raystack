#!/usr/bin/env bash
set -euo pipefail
if [[ "${RAYSTACK_RUNTIME_TEST:-0}" != 1 ]]; then
  echo 'SKIP HY2 runtime smoke test: set RAYSTACK_RUNTIME_TEST=1 to use a disposable Docker container.'
  exit 0
fi
command -v docker >/dev/null || { echo 'Docker is required for the opt-in runtime test' >&2; exit 1; }
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker run --rm -e DEBIAN_FRONTEND=noninteractive -e PYTHONDONTWRITEBYTECODE=1 \
  -v "${PROJECT_DIR}:/workspace:ro" -w /workspace ubuntu:24.04 bash -ec \
  'apt-get update -qq && apt-get install -y -qq python3 curl openssl ca-certificates >/dev/null && python3 tests/hy2_runtime.py'
