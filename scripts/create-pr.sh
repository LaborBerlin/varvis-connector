#!/bin/bash
# Prepare a pull request: generate changelog, optionally bump the version, create & push a release branch, and open the
# PR draft in a browser.
#
# Used by `make pr`.

set -Eeuo pipefail

CUR_VERS=$(uv version | cut -d" " -f2)
echo "Preparing a PR"
echo "Current version is: $CUR_VERS"
echo "Please enter new version (without \"v\" at the start!), a bump command like \"stable\", \"major\", \"minor\", \"patch\", etc. or leave empty to keep the current version:"

read -r NEW_VERS
if [ -n "$NEW_VERS" ]; then
  if [[ "$NEW_VERS" =~ ^[0-9] ]]; then
    # a fixed version like 0.1.2
    uv version "$NEW_VERS"
  else
    # not a version, but probably a bump command like "stable", "major", "minor", "patch", etc.
    uv version --bump "$NEW_VERS"
    NEW_VERS=$(uv version | cut -d" " -f2)
  fi
  git add pyproject.toml uv.lock
  CUR_VERS="$NEW_VERS"
fi

echo "Will generate and display the changelog ..."
make changelog
less CHANGELOG.md

git add CHANGELOG.md docs/source/changelog.rst

git_args=()
read -rp "Amend previous commit? (y/N): " a
[[ "$a" =~ ^[Yy]$ ]] && git_args+=(--amend)
git commit "${git_args[@]}" -m "chore: version bump to v$CUR_VERS"

BRANCH="release/v$CUR_VERS"
git branch -m "$BRANCH"

echo "Will push to branch $BRANCH"
git push origin "$BRANCH"

echo "Will open the browser to create a pull request for that branch"
gh pr create -a "@me" --web
