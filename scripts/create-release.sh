#!/bin/bash
# Create a release: Create a tag based on the current version and push that version.
# This will then trigger either the "build_and_release_dev" GHA workflow (development releases)
# or the "build_and_release_prod" GHA workflow (production releases).
#
# Used by `make release`.

set -Eeuo pipefail

CUR_VERS=$(uv version | cut -d" " -f2)
echo "Current version is: $CUR_VERS"

CUR_BRANCH=$(git branch --show-current)

if [[ "$CUR_BRANCH" != "main" ]] && [[ ! "$CUR_VERS" =~ dev[0-9]+$ ]]; then
  echo "Releasing a production version is only allowed on the main branch. You should rebase or merge this branch with main first."
  echo "Do you want to continue anyway? [Y/n]"
  read -r answ
  if [ "$answ" != "Y" ]; then
    echo "Aborted."
    exit 1
  fi
fi

if [[ "$CUR_VERS" != *"dev"* ]]; then
  ENV_NOTE="FOR PRODUCTION"
else
  ENV_NOTE="for development"
fi

echo "Note: If answering with yes, the following will trigger the CI pipeline and create a new release $ENV_NOTE!"
echo "Create version tag, push and release this version? [Y/n]"
read -r answ

if [ "$answ" != "Y" ]; then
  echo "Aborted."
  exit 1
fi

git tag -a "v$CUR_VERS" -m "release $CUR_VERS"
git push origin "v$CUR_VERS"
