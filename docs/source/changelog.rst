Changelog
=========

.. _030---2026-09-18:

0.3.0 - 2026-09-18
------------------

Bug Fixes
~~~~~~~~~

- Normalize test playground URL and update lockfile for security audit
- Validate filter columns, add dynamic bool overload, and normalize aliases
- Accept wire type field in CaseReportAnalysis alias

CI
~~

- Disable weekly dependency audit -- we rely on GitHub dependabot alerts for this
- Tolerate badge push failures on fork PRs without write permissions

Development
~~~~~~~~~~~

- Add your-highness to codeowners list
- Update dependencies

Features
~~~~~~~~

- Add streaming support for SNV annotations to prevent OOM

Other
~~~~~

- Bump astral-sh/setup-uv from 8.1.0 to 10.0.1
- Bump actions/checkout from 6 to 7

Styling
~~~~~~~

- Configure ruff lint select and clean up parser imports

Testing
~~~~~~~

- Skip playground tests when credentials are not configured

.. _022post1---2026-05-29:

0.2.2.post1 - 2026-05-29
------------------------

Documentation
~~~~~~~~~~~~~

- Add intended use, use absolute url for logo (fixes display on PyPI) and improve docs in ``build_and_release`` workflow

.. _022---2026-05-27:

0.2.2 - 2026-05-27
------------------

.. _documentation-1:

Documentation
~~~~~~~~~~~~~

- Add varvis logo and disclaimer

.. _other-1:

Other
~~~~~

- Update dependencies with fixed security vulnerabilities

.. _021---2026-05-13:

0.2.1 - 2026-05-13
------------------

.. _ci-1:

CI
~~

- Update setup-uv action to v8.1.0 in all workflows

.. _development-1:

Development
~~~~~~~~~~~

- Replace many dev dependencies by using ``uv tool`` / ``uvx``
- Don't overwrite commit message when amending the vers. bump commit
- Require ``make audit`` in update-dependencies skill

.. _documentation-2:

Documentation
~~~~~~~~~~~~~

- Fix link and typo in installation section

.. _other-2:

Other
~~~~~

- Bump actions/upload-pages-artifact from 4 to 5
- Bump actions/download-artifact from 6 to 8
- Bump actions/upload-artifact from 5 to 7
- Bump actions/configure-pages from 5 to 6
- Update dependencies to fix security vulnerability in urllib3 / closes #6

.. _styling-1:

Styling
~~~~~~~

- Set ruff line length to 120 and reformat code

.. _020---2026-04-29:

0.2.0 - 2026-04-29
------------------

.. _ci-2:

CI
~~

- Add docs pages workflow
- Set up publishing to PyPI and GitHub releases

.. _documentation-3:

Documentation
~~~~~~~~~~~~~

- Add GPLv3 license and respective notes

.. _other-3:

Other
~~~~~

- Squash git history to create first public release
- Set up AI assistance by providing AGENTS.md and ``update-dependencies`` skill

.. _testing-1:

Testing
~~~~~~~

- Fix type hint issue in ``test_optional_args``
