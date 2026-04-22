"""
varvis_connector CLI entry point module

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
