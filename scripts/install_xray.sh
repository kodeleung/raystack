#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Prepare binaries/accounts only; deployment.py owns service activation.
python3 "${SCRIPT_DIR}/runtime_install.py" reality
