Installation
============

Requirements
------------

* Python 3.10 or higher

Installation
------------

Currently, there are three ways to install this package. In any case, make sure to first create and activate a Python virtual environment in which to install *varvis_connector*.

Option 1 is to install it via ``pip`` from PyPI::

    pip install varvis-connector

Option 2 is to download either the "wheel" or source distribution package from the `GitHub releases page <https://github.com/LaborBerlin/varvis-connector/releases>`_ and then install it via ``pip``::

    pip install varvis_connector-<VERSION>.whl   # or .tar.gz

Option 3 is downloading or cloning this repository. The package and its command-line utility can then be installed with  ``pip install <path-to-repository>``.


Configuration / environment variables
-------------------------------------

API URL and login credentials can be set as environment variables. It's recommended to set these in a ``.env``-file::

    VARVIS_URL=https://...
    VARVIS_USER=<USER>
    VARVIS_PASSWORD=<PASSWORD>

The following environment variables are optional:

- ``HTTPS_PROXY``: Sets a proxy for all communication with the API.
- ``VARVIS_SSL_VERIFY`` (0 or 1): Disables SSL certificate verification when set to 0 – **only do this for development and testing (may be necessary in that case for some corporate network configurations where routers inspect SSL traffic).**
- ``VARVIS_CONNECTION_TIMEOUT``: Set the legacy timeout for both connection and response reads (default is 10s).
- ``VARVIS_CONNECT_TIMEOUT``: Optionally set a connection timeout independently in seconds.
- ``VARVIS_READ_TIMEOUT``: Optionally set a response-read timeout independently in seconds.
- ``VARVIS_BACKOFF_FACTOR_SECONDS``: Backoff factor in seconds for API request retries with full jitter and shared session recovery with deterministic exponential backoff. Default is 0.5s; zero disables delays.
- ``VARVIS_DOWNLOAD_BACKOFF_FACTOR_SECONDS``: Independent download retry backoff factor in seconds with full jitter. Default is 0.5s; zero disables delays.
- ``VARVIS_BACKOFF_MAX_TRIES``: Maximum attempts per API request and per shared session recovery, with separate budgets. Default is 5; must be at least 1.

The CLI and ``VarvisClient.from_env()`` also accept these integer download settings:

- ``VARVIS_DOWNLOAD_CHUNK_SIZE``: Bytes read per download chunk. Default is 5242880 (5 MiB).
- ``VARVIS_DOWNLOAD_POOL_SIZE``: Number of cached download connection pools. Default is 0, which uses the parallel download worker count.
- ``VARVIS_DOWNLOAD_POOL_MAX_SIZE``: Maximum connections retained per download pool. Default is 0, which uses the parallel download worker count.
- ``VARVIS_DOWNLOAD_MAX_RETRIES``: Maximum HTTP adapter retries per download request. Default is 2, allowing three attempts in total; zero disables retries.

Additional environment variables must be set for testing environments. See the :ref:`development` chapter.

Verifying Installation
----------------------

To verify that the installation was successful, you can run:

.. code-block:: bash

    varvis_connector --help

This should display the help message for the command-line interface.
