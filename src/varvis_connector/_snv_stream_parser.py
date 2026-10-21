"""
SNV annotations streaming parser module for Varvis API responses.

Provides incremental, low-memory streaming of large 2D variant arrays directly
from HTTP responses or binary files using standard library JSON decoding.

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Bernt Popp <bernt.popp@laborberlin.com>
:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

import codecs
import json
import re
from collections.abc import Iterator, Sequence
from typing import Any, BinaryIO, cast

import requests

from .errors import VarvisError

# buffer compaction threshold in characters
_BUFFER_COMPACTION_THRESHOLD = 65536

# locate value boundaries without scanning ordinary string content in Python
_CONTAINER_SPECIAL = re.compile(r'[\[\]{}"]')
_STRING_SPECIAL = re.compile(r'["\\]')
_SCALAR_DELIMITER = re.compile(r"[ \t\r\n,\]}]")


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
        "id": {"id", "variantid", "variant_id", "internal_id"},
        "gene": {"gene", "gene_symbol", "symbol", "genesymbol"},
        "chr": {"chr", "chromosome", "chrom"},
        "pos": {"pos", "position", "start", "genomic_position"},
        "ref": {"ref", "reference", "reference_allele"},
        "alt": {"alt", "alternative", "alternate", "alternative_allele"},
    }

    # inspect each column in order
    for idx, item in enumerate(header):
        # extract candidate names from item
        raw_candidates: list[str] = []
        if isinstance(item, str):
            raw_candidates.append(item)
        elif isinstance(item, dict):
            if "id" in item and item["id"]:
                raw_candidates.append(str(item["id"]))
            if "title" in item and item["title"]:
                raw_candidates.append(str(item["title"]))
        else:
            if hasattr(item, "id") and item.id:
                raw_candidates.append(str(item.id))
            if hasattr(item, "title") and item.title:
                raw_candidates.append(str(item.title))

        # normalize candidates to handle spaces and formatting variations
        item_names: set[str] = set()
        for cand in raw_candidates:
            clean = cand.strip().lower()
            item_names.add(clean)
            item_names.add(clean.replace(" ", "_"))
            item_names.add(clean.replace(" ", ""))

        # match against canonical targets
        for target, aliases in target_aliases.items():
            if target not in indices and any(name in aliases for name in item_names):
                indices[target] = idx

    return indices


def stream_snv_json_from_request_or_buffer(
    input_stream: requests.Response | BinaryIO,
    chunk_size: int = 65536,
    metadata_out: dict[str, Any] | None = None,
) -> Iterator[list[Any]]:
    """
    Streams 2D variant row arrays incrementally from a Varvis SNV JSON response.

    Decodes complete values directly and scans incomplete values incrementally before retrying once.
    Memory usage depends on the largest row or metadata value, plus collected metadata.
    Values spanning chunks are retained as fragments and joined once before decoding.
    Numeric metadata is decoded only when a delimiter confirms that its token is complete.
    Handles arbitrary key ordering in the root JSON object (including payloads where 'data' precedes
    'header'). Populates metadata_out with non-data keys as they are encountered.
    Binary input is read from its current position without rewinding. UTF-8 characters
    split across chunks are decoded incrementally. The caller owns closing the input.

    :param input_stream: HTTP response or readable binary file, including temporary-file wrappers.
    :param chunk_size: Read chunk size in bytes for the HTTP response or binary file.
    :param metadata_out: Optional dictionary to collect metadata fields such as 'header'.
    :return: An iterator yielding individual variant row lists.
    :raises VarvisError: If the payload is malformed or terminates prematurely.
    """
    decoder = json.JSONDecoder()
    utf8_decoder = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    pos = 0

    if isinstance(input_stream, requests.Response):
        input_iter = input_stream.iter_content(chunk_size=chunk_size)
    else:
        input_iter = None

    # fetch next available chunk from stream into buffer
    def fetch_more() -> bool:
        nonlocal buffer, pos
        # compact buffer when read position exceeds threshold
        if pos >= _BUFFER_COMPACTION_THRESHOLD:
            buffer = buffer[pos:]
            pos = 0
        while True:
            if input_iter is None:
                # read binary streams including temporary-file wrappers
                chunk = cast(BinaryIO, input_stream).read(chunk_size)
            else:
                try:
                    chunk = next(input_iter)
                except StopIteration:
                    return False

            if chunk:
                decoded = utf8_decoder.decode(chunk, final=False)
                if decoded:
                    buffer += decoded
                    return True

            if input_iter is None and (not chunk or len(chunk) < chunk_size):
                return False

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

    # collect complete keys, rows, and metadata without repeatedly decoding their prefixes
    def read_value(context: str) -> Any:
        """Decode a value, scanning across chunks before retrying an incomplete prefix once."""
        nonlocal buffer, pos
        if not ensure_chars(1):
            raise VarvisError(f"Unexpected EOF while parsing {context}")

        # keep complete values on the JSON decoder's fast path and confirm scalar delimiters
        scalar = buffer[pos] not in '[{"'
        try:
            value, end = decoder.raw_decode(buffer, pos)
            if not scalar or (end < len(buffer) and buffer[end] in " \t\r\n,]}"):
                pos = end
                return value
        except json.JSONDecodeError:
            pass

        # retain boundary state and text fragments for the current value
        closers: list[str] = []
        in_string = False
        escaped = False
        fragments: list[str] = []
        scan = pos
        complete = False
        while not complete:
            while scan < len(buffer):
                # an escape consumes the next character even across a chunk boundary
                if escaped:
                    scan += 1
                    escaped = False
                    continue

                pattern = _SCALAR_DELIMITER if scalar else _STRING_SPECIAL if in_string else _CONTAINER_SPECIAL
                match = pattern.search(buffer, scan)
                if match is None:
                    scan = len(buffer)
                    break
                scan = match.start()
                if scalar:
                    complete = True
                    break

                # track strings and nested containers while leaving syntax validation to JSONDecoder
                char = buffer[scan]
                scan += 1
                if in_string:
                    if char == "\\":
                        escaped = True
                    else:
                        in_string = False
                        complete = not closers
                elif char == '"':
                    in_string = True
                elif char in "[{":
                    closers.append("]" if char == "[" else "}")
                elif not closers or char != closers.pop():
                    raise VarvisError(f"Malformed JSON while parsing {context}: mismatched closing bracket")
                else:
                    complete = not closers
                if complete:
                    break

            if not complete:
                # release consumed input and keep fragments without copying the accumulated prefix
                fragments.append(buffer[pos:scan])
                buffer = ""
                pos = scan = 0
                if not fetch_more():
                    raise VarvisError(f"Unexpected EOF while parsing {context}")

        # join fragmented values once and reject trailing invalid characters inside the boundary
        if fragments:
            fragments.append(buffer[pos:scan])
            text = "".join(fragments)
        else:
            text = buffer
        start = 0 if fragments else pos
        end = len(text) if fragments else scan
        try:
            value, decoded_end = decoder.raw_decode(text, start)
            if decoded_end != end:
                raise VarvisError(f"Malformed JSON while parsing {context}: invalid value")
        except json.JSONDecodeError as error:
            raise VarvisError(f"Malformed JSON while parsing {context}: {error.msg}") from error
        pos = scan
        return value

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
        key = read_value("JSON object key")
        if not isinstance(key, str):
            raise VarvisError("Malformed JSON: expected a string object key")

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
                row = read_value("row array")

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
            val = read_value(f"value for key '{key}'")
            if metadata_out is not None:
                metadata_out[key] = val

        skip_whitespace()
        if ensure_chars(1) and buffer[pos] == ",":
            pos += 1
