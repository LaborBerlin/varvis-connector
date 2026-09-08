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

import io
import json
import pytest
from requests import Response

from varvis_connector import VarvisClient
from varvis_connector.errors import VarvisError
from varvis_connector._snv_stream_parser import (
    stream_snv_json_payload,
    resolve_header_indices,
)
from ._common import (
    MOCK_URL as MOCK_URL,
    varvis_mockapi_with_login as varvis_mockapi_with_login,
)


def _create_mock_streaming_response(raw_bytes: bytes, chunk_size: int = 16) -> Response:
    """Create a mock Response that streams chunks via iter_content."""
    resp = Response()
    resp.status_code = 200
    resp.raw = io.BytesIO(raw_bytes)
    return resp


def test_stream_snv_json_payload_data_first():
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

    rows = list(stream_snv_json_payload(resp, chunk_size=10, metadata_out=metadata))

    assert len(rows) == 2
    assert rows[0] == [1, "chr1", 1000, "A", "G", "GENE1"]
    assert rows[1] == [2, "chr2", 2000, "C", "T", "GENE2"]
    assert len(metadata.get("header", [])) == 6
    assert metadata.get("filterApplied") is False
    assert metadata.get("threshold") == 100


def test_stream_snv_json_payload_header_first():
    """Test streaming parser when header array precedes data in JSON payload."""
    # construct json with header before data
    raw_str = (
        '{"header": [{"id": "ID", "title": "ID"}, {"id": "Gene", "title": "Gene"}], '
        '"data": [[101, "BRCA1"], [102, "BRCA2"]], "threshold": 50}'
    )
    resp = _create_mock_streaming_response(raw_str.encode("utf-8"), chunk_size=8)
    metadata: dict = {}

    rows = list(stream_snv_json_payload(resp, chunk_size=8, metadata_out=metadata))

    assert len(rows) == 2
    assert rows[0] == [101, "BRCA1"]
    assert rows[1] == [102, "BRCA2"]
    assert len(metadata.get("header", [])) == 2
    assert metadata.get("threshold") == 50


def test_stream_snv_json_payload_empty_data():
    """Test streaming parser when data array is empty."""
    payload = {"data": [], "header": [{"id": "ID", "title": "ID"}]}
    resp = _create_mock_streaming_response(json.dumps(payload).encode("utf-8"), chunk_size=16)
    metadata: dict = {}

    rows = list(stream_snv_json_payload(resp, chunk_size=16, metadata_out=metadata))

    assert rows == []
    assert len(metadata.get("header", [])) == 1


def test_stream_snv_json_payload_utf8_split():
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

    rows = list(stream_snv_json_payload(resp, chunk_size=3, metadata_out=metadata))

    assert len(rows) == 1
    assert rows[0] == [1, "München", "α-thalassemia", "c.123A>G"]


def test_stream_snv_json_payload_malformed_root():
    """Test streaming parser raises VarvisError when root is not a JSON object."""
    resp = _create_mock_streaming_response(b"[1, 2, 3]")
    with pytest.raises(VarvisError, match="expected '{' at root"):
        list(stream_snv_json_payload(resp))


def test_stream_snv_json_payload_unexpected_eof():
    """Test streaming parser raises VarvisError on truncated payload."""
    resp = _create_mock_streaming_response(b'{"data": [[1, 2], [3, ')
    with pytest.raises(VarvisError):
        list(stream_snv_json_payload(resp))


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
    url = "https://playground.varvis.com/api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient("https://playground.varvis.com/", "mockuser", "mockpw")
    client.login()

    rows = list(client.iter_snv_annotations(123))
    assert len(rows) == 3
    assert rows[0] == [1, "chr1", 1000, "A", "G", "BRCA1", 0.01]
    assert rows[1] == [2, "chr2", 2000, "C", "T", "TP53", 0.50]


def test_client_iter_snv_annotations_as_dict_with_header(varvis_mockapi_with_login):
    """Test client.iter_snv_annotations yielding dictionaries when header is provided."""
    url = "https://playground.varvis.com/api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient("https://playground.varvis.com/", "mockuser", "mockpw")
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
    client = VarvisClient("https://playground.varvis.com/", "mockuser", "mockpw")
    client.login()

    with pytest.raises(ValueError, match="as_dict=True requires 'header'"):
        list(client.iter_snv_annotations(123, as_dict=True))


def test_client_iter_snv_annotations_allow_buffering(varvis_mockapi_with_login):
    """Test client.iter_snv_annotations with allow_buffering=True when header is at EOF."""
    url = "https://playground.varvis.com/api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient("https://playground.varvis.com/", "mockuser", "mockpw")
    client.login()

    rows = list(client.iter_snv_annotations(123, as_dict=True, allow_buffering=True))
    assert len(rows) == 3
    assert rows[0]["Gene"] == "BRCA1"
    assert rows[1]["Gene"] == "TP53"
    assert rows[2]["Gene"] == "BRCA1"


def test_client_iter_snv_annotations_filter_gene(varvis_mockapi_with_login):
    """Test filtering variants by gene symbol."""
    url = "https://playground.varvis.com/api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient("https://playground.varvis.com/", "mockuser", "mockpw")
    client.login()

    header = SAMPLE_STREAMING_PAYLOAD["header"]
    rows = list(client.iter_snv_annotations(123, header=header, target_genes={"TP53"}))
    assert len(rows) == 1
    assert rows[0][5] == "TP53"


def test_client_iter_snv_annotations_filter_coordinates(varvis_mockapi_with_login):
    """Test filtering variants by genomic coordinates."""
    url = "https://playground.varvis.com/api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient("https://playground.varvis.com/", "mockuser", "mockpw")
    client.login()

    header = SAMPLE_STREAMING_PAYLOAD["header"]
    rows = list(client.iter_snv_annotations(123, header=header, target_coordinates={("chr1", 3000)}))
    assert len(rows) == 1
    assert rows[0][1] == "chr1"
    assert rows[0][2] == 3000


def test_client_iter_snv_annotations_header_callback(varvis_mockapi_with_login):
    """Test header_callback is invoked with parsed header descriptors."""
    url = "https://playground.varvis.com/api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient("https://playground.varvis.com/", "mockuser", "mockpw")
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
    url = "https://playground.varvis.com/api/analysis/123/annotations"
    varvis_mockapi_with_login.get(url, json=SAMPLE_STREAMING_PAYLOAD)

    client = VarvisClient("https://playground.varvis.com/", "mockuser", "mockpw")
    client.login()

    header = client.get_snv_annotation_header(123)
    assert len(header) == 7
    assert header[0].id == "ID"
    assert header[5].id == "Gene"


def test_client_iter_snv_annotations_http_error(varvis_mockapi_with_login):
    """Test client.iter_snv_annotations raising VarvisError on HTTP error."""
    url = "https://playground.varvis.com/api/analysis/999/annotations"
    varvis_mockapi_with_login.get(url, status_code=400)

    client = VarvisClient("https://playground.varvis.com/", "mockuser", "mockpw")
    client.login()

    with pytest.raises(VarvisError, match="Analysis not found for the given ID."):
        list(client.iter_snv_annotations(999))
