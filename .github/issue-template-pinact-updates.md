As of {DATE} the following GitHub Actions updates are available (shown as diff produced by `pinact`):

```
{UPDATES}
```

In order to integrate these updates into this project, you can create a new branch, update the workflow definitons via
`make update_actions`, test the changes and integrate them via a PR into main.

**Tasks:**

- [ ] create a new branch
- [ ] run `make update_actions` to update the GH Actions pins in the workflow definitions
- [ ] adapt workflow code if necessary
- [ ] squash commits, push and create a PR
