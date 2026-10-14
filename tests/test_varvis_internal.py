"""
Tests for internal VarvisClient methods.

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

import logging
from unittest import mock

import pytest
import requests

from varvis_connector import VarvisClient
from varvis_connector.errors import VarvisError, VarvisTimeoutError, VarvisTransportError
from varvis_connector._log import default_logger

from ._common import (
    MOCK_URL,
    varvis_mockapi_with_login as varvis_mockapi_with_login,
)  # "as ..." prevents removal of fixture as "unused" by ruff linter


@pytest.fixture
def varvis_with_dbg_log():
    v = VarvisClient(MOCK_URL, "mockuser", "mockpw", logger=default_logger(logging.DEBUG))
    assert v.login()
    return v


def test_send_request_ok(varvis_mockapi_with_login, varvis_with_dbg_log):
    test_json = {"message": "foo"}
    varvis_mockapi_with_login.get(MOCK_URL + "api/test", json=test_json)

    resp = varvis_with_dbg_log._send_request("GET", "test")
    assert resp.ok
    assert resp.json() == test_json


@pytest.mark.parametrize(
    "exception, error_class, failure_kind, backoff_max_tries, backoff_factor_seconds",
    [
        (requests.ConnectionError, VarvisTransportError, "connection", 1, 0.1),
        (requests.ConnectionError, VarvisTransportError, "connection", 2, 0.1),
        (requests.ConnectionError, VarvisTransportError, "connection", 5, 0),
        (requests.Timeout, VarvisTimeoutError, "timeout", 1, 0.1),
        (requests.Timeout, VarvisTimeoutError, "timeout", 2, 0.1),
        (requests.Timeout, VarvisTimeoutError, "timeout", 5, 0),
        (requests.ConnectTimeout, VarvisTimeoutError, "connect_timeout", 2, 0),
        (requests.ReadTimeout, VarvisTimeoutError, "read_timeout", 2, 0),
    ],
)
def test_send_request_conn_or_timeout_error_retry_failure(
    varvis_mockapi_with_login,
    varvis_with_dbg_log,
    exception,
    error_class,
    failure_kind,
    backoff_max_tries,
    backoff_factor_seconds,
):
    varvis_mockapi_with_login.get(MOCK_URL + "api/test", exc=exception)

    varvis_with_dbg_log.backoff_max_tries = backoff_max_tries
    varvis_with_dbg_log.backoff_factor_seconds = backoff_factor_seconds

    with pytest.raises(error_class) as exc_info:
        varvis_with_dbg_log._send_request("GET", "test")

    # retain the final transport failure and actual request count
    assert exc_info.value.failure_kind == failure_kind
    assert exc_info.value.attempts == backoff_max_tries
    assert isinstance(exc_info.value.__cause__, exception)


def test_send_request_without_retries_preserves_transport_cause(varvis_mockapi_with_login, varvis_with_dbg_log):
    """Do not retry or lose a transport failure when retries are disabled."""
    # make the authenticated request fail immediately
    transport_error = requests.ReadTimeout("read timed out")
    varvis_with_dbg_log._session.request = mock.Mock(side_effect=transport_error)

    with pytest.raises(VarvisTimeoutError) as exc_info:
        varvis_with_dbg_log._send_request("GET", "test", allow_retries=False)

    # expose bounded failure metadata and the original exception
    assert exc_info.value.failure_kind == "read_timeout"
    assert exc_info.value.attempts == 1
    assert exc_info.value.__cause__ is transport_error
    varvis_with_dbg_log._session.request.assert_called_once()


def test_send_request_accepts_legacy_timeout(varvis_mockapi_with_login, varvis_with_dbg_log):
    """Legacy 'timeout' (not phase-specific) is passed on to requests."""
    # return a successful response while recording the request arguments
    response = mock.Mock(spec=requests.Response)
    response.status_code = 200
    varvis_with_dbg_log._session.request = mock.Mock(return_value=response)
    varvis_with_dbg_log.connection_timeout = 123.4

    assert varvis_with_dbg_log._send_request("GET", "test") is response

    # use the legacy timeout scalar
    assert varvis_with_dbg_log._session.request.call_args.kwargs["timeout"] == 123.4


def test_send_request_forwards_phase_specific_timeouts(varvis_mockapi_with_login, varvis_with_dbg_log):
    """Forward independently configured connection and read timeouts to Requests."""
    # return a successful response while recording the request arguments
    response = mock.Mock(spec=requests.Response)
    response.status_code = 200
    varvis_with_dbg_log._session.request = mock.Mock(return_value=response)
    varvis_with_dbg_log.connect_timeout = 2.5
    varvis_with_dbg_log.read_timeout = 15.0

    assert varvis_with_dbg_log._send_request("GET", "test") is response

    # use the configured timeout tuple for the request phases
    assert varvis_with_dbg_log._session.request.call_args.kwargs["timeout"] == (2.5, 15.0)


@pytest.mark.parametrize(
    "exception",
    [
        requests.ConnectionError,
        requests.Timeout,
    ],
)
def test_send_request_retry_success(varvis_mockapi_with_login, varvis_with_dbg_log, exception):
    # Set up the client to retry
    varvis_with_dbg_log.backoff_max_tries = 3
    varvis_with_dbg_log.backoff_factor_seconds = 0

    # Create a counter to track request attempts
    request_count = {"count": 0}

    # Define success response
    test_json = {"message": "success"}

    # Create a callback function that fails on first attempt
    def response_callback(request, context):
        request_count["count"] += 1

        if request_count["count"] == 1:
            # First request - raise an exception
            raise exception("connection error or timeout")
        else:
            # Subsequent requests - return successful response
            return test_json

    # Register the mock endpoint with the callback
    varvis_mockapi_with_login.get(MOCK_URL + "api/test", json=response_callback)

    # Request should fail initially but succeed on retry
    resp = varvis_with_dbg_log._send_request("GET", "test")
    assert resp.ok
    assert resp.json() == test_json
    assert request_count["count"] == 2  # Verify that retry happened


@pytest.mark.parametrize("n_failed_attempts", [1, 2, 3, 99])
def test_send_request_handles_forced_logout(varvis_mockapi_with_login, varvis_with_dbg_log, n_failed_attempts):
    """Test that _send_request method correctly handles a forced logout (302 redirect to base URL)
    and successfully retries with re-login."""
    # Set up the client to retry
    varvis_with_dbg_log.backoff_max_tries = 5
    varvis_with_dbg_log.backoff_factor_seconds = 0

    # Create counters to track request attempts
    request_counter = {"count": 0}
    login_counter = {"count": 1}  # Start at 1 because of initial login in fixture

    # Define success response
    test_json = {"message": "success"}

    # Define test URL paths
    test_url = MOCK_URL + "api/test"
    login_url = MOCK_URL + "login"

    # Mock the test endpoint to first redirect (simulating logout), then succeed
    def redirect_endpoint_callback(request, context):
        request_counter["count"] += 1

        if request_counter["count"] == 1:
            # Simulate a forced logout with 302 redirect to base URL
            context.status_code = 302
            context.headers["Location"] = MOCK_URL  # Redirect to base URL indicates forced logout
            return ""
        else:
            # Subsequent requests - return successful response
            return test_json

    # Mock the login endpoint to respond with new CSRF token for re-login
    def login_endpoint_callback(request, context):
        login_counter["count"] += 1

        if login_counter["count"] > n_failed_attempts:
            # Set CSRF token in response headers
            context.headers["X-CSRF-TOKEN"] = f"mock-csrf-token-{login_counter['count']}"
            context.cookies["session"] = f"mock-session-{login_counter['count']}"

        # Return login success response
        return ""

    # Register the mock endpoint
    varvis_mockapi_with_login.get(test_url, json=redirect_endpoint_callback)
    varvis_mockapi_with_login.post(login_url, json=login_endpoint_callback)

    if n_failed_attempts < varvis_with_dbg_log.backoff_max_tries:
        # Request should initially get a 302 redirect, then trigger re-login, and finally succeed
        resp = varvis_with_dbg_log._send_request("GET", "test")

        # Verify the results
        assert resp.ok
        assert resp.json() == test_json
        assert login_counter["count"] == n_failed_attempts + 1
    else:
        with pytest.raises(
            VarvisError,
            match=f"Failed to send request to Varvis API after {varvis_with_dbg_log.backoff_max_tries} attempts",
        ):
            varvis_with_dbg_log._send_request("GET", "test")
