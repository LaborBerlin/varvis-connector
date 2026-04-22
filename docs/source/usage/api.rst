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
