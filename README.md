# varvis® API Python package

![CI testing pipeline](https://github.com/LaborBerlin/varvis-connector/actions/workflows/tests.yaml/badge.svg)
![CI code quality
pipeline](https://github.com/LaborBerlin/varvis-connector/actions/workflows/codequality.yaml/badge.svg)
![Test coverage](https://github.com/LaborBerlin/varvis-connector/raw/refs/heads/badges/pr/pr-latest.svg)

Authors: Markus Konrad <markus.konrad@laborberlin.com>, Bernt Popp <bernt.popp@laborberlin.com>

## Summary

<p align="center">
<img
    alt="varvis logo"
    src="https://github.com/LaborBerlin/varvis-connector/raw/main/docs/source/_static/varvis_name.svg"
    style="width:25%; height:auto;">
</p>

The `varvis-connector` package provides a Python client and command-line interface (CLI) for the varvis® API. Retrieve
genomic data including SNV annotations, CNV target results, and CNV segments, process large SNV responses with low
memory use, and download analysis files safely in parallel. The package handles authentication and coordinated session
recovery for concurrent requests, with configurable timeouts, retries, and environment-based configuration.

## Features

- Typed Python client and CLI for genomic data retrieval, person records, and virtual panels
- Low-memory SNV iteration with optional temporary-file caching; the CLI uses caching for JSONL streaming so large
  responses do not need to be held in RAM
- Gene and coordinate filters that support scalar and array-valued SNV annotations
- Parallel HTTPS downloads with connection pooling, configurable retries with randomized delays, and separate
  download retry settings
- Atomic file downloads that preserve existing files on failure, clean up partial transfers, and reject unsafe
  filenames and conflicting destination paths
- Thread-safe authentication and coordinated re-login after session invalidation, with bounded shared recovery attempts
- Separate connection and read timeouts, environment-based configuration, and comprehensive error handling
- Memory-efficient CLI JSON serialization, with output files opened only when results are ready to be written

## Intended Use

This software is provided solely for research, educational, development, interoperability, and bioinformatics workflow
automation purposes.

This project is NOT intended by the authors to be used for:

- clinical diagnosis,
- in vitro diagnostic procedures,
- patient stratification,
- treatment selection,
- medical decision-making,
- or any other medical purpose as defined under applicable medical device or in vitro diagnostic regulations, including
  but not limited to Regulation (EU) 2017/746 (IVDR).

The software is not a certified in vitro diagnostic medical device and has not undergone clinical performance studies,
regulatory assessment, or conformity assessment procedures required for software intended for in vitro diagnostic use.

Users are solely responsible for ensuring compliance with all applicable laws, regulations, institutional policies,
and validation requirements in their jurisdiction and use case.

## License

This project is licensed under the GNU General Public License v3.0 (GPLv3).
See the LICENSE file for details.

## Documentation

The full documentation for this project is available at
[laborberlin.github.io/varvis-connector/](https://laborberlin.github.io/varvis-connector/)

It covers:

- Requirements and installation
- Configuration and environment variables
- Usage guide for the CLI and the Python package
- Python package API documentation
- Development guide
- Changelog

## Disclaimer

The varvis® logo is a registered trademark of Limbus Medical Technologies GmbH and is used in this project with
permission. This project is independent and is not affiliated with, endorsed by, or officially supported by Limbus
Medical Technologies GmbH.
