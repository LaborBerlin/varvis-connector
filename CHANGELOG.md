# Changelog

## 0.2.1 - 2026-05-13

### CI

- Update setup-uv action to v8.1.0 in all workflows

### Development

- Replace many dev dependencies by using `uv tool` / `uvx`
- Don't overwrite commit message when amending the vers. bump commit
- Require `make audit` in update-dependencies skill

### Documentation

- Fix link and typo in installation section

### Other

- Bump actions/upload-pages-artifact from 4 to 5
- Bump actions/download-artifact from 6 to 8
- Bump actions/upload-artifact from 5 to 7
- Bump actions/configure-pages from 5 to 6
- Update dependencies to fix security vulnerability in urllib3 / closes #6

### Styling

- Set ruff line length to 120 and reformat code

## 0.2.0 - 2026-04-29

### CI

- Add docs pages workflow
- Set up publishing to PyPI and GitHub releases

### Documentation

- Add GPLv3 license and respective notes

### Other

- Squash git history to create first public release
- Set up AI assistance by providing AGENTS.md and `update-dependencies` skill

### Testing

- Fix type hint issue in `test_optional_args`

