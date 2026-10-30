#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for mode in ws reality; do
  rendered="$(mktemp)"
  trap 'rm -f "${rendered}"' EXIT

  sed \
    -e 's|__UUID__|11111111-1111-4111-8111-111111111111|g' \
    -e 's|__REALITY_DEST__|www.bing.com:443|g' \
    -e 's|__REALITY_SNI__|www.bing.com|g' \
    -e 's|__REALITY_PRIVATE_KEY__|private-key|g' \
    -e 's|__REALITY_SHORT_ID__|a1b2c3d4e5f60708|g' \
    "${PROJECT_DIR}/config/xray-${mode}.json" > "${rendered}"

  python3 - "${rendered}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as config_file:
    config = json.load(config_file)

assert config["outbounds"][0]["settings"]["domainStrategy"] == "ForceIPv4"
PY

  rm -f "${rendered}"
  trap - EXIT
done
