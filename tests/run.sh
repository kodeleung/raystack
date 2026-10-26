#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONDONTWRITEBYTECODE=1
for script in install.sh scripts/*.sh tests/*.sh; do bash -n "$script"; done
for test in tests/test_*.sh; do
  [[ "$test" == tests/test_hy2_runtime.sh ]] && continue
  bash "$test"
done
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash tests/test_hy2_runtime.sh
