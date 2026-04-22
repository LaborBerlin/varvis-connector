Changelog
=========

.. _013---2026-04-21:

0.1.3 - 2026-04-21
------------------

Development
~~~~~~~~~~~

- Bump actions/upload-artifact from 6 to 7
- Switch from commitizen to git-cliff for commit linting and changelog generation
- Move complex Makefile targets to separate bash scripts
- Set uv dependency cooldown to 7 days
- Use pyright (basedpyright) instead of mypy for type checking

Documentation
~~~~~~~~~~~~~

- Add enrichment kit, gene, phenotype, and demographic analysis examples
- Add real-world examples

Other
~~~~~

- Update gitignore to exclude local data folders for analysis cache
- Update dependencies and fix security vulnerabilities (closes #106, #108)
- Clean up repo for publication

Testing
~~~~~~~

- Fix ``test_varvis.py::test_request_get`` failing due to API changes (closes #99)

.. _012---2026-02-23:

0.1.2 - 2026-02-23
------------------

CI
~~

- Don't require coverage-check in tests workflow

.. _development-1:

Development
~~~~~~~~~~~

- Also update changelog.rst via 'make changelog' [skip-ci]

.. _documentation-1:

Documentation
~~~~~~~~~~~~~

- Updated development chapter

.. _012rc1---2026-02-20:

0.1.2rc1 - 2026-02-20
---------------------

Bug Fixes
~~~~~~~~~

- Update pillow to fix vulnerability
- Allow analysisType 'STR'

.. _ci-1:

CI
~~

- Set up workflows for cred. leaks checks, codequality, dep. checks and adjust tests and build/release/deploy workflows

.. _development-2:

Development
~~~~~~~~~~~

- Update dependencies
- Add commitizen + pre-commit hook + CHANGELOG
- Add bandit + pre-commit hook
- Add pip-audit
- Add gitleaks pre-commit hook
- Add missing check_git_clean to Makefile
- Fix 'make docs'

.. _other-1:

Other
~~~~~

- Make mypy checks stricter and adapt code to pass stricter mypy checks

.. _testing-1:

Testing
~~~~~~~

- Fix problems with coverage
- Fix coverage issues

.. _010post1---2026-01-13:

0.1.0.post1 - 2026-01-13
------------------------

.. _ci-2:

CI
~~

- Move from val01 to bid01 and improve 'make build', 'make depsync', 'make depupgrade'

.. _testing-2:

Testing
~~~~~~~

- Disable failing test test_varvis.py::test_request_get for now
