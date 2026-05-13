#!/bin/bash
# Run all the checks for all the supported Python versions.
#
# Arguments: Python versions to check, e.g. ./test-all.sh 3.11 3.12
#
# Used by `make testall`.

set -u

export UV_SYSTEM_CERTS=1
export UV_EXCLUDE_NEWER="7 days"

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/.."
test -f "$ROOT/.env" && source "$ROOT/.env"

for pyvers in "$@"; do
  echo "Running tests with Python version $pyvers"
  if uvx run --python="$pyvers" ruff check &&
    uvx run --python="$pyvers" basedpyright src/ &&
    uv run --python="$pyvers" --isolated --dev --all-extras pytest -xrsfE -n auto tests; then
    echo -e "\033[32mAll checks passed for Python $pyvers\033[0m"
  else
    echo -e "\033[31mSome checks failed for Python $pyvers\033[0m"
    break
  fi
done
