Python API
==========

The ``varvis-connector`` package provides a Python API for interacting with the Varvis API. The main class is ``VarvisClient``, which handles authentication, session management, and provides methods to retrieve various types of genomic data from Varvis.

Basic Usage
-----------

To use the Python API, you first need to import the ``VarvisClient`` class:

.. code-block:: python

    from varvis_connector import VarvisClient

Then, you can create an instance of the client and authenticate:

.. code-block:: python

    # Create a client instance
    client = VarvisClient(
        api_url="https://varvis.example.com/",
        username="your_username",
        password="your_password"
    )

    # Authenticate with the Varvis API
    client.login()

Alternatively, you can initialize the client using environment variables:

.. code-block:: python

    # Initialize from environment variables
    client = VarvisClient.from_env()

    # Authenticate with the Varvis API
    client.login()

This requires the following environment variables to be set:

* ``VARVIS_URL``: The base URL for the Varvis API
* ``VARVIS_USER``: Your Varvis username
* ``VARVIS_PASSWORD``: Your Varvis password

See the :doc:`../installation` section for all environment variables that can be set.

Client Initialization Options
-----------------------------

The ``VarvisClient`` constructor accepts the following parameters:

* ``api_url`` (str): The base URL for the Varvis API. Must end with a slash ``/``, or one will be added automatically.
* ``username`` (str): The username for Varvis authentication.
* ``password`` (str): The password for Varvis authentication.
* ``https_proxy`` (str, optional): HTTPS proxy to use.
* ``ssl_verify`` (bool, optional): Whether to verify SSL certificates. Default is ``True``.
* ``connection_timeout`` (float, optional): Legacy HTTP timeout in seconds for both connection and response reads. Default is 10 seconds.
* ``connect_timeout`` (float, optional): Connection timeout in seconds. When set with or without ``read_timeout``, phase-specific timeouts are used.
* ``read_timeout`` (float, optional): Response-read timeout in seconds. When set with or without ``connect_timeout``, phase-specific timeouts are used.
* ``backoff_factor_seconds`` (float, optional): Backoff factor for API request and session recovery retries in seconds. Default is 0.5 seconds. Request retry delays use full jitter, chosen uniformly between zero and ``backoff_factor_seconds * 2 ** (retry_number - 1)``; zero disables delays. Shared session recovery uses deterministic exponential backoff.
* ``backoff_max_tries`` (int, optional): Maximum attempts per API request and per shared session recovery. Default is 5.
* ``download_pool_size`` (int, optional): Number of cached download connection pools. Default is 0, which uses the parallel download worker count.
* ``download_pool_max_size`` (int, optional): Maximum connections retained per download pool. Default is 0, which uses the parallel download worker count.
* ``download_backoff_factor_seconds`` (float, optional): Independent backoff factor for download retries with full jitter. Default is 0.5 seconds; zero disables delays.
* ``download_max_retries`` (int, optional): Maximum HTTP adapter retries per download request. Default is 2, allowing three attempts in total. Before each retry, the delay is chosen uniformly between zero and ``download_backoff_factor_seconds * 2 ** (retry_number - 1)``. Failures while streaming the response body are not retried.
* ``logger`` (logging.Logger, optional): Logger instance to use instead of default logger.

Authentication
--------------

Before making any API calls, you must authenticate:

.. code-block:: python

    client.login()

The client will automatically handle session management, including refreshing the authentication token when needed.

Concurrent requests using an invalidated session share one recovery sequence. One worker
performs up to ``backoff_max_tries`` re-login attempts in total while the others wait for
the result. This login budget is separate from each request's HTTP attempt budget and
does not include the initial explicit login. All affected workers receive the recovered
session or the recovery failure, including workers whose responses arrive late. A later
API request can start a fresh recovery sequence after a failed one. Requests with
``allow_retries=False`` do not initiate automatic recovery.

To explicitly log out and end the session:

.. code-block:: python

    client.logout()

Explicit logout invalidates existing recovery work, including when authentication has
already been cleared during recovery backoff. Waiting workers receive a ``VarvisError``;
old workers cannot start another login attempt or retry through a later session.
A login already in progress finishes before logout proceeds. HTTP requests already in
flight are not interrupted. Call ``client.login()`` explicitly to authenticate again.

VarvisClient API
----------------

The :doc:`API documentation </api/client>` gives an overview about all available methods.

Streaming SNV Annotations
-------------------------

For large whole-exome sequencing (WES) or whole-genome sequencing (WGS) analyses, loading the complete SNV annotations eagerly into memory using :meth:`~varvis_connector.VarvisClient.get_snv_annotations` can consume hundreds of megabytes or gigabytes of RAM.

To stream SNV annotations incrementally with constant, low memory overhead (< 2 MB peak RSS for raw streaming):

.. code-block:: python

    # Stream variants row-by-row as raw lists (constant < 2 MB peak RSS)
    for variant in client.iter_snv_annotations(analysis_id=37813):
        print(variant)

    # Stream variants as dictionaries with zero buffering by providing the header up front
    header = client.get_snv_annotation_header(analysis_id=37813)
    for variant in client.iter_snv_annotations(analysis_id=37813, as_dict=True, header=header):
        print(variant["Gene"], variant["Chr"], variant["Pos"])

    # Stream variants with column header discovered at stream end (compact row buffering)
    for variant in client.iter_snv_annotations(analysis_id=37813, as_dict=True, allow_buffering=True):
        print(variant["Gene"], variant["Chr"], variant["Pos"])

    # Stream with filtering by target genes or genomic coordinates
    for variant in client.iter_snv_annotations(
        analysis_id=37813,
        header=header,
        target_genes={"BRAF", "KRAS"},
        target_coordinates={("chr7", 140753336)},
    ):
        print("Filtered variant:", variant)

Header Inspection
~~~~~~~~~~~~~~~~~

You can inspect or retrieve the SNV annotation header schema without loading all variant records:

.. code-block:: python

    header = client.get_snv_annotation_header(analysis_id=37813)
    for col in header:
        print(col.id, col.title)

Downloading Files
-----------------

Parallel downloads share a connection-pooled HTTP session for each batch, reusing connections
to the same host. By default, both the cached pool count and the connections retained per
pool use ``max_parallel_downloads``. Override these with ``download_pool_size`` and
``download_pool_max_size`` when constructing the client. The session closes after all
download workers finish.

Download request retries use a separate budget and backoff from API requests and session
recovery. With the defaults, a download request has up to three attempts, with random
delays of 0–0.5 seconds before the first retry and 0–1 second before the second.
``download_max_retries=0`` disables download retries, and
``download_backoff_factor_seconds=0`` disables their delays. Failures while streaming
the response body are cleaned up without restarting the download.

The :meth:`~varvis_connector.VarvisClient.download_files` method downloads each file to a temporary file beside its
destination and atomically replaces the destination only after the transfer completes. Failed or interrupted
downloads preserve existing destination files and remove their partial temporary files. When the server provides a
valid ``Content-Length`` for an uncompressed response, the client also verifies the downloaded byte count before
committing the file.

The lower-level :meth:`~varvis_connector.VarvisClient.download_files_from_urls_parallel` method rejects a batch before
starting workers if different URLs resolve to the same target path. Call
:meth:`~varvis_connector.VarvisClient.check_download_files_for_path_collisions` first when assembling download batches
from multiple sources and you need to report collisions yourself.

