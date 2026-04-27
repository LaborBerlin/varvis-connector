#!/bin/bash
# Audit the Python dependencies using `pip-audit`
#
# Export *all* dependencies in requirements.txt format (includes dependencies for all extras and all dependency groups).
# The exported requirements file contains the exact versions and hashes, so we don't need pip for dependency resolution
# (--disable-pip). We also exclude packages passed as arguments.
#
# Used by `make audit`.
#
# Arguments: Packages to exclude from audit, e.g. ./audit-deps.sh baserow-connector

set -Eeuo pipefail

echo "Generating requirements.txt ..."
reqfile=$(mktemp --suffix .txt)
uv export --locked --all-extras --all-groups \
  --no-annotate \
  --no-editable \
  --no-emit-local \
  --no-progress -q \
  -o "$reqfile"

tmpfile=$(mktemp --suffix .txt)
for exclude_pkg in "$@"; do
  echo "Excluding package $exclude_pkg"

  grep -v "^$exclude_pkg==" "$reqfile" >"$tmpfile"
  cp "$tmpfile" "$reqfile"
done

echo "Auditing dependencies ..."
uv run pip-audit --disable-pip --aliases -r "$reqfile"
