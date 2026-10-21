"""
Unit tests for SNV annotations streaming parser and client methods.

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Bernt Popp <bernt.popp@laborberlin.com>
"""

from collections.abc import Generator
import io
import json
import os
import tempfile
from pathlib import Path
from unittest import mock
import pytest
import requests
from pydantic import ValidationError
from requests import Response

from varvis_connector import VarvisClient
from varvis_connector.errors import VarvisError
from varvis_connector._snv_stream_parser import (
    stream_snv_json_from_request_or_buffer,
    resolve_header_indices,
)
from ._common import (
    varvis_mockapi_with_login as varvis_mockapi_with_login,
    MOCK_URL,
)  # "as ..." prevents removal of fixture as "unused" by ruff linter


@pytest.fixture(autouse=True)
def snv_cache_home(monkeypatch, tmp_path):
    """Keep streaming caches inside each test's temporary directory."""
    # isolate cache selection from the developer's environment and home directory
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


def _create_mock_streaming_response(raw_bytes: bytes, chunk_size: int = 16) -> Response:
    """Create a mock Response that streams chunks via iter_content."""
    resp = Response()
    resp.status_code = 200
    resp.raw = io.BytesIO(raw_bytes)
    return resp


def test_stream_snv_json_from_request_or_buffer_data_first():
    """Test streaming parser when data array precedes header in JSON payload."""
    payload = {
        "data": [
            [1, "chr1", 1000, "A", "G", "GENE1"],
            [2, "chr2", 2000, "C", "T", "GENE2"],
        ],
        "header": [
            {"id": "ID", "title": "ID"},
            {"id": "Chr", "title": "Chr"},
            {"id": "Pos", "title": "Pos"},
            {"id": "Ref", "title": "Ref"},
            {"id": "Alt", "title": "Alt"},
            {"id": "Gene", "title": "Gene"},
        ],
        "uniquePersonLabelSuffixes": {},
        "filterApplied": False,
        "threshold": 100,
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    resp = _create_mock_streaming_response(raw_bytes, chunk_size=10)
    metadata: dict = {}

    rows = list(stream_snv_json_from_request_or_buffer(resp, chunk_size=10, metadata_out=metadata))

    assert len(rows) == 2
    assert rows[0] == [1, "chr1", 1000, "A", "G", "GENE1"]
    assert rows[1] == [2, "chr2", 2000, "C", "T", "GENE2"]
    assert len(metadata.get("header", [])) == 6
    assert metadata.get("filterApplied") is False
    assert metadata.get("threshold") == 100


def test_stream_snv_json_from_request_or_buffer_header_first():
    """Test streaming parser when header array precedes data in JSON payload."""
    # construct json with header before data
    raw_str = (
        '{"header": [{"id": "ID", "title": "ID"}, {"id": "Gene", "title": "Gene"}], '
        '"data": [[101, "BRCA1"], [102, "BRCA2"]], "threshold": 50}'
    )
    resp = _create_mock_streaming_response(raw_str.encode("utf-8"), chunk_size=8)
    metadata: dict = {}

    rows = list(stream_snv_json_from_request_or_buffer(resp, chunk_size=8, metadata_out=metadata))

    assert len(rows) == 2
    assert rows[0] == [101, "BRCA1"]
    assert rows[1] == [102, "BRCA2"]
    assert len(metadata.get("header", [])) == 2
    assert metadata.get("threshold") == 50


def test_stream_snv_json_from_request_or_buffer_empty_data():
    """Test streaming parser when data array is empty."""
    payload = {"data": [], "header": [{"id": "ID", "title": "ID"}]}
    resp = _create_mock_streaming_response(json.dumps(payload).encode("utf-8"), chunk_size=16)
    metadata: dict = {}

    rows = list(stream_snv_json_from_request_or_buffer(resp, chunk_size=16, metadata_out=metadata))

    assert rows == []
    assert len(metadata.get("header", [])) == 1


def test_stream_snv_json_from_request_or_buffer_utf8_split():
    """Test streaming parser with multi-byte unicode characters split across chunk boundaries."""
    payload = {
        "data": [
            [1, "München", "α-thalassemia", "c.123A>G"],
        ],
        "header": [{"id": "ID"}, {"id": "City"}, {"id": "Disease"}, {"id": "HGVS"}],
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    # small chunk size of 3 bytes will split utf-8 multi-byte characters
    resp = _create_mock_streaming_response(raw_bytes, chunk_size=3)
    metadata: dict = {}

    rows = list(stream_snv_json_from_request_or_buffer(resp, chunk_size=3, metadata_out=metadata))

    assert len(rows) == 1
    assert rows[0] == [1, "München", "α-thalassemia", "c.123A>G"]


def test_stream_snv_json_from_request_or_buffer_malformed_root():
    """Test streaming parser raises VarvisError when root is not a JSON object."""
    resp = _create_mock_streaming_response(b"[1, 2, 3]")
    with pytest.raises(VarvisError, match="expected '{' at root"):
        list(stream_snv_json_from_request_or_buffer(resp))


def test_stream_snv_json_from_request_or_buffer_unexpected_eof():
    """Test streaming parser raises VarvisError on truncated payload."""
    resp = _create_mock_streaming_response(b'{"data": [[1, 2], [3, ')
    with pytest.raises(VarvisError):
        list(stream_snv_json_from_request_or_buffer(resp))


def test_resolve_header_indices():
    """Test resolving canonical column indices from header items."""
    header = [
        {"id": "ID", "title": "Internal ID"},
        {"id": "Chr", "title": "Chromosome"},
        {"id": "Pos", "title": "Genomic Position"},
        {"id": "Ref", "title": "Reference Allele"},
        {"id": "Alt", "title": "Alternative Allele"},
        {"id": "Gene", "title": "Gene Symbol"},
    ]
    indices = resolve_header_indices(header)
    assert indices.get("id") == 0
    assert indices.get("chr") == 1
    assert indices.get("pos") == 2
    assert indices.get("ref") == 3
    assert indices.get("alt") == 4
    assert indices.get("gene") == 5


SAMPLE_STREAMING_PAYLOAD = {
    "data": [
        [1, "chr1", 1000, "A", "G", "BRCA1", 0.01],
        [2, "chr2", 2000, "C", "T", "TP53", 0.50],
        [3, "chr1", 3000, "T", "C", "BRCA1", 0.05],
    ],
    "header": [
        {"id": "ID", "title": "ID", "property": 0},
        {"id": "Chr", "title": "Chromosome", "property": 1},
        {"id": "Pos", "title": "Position", "property": 2},
        {"id": "Ref", "title": "Reference", "property": 3},
        {"id": "Alt", "title": "Alternative", "property": 4},
        {"id": "Gene", "title": "Gene Symbol", "property": 5},
        {"id": "AF", "title": "Allele Frequency", "property": 6},
    ],
    "uniquePersonLabelSuffixes": {},
    "uniqueCnvPersonLabelSuffixes": {},
    "filterApplied": False,
    "thresholdViolated": False,
    "threshold": 100,
}


def test_client_iter_snv_annotations_raw_rows(varvis_mockapi_with_login):
    """Test client.iter_snv_annotations yielding raw lists by default."""
    url = f"{MOCK_URL}api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    rows = list(client.iter_snv_annotations(123))
    assert len(rows) == 3
    assert rows[0] == [1, "chr1", 1000, "A", "G", "BRCA1", 0.01]
    assert rows[1] == [2, "chr2", 2000, "C", "T", "TP53", 0.50]


def test_client_iter_snv_annotations_as_dict_with_header(varvis_mockapi_with_login):
    """Test client.iter_snv_annotations yielding dictionaries when header is provided."""
    url = f"{MOCK_URL}api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    header = ["ID", "Chr", "Pos", "Ref", "Alt", "Gene", "AF"]
    rows = list(client.iter_snv_annotations(123, as_dict=True, header=header))

    assert len(rows) == 3
    assert isinstance(rows[0], dict)
    assert rows[0]["Gene"] == "BRCA1"
    assert rows[0]["Chr"] == "chr1"
    assert rows[0]["AF"] == 0.01
    assert rows[1]["Gene"] == "TP53"


def test_client_iter_snv_annotations_missing_header_error(varvis_mockapi_with_login):
    """Test ValueError is raised when as_dict=True without header or allow_buffering."""
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    with pytest.raises(ValueError, match="as_dict=True requires 'header'"):
        list(client.iter_snv_annotations(123, as_dict=True))


def test_client_iter_snv_annotations_allow_buffering(varvis_mockapi_with_login):
    """Test client.iter_snv_annotations with allow_buffering=True when header is at EOF."""
    url = f"{MOCK_URL}api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    rows = list(client.iter_snv_annotations(123, as_dict=True, allow_buffering=True))
    assert len(rows) == 3
    assert rows[0]["Gene"] == "BRCA1"
    assert rows[1]["Gene"] == "TP53"
    assert rows[2]["Gene"] == "BRCA1"


@pytest.mark.parametrize("stream_to_tempfile", [False, True])
def test_client_iter_snv_annotations_filter_gene(varvis_mockapi_with_login, stream_to_tempfile):
    """Filter genes case-insensitively with explicit or cached headers."""
    url = f"{MOCK_URL}api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    header = None if stream_to_tempfile else SAMPLE_STREAMING_PAYLOAD["header"]
    rows = list(
        client.iter_snv_annotations(123, header=header, target_genes={"tp53"}, stream_to_tempfile=stream_to_tempfile)
    )
    assert len(rows) == 1
    assert rows[0][5] == "TP53"


@pytest.mark.parametrize("stream_to_tempfile", [False, True])
def test_client_iter_snv_annotations_filter_coordinates(varvis_mockapi_with_login, stream_to_tempfile):
    """Filter normalized genomic coordinates with explicit or cached headers."""
    url = f"{MOCK_URL}api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    header = None if stream_to_tempfile else SAMPLE_STREAMING_PAYLOAD["header"]
    rows = list(
        client.iter_snv_annotations(
            123, header=header, target_coordinates={("1", 3000)}, stream_to_tempfile=stream_to_tempfile
        )
    )
    assert len(rows) == 1
    assert rows[0][1] == "chr1"
    assert rows[0][2] == 3000


def test_client_iter_snv_annotations_header_callback(varvis_mockapi_with_login):
    """Test header_callback is invoked with parsed header descriptors."""
    url = f"{MOCK_URL}api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    received_header: list = []

    def on_header(h):
        received_header.extend(h)

    rows = list(client.iter_snv_annotations(123, header_callback=on_header))
    assert len(rows) == 3
    assert len(received_header) == 7
    assert received_header[0].id == "ID"


def test_client_get_snv_annotation_header(varvis_mockapi_with_login):
    """Test client.get_snv_annotation_header parsing only header metadata."""
    url = f"{MOCK_URL}api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    header = client.get_snv_annotation_header(123)
    assert len(header) == 7
    assert header[0].id == "ID"
    assert header[5].id == "Gene"


def test_client_iter_snv_annotations_http_error(varvis_mockapi_with_login):
    """Test client.iter_snv_annotations raising VarvisError on HTTP error."""
    url = f"{MOCK_URL}api/analysis/999/annotations"
    varvis_mockapi_with_login.get(url, status_code=400)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    with pytest.raises(VarvisError, match="Analysis not found for the given ID."):
        list(client.iter_snv_annotations(999))


def test_resolve_header_indices_spaced_aliases():
    """Test resolve_header_indices handles title strings with spaces and case variants."""
    header = [
        {"title": "Variant ID"},
        {"title": "Gene Symbol"},
        {"title": "Chromosome"},
        {"title": "Genomic Position"},
        {"title": "Reference Allele"},
        {"title": "Alternative Allele"},
    ]
    indices = resolve_header_indices(header)
    assert indices["id"] == 0
    assert indices["gene"] == 1
    assert indices["chr"] == 2
    assert indices["pos"] == 3
    assert indices["ref"] == 4
    assert indices["alt"] == 5


def test_client_iter_snv_annotations_unresolved_filter_error(varvis_mockapi_with_login):
    """Test ValueError raised when target_genes or target_coordinates cannot resolve column index."""
    url = f"{MOCK_URL}api/analysis/123/annotations"
    bad_payload = {
        "header": [{"id": "foo", "title": "Foo"}, {"id": "bar", "title": "Bar"}],
        "data": [["val1", "val2"]],
    }
    varvis_mockapi_with_login.get(url, json=bad_payload)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    # upfront header missing gene
    with pytest.raises(ValueError, match="Could not resolve 'gene' column index"):
        list(client.iter_snv_annotations(123, header=bad_payload["header"], target_genes={"BRCA1"}))

    # upfront header missing chr / pos
    with pytest.raises(ValueError, match="Could not resolve chromosome"):
        list(client.iter_snv_annotations(123, header=bad_payload["header"], target_coordinates={("1", 100)}))

    # buffered header missing gene
    with pytest.raises(ValueError, match="Could not resolve 'gene' column index"):
        list(client.iter_snv_annotations(123, allow_buffering=True, target_genes={"BRCA1"}))


def test_client_get_snv_annotation_header_early_break(varvis_mockapi_with_login):
    """Test get_snv_annotation_header parses header and exits early without draining full data."""
    url = f"{MOCK_URL}api/analysis/123/annotations"
    payload_header_first = {
        "header": [{"id": "ID", "title": "Identifier"}, {"id": "Gene", "title": "Gene Symbol"}],
        "data": [["1", "BRCA1"], ["2", "TP53"]],
    }
    varvis_mockapi_with_login.get(url, json=payload_header_first)

    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()

    header = client.get_snv_annotation_header(123)
    assert len(header) == 2
    assert header[1].id == "Gene"


@pytest.mark.parametrize("file_factory", [tempfile.TemporaryFile, tempfile.NamedTemporaryFile])
@pytest.mark.parametrize("chunk_size", [1, 3, 65536])
def test_stream_snv_json_binary_files(file_factory, chunk_size):
    """Parse binary files and Windows-style wrappers across UTF-8 and buffer boundaries."""
    # make the payload large enough to exercise buffer compaction with literal utf-8
    payload = {
        "data": [[index, "München", "α-thalassemia"] for index in range(3000)],
        "header": [{"id": "ID"}, {"id": "City"}, {"id": "Disease"}],
    }
    metadata = {}
    with file_factory() as source:
        source.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        source.seek(0)
        rows = list(stream_snv_json_from_request_or_buffer(source, chunk_size=chunk_size, metadata_out=metadata))

    # preserve every row and trailing header regardless of source type or chunk size
    assert rows == payload["data"]
    assert metadata["header"] == payload["header"]


@pytest.mark.parametrize("as_dict", [False, True])
@pytest.mark.parametrize("provide_header", [False, True])
@pytest.mark.parametrize("empty_data", [False, True])
def test_client_iter_snv_annotations_tempfile(varvis_mockapi_with_login, as_dict, provide_header, empty_data):
    """Cache one response and yield raw rows or dictionaries using discovered or supplied headers."""
    # keep data before the header and optionally exercise a valid empty analysis
    payload = {**SAMPLE_STREAMING_PAYLOAD, "data": [] if empty_data else SAMPLE_STREAMING_PAYLOAD["data"]}
    endpoint = varvis_mockapi_with_login.get(f"{MOCK_URL}api/analysis/123/annotations", json=payload)
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    client.login()
    supplied_header = [f"supplied_{index}" for index in range(7)] if provide_header else None
    callback = mock.Mock()

    # temporary-file caching resolves trailing headers without enabling row buffering
    rows = list(
        client.iter_snv_annotations(
            123,
            as_dict=as_dict,
            header=supplied_header,
            stream_to_tempfile=True,
            header_callback=callback,
        )
    )

    # supplied headers take precedence while callbacks report the actual response header once
    keys = supplied_header if supplied_header is not None else [item["id"] for item in payload["header"]]
    expected = [dict(zip(keys, row)) for row in payload["data"]] if as_dict else payload["data"]
    assert rows == expected
    assert endpoint.call_count == 1
    callback.assert_called_once()
    assert [item.model_dump(exclude_unset=True) for item in callback.call_args.args[0]] == payload["header"]


@pytest.fixture
def snv_tempfile_resources(tmp_path):
    """Expose a real temporary-file wrapper and track response cleanup during streaming."""
    # use the wrapper returned by TemporaryFile on Windows on every platform
    response = _create_mock_streaming_response(json.dumps(SAMPLE_STREAMING_PAYLOAD).encode())
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")
    with (
        tempfile.NamedTemporaryFile(dir=tmp_path) as cache,
        mock.patch.object(VarvisClient, "_send_request", return_value=response),
        mock.patch.object(response, "close", wraps=response.close) as close_response,
        mock.patch("varvis_connector._varvis_client.tempfile.TemporaryFile", return_value=cache),
    ):
        yield client, response, cache, close_response


@pytest.mark.parametrize("finish", ["exhaust", "close"])
@pytest.mark.parametrize("allow_buffering", [False, True])
def test_client_tempfile_streaming_cleanup(snv_tempfile_resources, finish, allow_buffering):
    """Yield lazily from a fully cached response and close resources on exhaustion or explicit closure."""
    client, response, cache, close_response = snv_tempfile_resources
    # use a response larger than the parser read buffer to distinguish streaming from row accumulation
    payload = {**SAMPLE_STREAMING_PAYLOAD, "data": SAMPLE_STREAMING_PAYLOAD["data"] * 2000}
    raw_bytes = json.dumps(payload).encode()
    response.raw = io.BytesIO(raw_bytes)
    rows = client.iter_snv_annotations(123, as_dict=True, stream_to_tempfile=True, allow_buffering=allow_buffering)
    assert isinstance(rows, Generator)
    first_row = next(rows)

    # the complete response is cached but the second parsing pass has not read all rows
    assert first_row["Gene"] == "BRCA1"
    assert os.fstat(cache.fileno()).st_size == len(raw_bytes)
    assert cache.tell() < len(raw_bytes)
    assert not cache.closed
    close_response.assert_not_called()

    # both exhaustion and generator closure release the response and remove the cache
    if finish == "exhaust":
        assert sum(1 for _ in rows) == len(payload["data"]) - 1
    else:
        rows.close()
    close_response.assert_called_once()
    assert cache.closed
    assert not Path(cache.name).exists()


@pytest.mark.parametrize(
    "raw_bytes, error_type, message",
    [
        (b'{"data": [[1]], "header":', VarvisError, "Unexpected EOF"),
        (b'{"data": [[1]]}', VarvisError, "Header missing"),
        (b'{"data": [[1]], "header": [{}]}', ValidationError, "Field required"),
    ],
)
def test_client_tempfile_cleanup_on_parse_error(snv_tempfile_resources, raw_bytes, error_type, message):
    """Close the response and cache when payload parsing or header validation fails."""
    client, response, cache, close_response = snv_tempfile_resources
    response.raw = io.BytesIO(raw_bytes)

    # propagate the parsing error while releasing both acquired resources
    with pytest.raises(error_type, match=message):
        list(client.iter_snv_annotations(123, as_dict=True, stream_to_tempfile=True))
    close_response.assert_called_once()
    assert cache.closed


@pytest.mark.parametrize("failure", ["download", "write", "callback"])
def test_client_tempfile_cleanup_on_io_or_callback_error(snv_tempfile_resources, failure):
    """Release cached streaming resources when downloading, writing, or a callback fails."""
    client, response, cache, close_response = snv_tempfile_resources
    callback = mock.Mock()
    error = requests.ConnectionError("download interrupted") if failure == "download" else OSError("operation failed")

    # inject failures at distinct stages after the cache has been acquired
    with mock.patch.object(cache, "write", wraps=cache.write) as write:
        if failure == "download":
            response.raw = mock.Mock(spec=io.BytesIO)
            response.raw.read.side_effect = [b'{"data": [', error]
        elif failure == "write":
            write.side_effect = error
        else:
            callback.side_effect = error
        with pytest.raises(type(error), match=str(error)):
            list(client.iter_snv_annotations(123, as_dict=True, stream_to_tempfile=True, header_callback=callback))
        if failure == "download":
            write.assert_called_once_with(b'{"data": [')

    close_response.assert_called_once()
    assert cache.closed


def test_client_tempfile_creation_failure(tmp_path):
    """Close the HTTP response if both the user cache and system fallback fail."""
    response = _create_mock_streaming_response(b"{}")
    logger = mock.Mock()
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw", logger=logger)

    # propagate storage errors without leaving the already acquired response open
    with (
        mock.patch.object(VarvisClient, "_send_request", return_value=response),
        mock.patch.object(response, "close", wraps=response.close) as close_response,
        mock.patch(
            "varvis_connector._varvis_client.tempfile.TemporaryFile", side_effect=OSError("disk full")
        ) as create_cache,
    ):
        with pytest.raises(OSError, match="disk full"):
            list(client.iter_snv_annotations(123, as_dict=True, stream_to_tempfile=True))
        close_response.assert_called_once()

        assert create_cache.call_args_list == [mock.call(dir=tmp_path / "cache" / "varvis-connector"), mock.call()]
        logger.warning.assert_called_once()


@pytest.mark.parametrize(
    "options", [{"as_dict": True}, {"target_genes": {"BRCA1"}}, {"target_coordinates": {("1", 1)}}]
)
def test_client_streaming_validation_before_acquisition(options):
    """Reject missing-header arguments before requesting data or creating temporary files."""
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw")

    # invalid zero-buffering calls must not acquire network or filesystem resources
    with (
        mock.patch.object(VarvisClient, "_send_request") as request,
        mock.patch("varvis_connector._varvis_client.tempfile.TemporaryFile") as create_cache,
    ):
        with pytest.raises(ValueError, match="requires? 'header'"):
            list(client.iter_snv_annotations(123, **options))
        request.assert_not_called()
        create_cache.assert_not_called()


@pytest.mark.parametrize("cache_home", ["xdg", "unset", "empty", "relative"])
def test_client_tempfile_cache_location(varvis_mockapi_with_login, monkeypatch, tmp_path, cache_home):
    """Prefer the XDG cache or the home cache and remove the temporary file after use."""
    # resolve missing, empty, or invalid relative XDG paths to the standard home cache
    home = tmp_path / "home"
    expected = tmp_path / "cache" / "varvis-connector"
    if cache_home == "unset":
        monkeypatch.delenv("XDG_CACHE_HOME")
    elif cache_home == "empty":
        monkeypatch.setenv("XDG_CACHE_HOME", "")
    elif cache_home == "relative":
        monkeypatch.setenv("XDG_CACHE_HOME", "relative-cache")
    if cache_home != "xdg":
        expected = home / ".cache" / "varvis-connector"
    monkeypatch.setattr(Path, "home", mock.Mock(return_value=home))
    endpoint = varvis_mockapi_with_login.get(f"{MOCK_URL}api/analysis/123/annotations", json=SAMPLE_STREAMING_PAYLOAD)
    logger = mock.Mock()
    client = VarvisClient(MOCK_URL, "mockuser", "mockpw", logger=logger)
    client.login()

    # use a real temporary file to verify directory creation, placement, and cleanup
    with mock.patch("varvis_connector._varvis_client.tempfile.TemporaryFile", wraps=tempfile.TemporaryFile) as create:
        rows = list(client.iter_snv_annotations(123, stream_to_tempfile=True))
    assert rows == SAMPLE_STREAMING_PAYLOAD["data"]
    create.assert_called_once_with(dir=expected)
    assert expected.is_dir()
    assert list(expected.iterdir()) == []
    assert endpoint.call_count == 1
    logger.warning.assert_not_called()


@pytest.mark.parametrize("failure", ["directory", "file", "home"])
def test_client_tempfile_cache_fallback(snv_tempfile_resources, monkeypatch, tmp_path, failure):
    """Warn and stream through system temporary storage when the user cache cannot be created."""
    client, _, cache, close_response = snv_tempfile_resources
    logger = mock.Mock()
    client.logger = logger
    cache_dir = tmp_path / "cache" / "varvis-connector"
    create_cache = mock.Mock(return_value=cache)

    # fail directory creation, file creation, or home lookup before using the fallback
    if failure == "directory":
        cache_dir.parent.mkdir()
        cache_dir.write_text("not a directory")
    elif failure == "file":
        create_cache.side_effect = [PermissionError("cache is read-only"), cache]
    else:
        monkeypatch.delenv("XDG_CACHE_HOME")
        monkeypatch.setattr(Path, "home", mock.Mock(side_effect=RuntimeError("home unavailable")))
    # fallback preserves the rows and closes the response and temporary file
    with mock.patch("varvis_connector._varvis_client.tempfile.TemporaryFile", create_cache):
        rows = list(client.iter_snv_annotations(123, stream_to_tempfile=True))
    assert rows == SAMPLE_STREAMING_PAYLOAD["data"]
    expected_calls = [mock.call(dir=cache_dir), mock.call()] if failure == "file" else [mock.call()]
    assert create_cache.call_args_list == expected_calls
    logger.warning.assert_called_once()
    assert "system temporary directory" in logger.warning.call_args.args[0]
    assert "RAM-backed" in logger.warning.call_args.args[0]
    close_response.assert_called_once()
    assert cache.closed
