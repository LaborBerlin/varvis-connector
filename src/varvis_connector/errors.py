"""
varvis_connector custom error classes module

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""


class VarvisError(Exception):
    """Base class for all Varvis-API-related errors."""

    pass


class VarvisTransportError(VarvisError):
    """Raised when a request cannot reach the Varvis API."""

    def __init__(self, failure_kind: str, attempts: int) -> None:
        """Initialize an error with the transport failure kind and attempt count."""
        self.failure_kind = failure_kind
        self.attempts = attempts
        super().__init__(f"Varvis API request failed after {attempts} attempts ({failure_kind}).")


class VarvisTimeoutError(VarvisTransportError):
    """Raised when a request to the Varvis API times out."""

    def __init__(self, failure_kind: str, attempts: int) -> None:
        """Initialize an error with the timeout kind and attempt count."""
        super().__init__(failure_kind, attempts)
