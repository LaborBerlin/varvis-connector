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
* ``connection_timeout`` (float, optional): HTTP connection timeout in seconds. Default is 10 seconds.
* ``backoff_factor_seconds`` (float, optional): Backoff factor for API retries in seconds. Default is 0.5 seconds.
* ``backoff_max_tries`` (int, optional): Maximum number of API tries. Default is 5.
* ``logger`` (logging.Logger, optional): Logger instance to use instead of default logger.

Authentication
--------------

Before making any API calls, you must authenticate:

.. code-block:: python

    client.login()

The client will automatically handle session management, including refreshing the authentication token when needed.

To explicitly log out and end the session:

.. code-block:: python

    client.logout()

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

