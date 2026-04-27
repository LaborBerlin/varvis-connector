# AGENTS.md

## Project context

Read `.agents/research.md` **in depth** to get an overview about this project.

## Testing

- load the environment variables in `.env` before running tests
- test only what you need during implementation (i.e. only affected / new tests)
- make a full test run when completing a task

## Rules

General rules:

- do not install or update any dependencies on your own; if you think installing or updating dependencies is necessary
  give a notice so the user can do this manually
- prefer simple and short solutions over complex ones
- only move code to separate helper functions / methods if it is needed (i.e. called in more than one place)
- write a short comment before each code block that summarizes what the block does
- comments don't have to be full sentences but rather short notes, starting with lower case, ending without a period
- never update the changelog -- this is done automatically

To complete an implementation tasks other than minor tasks like documentation work, make sure:

- new functions / methods / classes have proper docstrings
- updated functions / methods / classes have updated docstrings
- write full sentences in docstrings
- all tests pass
- if a bash script was modified, `shellcheck -x` must pass
- `ruff check` must pass (if not, try `ruff check --fix` to fix any problems)
- run `ruff format` to format the generated / updated code
- `basedpyright` must pass
- `bandit -c pyproject.toml -r src/` must pass
- the package can be built successfully via `make build`
- the documentation can be built successfully via `make docs`
- `.agents/research.md` is updated according to the changes introduced to complete the task; treat
  `.agents/research.md` as knowledge base that should always reflect the current state of the project;
  don't use language that indicates changes -- the document is *not* a changelog
