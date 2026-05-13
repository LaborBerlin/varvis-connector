.. _development:

Development
===========

This section provides information for developers who want to contribute to the ``varvis-connector`` package.

Development workflow
--------------------

The development workflow is as follows:

1. Create an issue or pick an existing one and assign yourself to it.
2. Create a branch according to the branch naming conventions below (i.e.
   ``develop/123-nice-feature``) and start hacking. The branch should be based
   on the latest ``develop/**`` branch or ``main`` if there is no such branch
   yet. It's helpful to use the GitHub web UI for this to directly connect an
   issue to the branch.
3. Make commits according to the `conventional commits standard
   <https://www.conventionalcommits.org/en/v1.0.0/>`_ and push your commits.
   Check the CI pipeline. You may also create development releases from your
   branch by first bumping the version via ``uv version --bump ... --bump dev``
   (will create a version like ``vX.Y.Z.devN``) and then running
   ``make release``.
4. Once the issue is tackled and the CI pipeline succeeds, create a release
   branch (see naming conventions below) from the ``develop/**`` branch,
   optionally merging in other development branches.
5. Create a PR from the release branch to ``main`` using ``make pr``. This will
   also update the changelog. Make sure all necessary issues are referenced in
   the PR. The version then under review should **not** be a development
   version, but a production version (i.e. no ``.devN`` suffix). The CI
   pipeline will run on the PR with all necessary checks.
6. After the PR is reviewed, rebase to ``main``.
7. Finally, pull the updated ``main`` branch and run ``make release`` to create a production
   release. This will run the CI pipeline for building the package, creating a
   GitHub release, publishing the package to PyPI and generating the
   documentation for GitHub pages.

There may be deviations from this workflow, especially for hot fixes: You may
directly create a development branch without an issue, but then you should make
sure to create a PR from the branch to ``main`` as soon as possible.

Branch naming conventions
^^^^^^^^^^^^^^^^^^^^^^^^^

The following branch naming conventions are used and are also used as push
triggers by the GitHub Actions workflows:

- ``main`` is the main development branch: production releases are based from
  merges into this branch; avoid pushing to this branch directly;
- ``develop/**`` is used for development branches, mostly based on GitHub
  issues (i.e. ``develop/123-nice-feature`` for issue #123); pushes to these
  branches trigger CI tests and code quality checks;
- ``release/**`` is used for release branches, e.g. ``release/v1.2.3`` (don't
  omit the "v"!) for release v1.2.3; you should collect changes from one or
  more development branches into a release branch before creating a PR for a
  release; the Makefile command ``make release`` facilitates this.

Initial setup
-------------

Create an ``.env`` file and add the URL and credentials for the Varvis playground instance using the
``VARVIS_TEST_PLAYGROUND_`` prefix::

    VARVIS_TEST_PLAYGROUND_URL=https://playground.varvis.com/
    VARVIS_TEST_PLAYGROUND_USER=...
    VARVIS_TEST_PLAYGROUND_PASSWORD=...

To disable SSL verification for the test, set ``VARVIS_TEST_SSL_VERIFY=0`` in the ``.env`` file.

Install `uv <https://docs.astral.sh/uv/>`_, then install all dependencies and required tools and set up pre-commit::

    make init_dev

If you only want to (re-)synchronize the virtual environment with
``pyproject.toml`` / ``uv.lock``::

    make depsync

Note: commands that rely on the environment should generally be run via
``uv run <command>``. The Makefile targets handle this where appropriate.

Linting, formatting, type checks (local)
----------------------------------------

These checks are also run in CI (see below).

Ruff linter::

    ruff check

Ruff format check::

    ruff format --diff

Pyright type checks::

    basedpyright src/

Testing
-------

Run tests via *pytest* in the current Python venv::

    make test

Run linting, type checking and tests for all supported Python versions::

    make testall

Test coverage
-------------

Run coverage collection::

    make coverage

Enforce “no missing coverage in ``tests/`` files” (this is what CI uses on the
main Python version)::

    make coverage-check

Generate HTML/XML reports and update ``coverage-badge.svg`` (used in CI on
PRs)::

    make coverage-report

Preparing a Pull Request
------------------------

The Makefile features a shortcut to prepare a Pull Request for GitHub::

    make pr

This will update the package version (if necessary), update the changelog, create a release branch and push it.
It will then redirect to the GitHub PR page.

Dependency management
---------------------

Upgrade *all* dependencies (update lockfile, sync venv, update pre-commit
hooks)::

    make depupgrade

Check whether updates would be available (used by the scheduled dependency
update workflow)::

    make depcheck

Security: dependency audit
--------------------------

Run a vulnerability scan of the fully exported dependency set (is run also in
CI)::

    make audit

Building the package
--------------------

Build wheel and source distribution into ``dist/``::

    make build

Building the documentation
--------------------------

The package includes comprehensive documentation built with Sphinx. To build the documentation:

1. Make sure you've installed the "docs" extra. This is done automatically during ``make depsync``.
2. Build the HTML documentation via ``make docs``
3. The built documentation will be available in the ``docs/build/html`` directory. Open ``index.html`` in your browser to view it.

GitHub Actions workflows (CI, audits, builds and releases)
----------------------------------------------------------

Workflows live in ``.github/workflows/``:

- **``tests.yaml``**: pytest on Python 3.11 to 3.14; on push (3.13) enforces
  ``make coverage-check``; on PR (3.13) runs ``make coverage-report``, updates
  ``coverage-badge.svg``, and uploads the report artifact.
- **``codequality.yaml``**: conventional commits check, ruff format/lint, pyright,
  bandit (Python 3.11 to 3.14).
- **``gitleaks.yaml``**: credential leak scan on every push/PR.
- **``docs.yaml``**: build the documentation and publish it to GitHub pages.
- **``build_and_release.yaml``**: orchestrate production releases, including
  running the gate workflows, building the package and then publishing the
  documentation workflow.

CI runs can be skipped on branch pushes by including ``[skip-ci]`` in the
commit message (tests/codequality honor this).

Triggering a package release (tag-based)
----------------------------------------

Create and push a version tag based on the current package version::

    make release

This pushes a tag ``v<version>`` and triggers the ``build_and_release`` GitHub
Actions workflow.

Varvis API quirks
-----------------

The Varvis API is quite strange and often doesn't follow established standards in terms of API design. The API documentation doesn't cover many important details, especially in terms of error handling.

The following gives an incomplete overview of discovered quirks:

Rate limiting
^^^^^^^^^^^^^

The documentation says nothing about rate limiting. There is also no rate limit or retry information shared in the headers. However, when sending concurrent requests, the API may suddenly answer with an HTTP 302 redirect response (again, without any rate limit / retry information in the header) that leads to a visually empty, but still 50kB large HTML instead of a JSON object. The login session then seems to be invalidated and subsequent requests receive an HTTP 403 error, hence a new login must be attempted before continuing.

Login error handling
^^^^^^^^^^^^^^^^^^^^

The Varvis API responds with HTTP 200 OK **even when the login fails**, but doesn't return a CSRF in that case.

Obscure login procedure
^^^^^^^^^^^^^^^^^^^^^^^

The login procedure is rather non-standard. There are no API tokens or something like that, instead the procedure is as follows:

1. An initial session must be acquired to get a session cookie and CSRF token.
2. A login attempt can be performed using the session cookie and the CSRF.
3. The returned session cookie and CSRF token from this second request can then be used for further requests.

Incoherent parameter names
^^^^^^^^^^^^^^^^^^^^^^^^^^

Some endpoints (e.g. for CNV target results) have an analys\ **i**\sIds parameter, others (e.g. for pending CNV segments) an analys\ **e**\sIds parameter.

Incoherent API endpoint URLs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Some endpoints are at ``https://<HOST>/api/<endpoint>`` (e.g. */api/results*, */api/person*), others simply at ``https://<HOST>/<endpoint>`` (e.g. */login, /logout, /pending-cnv*).

Incoherent API endpoint parameters
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Some endpoints require to pass a person *LIMS* ID (e.g. */api/qualitycontrol/metrics/case/...*, */api/results/.../cnv*), others require a person *internal* ID (e.g. */pending-cnv*). It's possible to convert LIMS IDs to internal IDs via */api/person/.../id* endpoint, but the inverse operation is not supported.

Incoherent API response payload
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Some endpoints (e.g. */api/person/.../id*, */pending-cnv*) return their payload within a ``response`` item of a JSON structure that also contains ``success`` and ``errorMessageId`` information, while others (e.g. */api/analysis/.../annotations*) return their payload directly in the response body without further status or error information.

Incoherent API responses in case of errors
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In case of errors, e.g. when a certain data item cannot be found during a request, API endpoints behave wildly different:

- Very few endpoints do the "right thing" and return an HTTP 404 error (e.g. */api/results/.../cnv*).
- Most endpoints return an HTTP 400 error (e.g. */pending-cnv* or */.../coverage*).
- A few endpoints return an HTTP 200 code that normally indicates "everything OK", but set the ``success`` field in the returned JSON structure to *False* and provide some error information (*POST /virtual-panel*).
- Most crazy of all, some endpoints (*/virtual-panel/...*) return an HTTP 200 code together with ``success`` set to *True*, but set the ``response`` field to *None*.

Most of the time, the error behavior is not described in the API documentation.

No response paging for large responses
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Responses for some endpoints (e.g. */api/cases/.../report*) are very large and they are always fully transferred. There's no way to iteratively request partial responses, i.e. via paging. This leads to long delays to get a response, which is problematic for interactive applications and tests. It also means a higher load on the Varvis servers than would be necessary.

Different response structure for similar endpoints
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Some endpoints are used for querying similar data, but expose a different response structure. E.g. both the *Find Analyses* endpoint (*/api/analyses*) and the *Find By Customer Provided Input File Name* endpoint (*/analysis-list/find-by-customer-provided-input-file-name*) return a list of analysis items with similar but yet different sets of fields.
