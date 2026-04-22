As of {DATE} the following dependency updates are available:

```
{UPDATES}
```

In order to integrate these updates into this project, you can checkout the branch `{BRANCH}` and install the proposed dependency updates:

```
git fetch origin && git checkout {BRANCH}
make depsync
```

**Tasks:**

- [ ] also update pre-commit hooks via `pre-commit autoupdate`
- [ ] run tests locally to see if code changes are necessary after updates: `make test`
- [ ] adapt code if necessary
- [ ] edit `pyproject.toml` to raise minimum version requirements if necessary
- [ ] squash commits, push and create a PR for a new release
- [ ] build and deploy the new release

