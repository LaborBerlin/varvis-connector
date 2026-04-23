# varvis-connector: Deep Research Notes

## Executive Summary

`varvis-connector` is a Python integration package for the Varvis API with two primary surfaces:

- a typed Python client, `VarvisClient`
- a CLI executable, `varvis_connector`

Its core purpose is not just to wrap HTTP endpoints, but to hide a number of inconsistencies and operational quirks in the upstream Varvis API. The implementation handles a non-standard login flow, endpoint prefix irregularities, inconsistent payload formats, weak error signaling by the API, and session invalidation under concurrency.

The project is fairly mature in terms of developer ergonomics: it has strong documentation, broad automated tests, typed Pydantic models, linting/type-checking/security checks, and CI across Python 3.10 to 3.14. The main architectural weakness is concentration of logic in large modules, especially the CLI module. There are also a few places where runtime `assert` statements are used as correctness guards, which is less robust than explicit error handling.

## What The Project Does

At a high level, this repository provides a stable and scriptable interface around Varvis for:

- authentication and session management
- retrieving genomic analysis data
- retrieving person, QC, coverage, report, and virtual panel data
- creating/updating person records
- creating/updating virtual panels
- retrieving analysis file download links and downloading files
- issuing arbitrary authenticated requests to unsupported or undocumented endpoints

The project documents the currently wrapped endpoints in `docs/source/introduction.rst`. The covered set includes:

- internal person ID lookup from LIMS ID
- SNV annotations
- CNV target results
- pending CNV segments
- QC case metrics
- coverage data
- analyses listing
- person-linked analyses
- case reports
- person data including clinical information
- create/update person
- analysis lookup by uploaded filename
- virtual panel details, summaries, and create/update
- all genes
- analysis file download links and file download workflows

This is a fairly domain-specific adapter around genomics workflows in Varvis rather than a general-purpose SDK.

## Repository Layout

The implementation is compact and centered around a few files:

- `src/varvis_connector/_varvis_client.py`
  The core API client and transport logic.
- `src/varvis_connector/_cli.py`
  The full CLI implementation, including subcommand registration, argument parsing, data loading, command orchestration, and download UX.
- `src/varvis_connector/models.py`
  Pydantic models for API responses and update payloads.
- `src/varvis_connector/_log.py`
  Logging setup, split stdout/stderr handling, and CLI formatting.
- `src/varvis_connector/errors.py`
  The package-level custom exception type.
- `docs/source/*`
  Sphinx documentation, including usage, API reference, and a good development guide.
- `tests/*`
  Unit tests for client behavior, CLI behavior, internal retry/session handling, and logging.

The package entry point is simple:

- `src/varvis_connector/__main__.py` creates `VarvisCLI` and runs it
- `src/varvis_connector/__init__.py` re-exports `VarvisClient` and package version

## Runtime Architecture

### 1. Main abstraction: `VarvisClient`

`VarvisClient` is a `dataclass`, not a classic OOP service class with manual constructor logic. That matters because:

- configuration fields are introspected by the CLI to auto-generate top-level options
- the field metadata is reused for help text and environment variable mapping
- the client has a relatively clean public surface for both Python and CLI consumers

Main configuration fields:

- `api_url`
- `username`
- `password`
- `https_proxy`
- `ssl_verify`
- `connection_timeout`
- `backoff_factor_seconds`
- `backoff_max_tries`
- `download_chunk_size`
- `logger`

Notable implementation details:

- `__post_init__` normalizes trailing slash on `api_url`
- it can disable `urllib3` SSL warnings when verification is disabled
- it validates retry/backoff settings up front
- `__repr__` and `__str__` deliberately mask the password as `***`

### 2. Session and authentication model

Varvis does not appear to use a modern token-based API flow. Instead, the client implements a session+CSRF dance:

1. Create a `requests.Session`
2. Send `HEAD` to the base URL to acquire an initial session cookie and CSRF token
3. POST credentials plus `_csrf` to `/login`
4. Read the new authenticated session cookie and CSRF token from the login response
5. Store the authenticated cookie in the session and set the `X-CSRF-TOKEN` header for future requests

The implementation explicitly notes and handles a Varvis quirk: login can fail while still returning HTTP `200`, and the failure signal is simply absence of the expected CSRF token.

The client stores two internal pieces of state:

- `_session`
- `_loggedin_csrf`

The `logged_in` property treats both as required for a valid session.

### 3. Request sending model

Everything eventually funnels through `_send_request()`. That function is the real core of the package.

Responsibilities of `_send_request()`:

- verify a session exists
- normalize endpoints
- decide whether to auto-prepend `api/`
- send the request through the shared `requests.Session`
- disable redirects
- retry on connection/timeouts
- detect a forced logout pattern and re-login
- map selected HTTP statuses into `VarvisError`
- otherwise optionally call `raise_for_status()`

This is where most of the repository’s real “value-add” over a thin SDK lives.

## Varvis-Specific API Quirks Encoded In The Client

The development docs are unusually explicit about upstream API oddities, and the code reflects them directly.

### Non-uniform endpoint prefixes

Some Varvis endpoints live under `/api/...`, others do not. The client auto-fixes endpoints in `_send_request()` using rules based on the first/last URL path components.

The key cases:

- no `/api/` prefix for `login`, `logout`, `pending-cnv`, `analysis-list`, `virtual-panels`, `virtual-panel`, `virtual-panel-genes`
- no `/api/` prefix for `person/.../analyses`
- `virtual-panel` GET stays unprefixed, but non-GET methods on `virtual-panel` are prefixed with `/api/`
- most other endpoints are prefixed automatically with `api/`

This is a pragmatic rule engine, not a formally modeled router. It works because the package targets a bounded set of known endpoints.

### Inconsistent parameter names

One of the most concrete examples:

- CNV target results use `analysisIds`
- pending CNV segments use `analysesIds`

The client hard-codes this difference in separate methods and documents it in comments.

### Inconsistent payload envelopes

Some endpoints return the actual payload directly in the response body. Others wrap it in a JSON object containing keys like:

- `success`
- `response`
- error metadata

The helper layer handles both styles:

- `_parse_response_for_model(..., data_from_key=None)` for direct-body model parsing
- `_parse_response_for_model(..., data_from_key="response")` for wrapped payloads
- `_parse_response_for_model_list(...)`
- `_parse_response_for_primitive(...)`
- `_jsondata_from_response(...)`

This split is necessary because Varvis is not consistent about response shape.

### Weak error signaling

The client has two error paths:

- explicit HTTP status handling via `handle_http_errors`
- envelope-level error handling via `success == False`

When an envelope says the request failed, `_raise_varvis_error()` extracts and formats:

- `errorMessageId`
- `errorExpected`
- `errorId`
- `additionalInformation`

This is important because many upstream failures are apparently only understandable through those payload fields.

### Concurrency-triggered forced logout

This is one of the more unusual upstream behaviors and likely one of the main reasons the package exists.

The docs describe that too many concurrent requests can cause Varvis to:

- return HTTP `302`
- redirect to the base URL
- effectively invalidate the current session

The client detects exactly that pattern in `_send_request()`:

- response status `302`
- `Location` equals the base API URL

When it sees it, it:

- clears the session state
- treats it as retryable
- waits with exponential backoff
- attempts to re-login before retrying the original request

That behavior is also explicitly tested in `tests/test_varvis_internal.py`.

## Public Client Surface

The client methods are straightforward endpoint-specific wrappers around `_send_request()` plus response parsing:

- `get_internal_person_id()`
- `get_snv_annotations()`
- `get_cnv_target_results()`
- `get_pending_cnv_segments()`
- `get_qc_case_metrics()`
- `get_coverage_data()`
- `get_analyses()`
- `get_person()`
- `create_or_update_person()`
- `get_case_report()`
- `get_report_info_for_persons()`
- `get_person_analyses()`
- `find_analyses_by_filename()`
- `get_virtual_panel_summaries()`
- `get_virtual_panel()`
- `get_all_genes()`
- `get_file_download_links()`
- `create_or_update_virtual_panel()`
- `download_files()`
- `download_files_from_urls_parallel()`
- `request()`

### Design pattern used by most methods

Most methods follow the same pattern:

1. log a human-readable action
2. build endpoint and query parameters
3. define endpoint-specific HTTP error mappings
4. call `_send_request()`
5. convert the result into a typed Pydantic model or primitive

That consistency makes the library easy to extend.

### Notable method-specific behaviors

#### `from_env()`

The client can be fully initialized from environment variables:

- required: `VARVIS_URL`, `VARVIS_USER`, `VARVIS_PASSWORD`
- optional: `HTTPS_PROXY`, `VARVIS_SSL_VERIFY`, `VARVIS_CONNECTION_TIMEOUT`, `VARVIS_BACKOFF_FACTOR_SECONDS`, `VARVIS_BACKOFF_MAX_TRIES`

Type conversion is handled manually, including string-to-bool conversion for `ssl_verify`.

#### `get_pending_cnv_segments()`

This method accepts either:

- `person_id`
- `person_lims_id`

but not both. If only `person_lims_id` is given, it first calls `get_internal_person_id()` because the endpoint needs the internal ID.

#### `get_qc_case_metrics()`

This method has special response-shape logic. It expects the API response to contain a nested `metricResults` mapping keyed by LIMS ID, then it:

- extracts the sub-entry for the requested `person_lims_id`
- rewrites `data["metricResults"]`
- validates the mutated structure against `QCCaseMetricsData`

This is a good example of the client normalizing upstream payload oddities before presenting a stable typed object.

#### `create_or_update_person()`

The method accepts either:

- a `PersonUpdateData` model
- a plain `dict`

If a `dict` is passed, it validates it before sending. The response is expected to be the raw internal person ID in the response body, not a JSON envelope, so the code parses `resp.content` as `int`.

#### `create_or_update_virtual_panel()`

This follows a more conventional wrapped-response pattern than person create/update. The response is parsed through `_parse_response_for_primitive(resp, "response")`.

#### `request()`

This is an escape hatch for unsupported or undocumented endpoints. It bypasses endpoint auto-fixing and lets the caller send arbitrary authenticated requests while still reusing retry/session behavior.

That method makes the package useful even when official endpoint coverage is incomplete.

## Data Modeling Strategy

The models are extensive and mostly practical rather than dogmatic. They try to reflect Varvis payloads faithfully while acknowledging upstream inconsistency.

### Pydantic as boundary validation

All response models inherit from `BaseModel`. This serves several purposes:

- convert external JSON into typed Python objects
- constrain known enums via `Literal`
- keep the CLI JSON serialization predictable through `model_dump(mode="json")`
- catch upstream response changes early

### Model characteristics

The model file mixes three categories:

- direct representations from documented endpoints
- pragmatic approximations from playground samples
- update payload schemas for write endpoints

Several docstrings explicitly admit uncertainty, for example:

- some fields were inferred from playground responses
- some fields are marked TODO because docs and payloads disagree
- some optionality is based on observed behavior rather than documentation

That honesty is useful. This repo is clearly built against a moving or weakly documented target.

### Specific model observations

#### SNV and CNV models

- `SnvAnnotationData` uses very loosely typed tabular data: `header` plus `data: list[list]`
- `CnvTargetResults` also uses header metadata plus raw `data: list[list]`

This suggests the Varvis API returns some genomic result sets in table-oriented form rather than normalized object-per-record JSON.

#### Pending CNV data

`PendingCnvDataItem` is one of the more ad hoc models. It includes:

- positional/genomic fields
- overlap settings
- comments
- annotations
- relatives data

Many comments note uncertainty around field semantics or exact allowed values.

#### QC models

The QC model tree is elaborate:

- result items
- metric types
- threshold ranges
- enrichment kits
- grouping keys

This is one of the richer typed parts of the package and indicates QC payloads are relatively structured.

#### Person and case report models

The person/case-report side contains a mix of:

- personal data
- clinical information
- HPO terms
- disease metadata
- conclusions for SNV/CNV findings

The `CaseReport` model is interesting because `items` uses a discriminated union on `type`, allowing mixed report item kinds:

- `PERSON`
- `VIRTUAL_PANEL`
- `METHODS`

That is a sound approach for a heterogeneous report structure.

#### Virtual panel models

The virtual panel workflow is treated as a first-class feature:

- summaries
- full panel details
- update schema
- full gene inventory

This is one of the few write-capable parts of the package besides person update.

## CLI Design And Behavior

The CLI is large but coherent. It is built around command classes plus a single orchestrator.

### Structural pattern

The CLI uses:

- `_CmdBase`
- `_AutoLoginCmdBase`
- one dataclass per command
- a `VarvisCLI` registry mapping command name to class

At runtime:

1. `VarvisCLI._setup_argparser()` builds top-level config args by introspecting `VarvisClient` dataclass fields
2. it registers all subcommands
3. it parses arguments
4. it resolves config values from CLI args or environment variables
5. it initializes logging
6. it creates `VarvisClient`
7. it instantiates and runs the chosen command

### Good CLI design decisions

- Top-level connection/auth settings are derived from the client definition, reducing duplication.
- Many multi-ID retrieval commands degrade gracefully: failures for individual IDs log warnings while successful IDs are still returned.
- JSON output is centralized in `_write_file_output()`.
- The CLI automatically shifts logs to stderr when JSON output goes to stdout.

### CLI output model

The CLI is designed for shell pipelines and scripting:

- structured data goes to stdout or a file
- logs go to stderr when needed
- model instances are recursively converted to JSON
- empty result sets are sometimes considered an error and sometimes allowed, depending on the command

The command layer explicitly distinguishes those cases with `allow_empty_data`.

### Input model for write commands

`create-or-update-person`, `create-virtual-panel`, and `update-virtual-panel` support two input styles:

- structured CLI arguments
- JSON input from stdin or file

Important behavior:

- if any CLI data args are provided, JSON input is ignored
- otherwise stdin or `--input` is parsed as JSON

That is practical for both scripting and ad hoc use.

### Update semantics for virtual panels

`update-virtual-panel` is more careful than a naïve partial update:

- it requires an ID
- it forbids “ID only” updates
- it fetches the existing virtual panel first
- it backfills omitted fields from the current remote state
- for genes, it converts the existing `genes` list into `geneIds`

This means the CLI implements client-side merge semantics to preserve fields not explicitly passed. That is a thoughtful adaptation to an API that likely expects full-object updates.

### Download command workflow

The CLI download workflow is two-stage:

1. For each analysis ID, collect valid URLs and target paths via `client.download_files(..., only_collect_urls=True)`
2. Submit the union of URLs to `download_files_from_urls_parallel()`

Notable details:

- `--create-folder-per-id` can create per-analysis subfolders
- a placeholder `%ID` is supported in folder naming
- repeated `--file-pattern` arguments are flattened
- duplicate URLs across analyses are warned about and overwritten in the aggregate map
- progress bars can be disabled

This is more sophisticated than a trivial “loop and download”.

## Download Implementation Details

The file download subsystem is one of the more security-sensitive parts of the code, and it includes several good guardrails.

### Validation before download

Before any file is written, `download_files()` filters out link entries where:

- `fileName` is missing
- `downloadLink` is missing
- filename becomes empty after stripping
- filename is `.`, `..`, contains NUL, or contains `/`
- filename does not match requested patterns
- file is marked archived
- target file exists and overwrite is not allowed
- the same download URL is already collected

The filename checks are especially important: they prevent path traversal and malformed-name writes.

### Parallel download execution

`download_files_from_urls_parallel()` uses `ThreadPoolExecutor`.

For each download:

- it performs a plain `requests.get(..., stream=True, timeout=...)`
- checks status code
- reads `content-length`
- optionally renders a `tqdm` progress bar
- writes in chunks of `download_chunk_size`

Completion is then handled asynchronously through `concurrent.futures.as_completed()`.

### Logging around progress bars

When progress bars are enabled, success/failure log messages are collected and returned rather than logged immediately. The CLI then logs them after all progress bars complete. This avoids output corruption from interleaving logs and progress-bar rendering.

That is a small but well-considered UX detail.

### Minor implementation concern

Inside `download_single_file()`, one exception path uses `logging.error(...)` instead of the provided logger instance. That means those messages may bypass the structured CLI logger configuration.

This is not catastrophic, but it is inconsistent with the rest of the code.

## Logging Design

The logging system is more deliberate than average for a small package.

### Two logger entry points

- `cli_logger()`
- `default_logger()`

The distinction is meaningful:

- `cli_logger()` is optimized for terminal UX with colored level-specific formatting and stdout/stderr split
- `default_logger()` is more conventional and writes to stderr with timestamped formatting

### stdout/stderr split

`get_logger()` can attach two stream handlers:

- stdout for lower-severity informational output
- stderr for errors

It also uses `LogMaxFilter` so the handlers do not duplicate overlapping ranges unnecessarily.

This is important because the CLI frequently emits machine-readable JSON to stdout and must keep logs out of that stream.

### Formatting

CLI formatting uses:

- colored prefixes for DEBUG/WARN/ERROR/FATAL
- a `PrettyExceptionFormatter`
- a `MultiFormatter` that changes format by log level

The color helper is adapted from Click rather than depending on Click itself. That keeps runtime dependencies minimal.

## Test Strategy

The repository has a strong test surface.

### Test categories

- `tests/test_varvis.py`
  Client public API behavior.
- `tests/test_varvis_internal.py`
  Lower-level retry and forced-logout behavior.
- `tests/test_cli.py`
  CLI parsing, environment fallback, command behavior, write commands, downloads, and request command behavior.
- `tests/test_log.py`
  Logging configuration behavior.

### Mocking strategy

The project uses `requests-mock` fixtures rather than hitting the real API in most tests. Shared login mocks live in `tests/_common.py`.

The tests also use:

- `polyfactory` for generating model instances
- deterministic seeds for repeatability
- monkeypatching of environment variables and argv

### Particularly valuable tests

The strongest tests are arguably the internal ones around `_send_request()`:

- connection error retry failure
- timeout retry failure
- retry success after transient failure
- forced logout via `302` redirect to base URL followed by re-login

Those cover the most fragile integration behavior.

### Coverage philosophy

The project has an unusual but good coverage rule: it cares specifically about full coverage in test files themselves, under the assumption that misses in test code often indicate incomplete test implementation. `scripts/coverage-check.sh` enforces that locally, and CI uses coverage reporting on PRs.

## Documentation Quality

The docs are good and materially useful.

### Main strengths

- `README.md` gives a clear project summary and external docs link
- `docs/source/introduction.rst` enumerates endpoint coverage explicitly
- `docs/source/usage/api.rst` and `docs/source/usage/cli.rst` document both surfaces
- `docs/source/development.rst` explains workflow, tooling, CI, and upstream Varvis quirks
- API reference is generated with Sphinx autodoc

The development guide is better than average because it explains not only how to contribute, but why the code contains certain defensive logic.

### Documentation mismatch observed

The development docs mention workflow filenames `docs.yaml` and `release.yaml`, but the repository currently contains:

- `build_and_release.yaml`
- no `docs.yaml`

So at least part of the development documentation is stale relative to the current workflow file names.

## CI / Release / Maintenance Workflow

The automation story is comprehensive.

### Toolchain

The project uses:

- `uv` for environment and dependency management
- `uv_build` as build backend
- Ruff for linting/formatting
- basedpyright for type checking
- Bandit for security linting
- pip-audit for dependency vulnerability scanning
- pre-commit
- git-cliff for changelog generation and commit message linting

### CI workflows

The repository contains workflows for:

- tests
- code quality
- dependency audit
- scheduled dependency update issue/branch creation
- gitleaks secret scanning
- build/release orchestration

### Interesting maintenance choices

- tests and code quality run across Python 3.10 to 3.14
- tests intentionally serialize CI concurrency to reduce load on the Varvis server
- dependency updates are partially automated through a scheduled workflow that opens an issue, creates a branch, updates `uv.lock`, and pushes a commit
- `git-cliff` is used both for changelog generation and for conventional-commit enforcement

### Release state

The release workflow is not fully implemented yet:

- GitHub release publishing step is currently `echo "TODO"`
- PyPI publishing step is also `echo "TODO"`

So the repository has strong scaffolding for release automation, but not a fully completed publishing pipeline.

## Code Quality Assessment

## Overall

The codebase is in good shape. It reflects careful engineering against an awkward external API rather than rushed wrapper code.

### Strong points

- clear separation between client, CLI, models, and logging
- broad test coverage over the most failure-prone integration paths
- strong developer tooling and CI
- thoughtful handling of upstream API inconsistencies
- Pydantic validation at the API boundary
- good shell/script ergonomics in the CLI
- explicit documentation of upstream weirdness instead of pretending the API is clean

### Weaker points

#### Large monolithic modules

The main maintainability issue is file size and concentration of behavior:

- `_cli.py` is very large and contains all commands plus argument parsing plus orchestration
- `_varvis_client.py` contains both transport machinery and all endpoint-specific client methods

This makes local reasoning slower and raises the cost of adding features safely.

#### Use of `assert` in runtime paths

The client uses `assert` in a number of parsing and validation paths. In production code, explicit exceptions are preferable because:

- assertions are meant for internal invariants, not external input validation
- they can be disabled with optimization flags
- they often produce less user-oriented diagnostics

Most of these should ideally be converted to explicit `VarvisError` or `TypeError` branches.

#### Broad `except Exception` in CLI command handlers

Many CLI commands catch generic exceptions. That improves robustness for end users, but it also:

- flattens error taxonomy
- can hide programming errors as operational failures
- makes it harder to distinguish validation errors from integration bugs

This is not fatal, but it is a tradeoff toward operator convenience over internal strictness.

#### Some inconsistency in exit handling

Many command handlers call `exit(1)` directly. Others rely on the top-level `VarvisCLI.run()` exception trap. The result is a somewhat mixed control-flow style.

#### Minor stale docs / naming drift

There are a few documentation/workflow naming mismatches, which suggests the documentation is maintained actively but not perfectly synchronized with recent automation changes.

## Specific Findings And Nuances Worth Remembering

- The package is designed around the assumption that Varvis can invalidate sessions under concurrency.
- The library’s “endpoint auto-fix” behavior is opinionated and essential; bypass it only through `request()` when you really mean to.
- QC case metrics require custom payload reshaping before validation.
- Person create/update and virtual-panel create/update return different response shapes.
- The CLI is intentionally pipeline-friendly and carefully avoids polluting stdout when data output is expected there.
- Virtual panel update performs client-side merge behavior by fetching the current remote panel first.
- File download handling has decent filename/path safety checks.
- The project currently looks like an initial public release with mature tooling but a short external changelog history.

## Suggested Reading Order For Future Work

If I had to onboard quickly again, I would read the repository in this order:

1. `README.md`
2. `docs/source/introduction.rst`
3. `docs/source/development.rst`
4. `src/varvis_connector/_varvis_client.py`
5. `src/varvis_connector/models.py`
6. `src/varvis_connector/_cli.py`
7. `tests/test_varvis_internal.py`
8. `tests/test_cli.py`

That sequence gets you from purpose to quirks to core transport logic to payload shapes to user-facing behavior to failure-mode validation.

## Bottom Line

This repository is a pragmatic, well-tooled integration layer over a non-uniform external API. Its main accomplishment is not sophisticated architecture; it is reliable adaptation. The code understands the behavioral edges of Varvis and encodes those edges explicitly in transport logic, response parsing, CLI ergonomics, and tests.

If I were extending it, I would preserve that pragmatic orientation and focus on:

- keeping the transport behavior stable
- adding endpoint wrappers in the same narrow, validated style
- gradually splitting the CLI and client into smaller modules
- replacing runtime `assert` guards with explicit exceptions
- tightening documentation/workflow synchronization
