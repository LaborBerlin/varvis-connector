#!/bin/bash
# Run test coverage check: will check if all sources in the "tests/" directory have
# full coverage (misses in test code are usually a bug in the test implementation).
#
# Used by `make coverage-check`.

set -Euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/.."
test -f "$ROOT/.env" && source "$ROOT/.env"

if report=$(uv run coverage report -m); then
  set -e
  echo "$report"
  echo "$report" | while read -r line; do
    if [[ "$line" =~ ^tests/ ]]; then
      miss=$(echo "$line" | awk '{print $3}')
      if [[ "$miss" -gt 0 ]]; then
        echo -e "\033[31m Found missing coverage ($miss) in tests file: $(echo "$line" | awk '{print $1}')\033[0m"
        exit 1
      fi
    fi
  done &&
    echo -e "\033[32mCoverage report check passed\033[0m"
else
  echo -e "\033[31mNo coverage data present. You should run 'make coverage' first.\033[0m"
fi

