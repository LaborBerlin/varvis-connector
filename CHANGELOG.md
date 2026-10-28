# Changelog

## 0.4.0 - 2026-10-28

### Bug Fixes

- Validate download filenames more strictly and confine path in --create-folder-per-id to output directory
- Reject non-HTTPS file download URLs
- Limit SSL warning suppression to CLI
- Apply URL quoting to parameters
- Ensure atomic file downloads and cleanup on interruption (#28)
- Improve exception handling in CLI by fixing broad exception swallowing (#28)
- Replace runtime assertions with explicit exceptions (#28)
- Ensure login-state is completely reset also when the logout fails (#28)
- Add safeguard to prevent possible KeyError when asking for password interactively (#28)
- Handle possible target path collisions when downloading files (#28)
- Ensure logout when a command exits early
- Preserve transport failures and support phase-specific timeouts
- Implement thread-safe request session handling, re-login attempts and login status check to fix possible race conditions (#27)
- Add retry jitter to HTTP requests to prevent synchronous API hammering with multiple threads
- SNV stream reader may fail when numeric values are split across streaming chunks

### CI

- Fix CODEOWNERS parsing in dependencies update workflow
- Fix gitleaks workflow not being run on push
- Lint GitHub actions via actionlint
- Pin actions using pinact
- Update setup-uv action

### Development

- Add simongig to CODEOWNERS

### Documentation

- Update documentation to reflect the changes in file download handling
- Add information about download connection pool, retry jitter and new CLI options / env. variables
- Update documentation regarding actionlint, pinact and new workflows
- Update documentation to mention the latest improvements

### Features

- Warn when password is passed as an argument

### Other

- Bump astral-sh/setup-uv from 10.0.1 to 10.1.0
- Bump astral-sh/setup-uv from 10.1.0 to 10.2.0
- Bump urllib3 to fix security vuln.
- Update Python dependencies and pre-commit hooks

### Performance

- Use connection pool for downloads and add retry plus jitter (#27)
- Reduce SNV streaming memory use with temporary-file caching
- Use more memory-efficient pydantic function to serialize nested models to JSON instead of recursive model traversal
- Validate model lists with pydantic TypeAdapter
- Scan fragmented SNV values before retrying JSON decoding

### Refactor

- Replace argparse FileType with deferred pathlib file handling

### Testing

- Make sure MOCK_URL can be changed
- Cover playground SNV streaming and fix array-valued filters

## 0.3.0 - 2026-09-22

### Bug Fixes

- Normalize test playground URL and update lockfile for security audit
- Validate filter columns, add dynamic bool overload, and normalize aliases
- Accept wire type field in CaseReportAnalysis alias

### CI

- Disable weekly dependency audit -- we rely on GitHub dependabot alerts for this
- Tolerate badge push failures on fork PRs without write permissions

### Development

- Add your-highness to codeowners list
- Update dependencies

### Features

- Add streaming support for SNV annotations to prevent OOM

### Other

- Bump astral-sh/setup-uv from 8.1.0 to 10.0.1
- Bump actions/checkout from 6 to 7

### Styling

- Configure ruff lint select and clean up parser imports

### Testing

- Skip playground tests when credentials are not configured
- Update author attribution in test_models

## 0.2.2.post1 - 2026-05-29

### Documentation

- Add intended use, use absolute url for logo (fixes display on PyPI) and improve docs in `build_and_release` workflow

## 0.2.2 - 2026-05-27

### Documentation

- Add varvis logo and disclaimer

### Other

- Update dependencies with fixed security vulnerabilities

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

