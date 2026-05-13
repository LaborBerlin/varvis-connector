# Makefile with commands for for development convenience
#
# Requires a bash shell, git, fold and uv.
#
# Note: All commands that depend on activating a Python venv should be
#       run via "uv run <command>", e.g. "uv run pre-commit autoupdate"
#       instead of "pre-commit autoupdate".

.PHONY: build docs
SHELL := /bin/bash
TOOLS := pre-commit ruff git-cliff pip-audit basedpyright bandit[toml]
export UV_SYSTEM_CERTS := true
export UV_EXCLUDE_NEWER := 7 days

# initialize development
init_dev: depsync
	for t in $(TOOLS); do \
		uv tool install "$$t"; \
	done
	uv tool update-shell
	pre-commit install
	pre-commit autoupdate
	pre-commit install-hooks

# synchronize dependencies between pyproject.toml and the virtual environment;
# will install dependencies required in pyproject.toml but not installed in venv
depsync:
	uv sync --all-groups --all-extras

# upgrade dependencies: fetch updatable packages, update lockfile, install
# updates in venv, update pre-commit hooks;
# note: you may need to edit pyproject.toml afterwards to raise mininum
# dependency version requirements
# uses dependency cooldown if enabled in pyproject.toml via "exclude-newer"
depupgrade:
	uv lock -U
	uv sync --all-groups --all-extras
	for t in $(TOOLS); do \
		uv tool upgrade "$$t"; \
	done
	pre-commit autoupdate

# just check for possible updates; is used in dependencies_update.yaml GHA workflow
depcheck:
	@uv lock -U --dry-run --no-progress --color never 2>&1 | tail -n +2 | grep '^Update ' || true

# upgrade a specific package, ignoring the uv dependency cooldown setting "exclude-newer";
# good for quickly upgrading a package that has known vulnerabilities
pkgupgrade:
	@if [ -z "$(pkg)" ]; then \
        	echo "Error: argument 'pkg' is not set. Please run as 'make pkgupgrade pkg=<pkg>'"; \
        	exit 1; \
    	fi
	uv lock --exclude-newer-package $$pkg=false -P $$pkg

# fold the readme to 120 chars line length max.
fold_readme:
	fold -s -w 120 < README.md > README.md.tmp && mv README.md.tmp README.md

# run test coverage
coverage:
	@test -f .env && set -a && source .env && set +a; \
		uv run coverage run -m pytest tests

# run test coverage check: will check if all sources in the "tests/" directory have
# full coverage (misses in test code are usually a bug in the test implementation)
# note: this check may fail since the tests run with randomly generated models which sometimes leads
# to minor code coverage misses, hence it is disabled in the GHA workflows and should only be run locally
coverage-check: coverage
	bash scripts/coverage-check.sh

# generate a test coverage report in the ".reports" directory
# note: we can't require coverage-check here since the tests run with randomly generated models which sometimes leads
# to minor code coverage misses
coverage-report: coverage
	mkdir -p .reports
	uv run coverage html -d .reports/coverage-html
	uv run coverage xml -o .reports/coverage.xml
	uv run genbadge coverage -l -i .reports/coverage.xml

# run tests
test:
	test -f .env && set -a && source .env && set +a; \
		uv run pytest tests -rsfE

# run all the checks for all the supported Python versions; reset to default Python version at the end
testall:
	bash scripts/test-all.sh 3.10 3.11 3.12 3.13 3.14

# build the documentation; used in docs GHA workflow
docs:
	test -f .env && set -a && source .env && set +a; \
		cd docs && make html

# remove the built documentation
clean_docs:
	rm -r docs/build/*

# build the package; used in build_and_release GHA workflow
build:
	uv build --no-sources --no-progress --color never

# export *all* dependencies in requirements.txt format;
# includes dependencies for all extras and all dependency groups;
# the exported requirements file contains the exact versions and
# hashes, so we don't need pip for dependency resolution (--disable-pip)
audit:
	bash scripts/audit-deps.sh

# (re-)generate the changelog
changelog:
	git-cliff -o CHANGELOG.md --tag "v$$(uv version | cut -d" " -f2)"
	pandoc -f gfm -t rst --columns=120 -o docs/source/changelog.rst CHANGELOG.md

# prepare a pull request: generate changelog, optionally bump the version,
# create a release branch, push the release branch, open the PR draft in a browser
pr: check_git_clean
	bash scripts/create-pr.sh

# create a release: create a tag based on the current version,
# push that version; will then trigger the "build_and_release" GHA workflow
release: check_git_clean
	bash scripts/create-release.sh

# helper target to check if the current repository is "clean" (i.e. no uncommited changes)
check_git_clean:
	@test -z "$$(git status --porcelain)"
