---
name: update-dependencies
description: Update all dependencies in the current project, including Python packages in `uv.lock` and pre-commit hook revisions in `.pre-commit-config.yaml`. Use when the user asks to "update dependencies", "update all dependencies", refresh the lockfile, refresh pre-commit hooks, or bring direct dependency minimum versions in `pyproject.toml` up to the versions actually adopted after an update.
---

# Update Dependencies

## Overview

Update this repository's dependencies with the project's own automation, validate the result end to end, fix small breakages, and roll back only the dependency updates that are not worth fixing. Keep the final state intentional and report exactly what changed.

## Workflow

1. Read `AGENTS.md`, `.agents/research.md`, `pyproject.toml`, `Makefile`, and `.pre-commit-config.yaml` before making changes.
2. Capture the starting state for later reporting:
   - direct dependencies from `pyproject.toml`
   - optional dependencies and dependency groups from `pyproject.toml`
   - pre-commit hook revisions from `.pre-commit-config.yaml`
   - current version pins in `uv.lock` for direct dependencies if needed
3. Run the project's update command:

```bash
make depupgrade
```

1. Inspect which files changed. Expect at least:
   - `uv.lock`
   - `.pre-commit-config.yaml`
   - sometimes `pyproject.toml`
2. Update minimum versions in `pyproject.toml` for direct dependencies that were actually upgraded.
   - Only change direct dependencies already listed in `pyproject.toml`.
   - Do not add or remove dependencies unless the update flow clearly requires it.
   - Keep version specifiers simple and consistent with the file's current style, usually `>=<new_version>`.
3. Run the full validation flow after the update.
4. If validation fails, fix small compatibility issues directly.
5. If a failure is caused by one updated dependency and the fix is too large for the update task, roll back only that dependency update, then rerun validation.
6. Summarize all dependency changes and any rollback decisions.
7. Update `.agents/research.md` if the repository-specific dependency update workflow or skill inventory changed in a way future work should know about.

## Validation

Load environment variables from `.env` before validation commands that need them.

Run the full repo checks expected for non-trivial code changes:

```bash
test -f .env && set -a && source .env && set +a
make audit
ruff check
ruff format
basedpyright
bandit -c pyproject.toml -r src/
make testall
make build
make docs
```

Also refresh pre-commit hook state when useful:

```bash
uv run pre-commit run --all-files
```

If a command fails because the update changed generated files or formatting, fix that and rerun the failed command plus any downstream checks.

## Failure Triage

Use this order:

1. Determine whether the failure is caused by the dependency update or by unrelated local dirt.
2. If unrelated local dirt exists, avoid reverting it and work only with the update-related files.
3. If the failure is clearly caused by a small API or typing change, patch the project and keep the newer dependency.
4. If the failure points to one upgraded dependency and the fix would be broad, risky, or time-consuming, roll back that dependency instead of forcing a large refactor.

Treat these as "too big" unless the user asked for broader maintenance:

- wide API migrations across multiple modules
- behavior changes that require redesign rather than adaptation
- new dependency-family incompatibilities that spread across the repo

## Rolling Back One Dependency

Prefer the narrowest rollback possible.

For a direct dependency:

1. Find the previous working version from the git diff or pre-update state.
2. Restore the intended minimum version in `pyproject.toml`.
3. Re-lock to the previous version for that package.

For a transitive dependency:

1. Re-lock that package to the previous version without broad manual edits.
2. Keep the rest of the update set intact.

Useful commands:

```bash
uv lock -P <package>==<old_version>
uv sync --all-groups --all-extras
```

If pre-commit hook updates cause the problem and the issue is not worth fixing, revert only the affected hook revision in `.pre-commit-config.yaml` and rerun validation.

## Reporting

Always report:

- direct dependencies updated in `pyproject.toml`
- point out major-version changes in direct dependencies
- package updates reflected in `uv.lock`
- pre-commit hook revision changes
- any fixes made to keep the update
- any dependency rolled back and why
- validation commands run and their final outcome

Prefer a concise grouped summary rather than dumping raw lockfile diffs, but include exact package names and final versions.
