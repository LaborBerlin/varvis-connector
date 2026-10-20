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
import threading
from concurrent.futures import Future, ThreadPoolExecutor
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
def varvis_with_dbg_log(varvis_mockapi_with_login):
    """Create a logged-in debug client after its HTTP mocks are installed."""
    # authenticate against the endpoints provided by the prerequisite fixture
    v = VarvisClient(MOCK_URL, "mockuser", "mockpw", logger=default_logger(logging.DEBUG))
    assert v.login()
    return v


class _ObservedRLock:
    """Expose acquisition attempts while retaining real reentrant locking."""

    def __init__(self):
        """Create an independent lock and an acquisition notification."""
        self.lock = threading.RLock()
        self.attempted = threading.Event()

    def __enter__(self):
        """Notify the test before waiting for the underlying lock."""
        # signal before acquisition so the test can detect a blocked worker
        self.attempted.set()
        self.lock.acquire()

    def __exit__(self, *_exc):
        """Release the underlying lock after the protected operation."""
        self.lock.release()


def test_session_locks_are_independent():
    """Give separate clients independent session locks."""
    # avoid serializing authentication across unrelated clients
    first = VarvisClient(MOCK_URL, "first", "password")
    second = VarvisClient(MOCK_URL, "second", "password")
    assert first._session_lock is not second._session_lock


@pytest.mark.parametrize("peer_operation", ["login", "request", "logged_in", "reset"])
def test_session_operations_wait_for_login(varvis_mockapi_with_login, monkeypatch, peer_operation):
    """Wait for authentication before reading, using, or resetting session state."""
    # pause the initial login while its session is still unauthenticated
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    lock = _ObservedRLock()
    monkeypatch.setattr(client, "_session_lock", lock)
    login_started = threading.Event()
    finish_login = threading.Event()
    original_head = requests.Session.head

    def paused_head(session, *args, **kwargs):
        """Hold authentication open until the peer attempts to acquire its lock."""
        # login already holds the session lock but has not received cookies or a CSRF token
        login_started.set()
        assert finish_login.wait(timeout=5)
        return original_head(session, *args, **kwargs)

    monkeypatch.setattr(requests.Session, "head", paused_head)
    varvis_mockapi_with_login.get(MOCK_URL + "api/test", json={"message": "success"})

    # the peer is a second worker using the same VarvisClient instance
    # prove the peer reaches the lock and cannot observe an incomplete login
    with ThreadPoolExecutor(max_workers=2) as executor:
        login = executor.submit(client.login)
        try:
            assert login_started.wait(timeout=5)
            # discard notifications from the login thread before starting its peer
            lock.attempted.clear()
            if peer_operation == "login":
                peer = executor.submit(client.login)
            elif peer_operation == "request":
                peer = executor.submit(client._send_request, "GET", "test")
            elif peer_operation == "logged_in":
                # evaluate the property inside the worker rather than in the submitting thread
                peer = executor.submit(getattr, client, "logged_in")
            else:
                peer = executor.submit(client._reset_state_on_logout)
            # establish that the peer is waiting on the lock without relying on a sleep
            assert lock.attempted.wait(timeout=5)
            assert not peer.done()
            # the paused HEAD and the blocked peer must not have reached the transport
            assert not varvis_mockapi_with_login.request_history
        finally:
            # unblock login even when an assertion fails so executor cleanup can finish
            finish_login.set()
        assert login.result(timeout=5) is True
        result = peer.result(timeout=5)

    # authenticate exactly once and expose only the completed session to peers
    history = varvis_mockapi_with_login.request_history
    assert sum(request.method == "HEAD" for request in history) == 1
    assert sum(request.url == MOCK_URL + "login" for request in history) == 1
    if peer_operation == "request":
        # the waiting request must use the authenticated session's CSRF header
        assert isinstance(result, requests.Response)
        assert result.json() == {"message": "success"}
        assert history[-1].headers["X-CSRF-TOKEN"] == "mock_csrf_post_login"
    elif peer_operation == "reset":
        # resetting after login must clear both pieces of authentication state
        assert result is None
        assert client._session is None
        assert not client.logged_in
    else:
        # both the second login and the status read must see completed authentication
        assert result is True


def test_concurrent_forced_logouts_share_relogin(varvis_mockapi_with_login, varvis_with_dbg_log, monkeypatch):
    """Recover concurrent forced logouts through one replacement session."""
    # force every worker to send its first request through the same old session
    client = varvis_with_dbg_log
    client.backoff_factor_seconds = 0
    workers = 4
    requests_started = threading.Barrier(workers)  # worker threads wait until all reached requests_started.wait()
    old_session = client._session

    def forced_logout(*_args, **_kwargs):
        """Return redirects only after all old-session requests are in flight."""
        # prevent recovery from starting before every worker has captured the old session
        requests_started.wait(timeout=5)
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = MOCK_URL
        return response

    # patch only the old session so replacement sessions use the successful mock endpoint
    old_request = mock.Mock(side_effect=forced_logout)
    monkeypatch.setattr(old_session, "request", old_request)
    varvis_mockapi_with_login.get(MOCK_URL + "api/test", json={"message": "success"})

    # allow request I/O to overlap and collect all worker exceptions in the main thread
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(client._send_request, "GET", "test") for _ in range(workers)]
        responses = [future.result(timeout=5) for future in futures]

    # reuse one authenticated replacement without discarding it for late redirects
    assert [response.json() for response in responses] == [{"message": "success"}] * workers
    assert old_request.call_count == workers
    assert client._session is not old_session
    assert client.logged_in
    # include the fixture's initial login when counting the single reauthentication
    history = varvis_mockapi_with_login.request_history
    assert sum(request.method == "HEAD" for request in history) == 2
    assert sum(request.url == MOCK_URL + "login" for request in history) == 2
    assert sum(request.url == MOCK_URL + "api/test" for request in history) == workers


@pytest.mark.parametrize("max_tries", [2, 3])
@pytest.mark.parametrize("login_failure", ["rejected", "connection", "unexpected"])
def test_concurrent_forced_logouts_exhaust_failed_relogin(
    varvis_mockapi_with_login, varvis_with_dbg_log, monkeypatch, max_tries, login_failure
):
    """Share a single failed recovery budget and outcome across all request workers."""
    # let all workers use the authenticated session before any redirect invalidates it
    client = varvis_with_dbg_log
    client.backoff_factor_seconds = 0
    client.backoff_max_tries = max_tries
    workers = 4
    requests_started = threading.Barrier(workers)
    old_session = client._session

    def forced_logout(*_args, **_kwargs):
        """Return a forced logout after every worker has an old-session request in flight."""
        # prevent a fast worker from clearing authentication before the others send requests
        requests_started.wait(timeout=5)
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = MOCK_URL
        return response

    # reject credentials or raise an error on every re-login attempt
    old_request = mock.Mock(side_effect=forced_logout)
    monkeypatch.setattr(old_session, "request", old_request)
    if login_failure == "rejected":
        varvis_mockapi_with_login.post(MOCK_URL + "login", headers={})
    elif login_failure == "connection":
        varvis_mockapi_with_login.post(MOCK_URL + "login", exc=requests.ConnectionError("login unavailable"))
    else:
        # programming errors must also release workers waiting for the recovery result
        varvis_mockapi_with_login.post(MOCK_URL + "login", exc=RuntimeError("unexpected login failure"))

    # require each worker to finish with the expected retry error rather than crash or hang
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(client._send_request, "GET", "test") for _ in range(workers)]
        failures = []
        for future in futures:
            if login_failure == "unexpected":
                error = RuntimeError
                message = "^unexpected login failure$"
            else:
                error = VarvisError
                message = f"^Failed to reauthenticate with Varvis API after {max_tries} attempts$"
            with pytest.raises(error, match=message) as exc_info:
                future.result(timeout=5)
            failures.append(exc_info.value)

    # every worker must receive the recovery owner's failure without starting another cycle
    assert all(failure is failures[0] for failure in failures)
    if login_failure == "connection":
        # login retains the typed transport error and its underlying requests exception
        transport_error = failures[0].__cause__
        assert isinstance(transport_error, VarvisTransportError)
        assert isinstance(transport_error.__cause__, requests.ConnectionError)

    # failed authentication must leave no partially initialized session or CSRF marker
    assert old_request.call_count == workers
    assert client._session is None
    assert client._loggedin_csrf is None
    assert not client.logged_in

    # count one shared login budget plus the fixture's initial successful login
    history = varvis_mockapi_with_login.request_history
    expected_logins = 1 + (1 if login_failure == "unexpected" else max_tries)
    assert sum(request.method == "HEAD" for request in history) == expected_logins
    assert sum(request.url == MOCK_URL + "login" for request in history) == expected_logins
    # no API request may be retried through an unauthenticated replacement session
    assert not any(request.url == MOCK_URL + "api/test" for request in history)

    # a later API request may start a fresh recovery cycle after the earlier group has failed
    varvis_mockapi_with_login.post(MOCK_URL + "login", headers={"X-CSRF-TOKEN": "recovered"})
    varvis_mockapi_with_login.get(MOCK_URL + "api/test", json={"message": "recovered"})
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(client._send_request, "GET", "test").result(timeout=5).json() == {"message": "recovered"}
    assert client.logged_in
    assert sum(request.url == MOCK_URL + "login" for request in varvis_mockapi_with_login.request_history) == (
        expected_logins + 1
    )


@pytest.mark.parametrize("recovery_succeeds", [True, False])
@pytest.mark.parametrize("join_phase", ["backoff", "login"])
def test_requests_join_active_recovery(
    varvis_mockapi_with_login, varvis_with_dbg_log, monkeypatch, recovery_succeeds, join_phase
):
    """Share recovery with requests arriving during backoff or the final login attempt."""
    # pause the recovery owner while two additional requests join its existing outcome
    client = varvis_with_dbg_log
    client.backoff_factor_seconds = 0
    client.backoff_max_tries = 3
    recovery_paused = threading.Event()
    finish_recovery = threading.Event()
    waiters_ready = threading.Barrier(3)
    recovery = client._session_state.recovery
    original_result = Future.result

    def paused_backoff(_seconds):
        """Keep recovery pending until new requests are waiting for its outcome."""
        if join_phase == "backoff":
            recovery_paused.set()
            assert finish_recovery.wait(timeout=5)

    def paused_login(_request, context):
        """Hold the final login response open while new requests join recovery."""
        # the login owner holds the authentication lock while waiting for this response
        recovery_paused.set()
        assert finish_recovery.wait(timeout=5)
        if recovery_succeeds:
            context.headers["X-CSRF-TOKEN"] = "recovered"
        return ""

    def observed_result(future, *args, **kwargs):
        """Notify the main thread when a worker joins the shared recovery future."""
        if future is recovery:
            # only recovery waiters participate, not futures returned by the thread pool
            waiters_ready.wait(timeout=5)
        return original_result(future, *args, **kwargs)

    monkeypatch.setattr("varvis_connector._varvis_client.time.sleep", paused_backoff)
    monkeypatch.setattr(Future, "result", observed_result)
    login_responses: list[dict[str, object]] = [{"headers": {}}]
    if join_phase == "login":
        # use the full budget so workers joining the final attempt cannot start another budget
        login_responses.extend([{"headers": {}}, {"text": paused_login}])
    elif recovery_succeeds:
        login_responses.append({"headers": {"X-CSRF-TOKEN": "recovered"}})
    varvis_mockapi_with_login.post(MOCK_URL + "login", login_responses)
    varvis_mockapi_with_login.get(
        MOCK_URL + "api/test",
        [{"status_code": 302, "headers": {"Location": MOCK_URL}}, {"json": {"message": "success"}}],
    )

    # let requests enter while authentication is cleared but shared recovery is still active
    with ThreadPoolExecutor(max_workers=3) as executor:
        owner = executor.submit(client._send_request, "GET", "test")
        try:
            assert recovery_paused.wait(timeout=5)
            waiters = [executor.submit(client._send_request, "GET", "test") for _ in range(2)]
            waiters_ready.wait(timeout=5)
            assert not any(future.done() for future in [owner, *waiters])
        finally:
            # always release the owner so an assertion failure cannot strand the workers
            finish_recovery.set()

        for future in [owner, *waiters]:
            if recovery_succeeds:
                assert future.result(timeout=5).json() == {"message": "success"}
            else:
                with pytest.raises(VarvisError, match="Failed to reauthenticate with Varvis API after 3 attempts"):
                    future.result(timeout=5)

    # joining workers must add no login attempts of their own
    expected_logins = 3 if recovery_succeeds and join_phase == "backoff" else 4
    history = varvis_mockapi_with_login.request_history
    assert sum(request.url == MOCK_URL + "login" for request in history) == expected_logins
    assert client.logged_in is recovery_succeeds


@pytest.mark.parametrize("login_again", [False, True])
@pytest.mark.parametrize("login_during_backoff", [False, True])
def test_logout_cancels_active_recovery(
    varvis_mockapi_with_login, varvis_with_dbg_log, monkeypatch, login_again, login_during_backoff
):
    """Wake recovery waiters and prevent a paused owner from logging in after logout."""
    # pause recovery backoff after a rejected login and observe a worker joining its future
    client = varvis_with_dbg_log
    client.backoff_max_tries = 3
    recovery = client._session_state.recovery
    backoff_started = threading.Event()
    release_backoff = threading.Event()
    waiter_started = threading.Event()
    original_result = Future.result

    def paused_backoff(_seconds):
        """Keep the recovery owner asleep while logout wakes its waiting peer."""
        backoff_started.set()
        assert release_backoff.wait(timeout=5)

    def observed_result(future, *args, **kwargs):
        """Signal when a worker starts waiting for the recovery outcome."""
        if future is recovery:
            waiter_started.set()
        return original_result(future, *args, **kwargs)

    monkeypatch.setattr("varvis_connector._varvis_client.time.sleep", paused_backoff)
    monkeypatch.setattr(Future, "result", observed_result)
    varvis_mockapi_with_login.post(MOCK_URL + "login", headers={})
    varvis_mockapi_with_login.get(MOCK_URL + "api/test", status_code=302, headers={"Location": MOCK_URL})

    # cancel the shared sequence without waiting for its sleeping owner
    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(client._send_request, "GET", "test")
        try:
            assert backoff_started.wait(timeout=5)
            waiter = executor.submit(client._send_request, "GET", "test")
            assert waiter_started.wait(timeout=5)
            if login_during_backoff:
                # retain the sleeping owner's waiters even when an explicit login replaces its state
                varvis_mockapi_with_login.post(MOCK_URL + "login", headers={"X-CSRF-TOKEN": "during-backoff"})
                assert client.login()
            client.logout()
            assert not client.logged_in
            assert client._session_state is None
            with pytest.raises(VarvisError, match="cancelled by logout") as waiter_failure:
                waiter.result(timeout=5)
            assert not owner.done()

            # an explicit new login must not revive workers from the cancelled sequence
            if login_again:
                varvis_mockapi_with_login.post(MOCK_URL + "login", headers={"X-CSRF-TOKEN": "new-login"})
                assert client.login()
            replacement = client._session
        finally:
            release_backoff.set()

        with pytest.raises(VarvisError, match="cancelled by logout") as owner_failure:
            owner.result(timeout=5)
        assert owner_failure.value is waiter_failure.value

    # the cancelled owner must neither retry login nor clear newer authentication
    assert client._session is replacement
    assert client.logged_in is login_again
    assert not client._active_recoveries
    history = varvis_mockapi_with_login.request_history
    assert sum(request.url == MOCK_URL + "login" for request in history) == (
        2 + int(login_again) + int(login_during_backoff)
    )
    assert sum(request.url == MOCK_URL + "api/test" for request in history) == 1
    assert sum(request.url == MOCK_URL + "logout" for request in history) == int(login_during_backoff)


def test_logout_waits_for_recovery_login(varvis_mockapi_with_login, varvis_with_dbg_log, monkeypatch):
    """Finish an in-progress recovery login before logging its replacement session out."""
    # pause login I/O under an observed lock so logout must wait for authentication
    client = varvis_with_dbg_log
    state = client._session_state
    client._loggedin_csrf = None
    lock = _ObservedRLock()
    monkeypatch.setattr(client, "_session_lock", lock)
    login_started = threading.Event()
    release_login = threading.Event()
    original_head = requests.Session.head

    def paused_head(session, *args, **kwargs):
        """Keep the recovery login open until logout attempts to acquire the lock."""
        login_started.set()
        assert release_login.wait(timeout=5)
        return original_head(session, *args, **kwargs)

    monkeypatch.setattr(requests.Session, "head", paused_head)

    # release login only after proving logout cannot pass its authentication lock
    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(client._recover_session, state)
        try:
            assert login_started.wait(timeout=5)
            lock.attempted.clear()
            logout = executor.submit(client.logout)
            assert lock.attempted.wait(timeout=5)
            assert not logout.done()
        finally:
            release_login.set()
        replacement = owner.result(timeout=5)
        assert logout.result(timeout=5) is None

    # invalidate the completed recovery chain as well as its replacement session
    assert not client.logged_in
    assert client._session_state is None
    with pytest.raises(VarvisError, match="cancelled by logout"):
        client._recover_session(state)
    history = varvis_mockapi_with_login.request_history
    assert sum(request.url == MOCK_URL + "login" for request in history) == 2
    assert sum(request.url == MOCK_URL + "logout" for request in history) == 1
    assert replacement.session is not state.session


@pytest.mark.parametrize("login_again", [False, True])
@pytest.mark.parametrize("failure", ["redirect", "connection"])
def test_logout_stops_delayed_worker(varvis_mockapi_with_login, varvis_with_dbg_log, monkeypatch, login_again, failure):
    """Prevent delayed responses from restarting recovery or retries after explicit logout."""
    # hold an old session's request open while the controlling thread logs out
    client = varvis_with_dbg_log
    client.backoff_factor_seconds = 0
    request_started = threading.Event()
    release_response = threading.Event()
    old_session = client._session
    original_request = old_session.request

    def delayed_request(method, url, **kwargs):
        """Delay an API failure while letting the remote logout complete normally."""
        if url == MOCK_URL + "api/test":
            request_started.set()
            assert release_response.wait(timeout=5)
            if failure == "connection":
                raise requests.ConnectionError("delayed connection failure")
            response = requests.Response()
            response.status_code = 302
            response.headers["Location"] = MOCK_URL
            return response
        return original_request(method, url, **kwargs)

    monkeypatch.setattr(old_session, "request", delayed_request)
    varvis_mockapi_with_login.get(MOCK_URL + "api/test", json={"message": "new-session"})

    # allow a new explicit login before the old failure arrives
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker = executor.submit(client._send_request, "GET", "test")
        try:
            assert request_started.wait(timeout=5)
            client.logout()
            assert not client.logged_in
            if login_again:
                assert client.login()
            replacement = client._session
        finally:
            release_response.set()
        with pytest.raises(VarvisError, match="cancelled by logout"):
            worker.result(timeout=5)

    # preserve a later login and never send a retry through the replacement
    assert client._session is replacement
    assert client.logged_in is login_again
    history = varvis_mockapi_with_login.request_history
    assert sum(request.url == MOCK_URL + "logout" for request in history) == 1
    assert sum(request.url == MOCK_URL + "login" for request in history) == (2 if login_again else 1)
    assert not any(request.url == MOCK_URL + "api/test" for request in history)
    if login_again:
        assert client._send_request("GET", "test").json() == {"message": "new-session"}


@pytest.mark.parametrize("first_recovery_fails", [False, True])
def test_delayed_forced_logout_preserves_new_session(
    varvis_mockapi_with_login, varvis_with_dbg_log, monkeypatch, first_recovery_fails
):
    """Preserve a newer session while late responses retain their original recovery outcome."""
    # keep one old-session response pending while the other request recovers
    client = varvis_with_dbg_log
    client.backoff_factor_seconds = 0
    client.backoff_max_tries = 2
    requests_started = threading.Barrier(2)
    release_delayed_response = threading.Event()
    old_session = client._session

    def forced_logout(_method, url, **_kwargs):
        """Delay one redirect until the replacement session has served a request."""
        # ensure both requests use the old session before either redirect can trigger recovery
        requests_started.wait(timeout=5)
        if url.endswith("delayed"):
            # let the fast request finish its retry before returning this stale redirect
            assert release_delayed_response.wait(timeout=5)
        response = requests.Response()
        response.status_code = 302
        response.headers["Location"] = MOCK_URL
        return response

    monkeypatch.setattr(old_session, "request", forced_logout)
    varvis_mockapi_with_login.get(MOCK_URL + "api/fast", json={"message": "fast"})
    varvis_mockapi_with_login.get(MOCK_URL + "api/delayed", json={"message": "delayed"})
    if first_recovery_fails:
        varvis_mockapi_with_login.post(MOCK_URL + "login", headers={})

    # complete reauthentication before permitting the stale redirect to arrive
    with ThreadPoolExecutor(max_workers=2) as executor:
        fast = executor.submit(client._send_request, "GET", "fast")
        delayed = executor.submit(client._send_request, "GET", "delayed")
        try:
            if first_recovery_fails:
                # start a successful new cycle while a response from the failed group is pending
                with pytest.raises(VarvisError, match="Failed to reauthenticate") as failed_recovery:
                    fast.result(timeout=5)
                varvis_mockapi_with_login.post(MOCK_URL + "login", headers={"X-CSRF-TOKEN": "recovered"})
                assert client._send_request("GET", "fast").json() == {"message": "fast"}
            else:
                assert fast.result(timeout=5).json() == {"message": "fast"}
            # remember the authenticated replacement before releasing the old response
            replacement = client._session
            assert replacement is not old_session
            assert client.logged_in
        finally:
            # release the delayed worker on assertion failures as well as on success
            release_delayed_response.set()
        if first_recovery_fails:
            # the old request retains its group's failure even after a newer cycle succeeds
            with pytest.raises(VarvisError, match="Failed to reauthenticate") as delayed_failure:
                delayed.result(timeout=5)
            assert delayed_failure.value is failed_recovery.value
        else:
            # the delayed request must retry successfully through the existing replacement
            assert delayed.result(timeout=5).json() == {"message": "delayed"}

    # preserve the successful replacement without starting another cycle for the stale response
    assert client._session is replacement
    assert client.logged_in
    history = varvis_mockapi_with_login.request_history
    assert sum(request.url == MOCK_URL + "login" for request in history) == (4 if first_recovery_fails else 2)


@pytest.mark.parametrize("second_recovery_succeeds", [True, False])
def test_delayed_worker_follows_successive_recoveries(
    varvis_mockapi_with_login, varvis_with_dbg_log, monkeypatch, second_recovery_succeeds
):
    """Follow successive recovery outcomes before sending a delayed worker's request."""
    # pause a worker after it captures the original session but before its recovery check
    client = varvis_with_dbg_log
    client.backoff_factor_seconds = 0
    client.backoff_max_tries = 2
    worker_paused = threading.Event()
    release_worker = threading.Event()
    original_debug = client.logger.debug
    original_request = requests.Session.request
    delayed_sessions = []

    def paused_debug(message, *args, **kwargs):
        """Hold the delayed worker before it checks its captured session's recovery."""
        if message.startswith("Try #") and args[-1] == MOCK_URL + "api/delayed":
            worker_paused.set()
            assert release_worker.wait(timeout=5)
        original_debug(message, *args, **kwargs)

    def observed_request(session, method, url, **kwargs):
        """Record which session actually sends the delayed request."""
        if url == MOCK_URL + "api/delayed":
            delayed_sessions.append(session)
        return original_request(session, method, url, **kwargs)

    monkeypatch.setattr(client.logger, "debug", paused_debug)
    monkeypatch.setattr(requests.Session, "request", observed_request)
    varvis_mockapi_with_login.get(
        MOCK_URL + "api/fast",
        [
            {"status_code": 302, "headers": {"Location": MOCK_URL}},
            {"json": {"message": "success"}},
            {"status_code": 302, "headers": {"Location": MOCK_URL}},
            {"json": {"message": "success"}},
        ],
    )
    varvis_mockapi_with_login.get(MOCK_URL + "api/delayed", json={"message": "delayed"})

    # complete two recovery sequences while the worker retains the original session
    with ThreadPoolExecutor(max_workers=1) as executor:
        delayed = executor.submit(client._send_request, "GET", "delayed")
        try:
            assert worker_paused.wait(timeout=5)
            assert client._send_request("GET", "fast").json() == {"message": "success"}
            if second_recovery_succeeds:
                assert client._send_request("GET", "fast").json() == {"message": "success"}
            else:
                # retain the second sequence's shared error for the delayed worker
                varvis_mockapi_with_login.post(MOCK_URL + "login", headers={})
                with pytest.raises(VarvisError, match="Failed to reauthenticate") as recovery_failure:
                    client._send_request("GET", "fast")
        finally:
            # release the worker even if the controlling thread fails an assertion
            release_worker.set()

        # send once through the latest session or propagate failure without any request
        if second_recovery_succeeds:
            assert delayed.result(timeout=5).json() == {"message": "delayed"}
            assert delayed_sessions == [client._session]
        else:
            with pytest.raises(VarvisError, match="Failed to reauthenticate") as delayed_failure:
                delayed.result(timeout=5)
            assert delayed_failure.value is recovery_failure.value
            assert not delayed_sessions

    # following the chain must not initiate an additional login sequence
    history = varvis_mockapi_with_login.request_history
    assert sum(request.url == MOCK_URL + "login" for request in history) == (3 if second_recovery_succeeds else 4)


@pytest.mark.parametrize("failure_stage", ["head", "login"])
def test_failed_login_releases_lock_and_clears_session(varvis_mockapi_with_login, failure_stage):
    """Clear incomplete authentication and allow another thread to retry login."""
    # fail either stage of authentication with an exception
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    if failure_stage == "head":
        # simulate a transport failure before the initial CSRF token arrives
        varvis_mockapi_with_login.head(MOCK_URL, exc=requests.ConnectionError("login connection failed"))
        error = requests.ConnectionError
    else:
        # varvis signals rejected credentials by omitting the login response's CSRF token
        varvis_mockapi_with_login.post(MOCK_URL + "login", headers={})
        error = VarvisError
    with pytest.raises(error):
        client.login()
    # exceptions must not leave a partially initialized session visible to another thread
    assert client._session is None
    assert client._loggedin_csrf is None
    assert not client.logged_in

    # retry on a different thread to prove the failed attempt released its lock
    varvis_mockapi_with_login.head(MOCK_URL, headers={"X-CSRF-TOKEN": "initial"})
    varvis_mockapi_with_login.post(MOCK_URL + "login", headers={"X-CSRF-TOKEN": "authenticated"})
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(client.login).result(timeout=5) is True
    assert client.logged_in


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


@pytest.mark.parametrize("allow_retries, max_tries", [(False, 3), (True, 1)])
def test_forced_logout_respects_request_retry_limit(
    varvis_mockapi_with_login, varvis_with_dbg_log, allow_retries, max_tries
):
    """Avoid starting recovery when the original request cannot be retried."""
    # force a logout with either retries disabled or only one request attempt allowed
    client = varvis_with_dbg_log
    client.backoff_max_tries = max_tries
    varvis_mockapi_with_login.get(MOCK_URL + "api/test", status_code=302, headers={"Location": MOCK_URL})

    with pytest.raises(VarvisError, match="^Failed to send request to Varvis API after 1 attempts$"):
        client._send_request("GET", "test", allow_retries=allow_retries)

    # retain only the initial login and the failed API request in the transport history
    history = varvis_mockapi_with_login.request_history
    assert sum(request.url == MOCK_URL + "login" for request in history) == 1
    assert sum(request.url == MOCK_URL + "api/test" for request in history) == 1
    assert not client.logged_in


@pytest.mark.parametrize("n_failed_attempts", [1, 2, 3, 5, 99])
def test_send_request_handles_forced_logout(varvis_mockapi_with_login, varvis_with_dbg_log, n_failed_attempts):
    """Recover after a forced logout within the shared login budget, or report its exhaustion."""
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

    if n_failed_attempts <= varvis_with_dbg_log.backoff_max_tries:
        # Request should initially get a 302 redirect, then trigger re-login, and finally succeed
        resp = varvis_with_dbg_log._send_request("GET", "test")

        # Verify the results
        assert resp.ok
        assert resp.json() == test_json
        assert login_counter["count"] == n_failed_attempts + 1
    else:
        with pytest.raises(
            VarvisError,
            match=f"Failed to reauthenticate with Varvis API after {varvis_with_dbg_log.backoff_max_tries} attempts",
        ):
            varvis_with_dbg_log._send_request("GET", "test")
