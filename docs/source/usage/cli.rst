Command-Line Interface (CLI)
============================

The ``varvis-connector`` package provides a command-line interface (CLI) program called ``varvis_connector``, which allows you to interact with the Varvis API directly from the terminal.

If you want to see examples about what's possible with the CLI in combination with other tools on the command-line, you can skip over to the :ref:`real-world-applications` section.

Basic Usage
-----------

The general argument structure for ``varvis_connector`` is as follows:

.. code-block:: bash

    varvis_connector [global-options] <command> [command-options]

Global Options
--------------

These options apply to all commands:

* ``--api-url URL``: The base URL for the Varvis API. If not provided, the value from the ``VARVIS_URL`` environment variable will be used.
* ``--username USERNAME``: The username for Varvis authentication. If not provided, the value from the ``VARVIS_USER`` environment variable will be used.
* ``--password PASSWORD``: The password for Varvis authentication. If not provided, the value from the ``VARVIS_PASSWORD`` environment variable will be used. If neither the option nor the environment variable is set, the program will prompt for the password.
* ``--https-proxy PROXY``: HTTPS proxy to use for all communication with the API. If not provided, the value from the ``HTTPS_PROXY`` environment variable will be used.
* ``--ssl-verify {0,1}``: Whether to verify SSL certificates. If not provided, the value from the ``VARVIS_SSL_VERIFY`` environment variable will be used. Default is 1 (verify).
* ``--connection-timeout SECONDS``: HTTP connection timeout in seconds. If not provided, the value from the ``VARVIS_CONNECTION_TIMEOUT`` environment variable will be used. Default is 10 seconds.
* ``--backoff-factor SECONDS``: Backoff factor for API retries in seconds. If not provided, the value from the ``VARVIS_BACKOFF_FACTOR_SECONDS`` environment variable will be used. Default is 0.5 seconds.
* ``--backoff-max-tries TRIES``: Maximum number of API tries. If not provided, the value from the ``VARVIS_BACKOFF_MAX_TRIES`` environment variable will be used. Default is 5.
* ``--verbose``: Enable verbose output.
* ``--help``: Show help message and exit.

Available Commands
------------------

To see a list of all available commands, run:

.. code-block:: bash

    varvis_connector --help

For help on a specific command, run:

.. code-block:: bash

    varvis_connector <command> --help

Details on available commands
-----------------------------

Please note that general output control options ``--output`` and ``--output-indent`` are omitted from the usage overview for better readability. See :ref:`output_options` below.

.. _cli-check-login:

check-login
~~~~~~~~~~~

Check if logging in succeeds with the provided credentials.

**Usage:**

.. code-block:: bash

    varvis_connector check-login

.. _cli-get-internal-person-id:

get-internal-person-id
~~~~~~~~~~~~~~~~~~~~~~

Retrieve the internal Varvis ID associated with given persons' LIMS-IDs. Generates JSON that maps LIMS IDs to internal person IDs. If an error occurs while retrieving data for a specific LIMS-ID, this ID will be skipped, but data retrieval for the other IDs will continue. If retrieving data fails for all LIMS IDs, the program will exit with an error description.

**Usage:**

.. code-block:: bash

    varvis_connector get-internal-person-id lims-ids [lims-ids ...]

**Command Options:**

- ``lims-ids`` (required) (one or more values): Person LIMS-ID(s). Repeat argument for multiple persons.

For output formatting options see :ref:`output_options` below.

.. _cli-get-snv-annotations:

get-snv-annotations
~~~~~~~~~~~~~~~~~~~

Retrieves the SNV annotations for given analysis IDs. Generates JSON that maps analysis IDs to SNV annotation data. If an error occurs while retrieving data for a specific analysis ID, this analysis will be skipped, but data retrieval for the other IDs will continue. If retrieving data fails for all analysis IDs, the program will exit with an error description.

**Usage:**

.. code-block:: bash

    varvis_connector get-snv-annotations analysis-ids [analysis-ids ...]

**Command Options:**

- ``analysis-ids`` (required) (one or more values): One or more analysis IDs (integers).

For output formatting options see :ref:`output_options` below.

.. _cli-get-cnv-target-results:

get-cnv-target-results
~~~~~~~~~~~~~~~~~~~~~~

Retrieves the CNV target results for a specified person LIMS-ID and associated analyses. A virtual panel can optionally be specified to filter the results. Generates JSON with the CNV target results. If an error occurs while retrieving data, the program will exit with an error description.

**Usage:**

.. code-block:: bash

    varvis_connector get-cnv-target-results \
        [--virtual-panel-id VIRTUAL_PANEL_ID] \
        lims-id analysis-ids \
        [analysis-ids ...]

**Command Options:**

- ``lims-id`` (required): A person LIMS-ID for which to retrieve results.
- ``analysis-ids`` (required) (one or more values): One or more analysis IDs (integers).
- ``--virtual-panel-id`` (default: ``1``): Optional ID of the virtual panel to apply in filtering the CNV target data. By default, the virtual panel ID 1, i.e. the "all genes" panel is used. If set to the string "none", the virtual panel ID will be omitted. In that case, the Varvis documentation states that "the lastly selected virtual panel for the given person is used or 'All Genes' if no virtual panel was selected yet." This means, if set to "none" the behavior depends on the selection stored in the current user's session.

For output formatting options see :ref:`output_options` below.

.. _cli-get-pending-cnv-segments:

get-pending-cnv-segments
~~~~~~~~~~~~~~~~~~~~~~~~

Retrieves pending CNV segments based for a given person (identified either by internal ID or LIMS ID) and associated analysis IDs. A virtual panel can optionally be specified to filter the results. Generates JSON with the pending CNV segments. If an error occurs while retrieving data, the program will exit with an error description.

**Usage:**

.. code-block:: bash

    varvis_connector get-pending-cnv-segments \
        (--lims-id LIMS_ID | --internal-person-id INTERNAL_PERSON_ID) \
        [--virtual-panel-id VIRTUAL_PANEL_ID] \
        analysis-ids [analysis-ids ...]

**Command Options:**

- ``--lims-id``: A person LIMS-ID for which to retrieve results. Either this or ``--internal-person-id`` must be provided.
- ``--internal-person-id``: Internal varvis person ID for which to retrieve results. Either this or ``--lims-id`` must be provided.
- ``analysis-ids`` (required) (one or more values): One or more analysis IDs (integers).
- ``--virtual-panel-id`` (default: ``1``): Optional ID of the virtual panel to apply in filtering the CNV segments. By default, the virtual panel ID 1, i.e. the "all genes" panel is used. If set to the string "none", the virtual panel ID will be omitted. In that case, the Varvis documentation states that "the lastly selected virtual panel for the given person is used or 'All Genes' if no virtual panel was selected yet." This means, if set to "none" the behavior depends on the selection stored in the current user's session.

For output formatting options see :ref:`output_options` below.

.. _cli-get-qc-case-metrics:

get-qc-case-metrics
~~~~~~~~~~~~~~~~~~~

Retrieves QC case metrics for given person LIMS-ID(s).

**Usage:**

.. code-block:: bash

    varvis_connector get-qc-case-metrics lims-ids [lims-ids ...]

**Command Options:**

- ``lims-ids`` (required) (one or more values): Person LIMS-ID(s). Repeat argument for multiple persons.

For output formatting options see :ref:`output_options` below.

.. _cli-get-coverage-data:

get-coverage-data
~~~~~~~~~~~~~~~~~

Retrieves coverage data for given person LIMS-ID(s), optionally filtered by virtual panel ID.

**Usage:**

.. code-block:: bash

    varvis_connector get-coverage-data \
        [--virtual-panel-id VIRTUAL_PANEL_ID] \
        lims-ids [lims-ids ...]

**Command Options:**

- ``lims-ids`` (required) (one or more values): Person LIMS-ID(s). Repeat argument for multiple persons.
- ``--virtual-panel-id`` (default: ``1``): Optional ID of the virtual panel to apply in filtering the coverage data. By default, the virtual panel ID 1, i.e. the "all genes" panel is used. If set to the string "none", the virtual panel ID will be omitted. In that case, the Varvis documentation states that "the lastly selected virtual panel for the given person is used or 'All Genes' if no virtual panel was selected yet." This means, if set to "none" the behavior depends on the selection stored in the current user's session.

For output formatting options see :ref:`output_options` below.

.. _cli-get-analyses:

get-analyses
~~~~~~~~~~~~

Get basic information about analyses including the timestamps of first and last annotation. Optionally, the analyses can be filtered by analysis IDs.

**Usage:**

.. code-block:: bash

    varvis_connector get-analyses [--analysis-ids [ANALYSIS_IDS ...]]

**Command Options:**

- ``--analysis-ids`` (zero or more values): Optional analysis IDs to filter the results by.

For output formatting options see :ref:`output_options` below.

.. _cli-get-report-info-for-persons:

get-report-info-for-persons
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Retrieves case report information all persons.

**Usage:**

.. code-block:: bash

    varvis_connector get-report-info-for-persons

**Command Options:**

For output formatting options see :ref:`output_options` below.

.. _cli-get-person-analyses:

get-person-analyses
~~~~~~~~~~~~~~~~~~~

Get basic information about analyses for given person LIMS-ID(s).

**Usage:**

.. code-block:: bash

    varvis_connector get-person-analyses lims-ids [lims-ids ...]

**Command Options:**

- ``lims-ids`` (required) (one or more values): Person LIMS-ID(s). Repeat argument for multiple persons.

For output formatting options see :ref:`output_options` below.

.. _cli-get-case-report:

get-case-report
~~~~~~~~~~~~~~~

Retrieves case report information for given person LIMS-ID(s).

**Usage:**

.. code-block:: bash

    varvis_connector get-case-report [--draft] [--inactive] lims-ids [lims-ids ...]

**Command Options:**

- ``lims-ids`` (required) (one or more values): Person LIMS-ID(s). Repeat argument for multiple persons.
- ``--draft``: Set this flag if a draft report with pending changes is explicitly requested instead of the final report (submitted report). `--draft`
- ``--inactive``: Set this flag if inactive report items should be also returned (by default inactive report items are not returned). `--inactive`

For output formatting options see :ref:`output_options` below.

.. _cli-get-person:

get-person
~~~~~~~~~~

Retrieves person data including clinical information for given person LIMS-ID(s).

**Usage:**

.. code-block:: bash

    varvis_connector get-person lims-ids [lims-ids ...]

**Command Options:**

- ``lims-ids`` (required) (one or more values): Person LIMS-ID(s). Repeat argument for multiple persons.

For output formatting options see :ref:`output_options` below.

.. _cli-create-or-update-person:

create-or-update-person
~~~~~~~~~~~~~~~~~~~~~~~

Allows to create a new person entry, or updates an existing one. Person data can be passed either via arguments like ``--lims-id`` or as JSON data that follows the :any:`PersonUpdateData` schema. JSON data can be passed via stdin (default) or loaded from file using the ``--input`` argument. If any person data CLI argument is given, any JSON input will be ignored. The command reports the internal ID of the person entry that was created or updated.

**Usage:**

.. code-block:: bash

    varvis_connector create-or-update-person \
        [--lims-id LIMS_ID] \
        [--family-id FAMILY_ID] \
        [--first-name FIRST_NAME] \
        [--last-name LAST_NAME] \
        [--comment COMMENT] \
        [--sex SEX] \
        [--country COUNTRY] \
        [--birth-date BIRTH_DATE]  \
        [--hpo-term-ids HPO_TERM_ID [HPO_TERM_ID ...]] \
        [--input INPUT]

**Command Options:**

You can either pass the person data via CLI arguments like ``--lims-id``, ``--family-id``, etc. or as JSON input, **not both.**

If passing the data via CLI arguments, the following arguments are available:

- ``lims-id``: The custom ID for this person, e.g. as used in the LIMS system.
- ``family-id``: The ID of this person's family.
- ``first-name``: The person's first name.
- ``last-name``: The person's last name.
- ``comment``: A free-text comment on the person.
- ``sex``: The biological sex of the person.
- ``country``: The name of the person's home country.
- ``birth-date``: The person's birth date.
- ``hpo-term-ids``: A list of HPO term IDs (in the form of "HP:0123456") that are associated with the person.

Examples:

.. code-block:: bash

    # create or update a person identified by LIMS ID TEST and set the
    # birthdate to 2020-03-04
    varvis_connector create-or-update-person --lims-id TEST --birth-date 2020-03-04

    # same as above but also set two HPO terms
    varvis_connector create-or-update-person \
        --lims-id TEST \
        --birth-date 2020-03-04 \
        --hpo-term-ids HP:0123456 HP:0123457

If passing the data as JSON, you can either specify a file to load the data from via ``--input <PATH>`` or pipe the data via stdin. In both cases, the data must validate against the :any:`PersonUpdateData` schema.

Examples:

.. code-block:: bash

    # pass the data via stdin
    varvis_connector create-or-update-person <<EOF
    {
      "id": "TEST",
      "firstName": "Tester",
      "lastName": "Test",
      "birthDateYear": 2020,
      "birthDateMonth": 3,
      "birthDateDay": 4
    }
    EOF

    # load the data from a JSON file
    varvis_connector create-or-update-person --input /path/to/file.json

If any of the data fields apart from the LIMS-ID are not given, their respective value is set to "null", which means that the field will stay untouched in Varvis on update or will be set to a Varvis default on create.

.. _cli-find-analyses-by-filename:

find-analyses-by-filename
~~~~~~~~~~~~~~~~~~~~~~~~~

Find analyses by searching for the given filename components within customer-provided input file names.

**Usage:**

.. code-block:: bash

    varvis_connector find-analyses-by-filename filename [filename ...]

**Command Options:**

- ``filename`` (required) (one or more values): One or more filename components to search for. Each component is treated as a substring search where all of the provided components must be found in a customer input filename for the corresponding analysis to be included in the result (AND operator).

For output formatting options see :ref:`output_options` below.

.. _cli-get-virtual-panel:

get-virtual-panel
~~~~~~~~~~~~~~~~~

Retrieves virtual panel data for given virtual panel IDs. Returned data includes name, active status, and details of the genes that are associated with the virtual panel.

**Usage:**

.. code-block:: bash

    varvis_connector get-virtual-panel ids [ids ...]

**Command Options:**

- ``ids`` (required) (one or more values): Virtual panel IDs to retrieve data for.

For output formatting options see :ref:`output_options` below.

.. _cli-get-virtual-panel-summaries:

get-virtual-panel-summaries
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Retrieve the summaries for all virtual panels, except for the virtual panel containing all genes.

**Usage:**

.. code-block:: bash

    varvis_connector get-virtual-panel-summaries

For output formatting options see :ref:`output_options` below.

.. _cli-get-all-genes:

get-all-genes
~~~~~~~~~~~~~

Retrieves a list of all genes and their details. The details are reduced to information important for virtual panels.

**Usage:**

.. code-block:: bash

    varvis_connector get-all-genes

For output formatting options see :ref:`output_options` below.


.. _cli-create-virtual-panel:

create-virtual-panel
~~~~~~~~~~~~~~~~~~~~

Allows to create a new virtual panel entry. Data can be passed either via arguments like ``--name`` or as JSON data that follows the :any:`VirtualPanelUpdateData` schema (see documentation). The JSON data can be passed via stdin (default) or loaded from file using the ``--input`` argument. This works similar to :ref:`cli-create-or-update-person` -- please see the examples there.  If any virtual panel data CLI argument is given, any JSON input will be ignored. The command reports the ID of the virtual panel that was created.

**Usage:**

.. code-block:: bash

    varvis_connector create-virtual-panel \
        [--name NAME] \
        [--active] \
        [--gene-ids GENE_IDS [GENE_IDS ...]] \
        [--description DESCRIPTION] \
        [--person-id PERSON_ID] \
        [--input INPUT]

**Command Options:**

You can either pass the virtual panel data via CLI arguments like ``--name``, ``--active``, etc. or as JSON input, **not both.**

If passing the data via CLI arguments, the following arguments are available:

- ``--name``: The virtual panel name.
- ``--active``: Set this flag in order to activate the virtual panel.
- ``--gene-ids``: Gene ids of genes that should be associated with this virtual panel.
- ``--description``: Optional description of the virtual panel.
- ``--person-id``: Optional id of the bound person.
- ``--input INPUT``: Optional input JSON file that follows that :any:`VirtualPanelUpdateData`  schema. Can be used as alternative to providing the data via the above arguments. If not given, input will be read from stdin.

.. _cli-update-virtual-panel:

update-virtual-panel
~~~~~~~~~~~~~~~~~~~~

Allows to update an existing virtual panel entry identified by an ID. Data can be passed either via arguments like ``--name`` or as JSON data that follows the :any:`VirtualPanelUpdateData` schema (see documentation). The JSON data can be passed via stdin (default) or loaded from file using the ``--input`` argument. This works similar to :ref:`cli-create-or-update-person` -- please see the examples there.  If any virtual panel data CLI argument is given, any JSON input will be ignored. The command reports the ID of the virtual panel that was updated.

**Usage:**

.. code-block:: bash

    varvis_connector update-virtual-panel \
        [--id ID] \
        [--name NAME] \
        [--active] \
        [--inactive] \
        [--gene-ids GENE_IDS [GENE_IDS ...]] \
        [--description DESCRIPTION] \
        [--person-id PERSON_ID] \
        [--input INPUT]

**Command Options:**

You can either pass the virtual panel data via CLI arguments like ``--name``, ``--active``, etc. or as JSON input, **not both.**

If passing the data via CLI arguments, the following arguments are available:

- ``--id``: The virtual panel id for the panel to be updated.
- ``--name``: The virtual panel name.
- ``--active``: Set this flag in order to activate the virtual panel (has precedence over ``--inactive``).
- ``--inactive``:  Set this flag in order to deactivate the virtual panel.
- ``--gene-ids``: Gene ids of genes that should be associated with this virtual panel.
- ``--description``: Optional description of the virtual panel.
- ``--person-id``: Optional id of the bound person.
- ``--input INPUT``: Optional input JSON file that follows that :any:`VirtualPanelUpdateData`  schema. Can be used as alternative to providing the data via the above arguments. If not given, input will be read from stdin.

.. _cli-get-file-download-links:

get-file-download-links
~~~~~~~~~~~~~~~~~~~~~~~

Retrieve file download links for given analysis IDs.

**Usage:**

.. code-block:: bash

    varvis_connector get-file-download-links analysis-ids [analysis-ids ...]

**Command Options:**

- ``analysis-ids`` (required) (one or more values): One or more analysis IDs (integers).

For output formatting options see :ref:`output_options` below.

.. _cli-download-files:

download-files
~~~~~~~~~~~~~~

Downloads files for given analysis IDs.

**Usage:**

.. code-block:: bash

    varvis_connector download-files \
        [--output-dir OUTPUT_DIR] \
        [--create-folder-per-id [CREATE_FOLDER_PER_ID]] \
        [--file-pattern [FILE_PATTERN ...]] \
        [--overwrite] \
        [--no-progress] \
        [--parallel-downloads PARALLEL_DOWNLOADS] \
        analysis-ids [analysis-ids ...]

**Command Options:**

- ``analysis-ids`` (required) (one or more values): One or more analysis IDs (integers).
- ``--output-dir``: Optional output directory for downloaded files. Defaults to the current working directory.
- ``--create-folder-per-id``: If set, create a separate folder for each analysis ID using this folder name template. The template can contain the placeholder "%ID" which will be replaced by the analysis ID. If this placeholder is not given, the analysis ID will be simply appended. By default, no folders will be created and all files will be written to the directory specified by the "--output-dir" option.
- ``--file-pattern``: Optional file pattern(s) to filter the files to download. Pass glob-style patterns as arguments like ``'*.gz'`` and always use quotes to prevent shell expansion. Argument can be repeated.
- ``--overwrite``: Set this if existing files should be overwritten.
- ``--no-progress``: Set this if no progress bar should be shown during the download.
- ``--parallel-downloads``: Maximum number of parallel downloads. Defaults to 1 (no parallel downloads).

For output formatting options see :ref:`output_options` below.

.. _cli-request:

request
~~~~~~~

Perform an arbitrary authenticated request to a Varvis API endpoint.

**Usage:**

.. code-block:: bash

    varvis_connector request
        [--get | --post | --put | --head | --patch | --delete] \
        [--raw-input] \
        [--input INPUT] \
        endpoint

**Command Options:**

- ``endpoint`` (required): Varvis API endpoint to perform the request against. Note that some endpoints start with "api/", others don't. A slash at the beginning is not required.
- ``--get | --post | --put | --head | --patch | --delete``: Use the respective HTTP method (default is GET).
- ``--raw-input``: Send raw text input data instead of JSON.
- ``--input INPUT``: Optional input data in if sending data to an endpoint. Set to "-" in order to pass data from stdin. If not given, input will be read from stdin.

For output formatting options see :ref:`output_options` below.

.. _output_options:

Command output options
----------------------

If a command produces structured output, it will be stored as JSON. By default, the output will be written to stdout, but you can also specify an output file using the ``--output`` option:

.. code-block:: bash

    varvis_connector get-internal-person-id \
        --output /tmp/internal-person-id.json \
        200000000

.. code-block::

    [...]
    Writing output to file "/tmp/internal-person-id.json"
    [...]

If no output file is given, all log messages will be written to stderr while the generated JSON output goes to stdout. This allows for further processing, e.g., via ``jq``:

.. code-block:: bash

    # Suppress log messages by piping to /dev/null and format and colorize
    # JSON output by piping to `jq`
    varvis_connector get-internal-person-id P1-NA12878 2>/dev/null | jq -C

.. code-block:: json

    {
      "P1-NA12878": 7
    }

You can also control the output JSON indentation using the ``--output-indent`` option:

.. code-block:: bash

    varvis_connector get-internal-person-id \
        --output-indent 8 \
        200000000  OCI3-QK333-Zelllinie-dx-twist

.. code-block::

    {
            "200000000": 26,
            "OCI3-QK333-Zelllinie-dx-twist": 37
    }

Examples
--------

Here are some examples of how to use the CLI:

.. code-block:: bash

    # Get the internal person ID for a LIMS ID
    varvis_connector get-internal-person-id 200000000

    # Get the case report for a case ID and save it to a file
    varvis_connector get-case-report --output /tmp/case-report.json CASE123

    # Use with explicit API URL and credentials
    varvis_connector --api-url https://varvis.example.com/ \
        --username user --password pass \
        get-internal-person-id 200000000

    # Use with environment variables for API URL and credentials
    export VARVIS_URL=https://varvis.example.com/
    export VARVIS_USER=user
    export VARVIS_PASSWORD=pass
    varvis_connector get-internal-person-id 200000000

.. _real-world-applications:

Real-World Applications
-----------------------

This section demonstrates practical workflows combining the CLI with `jq <https://jqlang.org/>`_ (a tool for processing JSON data) for data analysis and filtering.

Some general hints
~~~~~~~~~~~~~~~~~~

All of these examples work by sending the standard output (stdout) of ``varvis_connector`` to ``jq`` using the pipe operator *|*, i.e. they follow this form::

    varvis_connector [global options] <command> [command options] | jq [jq options]

If you want to get rid of the log messages that ``varvis_connector`` produces and only see the JSON output, you can either send the standard error (stderr) stream to ``/dev/null`` or use the ``--loglevel off`` option, e.g.:

.. code-block:: bash

    # format and colorize the JSON output; send stderr to null
    varvis_connector get-virtual-panel-summaries 2>/dev/null | jq -C
    # same, but turn logging off instead of logging to stderr
    varvis_connector --loglevel off get-virtual-panel-summaries | jq -C

Instead of sending a request to the same API endpoint each time and piping the result to ``jq``, you can also write the JSON to a file and then work with that file directly with ``jq`` which saves time when working with endpoints that produce large JSON data:

.. code-block:: bash

    # write output to vp-summaries.json file first
    varvis_connector get-virtual-panel-summaries --output vp-summaries.json
    # now ingest the file via stdin to jq and format+colorize the output
    jq -C < vp-summaries.json

Analyzing panel usage
~~~~~~~~~~~~~~~~~~~~~

Filter active virtual panels that are not person-specific:

.. code-block:: bash

    varvis_connector get-virtual-panel-summaries | \
        jq -C '.[] | select(.active == true and .personId == null)'

List all active virtual panels sorted by usage count:

.. code-block:: bash

    varvis_connector get-virtual-panel-summaries | \
        jq -r '.[] | select(.active == true and .personId == null) | [.id, .name, .usageCount] | @tsv' | sort -t$'\t' -k3 -nr

Create a visual bar chart of the top 10 most used panels:

.. code-block:: bash

    varvis_connector get-virtual-panel-summaries | \
        jq -r '.[] | select(.active == true and .personId == null) | [.name, .usageCount] | @tsv' | sort -t$'\t' -k2,2nr | head -10 | awk -F'\t' 'BEGIN{max=0} {if($2>max) max=$2} {data[NR]=$0; counts[NR]=$2} END{for(i=1;i<=NR;i++){split(data[i],parts,"\t"); printf "%-40s %4d |", substr(parts[1],1,40), counts[i]; bars=int(counts[i]*50/max); for(j=0;j<bars;j++) printf "█"; printf "\n"}}'

Analyzing enrichment kit usage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get enrichment kit usage statistics:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | .enrichmentKits[]' | sort | uniq -c | sort -nr

Create a formatted table of enrichment kit usage counts:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | .enrichmentKits[]' | sort | uniq -c | sort -nr | \
        awk '{printf "%-30s %4d\n", $2, $1}'

Create a visual bar chart of enrichment kit usage:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | .enrichmentKits[]' | sort | uniq -c | sort -nr | \
        awk 'BEGIN{max=0} {if($1>max) max=$1} {data[NR]=$0; counts[NR]=$1; names[NR]=$2} END{for(i=1;i<=NR;i++){printf "%-30s %4d |", names[i], counts[i]; bars=int(counts[i]*50/max); for(j=0;j<bars;j++) printf "█"; printf "\n"}}'

Analyzing reported genes
~~~~~~~~~~~~~~~~~~~~~~~~

Get most frequently reported genes from variants:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | (.reportedSnvs[]?.gene // empty), (.reportedCnvs[]?.gene // empty)' | sort | uniq -c | sort -nr

Create formatted table of gene frequencies:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | (.reportedSnvs[]?.gene // empty), (.reportedCnvs[]?.gene // empty)' | sort | uniq -c | sort -nr | \
        awk '{printf "%-20s %4d\n", $2, $1}'

Create a visual bar chart of most reported genes:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | (.reportedSnvs[]?.gene // empty), (.reportedCnvs[]?.gene // empty)' | sort | uniq -c | sort -nr | head -10 | \
        awk 'BEGIN{max=0} {if($1>max) max=$1} {data[NR]=$0; counts[NR]=$1; names[NR]=$2} END{for(i=1;i<=NR;i++){printf "%-20s %4d |", names[i], counts[i]; bars=int(counts[i]*40/max); for(j=0;j<bars;j++) printf "█"; printf "\n"}}'

Analyzing clinical phenotypes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get most common clinical phenotypes:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | .clinicalInformation[]? // empty' | sed 's/^(+) //; s/^(-) //' | sort | uniq -c | sort -nr

Create formatted table of phenotype frequencies:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | .clinicalInformation[]? // empty' | sed 's/^(+) //; s/^(-) //' | sort | uniq -c | sort -nr | \
        awk '{$1=$1; printf "%-50s %4d\n", substr($0, index($0,$2)), $1}'

Create a visual bar chart of top phenotypes:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | .clinicalInformation[]? // empty' | sed 's/^(+) //; s/^(-) //' | sort | uniq -c | sort -nr | head -15 | \
        awk 'BEGIN{max=0} {if($1>max) max=$1} {$1=$1; data[NR]=$0; counts[NR]=$1; names[NR]=substr($0, index($0,$2))} END{for(i=1;i<=NR;i++){printf "%-40s %4d |", substr(names[i],1,40), counts[i]; bars=int(counts[i]*50/max); for(j=0;j<bars;j++) printf "█"; printf "\n"}}'

Analyzing patient demographics
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get sex distribution:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | .sex' | sort | uniq -c | sort -nr

Create formatted table of sex distribution:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | .sex' | sort | uniq -c | sort -nr | \
        awk '{printf "%-10s %4d\n", $2, $1}'

Calculate age statistics summary:

.. note:: The following commands requires that you have the GNU awk *(gawk)* variant of awk installed. The default awk variant *mawk* that comes with most Debian systems won't work.

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | select(.birthDate != null) | .birthDate' | \
        awk -F'-' '{age = 2025 - $1; ages[NR] = age; sum += age; if(age < min || min == "") min = age; if(age > max) max = age} END {n = NR; mean = sum/n; asort(ages); if(n%2==1) median = ages[(n+1)/2]; else median = (ages[n/2] + ages[n/2+1])/2; printf "Count: %d\nMean age: %.1f\nMedian age: %.1f\nMin age: %d\nMax age: %d\n", n, mean, median, min, max}'

Create a visual bar chart of age groups:

.. code-block:: bash

    varvis_connector request person-list | \
        jq -r '.[] | select(.birthDate != null) | .birthDate' | \
        awk -F'-' '{age = 2025 - $1; if(age < 18) group="Pediatric (<18)"; else if(age < 65) group="Adult (18-64)"; else group="Elderly (65+)"; print group}' | sort | uniq -c | sort -nr | \
        awk 'BEGIN{max=0} {if($1>max) max=$1} {data[NR]=$0; counts[NR]=$1; names[NR]=$2" "$3} END{for(i=1;i<=NR;i++){printf "%-20s %4d |", names[i], counts[i]; bars=int(counts[i]*50/max); for(j=0;j<bars;j++) printf "█"; printf "\n"}}'

Analyzing report turnaround times
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This workflow demonstrates how to analyze the time between report submission and approval across different dimensions. The analysis uses caching to avoid re-fetching data and includes statistical calculations and visualizations.

**Step 1: Collect recent approved reports data**

Get the most recent 1,000 approved reports and filter for those with approval timestamps:

.. code-block:: bash

    varvis_connector get-report-info-for-persons --output-indent 2 | \
        jq 'map(select(.timeApproved != null)) | sort_by(.timeApproved) | .[-1000:]' > recent-approved-reports.json

**Step 2: Fetch detailed case reports**

Create a caching directory and only fetch case reports that haven't been downloaded yet:

.. code-block:: bash

    mkdir -p case-reports
    jq -r '.[].limsId' recent-approved-reports.json | \
        while read id; do [ ! -f "case-reports/case-${id}.json" ] && echo "$id"; done | \
        xargs -P 4 -I {} sh -c 'varvis_connector get-case-report "{}" --output "case-reports/case-{}.json" 2>/dev/null'

**Step 3: Combine and process all case report data**

Process all cached case reports to extract turnaround time metrics:

.. code-block:: bash

    find case-reports -name "case-*.json" -exec cat {} \; | \
        jq -s 'map(to_entries[]) | map({limsId: .key, data: .value}) | map(select(.data.submitted != null and .data.approved != null)) | map({limsId, submitter: .data.submitter, submitted: .data.submitted, approver: .data.approver, approved: .data.approved, timeToApprovalHours: (((.data.approved | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601) - (.data.submitted | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601)) / 3600), submittedMonth: (.data.submitted | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601 | strftime("%Y-%m")), approvalMonth: (.data.approved | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601 | strftime("%Y-%m"))})' > analysis-data.json

**Overall turnaround time statistics:**

.. note:: The following commands requires that you have the GNU awk *(gawk)* variant of awk installed. The default awk variant *mawk* that comes with most Debian systems won't work.

.. code-block:: bash

    jq -r '.[] | .timeToApprovalHours' analysis-data.json | \
        awk '{sum+=$1; hours[NR]=$1; if($1<min || min=="") min=$1; if($1>max) max=$1} END{n=NR; mean=sum/n; asort(hours); median = (n%2==1) ? hours[(n+1)/2] : (hours[n/2] + hours[n/2+1])/2; printf "Count: %d\nMean: %.1f hours\nMedian: %.1f hours\nMin: %.1f hours\nMax: %.1f hours\n", n, mean, median, min, max}'

**Monthly turnaround time trends:**

.. code-block:: bash

    jq -r '.[] | [.submittedMonth, .timeToApprovalHours] | @tsv' analysis-data.json | \
        awk -F'\t' '{sum[$1]+=$2; count[$1]++} END{for(month in sum) printf "%s\t%.1f\n", month, sum[month]/count[month]}' | sort

**Visual chart of monthly average turnaround times:**

.. code-block:: bash

    jq -r '.[] | [.submittedMonth, .timeToApprovalHours] | @tsv' analysis-data.json | \
        awk -F'\t' '{sum[$1]+=$2; count[$1]++} END{for(month in sum) {avg=sum[month]/count[month]; data[month]=avg} for(month in data) {if(data[month]>max) max=data[month]} for(month in data) printf "%s %6.1f |", month, data[month]; bars=int(data[month]*50/max); for(j=0;j<bars;j++) printf "█"; printf "\n"}' | sort

**Approver performance analysis:**

.. code-block:: bash

    jq -r '.[] | [.approver, .timeToApprovalHours] | @tsv' analysis-data.json | \
        awk -F'\t' '{sum[$1]+=$2; count[$1]++} END{for(approver in sum) printf "%-20s %4d reports, avg: %6.1f hours\n", approver, count[approver], sum[approver]/count[approver]}' | sort -k3,3n

**Visual chart of approver average turnaround times:**

.. code-block:: bash

    jq -r '.[] | [.approver, .timeToApprovalHours] | @tsv' analysis-data.json | \
        awk -F'\t' '{sum[$1]+=$2; count[$1]++} END{for(approver in sum) {avg=sum[approver]/count[approver]; data[approver]=avg; counts[approver]=count[approver]} for(approver in data) {if(data[approver]>max) max=data[approver]} for(approver in data) {printf "%-15s %6.1f |", approver, data[approver]; bars=int(data[approver]*40/max); for(j=0;j<bars;j++) printf "█"; printf " (%d)\n", counts[approver]}}' | sort -k2,2n

**Submitter turnaround time patterns:**

.. code-block:: bash

    jq -r '.[] | [.submitter, .timeToApprovalHours] | @tsv' analysis-data.json | \
        awk -F'\t' '{sum[$1]+=$2; count[$1]++} END{for(submitter in sum) printf "%-20s %4d reports, avg: %6.1f hours\n", submitter, count[submitter], sum[submitter]/count[submitter]}' | sort -k5,5n

**Distribution of turnaround times by hour ranges:**

.. code-block:: bash

    jq -r '.[] | .timeToApprovalHours' analysis-data.json | \
        awk '{if($1<=24) range="0-24h"; else if($1<=48) range="24-48h"; else if($1<=72) range="48-72h"; else if($1<=168) range="72h-1w"; else range=">1week"; print range}' | sort | uniq -c | sort -k2 | \
        awk 'BEGIN{max=0} {if($1>max) max=$1} {data[NR]=$0; counts[NR]=$1; names[NR]=$2} END{for(i=1;i<=NR;i++){printf "%-10s %4d |", names[i], counts[i]; bars=int(counts[i]*50/max); for(j=0;j<bars;j++) printf "█"; printf "\n"}}'

**Reports with longest turnaround times:**

.. code-block:: bash

    jq -r '.[] | [.limsId, .submitter, .approver, .timeToApprovalHours] | @tsv' analysis-data.json | \
        sort -t$'\t' -k4,4nr | head -10 | \
        awk -F'\t' '{printf "%-15s %-15s -> %-15s %6.1f hours\n", $1, $2, $3, $4}'

Searching for genes and variants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These examples demonstrate how to search for specific genes and variants using the Varvis search endpoints. Gene searches return variant information, while variant searches return case/patient information for individuals carrying that specific variant.

**Basic gene search with all columns**

Search for all variants in a specific gene:

.. code-block:: bash

    varvis_connector request "search/griddata?gene=BRCA1" | \
        jq -r '
        "cDNA\tChr\tPos\tTranscript\tAAChange\tType\tGene\tFound\tHom\tRel\tSig",
        (.data[] |
         [.[0], .[1], .[2], .[3], .[4], .[5], .[6], .[7], .[8], .[9], .[10]] |
         map(if . == null then "-" else . end) |
         @tsv
        )'

**Filter variants with local significance**

Show only variants that have been assigned local clinical significance classifications:

.. code-block:: bash

    varvis_connector request "search/griddata?gene=BRCA1" | \
        jq -r '
        "cDNA\tChr\tPos\tTranscript\tAAChange\tType\tGene\tFound\tHom\tRel\tSig",
        (.data[] |
         select(.[10] != null and .[10] != "") |
         [.[0], .[1], .[2], .[3], .[4], .[5], .[6], .[7], .[8], .[9], .[10]] |
         map(if . == null then "-" else . end) |
         @tsv
        )'

**Basic gene statistics**

Generate summary statistics for all variants in a gene:

.. code-block:: bash

    varvis_connector request "search/griddata?gene=BRCA1" | \
        jq -r '
        "Total variants: \(.data | length)",
        "Total observations: \(.data | map(.[7]) | add)",
        "Average per variant: \((.data | map(.[7]) | add) / (.data | length) | . * 100 | round / 100)",
        "Found >1 time: \(.data | map(select(.[7] > 1)) | length)",
        "Marked relevant: \(.data | map(select(.[9] > 0)) | length)"
        '

**Variant type distribution**

Analyze the distribution and frequency of different variant types:

.. code-block:: bash

    varvis_connector request "search/griddata?gene=BRCA1" | \
        jq -r '
        "Type\tCount\tTotal_Found",
        (.data |
         group_by(.[5]) |
         map({type: .[0][5], count: length, total_found: (map(.[7]) | add)}) |
         sort_by(-.count) |
         .[] |
         [.type, .count, .total_found] |
         @tsv
        )'

**Local significance distribution**

Analyze the distribution of clinical significance classifications:

.. code-block:: bash

    varvis_connector request "search/griddata?gene=BRCA1" | \
        jq -r '
        "LocalSig\tCount\tTotal_Found",
        (.data |
         map(select(.[10] != null and .[10] != "")) |
         group_by(.[10]) |
         map({
           sig: .[0][10],
           count: length,
           total_found: (map(.[7]) | add)
         }) |
         sort_by(-.count) |
         .[] |
         [.sig, .count, .total_found] |
         @tsv
        )'

**Search for specific variants**

Search for cases containing a specific variant:

.. code-block:: bash

    varvis_connector request "search/griddata?gene=BRCA1&variant=NM_007294.4%3Ac.3018_3021del" | \
        jq -r '
        "PersonID\tGene\tAltAF\tQual\tReads\tCaseSig\tLocalSig",
        (.data[] |
         [.[0],
          (.[3] | if type == "array" then join(";") else . end),
          (.[7] | if type == "array" then .[0] else . end),
          .[8],
          (.[9] | if type == "array" then .[0] else . end),
          (.[15] | if type == "array" then join(";") else . end),
          .[16]] |
         map(if . == null then "-" else . end) |
         @tsv
        )'
