"""
SNV annotations streaming parser module for Varvis API responses.

Provides incremental, low-memory streaming of large 2D variant arrays directly
from HTTP response streams using standard library JSON decoding.

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Bernt Popp <bernt.popp@laborberlin.com>
"""

import codecs
import json
from collections.abc import Iterator, Sequence
from typing import Any
import requests

from .errors import VarvisError

# buffer compaction threshold in characters
_BUFFER_COMPACTION_THRESHOLD = 65536


def resolve_header_indices(header: Sequence[Any]) -> dict[str, int]:
    """
    Resolves canonical genomic column indices from a list of header descriptors.

    Searches header items (dictionaries, objects with an id/title attribute, or strings)
    for standard canonical genomic annotations such as gene symbol, chromosome, position,
    reference allele, and alternate allele.

    :param header: Sequence of header descriptors or names.
    :return: Dictionary mapping canonical column names ('gene', 'chr', 'pos', 'ref', 'alt', 'id')
        to their zero-based integer column index.
    """
    indices: dict[str, int] = {}

    target_aliases: dict[str, set[str]] = {
        "id": {"id", "variantid", "variant_id"},
        "gene": {"gene", "gene_symbol", "symbol", "genesymbol"},
        "chr": {"chr", "chromosome", "chrom"},
        "pos": {"pos", "position", "start"},
        "ref": {"ref", "reference", "reference_allele"},
        "alt": {"alt", "alternative", "alternate", "alternative_allele"},
    }

    # inspect each column in order
    for idx, item in enumerate(header):
        # extract candidate names from item
        item_names: list[str] = []
        if isinstance(item, str):
            item_names.append(item.lower())
        elif isinstance(item, dict):
            if "id" in item and item["id"]:
                item_names.append(str(item["id"]).lower())
            if "title" in item and item["title"]:
                item_names.append(str(item["title"]).lower())
        else:
            if hasattr(item, "id") and item.id:
                item_names.append(str(item.id).lower())
            if hasattr(item, "title") and item.title:
                item_names.append(str(item.title).lower())

        # match against canonical targets
        for target, aliases in target_aliases.items():
            if target not in indices and any(name in aliases for name in item_names):
                indices[target] = idx

    return indices


def stream_snv_json_payload(
    resp: requests.Response,
    chunk_size: int = 65536,
    metadata_out: dict[str, Any] | None = None,
) -> Iterator[list[Any]]:
    """
    Streams 2D variant row arrays incrementally from a Varvis SNV JSON response.

    Parses the response stream in a single pass with constant memory overhead. Handles
    arbitrary key ordering in the root JSON object (including payloads where 'data' precedes
    'header'). Populates metadata_out with non-data keys as they are encountered.

    :param resp: Streaming requests.Response object.
    :param chunk_size: Read chunk size in bytes for the HTTP stream.
    :param metadata_out: Optional dictionary to collect metadata fields such as 'header'.
    :return: An iterator yielding individual variant row lists.
    :raises VarvisError: If the payload is malformed or terminates prematurely.
    """
    decoder = json.JSONDecoder()
    utf8_decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    pos = 0

    chunk_iter = resp.iter_content(chunk_size=chunk_size)

    # fetch next available chunk from stream into buffer
    def fetch_more() -> bool:
        nonlocal buffer, pos
        # compact buffer when read position exceeds threshold
        if pos >= _BUFFER_COMPACTION_THRESHOLD:
            buffer = buffer[pos:]
            pos = 0
        while True:
            try:
                chunk = next(chunk_iter)
            except StopIteration:
                return False
            if chunk:
                decoded = utf8_decoder.decode(chunk, final=False)
                if decoded:
                    buffer += decoded
                    return True

    # ensure buffer has at least required characters past pos
    def ensure_chars(count: int = 1) -> bool:
        while len(buffer) - pos < count:
            if not fetch_more():
                return len(buffer) - pos >= count
        return True

    # advance pointer past whitespace
    def skip_whitespace() -> None:
        nonlocal pos
        while True:
            while pos < len(buffer) and buffer[pos] in " \t\r\n":
                pos += 1
            if pos < len(buffer) or not fetch_more():
                break

    # ensure root object starts with opening brace
    skip_whitespace()
    if not ensure_chars(1) or buffer[pos] != "{":
        raise VarvisError("Malformed SNV JSON response: expected '{' at root")
    pos += 1

    # iterate root object key-value pairs
    while True:
        skip_whitespace()
        if not ensure_chars(1):
            raise VarvisError("Unexpected EOF while reading JSON root object")
        if buffer[pos] == "}":
            pos += 1
            break

        # decode object key string
        while True:
            try:
                key, pos = decoder.raw_decode(buffer, pos)
                break
            except json.JSONDecodeError:
                if not fetch_more():
                    raise VarvisError("Unexpected EOF while parsing JSON object key") from None

        skip_whitespace()
        if not ensure_chars(1) or buffer[pos] != ":":
            raise VarvisError(f"Malformed JSON: expected ':' after key '{key}'")
        pos += 1
        skip_whitespace()

        # handle data array streaming
        if key == "data":
            if not ensure_chars(1) or buffer[pos] != "[":
                raise VarvisError("Expected '[' at start of 'data' array")
            pos += 1

            while True:
                skip_whitespace()
                if not ensure_chars(1):
                    raise VarvisError("Unexpected EOF inside 'data' array")
                if buffer[pos] == "]":
                    pos += 1
                    break

                # decode single variant row array
                while True:
                    try:
                        row, end_idx = decoder.raw_decode(buffer, pos)
                        pos = end_idx
                        break
                    except json.JSONDecodeError:
                        if not fetch_more():
                            raise VarvisError("Unexpected EOF while parsing row array") from None

                if not isinstance(row, list):
                    raise VarvisError(f"Expected list for variant row, got {type(row).__name__}")

                yield row

                skip_whitespace()
                if not ensure_chars(1):
                    raise VarvisError("Unexpected EOF after row array")
                if buffer[pos] == ",":
                    pos += 1
                elif buffer[pos] == "]":
                    pos += 1
                    break
                else:
                    raise VarvisError(f"Expected ',' or ']' in 'data' array, found '{buffer[pos]}'")
        else:
            # decode metadata value
            while True:
                try:
                    val, end_idx = decoder.raw_decode(buffer, pos)
                    pos = end_idx
                    if metadata_out is not None:
                        metadata_out[key] = val
                    break
                except json.JSONDecodeError:
                    if not fetch_more():
                        raise VarvisError(f"Unexpected EOF while parsing value for key '{key}'") from None

        skip_whitespace()
        if ensure_chars(1) and buffer[pos] == ",":
            pos += 1
