"""
varvis_connector CLI entry point module

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

import os

from ._cli import VarvisCLI


def main() -> VarvisCLI | None:
    cli = VarvisCLI()
    cli.run()

    if int(os.getenv("TEST_RETURN_CLI", "0")):
        return cli
    return None


if __name__ == "__main__":
    main()
