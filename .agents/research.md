# varvis-connector: Deep Research Notes

## Executive Summary

`varvis-connector` is a Python integration package for the Varvis API with two primary surfaces:

- a typed Python client, `VarvisClient`
- a CLI executable, `varvis_connector`

Its core purpose is not just to wrap HTTP endpoints, but to hide a number of inconsistencies and operational quirks in the upstream Varvis API. The implementation handles a non-standard login flow, endpoint prefix irregularities, inconsistent payload formats, weak error signaling by the API, and session invalidation under concurrency.

The project is fairly mature in terms of developer ergonomics: it has strong documentation, broad automated tests, typed Pydantic models, linting/type-checking/security checks, and CI across Python 3.10 to 3.14. The main architectural weakness is concentration of logic in large modules, especially the CLI module.

The package version is managed in `pyproject.toml`; the repository is on the `0.3.0` release line.

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
- `src/varvis_connector/_snv_stream_parser.py`
  Low-overhead streaming JSON parser for SNV annotation payloads supporting row-by-row iteration, with parser storage depending on the current row or metadata value.
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

The package metadata in `pyproject.toml` is set up for public distribution. It includes README, author, GPL-3.0-only license metadata, license file declaration, keywords, PyPI classifiers for Python 3.10 through 3.14, and project URLs for homepage, hosted documentation, repository, issues, and changelog.

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
- `connect_timeout`
- `read_timeout`
- `backoff_factor_seconds`
- `backoff_max_tries`
- `download_chunk_size`
- `download_pool_size` (default `0`, using the parallel download worker count)
- `download_pool_max_size` (default `0`, using the parallel download worker count)
- `download_max_retries` (default `2`, for the download HTTP adapter)
- `download_backoff_factor_seconds` (default `0.5`, independent from API backoff)
- `logger`

Notable implementation details:

- `__post_init__` normalizes trailing slash on `api_url`
- the CLI suppresses `urllib3` insecure-request warnings when verification is disabled, while direct `VarvisClient` use leaves process-wide warning filters unchanged
- it validates retry/backoff and timeout settings up front
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

The `logged_in` property reads both fields under the session lock and treats both as required for a valid session.

A per-client reentrant lock serializes login, session acquisition, and authentication reset.
Each successful login creates a `_SessionState` record containing the authenticated session
and a `concurrent.futures.Future` for its shared recovery outcome. Requests capture this record
before network I/O and retain it even if the client's current session changes. Session identity
prevents delayed forced-logout responses from clearing a replacement session. A separate
logout generation counter invalidates workers from before an explicit logout, including
when a later explicit login establishes a new session.

One recovery owner performs up to `backoff_max_tries` login attempts for an invalidated session.
The login budget is shared across all affected workers and is separate from each API request's
HTTP attempt budget. A separate recovery lock registers participating requests without waiting
for login I/O under the authentication lock. Waiting workers use the future's condition
synchronization without holding either client lock. Failed login attempts clear incomplete authentication while retaining the
shared recovery record. Backoff sleeps release the session lock so new requests can join active
recovery. Success publishes a replacement session record; exhaustion or an unexpected exception
publishes the same failure to all affected workers, including delayed old-session responses.
Before sending, delayed workers follow successive recovery outcomes until reaching a session
without known recovery. Following these outcomes consumes no HTTP attempts and propagates
any intervening recovery failure.
A later API request may create a new recovery record after a failed sequence. Explicit initial
login remains required, and requests with retries disabled do not initiate automatic recovery.

`logout()` holds the session lock while invalidating active recovery futures and sending
the remote logout request, then clears authentication and the current session record in a
`finally` block. It advances the logout generation even when already unauthenticated.
Recovery waiters receive a shared `VarvisError` immediately; a sleeping owner rejects its
next login attempt when backoff ends. Generation checks prevent delayed responses and
transport retries from reviving old work, including after a new explicit login. A login
already in progress finishes before logout acquires the lock. In-flight HTTP requests are
not interrupted. Login and logout requests bypass automatic recovery.
An active-owner list retains sleeping recovery records even if an explicit login replaces
the current session during backoff; logout releases those owners' waiters as well.

### 3. Request sending model

Everything eventually funnels through `_send_request()`. That function is the real core of the package.

Responsibilities of `_send_request()`:

- verify a session exists
- normalize endpoints
- decide whether to auto-prepend `api/`
- send the request through the shared `requests.Session`
- disable redirects
- retry on connection/timeouts while preserving the final transport exception as the cause of a typed error
- spread request retries after transport failures or forced logouts with full jitter: each delay is uniformly chosen between zero and `backoff_factor_seconds * 2 ** (retry_number - 1)`, with zero disabling delays; shared session recovery retains deterministic exponential backoff
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

User-provided LIMS IDs interpolated into endpoint paths and filename components interpolated into search query strings are percent-encoded before requests are sent, so reserved URL characters remain part of the parameter value.

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

- invalidates authentication only if the response belongs to the current session
- joins or starts that session's shared recovery sequence when a request retry is available
- applies exponential backoff between the recovery owner's bounded login attempts
- retries the original request through the authenticated replacement session

That behavior is also explicitly tested in `tests/test_varvis_internal.py`.

## Public Client Surface

The client methods are straightforward endpoint-specific wrappers around `_send_request()` plus response parsing:

- `get_internal_person_id()`
- `get_snv_annotations()`
- `iter_snv_annotations()`
- `get_snv_annotation_header()`
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
- optional: `HTTPS_PROXY`, `VARVIS_SSL_VERIFY`, `VARVIS_CONNECTION_TIMEOUT`, `VARVIS_CONNECT_TIMEOUT`, `VARVIS_READ_TIMEOUT`, `VARVIS_BACKOFF_FACTOR_SECONDS`, `VARVIS_DOWNLOAD_BACKOFF_FACTOR_SECONDS`, `VARVIS_BACKOFF_MAX_TRIES`

Download settings include `VARVIS_DOWNLOAD_CHUNK_SIZE`, `VARVIS_DOWNLOAD_POOL_SIZE`,
`VARVIS_DOWNLOAD_POOL_MAX_SIZE`, and `VARVIS_DOWNLOAD_MAX_RETRIES`, all parsed as integers.
Type conversion is handled manually, including string-to-bool conversion for `ssl_verify`.

The CLI also accepts a `--password` argument for constrained workflows. Its help text warns that command-line passwords may be visible in process listings and shell history, and CLI startup emits the same warning when the argument is explicitly used. The environment variable `VARVIS_PASSWORD` and interactive prompt avoid placing the password directly in the process argument list.

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

#### `iter_snv_annotations()` and `get_snv_annotation_header()`

Varvis SNV annotation payloads for whole-exome sequencing (WES) or whole-genome sequencing (WGS) can be large (often ~64,000+ variants across 160+ columns, corresponding to 180+ MB of uncompressed JSON). When loaded eagerly via `get_snv_annotations()`, the combined JSON parsing, dictionary construction, and Pydantic validation peak at ~1.67 GB RSS and retain ~936 MB heap memory, risking container out-of-memory (OOM) kills.

To handle large payloads efficiently:

- `iter_snv_annotations()` streams the HTTP response body in chunks (64 KB) using a low-overhead, single-pass streaming JSON decoder (`_snv_stream_parser.py`) without external parser dependencies.
- **Payload layout:** Varvis API serializes the variant data table before the column header in the JSON object (`{"data": [[...]], "header": [...]}`).
- **Streaming modes:**
  - `as_dict=False` (default): Yields each variant as a raw `list[Any]` immediately over the wire in constant memory (< 2 MB peak RSS).
  - `as_dict=True` with `header`: Resolves column names dynamically and yields variants as `dict[str, Any]` in constant memory (< 2 MB peak RSS).
  - `allow_buffering=True` without a supplied or cached header: Buffers all raw row lists in memory, parses the trailing header, and then yields filtered lists or dictionaries. Memory scales with the full row set.
- **Temporary-file streaming:** `stream_to_tempfile=True` caches one HTTP response, discovers its header from the cache, then rewinds to stream rows. An `ExitStack` closes the response and temporary file on completion, exceptions, or explicit generator closure; argument validation happens before acquiring resources. Temporary files prefer `$XDG_CACHE_HOME/varvis-connector`, using `~/.cache/varvis-connector` when the variable is unset, empty, or relative. The application cache directory is created with mode `0700`. User caches usually use disk storage, while system temporary directories may use RAM; filesystem backing is not inspected. Cache directory or file creation failures trigger a warning and fallback to the system temporary directory. Write failures propagate without restarting the download. Cached streams use the binary file interface, including the temporary-file wrappers returned on Windows. Raw-row overloads retain their list iterator return type with temporary-file caching enabled.
- **Filtering:** Supports `target_genes` (case-insensitive gene symbols) and `target_coordinates` (chrom and 1-based pos tuples). Dynamic column indices are discovered from header IDs via `resolve_header_indices()` to tolerate panel variations.
- **Header inspection:** `get_snv_annotation_header()` streams the payload until the header definition is encountered, parses the `SnvAnnotationHeaderItem` models, and terminates the connection early.
- **CLI integration:** `varvis_connector get-snv-annotations --stream` streams variants as newline-delimited JSON (JSONL) records containing `analysis_id` alongside variant fields.

Temporary-file mode finishes the full transfer and, if no header was supplied, scans the cached
header before yielding its first row, then parses rows lazily from the rewound file. It avoids
row buffering even with `allow_buffering=True`. A supplied header controls row mapping, while `header_callback` reports
the actual response header during the row-parsing pass; early generator closure can skip the
callback. Callers that stop early must explicitly close the generator, for example with
`contextlib.closing`. Header-only inspection discards rows but can still transfer nearly the
whole response when the header is last. Fetching the header separately and then iterating
requires two annotations requests; temporary-file iteration requires one.

Dictionary keys use column IDs, then titles, then `col_<index>` fallbacks. Coordinate filters
normalize chromosome case and optional `chr` prefixes and compare 1-based positions. Gene
and coordinate filters combine with AND and run locally without reducing network traffic.
Filters accept scalar and array-valued cells. Array-valued gene IDs are translated through
the Gene header's `dataDictionary`; any matching gene retains a row. This requires full
header descriptors for dictionary-backed genes, rather than column names alone. Coordinate
arrays use their first chromosome and position values. Yielded rows retain their original cells.
The CLI processes analyses sequentially and always uses temporary-file mode for `--stream`.
Its JSONL records have no outer analysis-ID mapping or header/data envelope, and
`--output-indent` is ignored. Cache write failures propagate and abort the CLI command.

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

Command cleanup runs after command execution on normal returns, raised errors, and command-level exits. Automatic-login commands use cleanup to send the logout request, while unexpected ordinary exceptions are logged and converted to exit status 1.

### Good CLI design decisions

- Top-level connection/auth settings are derived from the client definition, reducing duplication.
- Many multi-ID retrieval commands degrade gracefully: failures for individual IDs log warnings while successful IDs are still returned.
- JSON output is centralized in `_write_file_output()`.
- The CLI automatically shifts logs to stderr when JSON output goes to stdout.

### CLI output model

The CLI is designed for shell pipelines and scripting:

- structured data goes to stdout or a file
- logs go to stderr when needed
- `json.dump` traverses the original result container and converts model instances on demand with
  `pydantic_core.to_jsonable_python`, preserving Pydantic JSON serialization for dates and nested models
- empty result sets are sometimes considered an error and sometimes allowed, depending on the command

The command layer explicitly distinguishes those cases with `allow_empty_data`.
Output serialization retains a temporary JSON-compatible representation for the current model,
without allocating a duplicate dictionary/list tree for the entire batch of results.
Input and output arguments are parsed as `pathlib.Path` objects without opening files.
The path `-` selects stdin or stdout. Input files are read as UTF-8 only when needed;
explicit data arguments can bypass an unused input path. Regular output files are opened as
UTF-8 after retrieval and empty-result validation. JSONL output opens on the first record,
or after successful empty retrieval. Argument errors, login failures, and total retrieval
failures before any records leave existing output intact. Owned files are closed after use,
including exceptions, while standard streams remain open. Streaming or serialization failures
after writing begins can leave partial output. Stdout log routing uses the selected path.

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
- duplicate resolved target paths from different URLs abort the batch before downloads begin
- `--create-folder-per-id` separates same-named files belonging to different analyses
- progress bars can be disabled

This is more sophisticated than a trivial “loop and download”.

## Download Implementation Details

The file download subsystem is one of the more security-sensitive parts of the code, and it includes several good guardrails.

### Validation before download

Before any file is written, `download_files()` filters out invalid link entries and the parallel downloader rejects
an unsafe batch. The guarded cases are:

- `fileName` is missing
- `downloadLink` is missing
- filename becomes empty after stripping
- filename is `.`, `..`, contains NUL, or contains `/`
- filename does not match requested patterns
- file is marked archived
- target file exists and overwrite is not allowed
- the same download URL is already collected
- multiple URLs in a download batch resolve to the same target path

Download filenames are validated as single path components on both POSIX and Windows conventions. The client rejects separators, drive syntax, NUL bytes, and Windows DOS device names, including the superscript-digit COM and LPT aliases, then resolves the target and verifies that it remains under the requested output directory. The CLI applies the same resolved-path confinement check to per-analysis folder templates before creating directories, including templates that traverse through existing symlinks.

### Parallel download execution

`download_files_from_urls_parallel()` uses `ThreadPoolExecutor` and a shared `requests.Session`.
The session mounts an HTTP adapter whose cached pool count and retained connections per pool
use `download_pool_size` and `download_pool_max_size`; zero selects the worker count. The
session context encloses the executor so workers finish before pooled connections are closed.

`_DownloadRetry` extends urllib3's retry policy with full jitter before every retry, including
the first. The default `download_max_retries=2` allows three attempts in total. Delay bounds
are `download_backoff_factor_seconds * 2 ** (retry_number - 1)`, capped by urllib3's maximum backoff,
so the default retry delays are uniformly distributed over 0–0.5 seconds and 0–1 second.
Download backoff is independent from API request and session recovery backoff. It can be set
through the constructor, `VARVIS_DOWNLOAD_BACKOFF_FACTOR_SECONDS`, or the CLI option
`--download-backoff-factor-seconds`; zero disables delays and negative values are rejected.
Only request-level failures handled by the adapter are retried; interrupted streamed bodies
are cleaned up without restarting the download.

The CLI exposes download chunk size, pool sizes, and retry limits as global options. Both
the CLI and `from_env()` read `VARVIS_DOWNLOAD_CHUNK_SIZE`, `VARVIS_DOWNLOAD_POOL_SIZE`,
`VARVIS_DOWNLOAD_POOL_MAX_SIZE`, and `VARVIS_DOWNLOAD_MAX_RETRIES`, retaining constructor
defaults when unset and rejecting malformed integers. The CLI's API backoff option is
`--backoff-factor-seconds`. The usage guides document pooled download lifetimes, separate
retry budgets, and the distinction between request jitter and deterministic shared login recovery.

For each download:

- it performs `session.get(..., stream=True, timeout=...)` through the shared pooled adapter
- it accepts only URLs with an HTTPS scheme and network location
- checks status code
- reads `Content-Length` for identity-encoded responses and verifies the final byte count when the header is valid
- optionally renders a `tqdm` progress bar
- writes chunks to a temporary `.part` file in the destination directory
- preserves the destination's permissions when overwriting, or uses mode `0664` for a new file
- atomically replaces the destination with `os.replace()` only after the transfer completes
- removes partial temporary files after request, filesystem, or interruption failures

Completion is then handled asynchronously through `concurrent.futures.as_completed()`.

Keyboard interruption sets a shared event so active workers stop at chunk boundaries and clean up before the interruption returns to the caller. A preflight collision check compares resolved target paths and refuses to start the thread pool if distinct URLs would write to the same destination.

### Logging around progress bars

When progress bars are enabled, success/failure log messages are collected and returned rather than logged immediately. The CLI then logs them after all progress bars complete. This avoids output corruption from interleaving logs and progress-bar rendering.

That is a small but well-considered UX detail.

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
  Client public API behavior. Live SNV streaming and header tests use playground analyses 7
  and 61 with credentials from `VARVIS_TEST_PLAYGROUND_URL`, `VARVIS_TEST_PLAYGROUND_USER`,
  and `VARVIS_TEST_PLAYGROUND_PASSWORD`. A module-scoped fixture shares one authenticated
  client and eager reference payload per analysis. Eight representative streaming cases per
  analysis cover every listed parameter value: list/dictionary output, absent/model/dictionary
  headers, gene/coordinate/combined filters, 1 KiB and 64 KiB chunks, buffering, temporary-file
  caching, and invalid parameter combinations. Additional
  cases cover header names, empty filter collections, and filters with no matches. Expected
  matches are derived independently from live gene dictionaries and array-valued coordinates.
- `tests/test_varvis_internal.py`
  Lower-level retry and forced-logout behavior.
- `tests/test_cli.py`
  CLI parsing, environment fallback, command behavior, write commands, downloads, and request command behavior.
- `tests/test_log.py`
  Logging configuration behavior.
- `tests/test_snv_streaming.py`
  Incremental parsing through `stream_snv_json_from_request_or_buffer`, header discovery, row formatting, and filtering. Temporary-file tests cover binary files and Windows-style wrappers, UTF-8 chunk boundaries, empty data, supplied-header precedence, single-response reuse, lazy cached reads, filters, callbacks, argument validation, and cleanup on exhaustion, closure, and parsing, network, or filesystem errors. CLI streaming tests use data-first payloads and verify cache locations, request counts, fallback warnings without JSONL contamination, and help text. Cache-selection tests isolate XDG and home defaults and cover missing home directories, directory creation failures, file creation failures, and failure of both preferred and fallback storage.

### Mocking strategy

The project uses `requests-mock` fixtures rather than hitting the real API in most tests. Shared login mocks live in `tests/_common.py`.

Download retry tests replace urllib3's wire request method while exercising the actual
session, mounted adapter, and retry policy. Controlled jitter draws and intercepted sleeps
verify attempt limits, exponential delay windows, disabled backoff, and eventual success or
failure without network traffic or real retry delays.

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
- independent locks for separate clients
- login, requests, status reads, and authentication resets waiting for an in-progress login
- concurrent forced logouts sharing a single replacement session
- concurrent forced logouts sharing one login retry budget and failure after rejected credentials or transport errors
- unexpected recovery errors waking all waiting workers
- requests joining shared recovery during backoff or the final login attempt and receiving its success or failure
- later API requests starting fresh recovery after failure while delayed old requests retain their original failure
- delayed redirects from an old session preserving a successfully authenticated replacement
- delayed workers following multiple recovery outcomes before sending, including shared failures
- explicit logout waking recovery waiters during backoff and stopping the owner before its next login
- delayed redirects and transport failures after logout preserving a later explicit login without retrying
- failed authentication clearing incomplete state and releasing the lock for another thread

The concurrency tests use real worker threads with events and barriers to control ordering.
An observed reentrant lock exposes acquisition attempts so waiting assertions do not depend on
sleep intervals. Transport calls are mocked, synchronization waits are bounded, and worker
results propagate failures to the test thread.

Those cover the most fragile integration behavior.

The streaming parser decodes complete values directly. After an incomplete prefix, it scans
subsequent chunks while retaining string, escape, and nested-container state, then retries decoding
once the value boundary is known. Keys, rows, and metadata use the same scanner. Text fragments
are retained separately and joined once, avoiding repeated copying of the accumulated prefix.
Scalar values require a delimiter before acceptance. No fixed size limit is imposed: memory still
depends on the largest individual row or metadata value, plus retained metadata; unterminated
values can continue accumulating until EOF. Regression tests cover split integers, fractions,
exponents, final-value delimiters, compaction, large keys and values, nested containers, escapes,
Unicode, bounded decoder attempts, lazy row delivery, and malformed or truncated values for
HTTP responses and binary files.

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

### Documentation publishing

The documentation is published through the `docs.yaml` workflow and hosted on GitHub Pages. Production releases trigger the release orchestration workflow, which builds the package and then calls the docs workflow to publish the generated Sphinx documentation.

## CI / Release / Maintenance Workflow

The automation story is comprehensive.

### Toolchain

The project uses:

- `uv` for environment and dependency management
- `uv_build` as build backend
- Pydantic, requests, and tqdm as runtime dependencies
- Ruff for linting/formatting
- basedpyright for type checking
- Bandit for security linting
- pip-audit for dependency vulnerability scanning
- pre-commit
- git-cliff for changelog generation and commit message linting
- actionlint (`@kjanat/actionlint` v1.17.0) for GitHub Actions workflow linting
- pinact (v5.0.0 in CI) for GitHub Actions SHA pinning and updates

### CI workflows

The repository contains workflows for:

- tests
- code quality
- dependency audit
- scheduled dependency update issue/branch creation
- GitHub Actions linting and SHA pin checks on push, pull request, and release workflow calls
- scheduled GitHub Actions update issue creation
- gitleaks secret scanning
- build/release orchestration
- documentation publishing to GitHub Pages

### Interesting maintenance choices

- tests and code quality run across Python 3.10 to 3.14
- tests intentionally serialize CI concurrency to reduce load on the Varvis server
- dependency updates are partially automated through a scheduled workflow that opens an issue, creates a branch, updates `uv.lock`, and pushes a commit
- `git-cliff` is used both for changelog generation and for conventional-commit enforcement
- `uv` uses a seven-day dependency cooldown through `exclude-newer`, with a package-specific exception for `urllib3`
- Python dependency refreshes use `make depupgrade`, which runs only `uv lock -U` and `uv sync --all-groups --all-extras`; `make toolupgrade` separately upgrades the tools listed in `Makefile` and runs `pre-commit autoupdate`
- external GitHub Actions use full commit SHA pins with version comments; `astral-sh/setup-uv` uses `1c37ad07a6a961277cf70c0d37d6f313000f5884` (`v10.3.0`), and GitHub Releases use `softprops/action-gh-release`
- `make pin_actions` pins tagged action references, `make update_actions` refreshes pins, and `make check_actions` runs actionlint via npx followed by `pinact run --check`; pinact uses the seven-day minimum release age in `.github/pinact.yaml`
- `pinact_update.yaml` replaces Dependabot for GitHub Actions updates; on the 15th of each month at 08:30 UTC it uses a self-hosted runner to open an issue with the pinact diff, assigned from `.github/CODEOWNERS` and labeled `github_actions`, using `.github/issue-template-pinact-updates.md`; it does not create a branch or push workflow changes
- pinact workflows pass `${{ github.token }}` through `GITHUB_TOKEN`, which authenticates both pinact's API requests and the GitHub CLI's downloads and issue creation
- local GitHub Actions checks require pinact on `PATH` and Node.js/npm for npx; `make init_dev` does not install them
- `.agents/skills/update-dependencies/SKILL.md` covers Python packages, development tools and hooks, and GitHub Actions pins through their separate Makefile targets
- the current pre-commit baseline includes `ruff-pre-commit` and `basedpyright-pre-commit-mirror`
- gitleaks ignores version-tag push events as a standalone workflow trigger because the release orchestration workflow calls it explicitly for releases
- pre-commit mirrors the main local quality gates, including Ruff, Bandit, basedpyright, shellcheck, actionlint, a local always-run `pinact-check` hook, and project-local commit/changelog checks

### Release state

The release workflow is fully responsible for package publication on version tags.

`build_and_release.yaml` runs on tags matching `v*.*.*`. It gates releases with gitleaks, actionlint, pinact, and dependency audit for all tags. Non-development tags additionally require code quality and tests. Development tags containing `.dev` can build and publish after those four gates without running the full code quality and test gate inside the release workflow.

The build job lists all gate workflows in `needs`. Its explicit `always()` condition
requires gitleaks, actionlint, pinact, and dependency audit to succeed, while allowing
code quality and tests to be skipped for development tags.

The build job creates wheel and source distributions with `make build`, derives the package version from the tag name, and uploads the `dist/` directory as a workflow artifact.

Publication is split by tag type:

- non-development tags publish artifacts to GitHub Releases
- non-development tags publish to PyPI through trusted publishing/OIDC
- development tags publish to TestPyPI
- all successful release builds trigger the documentation workflow for GitHub Pages

GitHub release notes are generated from the current top section of `CHANGELOG.md`, and the release assets include both wheel and source distribution files.

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

#### Exception boundaries span a large CLI module

Individual retrieval commands catch expected `VarvisError` and `requests.RequestException` failures so batch-oriented commands can continue with other IDs. Unexpected programming errors propagate to the top-level CLI boundary, which logs the traceback and exits with status 1. This is a sound failure policy, although the large command module makes it important to keep each local exception boundary narrow as new commands are added.

#### Some inconsistency in exit handling

Many command handlers call `exit(1)` directly. Others rely on the top-level `VarvisCLI.run()` exception trap. The result is a somewhat mixed control-flow style.

#### Release workflow complexity

The release workflow is one of the higher-risk pieces of repository automation. It coordinates security gates, optional quality/test gates for development tags, package artifact upload/download, GitHub Release publication, PyPI/TestPyPI publication, changelog extraction, and documentation publishing. Small YAML changes here can affect published artifacts directly.

## Specific Findings And Nuances Worth Remembering

- The package is designed around the assumption that Varvis can invalidate sessions under concurrency.
- The library’s “endpoint auto-fix” behavior is opinionated and essential; bypass it only through `request()` when you really mean to.
- QC case metrics require custom payload reshaping before validation.
- Person create/update and virtual-panel create/update return different response shapes.
- The CLI is intentionally pipeline-friendly and carefully avoids polluting stdout when data output is expected there.
- Virtual panel update performs client-side merge behavior by fetching the current remote panel first.
- File downloads use filename/path safety checks, collision preflight, atomic replacement, size verification when possible, and interruption cleanup.
- The project is an early but actively publishable package line, with mature tooling and an implemented release pipeline rather than only local build support.

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
- tightening documentation/workflow synchronization
