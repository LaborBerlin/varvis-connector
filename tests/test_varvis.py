"""
Tests for the VarvisClient class.

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

from collections.abc import Generator
from contextlib import closing
from dataclasses import fields
import logging
import os
import random
import stat
import threading
import uuid
from datetime import date
from fnmatch import fnmatchcase
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest
import requests
from polyfactory.factories.pydantic_factory import ModelFactory
from requests import Response
from urllib3.exceptions import ConnectTimeoutError
from urllib3.response import HTTPResponse

from ._common import (
    MOCK_URL,
    varvis_mockapi_with_login as varvis_mockapi_with_login,
    create_varvis_mockapi_downloads,
)  # "as ..." prevents removal of fixture as "unused" by ruff linter

from varvis_connector import VarvisClient
from varvis_connector._varvis_client import _validate_download_filename
from varvis_connector.errors import VarvisError
from varvis_connector.models import (
    SnvAnnotationData,
    SnvAnnotationHeaderItem,
    CnvTargetResults,
    PendingCnvData,
    QCCaseMetricsData,
    CoverageData,
    AnalysisItem,
    PersonReportItem,
    CaseReport,
    CaseReportVirtualPanelItem,
    CaseReportMethodsItem,
    CaseReportPersonItem,
    CaseReportAnalysis,
    FindByInputFileNameAnalysisItem,
    AnalysisFileDownloadLinks,
    PersonUpdateData,
    PersonData,
    VirtualPanelSummary,
    VarvisGene,
    VirtualPanelUpdateData,
    VirtualPanelData,
)


class PersonUpdateDataFactory(ModelFactory):
    __model__ = PersonUpdateData


def _get_varvis_instance(init_data):
    url, username, password, https_proxy, ssl_verify = init_data
    v = VarvisClient(url, username, password, https_proxy=https_proxy, ssl_verify=ssl_verify)

    if not v.login():  # pragma: no cover
        pytest.fail("Failed to login")

    return v


@pytest.fixture(scope="module")
def varvis_init_data():
    """Read playground credentials and connection settings from the loaded environment."""
    env_vars = [f"VARVIS_TEST_PLAYGROUND_{s}" for s in ("URL", "USER", "PASSWORD")]
    init_data: list[str | bool | None] = [os.getenv(var) for var in env_vars]

    if not all(init_data):  # pragma: no cover
        pytest.skip(
            "At least one of the following environment variables is missing or empty for running tests with the "
            "Varvis playground: " + ", ".join(env_vars)
        )

    assert isinstance(init_data[0], str)
    if not init_data[0].endswith("/"):
        init_data[0] += "/"

    https_proxy = os.getenv("HTTPS_PROXY", None)
    init_data.append(https_proxy)
    ssl_verify = os.getenv("VARVIS_TEST_SSL_VERIFY", "true").lower() in {"true", "1"}
    init_data.append(ssl_verify)

    return init_data


@pytest.fixture
def varvis(varvis_init_data):
    v = _get_varvis_instance(varvis_init_data)

    yield v

    v.logout()


@pytest.fixture(scope="module", params=[7, 61], ids=["analysis-7", "analysis-61"])
def playground_snv_analysis(varvis_init_data, request):
    """Share a live client and eager reference payload for each playground SNV analysis."""
    # reuse one authenticated session and one reference fetch across the parameter matrix
    client = _get_varvis_instance(varvis_init_data)
    try:
        reference = client.get_snv_annotations(request.param)
        assert reference.data
        assert reference.header
        yield request.param, client, reference
    finally:
        client.logout()


@pytest.fixture()
def monkeypatch_clean_env(monkeypatch):
    envvars = {
        "VARVIS_URL",
        "VARVIS_USER",
        "VARVIS_PASSWORD",
        "HTTPS_PROXY",
        "VARVIS_SSL_VERIFY",
        "VARVIS_CONNECT_TIMEOUT",
        "VARVIS_READ_TIMEOUT",
    }
    for var in envvars:
        if os.getenv(var) is not None:
            monkeypatch.delenv(var)

    return monkeypatch


@pytest.mark.parametrize(
    "with_proxy, ssl_verify, connection_timeout, connect_timeout, read_timeout, backoff_factor_seconds, backoff_max_tries",
    [
        (True, True, 1, None, None, 2, 3),
        (False, True, 0.1, 0.2, 0.3, 0.2, 1),
        (True, False, 0.1, 0.2, 5, 0, 10),
        (False, False, 5, None, 7, 0, 99),
    ],
)
def test_from_env(
    monkeypatch_clean_env,
    with_proxy,
    ssl_verify,
    connection_timeout,
    connect_timeout,
    read_timeout,
    backoff_factor_seconds,
    backoff_max_tries,
):
    url = "https://mock.varvis.com/"
    username = "mockuser"
    password = "mockpw"
    monkeypatch_clean_env.setenv("VARVIS_URL", url)
    monkeypatch_clean_env.setenv("VARVIS_USER", username)
    monkeypatch_clean_env.setenv("VARVIS_PASSWORD", password)

    if with_proxy:
        monkeypatch_clean_env.setenv("HTTPS_PROXY", "https://proxy.example.com:8080")
    else:
        monkeypatch_clean_env.delenv("HTTPS_PROXY", raising=False)

    if ssl_verify:
        monkeypatch_clean_env.delenv("VARVIS_SSL_VERIFY", raising=False)
    else:
        monkeypatch_clean_env.setenv("VARVIS_SSL_VERIFY", "0")

    monkeypatch_clean_env.setenv("VARVIS_CONNECTION_TIMEOUT", str(connection_timeout))
    if connect_timeout is not None:
        monkeypatch_clean_env.setenv("VARVIS_CONNECT_TIMEOUT", str(connect_timeout))
    if read_timeout is not None:
        monkeypatch_clean_env.setenv("VARVIS_READ_TIMEOUT", str(read_timeout))
    monkeypatch_clean_env.setenv("VARVIS_BACKOFF_FACTOR_SECONDS", str(backoff_factor_seconds))
    monkeypatch_clean_env.setenv("VARVIS_BACKOFF_MAX_TRIES", str(backoff_max_tries))

    v = VarvisClient.from_env()
    assert v.api_url == url
    assert v.username == username
    assert v.password == password
    if with_proxy:
        assert v.https_proxy == "https://proxy.example.com:8080"
    else:
        assert v.https_proxy is None
    assert v.ssl_verify == ssl_verify
    assert v.connection_timeout == connection_timeout
    assert v.connect_timeout == connect_timeout
    assert v.read_timeout == read_timeout
    assert v.backoff_factor_seconds == backoff_factor_seconds
    assert v.backoff_max_tries == backoff_max_tries
    assert not v.logged_in


@pytest.mark.parametrize(
    "setting, default",
    [
        ("download_chunk_size", 5 * 1024 * 1024),
        ("download_pool_size", 0),
        ("download_pool_max_size", 0),
        ("download_max_retries", 2),
    ],
)
@pytest.mark.parametrize("value", [None, "0", "7", "invalid"])
def test_from_env_download_integer_settings(monkeypatch_clean_env, setting, default, value):
    """Read integer download settings, preserve defaults, and reject invalid integers."""
    # provide credentials and isolate all integer download settings from the caller's environment
    monkeypatch_clean_env.setenv("VARVIS_URL", MOCK_URL)
    monkeypatch_clean_env.setenv("VARVIS_USER", "mockuser")
    monkeypatch_clean_env.setenv("VARVIS_PASSWORD", "mockpw")
    for name in ("CHUNK_SIZE", "POOL_SIZE", "POOL_MAX_SIZE", "MAX_RETRIES"):
        monkeypatch_clean_env.delenv("VARVIS_DOWNLOAD_" + name, raising=False)
    if value is not None:
        monkeypatch_clean_env.setenv("VARVIS_" + setting.upper(), value)

    # check numeric conversion and default retention or reject malformed input
    if value == "invalid":
        with pytest.raises(ValueError, match="invalid literal for int"):
            VarvisClient.from_env()
    else:
        client = VarvisClient.from_env()
        actual = getattr(client, setting)
        assert actual == (default if value is None else int(value))
        assert isinstance(actual, int)


@pytest.mark.parametrize("download_factor", [None, "0", "1.25", "-1"])
def test_from_env_download_backoff(monkeypatch_clean_env, download_factor):
    """Configure and validate download backoff independently of API backoff."""
    # isolate the download setting while giving API retries a different backoff factor
    monkeypatch_clean_env.setenv("VARVIS_URL", MOCK_URL)
    monkeypatch_clean_env.setenv("VARVIS_USER", "mockuser")
    monkeypatch_clean_env.setenv("VARVIS_PASSWORD", "mockpw")
    monkeypatch_clean_env.setenv("VARVIS_BACKOFF_FACTOR_SECONDS", "3")
    if download_factor is None:
        monkeypatch_clean_env.delenv("VARVIS_DOWNLOAD_BACKOFF_FACTOR_SECONDS", raising=False)
    else:
        monkeypatch_clean_env.setenv("VARVIS_DOWNLOAD_BACKOFF_FACTOR_SECONDS", download_factor)

    # reject invalid settings and retain the independent default or configured download factor
    if download_factor == "-1":
        with pytest.raises(ValueError, match="download_backoff_factor_seconds must be a non-negative number"):
            VarvisClient.from_env()
    else:
        client = VarvisClient.from_env()
        assert client.download_backoff_factor_seconds == (0.5 if download_factor is None else float(download_factor))
        assert client.backoff_factor_seconds == 3


def test_varvis_fields_order_username_before_password():
    """
    Make sure that username field comes before password field. This is required when asking for the password
    interactively in VarvisCLI._setup_argparser.
    """
    classfields = [f.name for f in fields(VarvisClient)]
    assert classfields.index("username") < classfields.index("password")


def test_post_init(varvis_init_data):
    url, username, password, https_proxy, ssl_verify = varvis_init_data
    url = url.removesuffix("/")
    v = VarvisClient(url, username, password, https_proxy=https_proxy, ssl_verify=ssl_verify)
    assert v.api_url == url + "/"


def test_login(varvis_init_data):
    url, username, password, https_proxy, ssl_verify = varvis_init_data
    v = VarvisClient(url, username, password, https_proxy=https_proxy, ssl_verify=ssl_verify)
    assert not v.logged_in
    assert v.login()
    sess = v._session
    assert v.logged_in

    # no second login
    assert v.login()
    assert v.logged_in
    assert v._session is sess


def test_login_mocked(varvis_mockapi_with_login):
    username = "mockuser"
    password = "mockpw"

    assert varvis_mockapi_with_login
    v = VarvisClient(MOCK_URL, username, password)
    assert v.login()


def test_disabling_ssl_verification_does_not_disable_warnings(monkeypatch):
    def unexpected_disable_warnings(*args, **kwargs):
        pytest.fail("Client construction must not change process-wide warning filters")

    monkeypatch.setattr("urllib3.disable_warnings", unexpected_disable_warnings)

    VarvisClient("https://example.com/", "user", "password", ssl_verify=False)


def test_login_fail(varvis_init_data):
    url, username, password, https_proxy, ssl_verify = varvis_init_data
    v = VarvisClient(
        url,
        username,
        password + "wrong",
        https_proxy=https_proxy,
        ssl_verify=ssl_verify,
    )
    with pytest.raises(VarvisError, match="Login failed"):
        v.login()

    assert not v.login(raise_for_status=False)


def test_no_credentials_leakage_in_str_repr():
    varvis = VarvisClient("https://example.com/", username="test-USERNAME", password="test-PASSWORD")
    internal_attrs = [attr for attr in dir(varvis) if attr.startswith("_")]

    for func in (str, repr):
        output = func(varvis)
        assert varvis.password not in output
        assert not any(a in output for a in internal_attrs)


def test_logout(varvis):
    varvis.logout()
    assert not varvis.logged_in
    assert varvis._session is None
    assert varvis._loggedin_csrf is None

    # second logout is not performed
    varvis.logout()
    assert not varvis.logged_in


def test_logout_fails_but_state_resets(varvis_mockapi_with_login):
    varvis = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    assert varvis.login()

    def mock_send_request(*args, **kwargs):
        raise TimeoutError("mock error")

    varvis._send_request = mock_send_request

    with pytest.raises(TimeoutError):
        varvis.logout()

    assert varvis._session is None
    assert varvis._loggedin_csrf is None


def test_not_logged_in(monkeypatch_clean_env):
    var_suffixes = ("URL", "USER", "PASSWORD")
    env_vars = [os.getenv(f"VARVIS_TEST_PLAYGROUND_{s}", "") for s in var_suffixes]
    if not all(env_vars):  # pragma: no cover
        pytest.skip(
            "At least one of the following environment variables is missing or empty for running tests with the "
            "Varvis playground: " + ", ".join(f"VARVIS_TEST_PLAYGROUND_{s}" for s in var_suffixes)
        )

    for suffix, value in zip(var_suffixes, env_vars):
        monkeypatch_clean_env.setenv("VARVIS_" + suffix, value)

    v = VarvisClient.from_env()

    with pytest.raises(VarvisError, match="Session not initialized -- you need to login first"):
        v.get_internal_person_id("lims-123-doesnt-matter")


@pytest.mark.parametrize(
    "analysis_id, expect_error",
    [
        (7, None),
        (61, None),
        (0, "Analysis not found for the given ID"),
    ],
)
def test_get_snv_annotations(varvis, analysis_id, expect_error):
    if expect_error:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.get_snv_annotations(analysis_id)
    else:
        res = varvis.get_snv_annotations(analysis_id)
        assert isinstance(res, SnvAnnotationData)
        assert res.data
        assert res.header
        assert not res.thresholdViolated


def test_get_snv_annotation_header(playground_snv_analysis):
    """Read the live annotation header and compare every column with eager retrieval."""
    # a separate streaming request must preserve header ordering and all model fields
    analysis_id, client, reference = playground_snv_analysis
    header = client.get_snv_annotation_header(analysis_id)
    assert header
    assert all(isinstance(item, SnvAnnotationHeaderItem) for item in header)
    assert header == reference.header


@pytest.mark.parametrize(
    "as_dict, header_format, filter_mode, chunk_size, allow_buffering, stream_to_tempfile",
    [
        pytest.param(False, "none", "none", 65536, False, False, id="raw-direct"),
        pytest.param(True, "models", "gene", 1024, False, False, id="model-header-gene"),
        pytest.param(False, "dicts", "coordinate", 65536, False, False, id="dict-header-coordinate"),
        pytest.param(True, "none", "both", 1024, True, False, id="buffered-combined-filters"),
        pytest.param(False, "none", "gene", 65536, False, True, id="tempfile-discovered-header"),
        pytest.param(True, "dicts", "both", 1024, True, True, id="tempfile-supplied-header"),
        pytest.param(True, "none", "none", 65536, False, False, id="missing-dictionary-header"),
        pytest.param(False, "none", "coordinate", 1024, False, False, id="missing-filter-header"),
    ],
)
def test_iter_snv_annotations(
    playground_snv_analysis,
    monkeypatch,
    tmp_path,
    as_dict,
    header_format,
    filter_mode,
    chunk_size,
    allow_buffering,
    stream_to_tempfile,
):
    """Cover each streaming parameter value with representative live cases and independently filtered eager rows."""
    # exercise absent headers and metadata-bearing representations using real annotation columns
    analysis_id, client, reference = playground_snv_analysis
    keys = [item.id or item.title or f"col_{index}" for index, item in enumerate(reference.header)]
    header = {
        "none": None,
        "models": reference.header,
        "dicts": [item.model_dump() for item in reference.header],
    }[header_format]
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    # derive matching gene and coordinate targets from the playground's array-valued cells
    gene_index = keys.index("Gene")
    chr_index = keys.index("Chr")
    pos_index = keys.index("Pos")
    first = reference.data[0]
    dictionary = reference.header[gene_index].dataDictionary
    assert dictionary is not None
    gene = dictionary[str(first[gene_index][0])]
    chromosome = str(first[chr_index][0])
    position = int(first[pos_index][0])
    use_gene = filter_mode in {"gene", "both"}
    use_coordinate = filter_mode in {"coordinate", "both"}

    # expected matches use raw gene IDs and coordinates rather than the streaming filter implementation
    gene_ids = {str(key) for key, symbol in dictionary.items() if symbol == gene}
    expected_rows = [
        row
        for row in reference.data
        if (not use_gene or any(str(value) in gene_ids for value in row[gene_index]))
        and (not use_coordinate or (str(row[chr_index][0]), int(row[pos_index][0])) == (chromosome, position))
    ]
    assert expected_rows
    expected = [dict(zip(keys, row, strict=True)) for row in expected_rows] if as_dict else expected_rows

    # missing headers must be rejected when dictionaries or filters cannot discover them without buffering
    rows = client.iter_snv_annotations(
        analysis_id,
        as_dict=as_dict,
        header=header,
        target_genes=[gene.lower()] if use_gene else None,
        target_coordinates=[(f"CHR{chromosome}", position)] if use_coordinate else None,
        chunk_size=chunk_size,
        allow_buffering=allow_buffering,
        stream_to_tempfile=stream_to_tempfile,
    )
    assert isinstance(rows, Generator)
    with closing(rows):
        if (
            header is None
            and not allow_buffering
            and not stream_to_tempfile
            and (as_dict or use_gene or use_coordinate)
        ):
            with pytest.raises(ValueError, match="requires|Filtering"):
                list(rows)
        else:
            assert list(rows) == expected


@pytest.mark.parametrize("as_dict", [False, True], ids=["lists", "dicts"])
def test_iter_snv_annotations_header_names(playground_snv_analysis, as_dict):
    """Accept column names alone when no gene dictionary is needed for filtering."""
    # names preserve row mapping but cannot translate the playground's gene IDs into symbols
    analysis_id, client, reference = playground_snv_analysis
    keys = [item.id for item in reference.header]
    expected = [dict(zip(keys, row, strict=True)) for row in reference.data] if as_dict else reference.data
    rows = client.iter_snv_annotations(analysis_id, as_dict=as_dict, header=keys)
    assert isinstance(rows, Generator)
    with closing(rows):
        assert list(rows) == expected


@pytest.mark.parametrize("empty_filters", [[], (), set()], ids=["lists", "tuples", "sets"])
def test_iter_snv_annotations_empty_filters(playground_snv_analysis, empty_filters):
    """Treat empty filter collections as an unfiltered direct stream."""
    # empty filters must not require a header, buffering, or temporary storage
    analysis_id, client, reference = playground_snv_analysis
    rows = client.iter_snv_annotations(analysis_id, target_genes=empty_filters, target_coordinates=empty_filters)
    assert isinstance(rows, Generator)
    with closing(rows):
        assert list(rows) == reference.data


@pytest.mark.parametrize(
    "target_genes, target_coordinates",
    [
        (["__NO_MATCHING_PLAYGROUND_GENE__"], None),
        (None, [("chr0", 0)]),
        (["__NO_MATCHING_PLAYGROUND_GENE__"], [("chr0", 0)]),
    ],
    ids=["gene", "coordinate", "both"],
)
def test_iter_snv_annotations_no_matching_filters(playground_snv_analysis, target_genes, target_coordinates):
    """Return an empty iterator when valid filters match no playground variants."""
    # unmatched filters are a successful result rather than an API or parsing error
    analysis_id, client, reference = playground_snv_analysis
    rows = client.iter_snv_annotations(
        analysis_id, header=reference.header, target_genes=target_genes, target_coordinates=target_coordinates
    )
    assert isinstance(rows, Generator)
    with closing(rows):
        assert list(rows) == []


def test_iter_snv_annotations_filters_combine_with_and(playground_snv_analysis):
    """Require both filters even when each separately matches real playground rows."""
    # choose a gene from the first variant and a coordinate belonging to a different gene
    analysis_id, client, reference = playground_snv_analysis
    keys = [item.id for item in reference.header]
    gene_index, chr_index, pos_index = (keys.index(key) for key in ("Gene", "Chr", "Pos"))
    first_id = reference.data[0][gene_index][0]
    dictionary = reference.header[gene_index].dataDictionary
    assert dictionary is not None
    gene = dictionary[str(first_id)]
    other = next(row for row in reference.data if first_id not in row[gene_index])
    chromosome, position = str(other[chr_index][0]), int(other[pos_index][0])
    assert all(
        first_id not in row[gene_index]
        for row in reference.data
        if (str(row[chr_index][0]), int(row[pos_index][0])) == (chromosome, position)
    )

    # an OR implementation would incorrectly return matches from either target
    rows = client.iter_snv_annotations(
        analysis_id, header=reference.header, target_genes={gene}, target_coordinates={(chromosome, position)}
    )
    assert isinstance(rows, Generator)
    with closing(rows):
        assert list(rows) == []


@pytest.mark.parametrize("filter_kind", ["genes", "coordinates"])
@pytest.mark.parametrize("collection_type", [list, tuple, set], ids=["lists", "tuples", "sets"])
def test_iter_snv_annotations_multiple_filter_targets(playground_snv_analysis, filter_kind, collection_type):
    """Match any target within gene or coordinate collections against real variants."""
    # derive two targets and their expected union from the eager reference data
    analysis_id, client, reference = playground_snv_analysis
    keys = [item.id for item in reference.header]
    gene_index, chr_index, pos_index = (keys.index(key) for key in ("Gene", "Chr", "Pos"))
    dictionary = reference.header[gene_index].dataDictionary
    assert dictionary is not None
    chosen = [reference.data[0], reference.data[-1]]
    genes = {dictionary[str(row[gene_index][0])] for row in chosen}
    gene_ids = {str(key) for key, symbol in dictionary.items() if symbol in genes}
    coordinates = {(str(row[chr_index][0]), int(row[pos_index][0])) for row in chosen}
    expected = [
        row
        for row in reference.data
        if (
            any(str(value) in gene_ids for value in row[gene_index])
            if filter_kind == "genes"
            else (str(row[chr_index][0]), int(row[pos_index][0])) in coordinates
        )
    ]

    # collection types affect neither matching nor original row contents
    rows = client.iter_snv_annotations(
        analysis_id,
        header=reference.header,
        target_genes=collection_type(genes) if filter_kind == "genes" else None,
        target_coordinates=collection_type(coordinates) if filter_kind == "coordinates" else None,
    )
    assert isinstance(rows, Generator)
    with closing(rows):
        assert list(rows) == expected


@pytest.mark.parametrize(
    "person_lims_id, analysis_ids, virtual_panel_id, expect_error, data_can_be_empty",
    [
        ("200000000", 43, 1, None, False),
        ("200000000", 43, None, None, False),
        ("200000000", [43], 1, None, False),
        ("200000000", [], 1, None, False),
        (
            "notexistent",
            [1],
            1,
            "Person with given LIMS-ID was not found",
            False,
        ),
        (
            "OCI3-QK333-Zelllinie-dx-twist",
            61,
            1,
            "Analysis ID is not associated with a CNV analysis or is not valid for the specified person LIMS-ID",
            False,
        ),
    ],
)
def test_get_cnv_target_results(
    varvis,
    person_lims_id,
    analysis_ids,
    virtual_panel_id,
    expect_error,
    data_can_be_empty,
):
    if isinstance(analysis_ids, list) and not analysis_ids:
        with pytest.raises(ValueError, match="must be either an integer a non-empty list of integers"):
            varvis.get_cnv_target_results(person_lims_id, analysis_ids, virtual_panel_id)
    else:
        if expect_error:
            with pytest.raises(VarvisError, match=expect_error):
                varvis.get_cnv_target_results(person_lims_id, analysis_ids, virtual_panel_id)
        else:
            res = varvis.get_cnv_target_results(person_lims_id, analysis_ids, virtual_panel_id)
            assert isinstance(res, CnvTargetResults)
            if not data_can_be_empty:
                assert res.data
            assert res.targetRegionsHeader


@pytest.mark.parametrize("person_lims_id", ["200000000", "OCI3-QK333-Zelllinie-dx-twist", "notexistent"])
def test_get_internal_person_id(varvis, person_lims_id):
    if person_lims_id == "notexistent":
        with pytest.raises(
            VarvisError,
            match="Person not found for the given LIMS-ID",
        ):
            varvis.get_internal_person_id(person_lims_id)
    else:
        res = varvis.get_internal_person_id(person_lims_id)
        assert isinstance(res, int)


def test_get_internal_person_id_quotes_lims_id(varvis_mockapi_with_login):
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()
    person_lims_id = "person/a?b#c"
    encoded_lims_id = "person%2Fa%3Fb%23c"
    mock_url = f"{MOCK_URL}api/person/{encoded_lims_id}/id"
    varvis_mockapi_with_login.get(mock_url, json={"success": True, "response": 123})

    assert client.get_internal_person_id(person_lims_id) == 123
    assert varvis_mockapi_with_login.last_request.url == mock_url


@pytest.mark.parametrize(
    "person_id, person_lims_id, analysis_ids, virtual_panel_id, expect_error",
    [
        (None, None, 13, 1, None),
        (7, "P1-NA12878", 13, 1, None),
        (7, None, None, 1, None),
        (7, None, 13, 1, None),
        (7, None, 0, 1, "Person or analysis ID not found"),
        (0, None, 13, 1, "Person or analysis ID not found"),
        (None, "P1-NA12878", 13, 1, None),
        (None, "P1-NA12878", 13, None, None),
    ],
)
def test_get_pending_cnv_segments(
    varvis,
    person_id,
    person_lims_id,
    analysis_ids,
    virtual_panel_id,
    expect_error,
):
    kwargs = dict(
        person_id=person_id,
        person_lims_id=person_lims_id,
        analysis_ids=analysis_ids,
        virtual_panel_id=virtual_panel_id,
    )
    if (person_id is None and person_lims_id is None) or (person_id is not None and person_lims_id is not None):
        with pytest.raises(ValueError, match="`person_id` or `person_lims_id`"):
            varvis.get_pending_cnv_segments(**kwargs)
    elif analysis_ids is None:
        with pytest.raises(
            ValueError,
            match="Parameter `analysis_ids` must be either an integer a non-empty list of integers",
        ):
            varvis.get_pending_cnv_segments(**kwargs)
    else:
        if expect_error:
            with pytest.raises(VarvisError, match=expect_error):
                varvis.get_pending_cnv_segments(**kwargs)
        else:
            res = varvis.get_pending_cnv_segments(**kwargs)
            assert isinstance(res, PendingCnvData)
            assert res.data
            assert res.cnvHeader


@pytest.mark.parametrize(
    "person_lims_id, expect_error",
    [
        ("P1-NA12878", None),
        ("OCI3-QK333-Zelllinie-dx-twist", None),
        ("P18-NA12878", None),
        ("notexistent", "Person with given LIMS-ID was not found"),
    ],
)
def test_get_qc_case_metrics(varvis, person_lims_id, expect_error):
    if expect_error:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.get_qc_case_metrics(person_lims_id)
    else:
        res = varvis.get_qc_case_metrics(person_lims_id)
        assert isinstance(res, QCCaseMetricsData)
        assert res.metricResults.personId == person_lims_id


@pytest.mark.parametrize(
    "person_lims_id, virtual_panel_id, expect_error",
    [
        ("P1-NA12878", None, None),
        ("P1-NA12878", 1, None),
        ("P1-NA12878", 2, None),
        ("notexistent", 2, "Person with given LIMS-ID was not found"),
        ("OCI3-QK333-Zelllinie-dx-twist", 1, None),
    ],
)
def test_get_coverage_data(varvis, person_lims_id, virtual_panel_id, expect_error):
    if expect_error:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.get_coverage_data(person_lims_id, virtual_panel_id=virtual_panel_id)
    else:
        res = varvis.get_coverage_data(person_lims_id, virtual_panel_id=virtual_panel_id)
        assert isinstance(res, list)
        assert len(res) > 0
        assert all(isinstance(item, CoverageData) for item in res)


@pytest.mark.parametrize(
    "analysis_ids, expect_empty_result",
    [
        (None, False),
        ([], False),
        ([1], True),
        ([2, 3, 4], False),
    ],
)
def test_get_analyses(varvis, analysis_ids, expect_empty_result):
    res = varvis.get_analyses(analysis_ids)
    assert isinstance(res, list)
    if expect_empty_result:
        assert len(res) == 0
    else:
        assert len(res) > 0
        assert all(isinstance(item, AnalysisItem) for item in res)
        if analysis_ids:
            assert set(analysis_ids) == {item.id for item in res}


@pytest.mark.parametrize(
    "person_lims_id, expect_error",
    [
        ("P1-NA12878", None),
        ("200000000", None),
        ("nonexistent", "Person with given LIMS-ID was not found"),
    ],
)
def test_get_person(varvis, person_lims_id, expect_error):
    if expect_error:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.get_person(person_lims_id)
    else:
        res = varvis.get_person(person_lims_id)
        assert isinstance(res, PersonData)
        assert res.personalInformation.limsId == person_lims_id
        assert res.clinicalInformation.limsId == person_lims_id


@pytest.mark.parametrize(
    "data_as_dict, simulate_validation_error",
    [
        (False, False),
        (True, False),
        (False, True),
    ],
)
def test_create_or_update_person(varvis, data_as_dict, simulate_validation_error):
    def _check_person_stored(person_stored, model, updated_birthdate=None):
        assert person_stored.personalInformation.limsId == lims_id
        assert person_stored.clinicalInformation.limsId == lims_id
        check_person_attrs = (
            "familyId",
            "firstName",
            "lastName",
            "comment",
            "sex",
            "country",
        )
        for attr in check_person_attrs:
            if attr == "sex" and model.sex is None:
                expected_value = (
                    "UNKNOWN"  # another Varvis API quirk: passing None leads to storing this data as "UNKNOWN"
                )
            else:
                expected_value = getattr(model, attr)
            assert getattr(person_stored.personalInformation, attr) == expected_value
        if updated_birthdate is None:
            assert person_stored.personalInformation.birthDate == date(
                model.birthDateYear, model.birthDateMonth, model.birthDateDay
            )
        else:
            assert person_stored.personalInformation.birthDate == updated_birthdate

    if data_as_dict:
        # check validation
        with pytest.raises(
            ValueError,
            match="Parameter `person_data` must be a PersonUpdateData object or a "
            "dictionary that can be validated against the PersonUpdateData schema",
        ):
            varvis.create_or_update_person({})

    # check server-side validation error
    if simulate_validation_error:
        with pytest.raises(VarvisError, match="Could not create or update person entry"):
            # simulate invalid LIMS ID
            model = PersonUpdateData(id="")
            varvis.create_or_update_person(model)
        return

    # generate a random LIMS ID
    lims_id = "lbrbln-test-" + str(uuid.uuid4())

    # create a model with auto-generated data
    hpo_term_ids = ["HP:0025337", "HP:0001386", "HP:0003037"]
    hpo_term_sample = random.sample(hpo_term_ids, k=random.randint(0, len(hpo_term_ids)))
    model = PersonUpdateDataFactory.build(
        id=lims_id,
        birthDateYear=1999,
        birthDateMonth=10,
        birthDateDay=8,
        hpoTermIds=hpo_term_sample or None,
        country="Germany",
    )
    if data_as_dict:
        data = model.model_dump()
    else:
        data = model

    # create the person entry
    internal_pers_id = varvis.create_or_update_person(data)

    # check that the internal person ID matches
    assert varvis.get_internal_person_id(lims_id) == internal_pers_id

    # fetch data using get-person endpoint and compare
    person_stored = varvis.get_person(lims_id)
    _check_person_stored(person_stored, model)

    # update existing entry and check that the internal person ID matches
    if data_as_dict:
        update = {
            "id": lims_id,
            "birthDateDay": 9,
            "birthDateMonth": 10,
            "birthDateYear": 1999,
        }
    else:
        update = PersonUpdateData(id=lims_id, birthDateYear=1999, birthDateMonth=10, birthDateDay=9)
    assert varvis.create_or_update_person(update) == internal_pers_id

    # fetch data using get-person endpoint and compare again
    person_stored = varvis.get_person(lims_id)
    _check_person_stored(person_stored, model, updated_birthdate=date(1999, 10, 9))


def test_get_report_info_for_persons(varvis):
    res = varvis.get_report_info_for_persons()
    assert isinstance(res, list)
    assert len(res) > 0
    assert all(isinstance(item, PersonReportItem) for item in res)

    # expect some known person LIMS-IDs
    expected_person_ids = {"P1-NA12878", "OCI3-QK333-Zelllinie-dx-twist"}
    person_ids = {item.limsId for item in res}
    assert expected_person_ids <= person_ids


@pytest.mark.parametrize(
    "person_lims_id, expect_error",
    [
        ("P1-NA12878", None),
        ("nonexistent", "Person with given LIMS-ID was not found"),
    ],
)
def test_get_person_analyses(varvis, person_lims_id, expect_error):
    if expect_error:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.get_person_analyses(person_lims_id)
    else:
        res = varvis.get_person_analyses(person_lims_id)
        assert isinstance(res, list)
        assert len(res) > 0
        for item in res:
            assert isinstance(item, AnalysisItem)
            assert item.personLimsId == person_lims_id


@pytest.mark.parametrize(
    "person_lims_id, draft, inactive, expect_error",
    [
        # note: at the moment, only tests with the LB varvis instance are implemented, since the playground always responds with an HTTP 500 error
        ("P2-NA12878", False, False, None),
        (
            "notexistent",
            False,
            False,
            "Person with given LIMS-ID was not found or no report exists for the given criteria",
        ),
        ("P2-NA12878", False, True, None),
        ("P2-NA12878", True, False, None),
    ],
    ids=["std-ok", "not-existent", "inactive", "draft"],
)
def test_get_case_report(varvis, person_lims_id, draft, inactive, expect_error):
    if expect_error:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.get_case_report(person_lims_id, draft=draft, inactive=inactive)
        return

    internal_person_id = varvis.get_internal_person_id(person_lims_id)

    res = varvis.get_case_report(person_lims_id, draft=draft, inactive=inactive)
    assert isinstance(res, CaseReport)
    assert res.draft == draft  # requesting a draft always returns a draft, even if a final report already exists

    if res.personId is not None:
        assert res.personId == internal_person_id

    assert len(res.items) > 0

    for item in res.items:
        assert isinstance(
            item,
            (CaseReportVirtualPanelItem, CaseReportMethodsItem, CaseReportPersonItem),
        )

        if not inactive:
            assert item.active

        if isinstance(item, CaseReportVirtualPanelItem):
            assert item.type == "VIRTUAL_PANEL"
            if item.allGenesPanel:
                assert item.virtualPanelId == 1  # "all genes panel" must be ID 1
        elif isinstance(item, CaseReportMethodsItem):
            assert item.type == "METHODS"
            assert len(item.analyses) > 0
            assert all(isinstance(analysis, CaseReportAnalysis) for analysis in item.analyses)
        else:  # CaseReportPersonItem
            assert item.type == "PERSON"
            assert item.personId == internal_person_id
            assert item.limsId == person_lims_id
            assert len(item.analyses) > 0
            assert all(isinstance(analysis, CaseReportAnalysis) for analysis in item.analyses)


@pytest.mark.parametrize(
    "filename, expect_empty, expect_error",
    [
        ("NA12878", False, None),
        ("Kasumi1-QK318-Zelllinie-dx-twist_S44-ready", False, None),
        ([" NA12878  ", "unlinked3"], False, None),
        (["NA12878", "foobar-non-existing"], True, None),
        (
            [],
            None,
            "Parameter `filename` must be a non-empty string or a non-empty list of strings",
        ),
        (
            [""],
            None,
            "Parameter `filename` must be a non-empty string or a non-empty list of strings",
        ),
        (
            " ",
            None,
            "Parameter `filename` must be a non-empty string or a non-empty list of strings",
        ),
    ],
)
def test_find_analyses_by_filename(varvis, filename, expect_empty, expect_error):
    if expect_error:
        with pytest.raises(ValueError, match=expect_error):
            varvis.find_analyses_by_filename(filename)
    else:
        res = varvis.find_analyses_by_filename(filename)
        assert isinstance(res, list)
        if expect_empty:
            assert len(res) == 0
        else:
            assert len(res) > 0
            assert all(isinstance(item, FindByInputFileNameAnalysisItem) for item in res)


def test_find_analyses_by_filename_quotes_query_components(varvis_mockapi_with_login):
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()
    filename = "sample#1?x&y.vcf"
    mock_url = (
        f"{MOCK_URL}analysis-list/find-by-customer-provided-input-file-name?"
        "customerProvidedInputFileName=sample%231%3Fx%26y.vcf"
    )
    varvis_mockapi_with_login.get(mock_url, json={"success": True, "response": []})

    assert client.find_analyses_by_filename(filename) == []
    assert varvis_mockapi_with_login.last_request.url == mock_url


@pytest.mark.parametrize(
    "vp_id, expect_error",
    [
        (2, None),
        (999, "Virtual panel with ID 999 not found"),
    ],
)
def test_get_virtual_panel(varvis, vp_id, expect_error):
    if expect_error:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.get_virtual_panel(vp_id)
    else:
        res = varvis.get_virtual_panel(vp_id)
        assert isinstance(res, VirtualPanelData)
        assert res.id == vp_id


def test_get_virtual_panel_summaries(varvis):
    res = varvis.get_virtual_panel_summaries()
    assert isinstance(res, list)
    assert len(res) > 0
    for item in res:
        assert isinstance(item, VirtualPanelSummary)
        assert item.id > 0
        assert item.name
        assert item.numberOfGenesInPanel >= 0
        assert item.lengthOfTranscriptsCds >= 0


def test_get_all_genes(varvis):
    res = varvis.get_all_genes()
    assert isinstance(res, list)
    assert len(res) > 0
    for item in res:
        assert isinstance(item, VarvisGene)
        assert item.id > 0
        assert item.name
        assert item.symbol
        assert item.transcriptCdsLength >= 0
        assert item.transcriptExonCount >= 0
        assert item.chromosome
        assert item.chromosomeLocation
        assert isinstance(item.hpoTerms, list)
        assert all(isinstance(item, str) for item in item.hpoTerms)


@pytest.mark.parametrize(
    "data_as_dict, simulate_validation_error",
    [
        (False, False),
        (True, False),
        (False, True),
    ],
)
def test_create_or_update_virtual_panel(varvis, data_as_dict, simulate_validation_error):
    if data_as_dict:
        # check validation
        with pytest.raises(
            ValueError,
            match="Parameter `virtual_panel_data` must be a VirtualPanelUpdateData instance or a "
            "dictionary that can be validated against the VirtualPanelUpdateData schema",
        ):
            varvis.create_or_update_virtual_panel({})

    # check server-side validation error
    if simulate_validation_error:
        with pytest.raises(VarvisError, match="Varvis API request did not succeed"):
            # simulate invalid geneIds (empty)
            model = VirtualPanelUpdateData(name="lbrbln-test-will-fail", active=True, geneIds=[])
            varvis.create_or_update_virtual_panel(model)
        return

    # generate a random VP name
    name = "lbrbln-test-" + str(uuid.uuid4())

    # create a model without ID -> will create a VP
    model = VirtualPanelUpdateData(name=name, active=True, geneIds=[24309, 50200], description="An automated test.")
    if data_as_dict:
        data = model.model_dump()
    else:
        data = model

    # create the VP
    vp_id = varvis.create_or_update_virtual_panel(data)

    # check that the VP was created
    vp = varvis.get_virtual_panel(vp_id)
    assert vp.name == name
    assert vp.active
    assert {g.id for g in vp.genes} == set(model.geneIds)
    assert vp.description == model.description
    assert vp.personId is None

    # update existing VP
    model.id = vp_id
    model.personId = 7  # this person exists

    if data_as_dict:
        data = model.model_dump()
    else:
        data = model

    assert varvis.create_or_update_virtual_panel(data) == vp_id

    # check that the VP was updated
    for vp in varvis.get_virtual_panel_summaries():
        if vp.id == vp_id:
            assert vp.name == name
            assert vp.active
            assert vp.numberOfGenesInPanel == len(model.geneIds)
            assert vp.description == model.description
            assert vp.personId == model.personId
            break
    else:  # pragma: no cover
        raise AssertionError("VP does not exist anymore")


@pytest.mark.parametrize(
    "analysis_id, expect_error",
    [
        (2, None),
        (61, None),
        (0, "Analysis with given ID was not found"),
    ],
)
def test_get_file_download_links(varvis, analysis_id, expect_error):
    if expect_error is None:
        res = varvis.get_file_download_links(analysis_id)
        assert isinstance(res, AnalysisFileDownloadLinks)
        assert res.id == analysis_id
        assert res.apiFileLinks
        for link in res.apiFileLinks:
            assert link.fileName
            assert isinstance(link.downloadLink, str)
            assert link.downloadLink.startswith("https://")
            assert link.currentlyArchived is False
            assert link.estimatedRestoreTime is None
    else:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.get_file_download_links(analysis_id)


@pytest.mark.parametrize(
    "analysis_id, file_patterns, allow_overwrite, simulate_file_exists, show_progress_bar, max_parallel_downloads, only_collect_urls, expect_error",
    [
        (2, None, False, False, False, 1, False, None),
        (2, None, False, False, False, 1, True, None),
        (
            1,
            None,
            False,
            False,
            False,
            1,
            False,
            "Analysis with given ID was not found",
        ),
        (2, "*.gz", False, False, False, 1, False, None),
        (2, "*.gz", False, False, False, 1, True, None),
        (2, ["*.gz", "*.bai"], False, False, False, 1, False, None),
        (61, ["*.gz", "*.bai"], True, False, False, 1, False, None),
        (61, ["*.gz", "*.bai"], True, False, False, 2, False, None),
        (61, ["*.gz", "*.bai"], True, False, True, 2, False, None),
        (61, ["*.notexisting"], False, False, False, 1, False, None),
        (2, None, False, True, False, 1, False, None),
        (2, "*.gz", True, True, False, 1, False, None),
    ],
)
def test_download_files(
    tmp_path,
    varvis_mockapi_with_login,
    analysis_id,
    file_patterns,
    allow_overwrite,
    simulate_file_exists,
    show_progress_bar,
    max_parallel_downloads,
    only_collect_urls,
    expect_error,
):
    varvis = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    assert varvis.login()

    mocked_files = create_varvis_mockapi_downloads(
        varvis_mockapi_with_login,
        analysis_id,
        expect_error,
        simulate_file_exists,
        tmp_path,
    )

    # test passing Path object and str
    if analysis_id == 2:
        output_path = str(tmp_path)
    else:
        output_path = tmp_path

    kwargs = dict(
        analysis_id=analysis_id,
        output_path=output_path,
        file_patterns=file_patterns,
        allow_overwrite=allow_overwrite,
        show_progress_bar=show_progress_bar,
        max_parallel_downloads=max_parallel_downloads,
        only_collect_urls=only_collect_urls,
    )

    if expect_error is None:
        res = varvis.download_files(**kwargs)  # type: ignore[reportArgumentType]
        assert isinstance(res, dict)
        for file_name_or_url, target_path in res.items():
            assert isinstance(file_name_or_url, str)
            assert isinstance(target_path, Path)

            assert not file_name_or_url.endswith(".archive")

            if only_collect_urls:
                assert file_name_or_url == "https://mock-dl/" + target_path.name
                assert file_name_or_url != "https://mock-dl/."
                assert not target_path.exists()
            else:
                assert file_name_or_url == target_path.name
                assert file_name_or_url != "."
                assert target_path.exists()
                assert target_path.read_text() == "testdata"

            if file_patterns:
                file_name_lwr = file_name_or_url.lower()
                if isinstance(file_patterns, str):
                    file_patterns = [file_patterns]
                assert any(fnmatchcase(file_name_lwr, pat.lower()) for pat in file_patterns)

        if simulate_file_exists and not allow_overwrite:
            assert mocked_files[0] not in res
            assert (tmp_path / mocked_files[0]).read_text() == "already existed"
    else:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.download_files(**kwargs)  # type: ignore[reportArgumentType]


def test_download_files_param_errors(varvis, tmp_path):
    with pytest.raises(ValueError, match="Output path does not exist: "):
        varvis.download_files(1, "/foo/bar")
    with pytest.raises(ValueError, match="Parameter `max_parallel_downloads` must be at least 1"):
        varvis.download_files(1, tmp_path, max_parallel_downloads=0)


@pytest.mark.parametrize(
    "file_name",
    [
        "",
        " ",
        "foo.bar.",
        " foo.  ",
        "..\\outside.bat",
        "C:outside.bat",
        "\\\\server\\share",
        "CON",
        "nul.txt",
        "COM9.log",
        "COM¹.txt",
        "COM²",
        "COM³.log",
        "LPT1",
        "LPT¹.txt",
        "LPT²",
        "LPT³.log",
    ],
)
def test_validate_download_filename_rejects_unsafe_names(file_name):
    with pytest.raises(ValueError, match="Invalid download filename"):
        _validate_download_filename(file_name)


@pytest.mark.parametrize("file_name", ["sample.bam", "report.final.vcf", "sample_1.txt"])
def test_validate_download_filename_accepts_regular_names(file_name):
    assert _validate_download_filename(file_name) == file_name


@pytest.mark.parametrize("url", ["http://example.com/file", "ftp://example.com/file", "https:file"])
def test_download_files_from_urls_parallel_rejects_non_https(monkeypatch, varvis, tmp_path, url):
    def unexpected_request(*args, **kwargs):
        pytest.fail("Non-HTTPS URL should be rejected before making a request")

    monkeypatch.setattr("varvis_connector._varvis_client.Session.get", unexpected_request)

    result = varvis.download_files_from_urls_parallel(
        {url: tmp_path / "file"},
        max_parallel_downloads=1,
        show_progress_bar=False,
        return_messages=False,
    )

    assert result == {}
    assert not (tmp_path / "file").exists()


@pytest.mark.parametrize("failures_before_success", [0, 1, 2, 3])
@pytest.mark.parametrize("backoff_factor", [0.5, 0])
def test_download_retries_use_exponential_backoff_with_jitter(
    monkeypatch, tmp_path, failures_before_success, backoff_factor
):
    """Use independent download backoff with jitter and stop after two download retries."""
    # bypass environment proxies and replace only wire I/O so urllib3 performs real retries
    monkeypatch.setenv("NO_PROXY", "*")
    attempts = []
    payload = b"new data"

    def make_request(pool, connection, method, url, **_kwargs):
        """Fail connection attempts before returning a complete streamed response."""
        attempts.append((method, url))
        if len(attempts) <= failures_before_success:
            raise ConnectTimeoutError("download connection timed out")
        return HTTPResponse(
            body=BytesIO(payload),
            headers={"Content-Length": str(len(payload))},
            status=200,
            preload_content=False,
            connection=connection,
            pool=pool,
        )

    monkeypatch.setattr("urllib3.connectionpool.HTTPSConnectionPool._make_request", make_request)
    # control jitter draws and record sleeps without waiting or depending on random values
    jitter = mock.Mock(side_effect=[0.5 * backoff_factor, 1.5 * backoff_factor])
    sleep = mock.Mock()
    monkeypatch.setattr("varvis_connector._varvis_client.random.uniform", jitter)
    monkeypatch.setattr("urllib3.util.retry.time.sleep", sleep)
    # make API backoff differ so accidentally using it produces different retry windows
    client = VarvisClient(
        MOCK_URL,
        "mockuser",
        "mockpw",
        backoff_factor_seconds=3,
        download_backoff_factor_seconds=backoff_factor,
    )
    target_path = tmp_path / "sample.bam"

    # exercise the actual session and adapter, including immutable retry policy cloning
    result = client.download_files_from_urls_parallel(
        {"https://mock-dl/sample.bam": target_path},
        max_parallel_downloads=1,
        show_progress_bar=False,
        return_messages=False,
    )

    # allow one initial attempt and at most two retries, with no incomplete file on failure
    assert len(attempts) == min(failures_before_success + 1, 3)
    if failures_before_success < 3:
        assert result == {"sample.bam": target_path}
        assert target_path.read_bytes() == payload
    else:
        assert result == {}
        assert not target_path.exists()
    assert not list(tmp_path.glob("*.part"))

    # increase the jitter window exponentially and skip sleeping when backoff is disabled
    retry_count = min(failures_before_success, 2)
    assert jitter.call_args_list == [mock.call(0, backoff_factor), mock.call(0, 2 * backoff_factor)][:retry_count]
    expected_sleeps = [mock.call(0.5 * backoff_factor), mock.call(1.5 * backoff_factor)][:retry_count]
    assert sleep.call_args_list == (expected_sleeps if backoff_factor else [])


def test_check_download_files_for_path_collisions(tmp_path):
    """Return each resolved target path once when multiple URLs share it."""
    # start with two distinct download destinations
    target_dir = tmp_path / "downloads"
    target_dir.mkdir()
    first_target = target_dir / "alignment.bam"
    second_target = target_dir / "report.vcf"
    urls_and_targets = {
        "https://mock-dl/1": first_target,
        "https://mock-dl/2": second_target,
    }
    assert VarvisClient.check_download_files_for_path_collisions(urls_and_targets) == []

    # add an alias for the first destination and repeat both targets
    alias_dir = tmp_path / "alias"
    alias_dir.symlink_to(target_dir, target_is_directory=True)
    urls_and_targets["https://mock-dl/3"] = alias_dir / first_target.name
    urls_and_targets["https://mock-dl/4"] = first_target
    urls_and_targets["https://mock-dl/5"] = second_target

    assert VarvisClient.check_download_files_for_path_collisions(urls_and_targets) == [
        str(first_target.resolve()),
        str(second_target.resolve()),
    ]


@pytest.mark.parametrize("use_symlink", [False, True])
def test_download_files_from_urls_parallel_rejects_target_path_collision(tmp_path, use_symlink):
    """Reject distinct URLs that resolve to one target before starting workers."""
    # create two path spellings that point to the same destination
    target_dir = tmp_path / "downloads"
    target_dir.mkdir()
    second_dir = target_dir
    if use_symlink:
        second_dir = tmp_path / "alias"
        second_dir.symlink_to(target_dir, target_is_directory=True)

    target_path = target_dir / "alignment.bam"
    urls_and_targets = {
        "https://mock-dl/1/alignment.bam": target_path,
        "https://mock-dl/2/alignment.bam": second_dir / "alignment.bam",
    }
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")

    # reject the batch before starting any download worker
    with mock.patch("varvis_connector._varvis_client.ThreadPoolExecutor") as executor_mock:
        with pytest.raises(ValueError, match="duplicate target paths") as exc_info:
            client.download_files_from_urls_parallel(
                urls_and_targets,
                max_parallel_downloads=2,
                show_progress_bar=False,
                return_messages=False,
            )

    executor_mock.assert_not_called()
    assert str(target_path) in str(exc_info.value)
    assert not target_path.exists()


@pytest.fixture
def download_logger(caplog):
    """Provide a logger whose records can be asserted through pytest's log capture."""
    # configure a dedicated logger that propagates records to caplog
    logger = logging.getLogger("download_test")
    logger.handlers.clear()
    logger.propagate = True
    caplog.set_level(logging.INFO, logger=logger.name)
    return logger


@pytest.mark.parametrize("existing_mode", [None, 0o640])
def test_download_files_from_urls_parallel_commits_atomically(
    monkeypatch, tmp_path, caplog, download_logger, existing_mode
):
    """The destination remains unchanged until a complete download is committed."""
    # set up a new or existing destination
    target_path = tmp_path / "sample.bam"
    if existing_mode is not None:
        target_path.write_bytes(b"existing data")
        target_path.chmod(existing_mode)

    # observe the destination while chunks are streamed
    def iter_content(chunk_size):
        """Yield download chunks while checking the destination state."""
        assert chunk_size > 0
        if existing_mode is None:
            assert not target_path.exists()
        else:
            assert target_path.read_bytes() == b"existing data"
        assert len(list(tmp_path.glob("*.part"))) == 1
        yield b"new "
        yield b"data"

    # return a complete streamed response
    response = mock.Mock(spec=Response)
    response.ok = True
    response.headers = {"Content-Length": "8"}
    response.iter_content.side_effect = iter_content
    monkeypatch.setattr("varvis_connector._varvis_client.Session.get", mock.Mock(return_value=response))
    varvis = VarvisClient(MOCK_URL, "mockuser", "mockpw", logger=download_logger)
    caplog.clear()

    # download and atomically replace the destination
    result = varvis.download_files_from_urls_parallel(
        {"https://mock-dl/sample.bam": target_path},
        max_parallel_downloads=1,
        show_progress_bar=False,
        return_messages=False,
    )

    # verify the committed file and cleanup
    assert result == {"sample.bam": target_path}
    assert target_path.read_bytes() == b"new data"
    expected_mode = 0o664 if existing_mode is None else existing_mode
    assert stat.S_IMODE(target_path.stat().st_mode) == expected_mode
    assert not list(tmp_path.glob("*.part"))
    response.close.assert_called_once_with()
    assert (download_logger.name, logging.INFO, 'Download #1: Successfully downloaded file "sample.bam"') in (
        caplog.record_tuples
    )


def test_download_files_from_urls_parallel_cleans_up_after_stream_timeout(
    monkeypatch, tmp_path, caplog, download_logger
):
    """A timeout preserves the destination and removes the partial download."""
    # set up an existing destination and an interrupted response
    target_path = tmp_path / "sample.bam"
    target_path.write_bytes(b"existing data")

    def iter_content(chunk_size):
        """Yield one chunk before simulating a network timeout."""
        assert chunk_size > 0
        yield b"partial"
        raise requests.Timeout("download timed out")

    # return the interrupted streamed response
    response = mock.Mock(spec=Response)
    response.ok = True
    response.headers = {"Content-Length": "20"}
    response.iter_content.side_effect = iter_content
    monkeypatch.setattr("varvis_connector._varvis_client.Session.get", mock.Mock(return_value=response))
    varvis = VarvisClient(MOCK_URL, "mockuser", "mockpw", logger=download_logger)
    caplog.clear()

    # attempt the interrupted download
    result = varvis.download_files_from_urls_parallel(
        {"https://mock-dl/sample.bam": target_path},
        max_parallel_downloads=1,
        show_progress_bar=False,
        return_messages=False,
    )

    # verify the original destination and cleanup
    assert result == {}
    assert target_path.read_bytes() == b"existing data"
    assert not list(tmp_path.glob("*.part"))
    response.close.assert_called_once_with()
    error_records = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert [record.getMessage() for record in error_records] == [
        "Download #1: Error while downloading the file",
        'Download #1: Could not download file "sample.bam"',
    ]
    assert isinstance(error_records[0].exc_info[1], requests.Timeout)


def test_download_files_from_urls_parallel_cleans_up_after_keyboard_interrupt(
    monkeypatch, tmp_path, caplog, download_logger
):
    """A keyboard interrupt stops workers, cleans up, and propagates to the caller."""
    # set up an existing destination and a continuously streaming response
    target_path = tmp_path / "sample.bam"
    target_path.write_bytes(b"existing data")
    download_started = threading.Event()

    def iter_content(chunk_size):
        """Stream chunks until the download worker receives the interruption event."""
        assert chunk_size > 0
        download_started.set()
        while True:
            yield b"partial"

    # interrupt the coordinating thread after the worker starts streaming
    def interrupt_when_download_started(futures):
        """Raise a keyboard interrupt once the worker has started downloading."""
        assert futures
        assert download_started.wait(timeout=1)
        raise KeyboardInterrupt

    # return the streaming response and interrupt future collection
    response = mock.Mock(spec=Response)
    response.ok = True
    response.headers = {}
    response.iter_content.side_effect = iter_content
    monkeypatch.setattr("varvis_connector._varvis_client.Session.get", mock.Mock(return_value=response))
    monkeypatch.setattr(
        "varvis_connector._varvis_client.concurrent.futures.as_completed",
        interrupt_when_download_started,
    )
    varvis = VarvisClient(MOCK_URL, "mockuser", "mockpw", logger=download_logger)
    caplog.clear()

    # verify that the caller receives the interruption
    with pytest.raises(KeyboardInterrupt):
        varvis.download_files_from_urls_parallel(
            {"https://mock-dl/sample.bam": target_path},
            max_parallel_downloads=1,
            show_progress_bar=False,
            return_messages=False,
        )

    # verify the original destination and cleanup
    assert target_path.read_bytes() == b"existing data"
    assert not list(tmp_path.glob("*.part"))
    response.close.assert_called_once_with()
    assert (download_logger.name, logging.WARNING, "Download #1: Download interrupted") in caplog.record_tuples


def test_download_files_from_urls_parallel_rejects_incomplete_content(monkeypatch, tmp_path, caplog, download_logger):
    """A cleanly ended response with missing bytes is not committed."""
    # return fewer bytes than declared by the response
    response = mock.Mock(spec=Response)
    response.ok = True
    response.headers = {"Content-Length": "20"}
    response.iter_content.return_value = [b"partial"]
    monkeypatch.setattr("varvis_connector._varvis_client.Session.get", mock.Mock(return_value=response))
    varvis = VarvisClient(MOCK_URL, "mockuser", "mockpw", logger=download_logger)
    caplog.clear()
    target_path = tmp_path / "sample.bam"

    # attempt the incomplete download
    result = varvis.download_files_from_urls_parallel(
        {"https://mock-dl/sample.bam": target_path},
        max_parallel_downloads=1,
        show_progress_bar=False,
        return_messages=False,
    )

    # verify that no incomplete file remains
    assert result == {}
    assert not target_path.exists()
    assert not list(tmp_path.glob("*.part"))
    response.close.assert_called_once_with()
    assert (
        download_logger.name,
        logging.ERROR,
        "Download #1: Number of downloaded bytes (7) does not match number of expected bytes (20)",
    ) in caplog.record_tuples


def test_download_files_from_urls_parallel_handles_request_timeout(monkeypatch, tmp_path, caplog, download_logger):
    """A timeout before receiving a response does not escape the worker."""
    # make the initial download request time out
    request = mock.Mock(side_effect=requests.Timeout("request timed out"))
    monkeypatch.setattr("varvis_connector._varvis_client.Session.get", request)
    varvis = VarvisClient(MOCK_URL, "mockuser", "mockpw", logger=download_logger)
    caplog.clear()
    target_path = tmp_path / "sample.bam"

    # attempt the timed-out request
    result = varvis.download_files_from_urls_parallel(
        {"https://mock-dl/sample.bam": target_path},
        max_parallel_downloads=1,
        show_progress_bar=False,
        return_messages=False,
    )

    # verify that no download artifacts remain
    assert result == {}
    assert not target_path.exists()
    assert not list(tmp_path.glob("*.part"))
    request.assert_called_once()
    error_records = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert [record.getMessage() for record in error_records] == [
        "Download #1: Error on download request",
        'Download #1: Could not download file "sample.bam"',
    ]
    assert isinstance(error_records[0].exc_info[1], requests.Timeout)


@pytest.mark.parametrize(
    "endpoint, handle_errors, expect_error",
    [
        ("/virtual-panels", True, None),
        ("virtual-panels", True, None),
        (
            "invalid-endpoint",
            True,
            "Varvis API returned HTTP status code 404. Not found.",
        ),
        ("invalid-endpoint", False, None),
    ],
)
def test_request_get(varvis, endpoint, handle_errors, expect_error):
    if expect_error:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.request(
                endpoint,
                raise_for_status=handle_errors,
                handle_http_errors=handle_errors,
            )
    else:
        res = varvis.request(endpoint, raise_for_status=handle_errors, handle_http_errors=handle_errors)

        assert isinstance(res, Response)

        if endpoint == "invalid-endpoint":
            assert res.status_code == 404
        else:
            assert res.status_code == 200


def test_request_put(varvis):
    person_data = {
        "id": "lbrbln-test-request-put-" + str(uuid.uuid4()),
        "familyId": None,
        "firstName": "Tester",
        "lastName": "Test",
        "comment": None,
        "sex": None,
        "birthDateYear": 2020,
        "birthDateMonth": 3,
        "birthDateDay": 3,
        "country": None,
    }

    res = varvis.request("api/person", method="PUT", json=person_data)
    assert isinstance(res, Response)
    assert res.ok
