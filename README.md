# varvis® API Python package

![CI testing pipeline](https://github.com/LaborBerlin/varvis-connector/actions/workflows/tests.yaml/badge.svg)
![CI code quality
pipeline](https://github.com/LaborBerlin/varvis-connector/actions/workflows/codequality.yaml/badge.svg)
![Test coverage](https://github.com/LaborBerlin/varvis-connector/raw/refs/heads/badges/pr/pr-latest.svg)

Authors: Markus Konrad <markus.konrad@laborberlin.com>, Bernt Popp <bernt.popp@laborberlin.com>

## Summary

<p align="center">
<img alt="varvis logo" src="docs/source/_static/varvis_name.svg" style="width:25%; height:auto;">
</p>

The `varvis-connector` package provides a Python interface for the varvis® API. It includes both a command-line interface
(CLI) and a Python package with a client implementation. The package handles authentication, session management, and
provides methods to retrieve various types of genomic data including SNV annotations, CNV target results, and CNV
segments. It supports environment-based configuration and includes comprehensive error handling.

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
