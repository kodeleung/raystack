#!/usr/bin/env bash
set -euo pipefail
# Disposable Linux smoke test. No public ports, production certificates or credentials.
if [[ "${RAYSTACK_SUBSCRIPTION_RUNTIME_TEST:-0}" != 1 ]]; then
  echo 'SKIP subscription Linux smoke test: set RAYSTACK_SUBSCRIPTION_RUNTIME_TEST=1.'
  exit 0
fi
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker run --rm -e DEBIAN_FRONTEND=noninteractive -e PYTHONDONTWRITEBYTECODE=1 \
  -v "${PROJECT_DIR}:/workspace:ro" -w /workspace ubuntu:24.04 bash -ec '
apt-get update -qq
apt-get install -y -qq python3 vnstat caddy tzdata >/dev/null
python3 tests/subscription_linux.py
'
