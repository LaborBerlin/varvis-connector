"""
varvis_connector pytest common test helpers.

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

import pytest

MOCK_URL = "https://playground.varvis.com/"


@pytest.fixture
def varvis_mockapi_with_login(requests_mock):
    requests_mock.head(
        MOCK_URL,
        headers={"X-CSRF-TOKEN": "mock_csrf_pre_login"},
        cookies={"session": "mock_session_pre_login"},
    )
    requests_mock.post(
        MOCK_URL + "login",
        headers={"X-CSRF-TOKEN": "mock_csrf_post_login", "BUILD-VERSION": "mock-build"},
        cookies={"session": "mock_session_post_login"},
    )
    requests_mock.post(MOCK_URL + "logout")

    return requests_mock


def create_varvis_mockapi_downloads(
    mockapi,
    analysis_id,
    expect_error,
    simulate_file_exists,
    output_path,
    fname_prepend="",
):
    mocked_extensions = ["bam", "gz", "bai", "vcf", "archive"]
    mocked_files = [
        f"{fname_prepend}mock-file{i}.{ext}"
        for i, ext in enumerate(mocked_extensions, 1)
    ]

    for f in mocked_files:
        mockapi.get("https://mock-dl/" + f, content=b"testdata")

    mocked_files.extend([".", " "])  # simulate invalid file names

    dl_links_url = f"https://playground.varvis.com/api/analysis/{analysis_id}/get-file-download-links"
    if expect_error is None or expect_error is False:
        mockapi.get(
            dl_links_url,
            json={
                "success": True,
                "response": {
                    "id": analysis_id,
                    "customerProvidedInputFilePaths": ["upload/mock-file.ext"],
                    "apiFileLinks": [
                        {
                            "fileName": f,
                            "downloadLink": "https://mock-dl/" + f,
                            "currentlyArchived": f.endswith(".archive"),
                        }
                        for f in mocked_files
                    ],
                },
            },
        )
    else:
        mockapi.get(dl_links_url, status_code=400)

    if simulate_file_exists:
        (output_path / mocked_files[0]).write_text("already existed")

    return mocked_files
