Introduction
------------

The ``varvis-connector`` package provides a Python interface for the Varvis API. It includes both a command-line interface (CLI) and a Python package with a client implementation. The package handles authentication, session management, and provides methods to retrieve various types of genomic data including SNV annotations, CNV target results, and CNV segments. It supports environment-based configuration and includes comprehensive error handling.

Features
~~~~~~~~

* Python client for the Varvis API
* Command-line interface for direct interaction with the API
* Authentication and session management
* Methods to retrieve various types of genomic data
* Environment-based configuration
* Comprehensive error handling
* Support for Python 3.10 and above

Currently covered Varvis API endpoints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following API endpoints are currently covered both by the CLI and the Python package:

.. list-table::
   :widths: 30 20 30 20
   :header-rows: 1

   * - Varvis API endpoint
     - Varvis docs title
     - CLI command ``varvis_connector ...``
     - :any:`VarvisClient` method
   * - ``GET /api/person/{personLimsId}/id``
     - Get Person Id
     - :ref:`cli-get-internal-person-id`
     - :any:`VarvisClient.get_internal_person_id`
   * - ``GET /api/analysis/{analysisId}/annotations``
     - Get Variant Annotations
     - :ref:`cli-get-snv-annotations`
     - :any:`VarvisClient.get_snv_annotations`
   * - ``GET /api/results/{personLimsId}/cnv``
     - Get Cnv Results
     - :ref:`cli-get-cnv-target-results`
     - :any:`VarvisClient.get_cnv_target_results`
   * - ``GET /pending-cnv``
     - Get Pending Cnvs
     - :ref:`cli-get-pending-cnv-segments`
     - :any:`VarvisClient.get_pending_cnv_segments`
   * - ``GET /api/qualitycontrol/metrics/case/{personId}``
     - Get Case Metrics
     - :ref:`cli-get-qc-case-metrics`
     - :any:`VarvisClient.get_qc_case_metrics`
   * - ``GET /api/{personId}/coverage``
     - Api Coverage Task Data
     - :ref:`cli-get-coverage-data`
     - :any:`VarvisClient.get_coverage_data`
   * - ``GET /api/analyses``
     - Find Analyses
     - :ref:`cli-get-analyses`
     - :any:`VarvisClient.get_analyses`
   * - ``GET /person/{personLimsId}/analyses``
     - Api Get Analyses Linked With Person
     - :ref:`cli-get-person-analyses`
     - :any:`VarvisClient.get_person_analyses`
   * - ``GET /api/cases/{personId}/report``
     - Get Case Report
     - :ref:`cli-get-case-report`
     - :any:`VarvisClient.get_case_report`
   * - ``GET /api/person/{personLimsId}``
     - Get Person Including Clinical Information
     - :ref:`cli-get-person`
     - :any:`VarvisClient.get_person`
   * - ``PUT /api/person``
     - Api Create Or Update Person
     - :ref:`cli-create-or-update-person`
     - :any:`VarvisClient.create_or_update_person`
   * - ``GET /analysis-list/find-by-customer-provided-input-file-name``
     - Find By Customer Provided Input File Name
     - :ref:`cli-find-analyses-by-filename`
     - :any:`VarvisClient.find_analyses_by_filename`
   * - ``GET /virtual-panel/{id}``
     - Get Virtual Panel Details
     - :ref:`cli-get-virtual-panel`
     - :any:`VarvisClient.get_virtual_panel`
   * - ``POST /api/virtual-panel``
     - Create Or Update Virtual Panel
     - :ref:`cli-create-virtual-panel` / :ref:`cli-update-virtual-panel`
     - :any:`VarvisClient.create_or_update_virtual_panel`
   * - ``GET /virtual-panels``
     - Get Virtual Panel Summaries
     - :ref:`cli-get-virtual-panel-summaries`
     - :any:`VarvisClient.get_virtual_panel_summaries`
   * - ``GET /virtual-panel-genes``
     - Get All Genes
     - :ref:`cli-get-all-genes`
     - :any:`VarvisClient.get_all_genes`
   * - ``GET /api/analysis/{analysisId}/get-file-download-links``
     - Get File Download Links (and download the files)
     - :ref:`cli-get-file-download-links` / :ref:`cli-download-files`
     - :any:`VarvisClient.get_file_download_links` / :any:`VarvisClient.download_files`


In addition to that, it's possible to send arbitrary authenticated requests to the API using the CLI :ref:`cli-request` command or the :any:`VarvisClient.request` method, which is especially useful for undocumented endpoints.
