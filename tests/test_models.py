"""
Tests for varvis_connector data models.

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Bernt Popp <bernt.popp@laborberlin.com>
"""

from typing import Any
import pytest
from pydantic import ValidationError

from varvis_connector.models import (
    CaseReport,
    CaseReportAnalysis,
    CaseReportMethodsItem,
    CaseReportPersonItem,
)
from varvis_connector._varvis_client import _parse_response_for_model


@pytest.mark.parametrize("input_key", ["type", "analysisType"])
@pytest.mark.parametrize("kind", ["SNV", "CNV", "STR"])
def test_analysis_discriminator_survives_parsing(input_key: str, kind: str):
    payload = {
        "analysisId": 900001,
        "enrichmentKit": "SyntheticKit",
        "sourceId": "synthetic",
        "annotationSources": [],
        "selected": True,
        input_key: kind,
    }
    parsed = CaseReportAnalysis.model_validate(payload)
    assert parsed.analysisType == kind


def test_analysis_discriminator_precedence():
    """Wire key 'type' takes precedence over legacy 'analysisType' if both are provided."""
    payload = {
        "analysisId": 900001,
        "enrichmentKit": "SyntheticKit",
        "sourceId": "synthetic",
        "annotationSources": [],
        "selected": True,
        "type": "SNV",
        "analysisType": "CNV",
    }
    parsed = CaseReportAnalysis.model_validate(payload)
    assert parsed.analysisType == "SNV"


def test_analysis_discriminator_optional_and_null():
    """Missing or None discriminator values evaluate to None."""
    payload_missing: dict[str, Any] = {
        "analysisId": 900001,
        "enrichmentKit": "SyntheticKit",
        "sourceId": "synthetic",
        "annotationSources": [],
        "selected": True,
    }
    parsed_missing = CaseReportAnalysis.model_validate(payload_missing)
    assert parsed_missing.analysisType is None

    payload_null_type: dict[str, Any] = {**payload_missing, "type": None}
    parsed_null_type = CaseReportAnalysis.model_validate(payload_null_type)
    assert parsed_null_type.analysisType is None

    payload_null_legacy: dict[str, Any] = {**payload_missing, "analysisType": None}
    parsed_null_legacy = CaseReportAnalysis.model_validate(payload_null_legacy)
    assert parsed_null_legacy.analysisType is None


def test_analysis_discriminator_validation():
    """Invalid analysisType values are rejected with ValidationError."""
    payload_invalid_wire = {
        "analysisId": 900001,
        "enrichmentKit": "SyntheticKit",
        "sourceId": "synthetic",
        "annotationSources": [],
        "selected": True,
        "type": "INVALID_KIND",
    }
    with pytest.raises(ValidationError):
        CaseReportAnalysis.model_validate(payload_invalid_wire)

    payload_invalid_legacy = {
        "analysisId": 900001,
        "enrichmentKit": "SyntheticKit",
        "sourceId": "synthetic",
        "annotationSources": [],
        "selected": True,
        "analysisType": "INVALID_KIND",
    }
    with pytest.raises(ValidationError):
        CaseReportAnalysis.model_validate(payload_invalid_legacy)


def test_analysis_serialization_contract():
    """Serialization preserves the public attribute name 'analysisType' without extra fields."""
    payload = {
        "analysisId": 900001,
        "enrichmentKit": "SyntheticKit",
        "sourceId": "synthetic",
        "annotationSources": [],
        "selected": True,
        "type": "SNV",
    }
    parsed = CaseReportAnalysis.model_validate(payload)
    dumped = parsed.model_dump()
    assert dumped["analysisType"] == "SNV"
    assert "type" not in dumped
    assert dumped["analysisId"] == 900001
    assert dumped["selected"] is True


def _synthetic_case_report_raw() -> dict[str, Any]:
    analyses_raw = [
        {
            "analysisId": 900001,
            "type": "SNV",
            "sampleId": "SAMPLE-1",
            "enrichmentKit": "TwistExomev2",
            "sourceId": "varvis 2.10.0",
            "annotationSources": [{"name": "CLINVAR", "value": "2026-01"}],
            "selected": True,
        },
        {
            "analysisId": 900002,
            "type": "CNV",
            "sampleId": "SAMPLE-1",
            "enrichmentKit": "TwistExomev2",
            "sourceId": "varvis 2.10.0",
            "annotationSources": [{"name": "DECIPHER", "value": "2026-01"}],
            "selected": True,
        },
        {
            "analysisId": 900003,
            "type": "SNV",
            "sampleId": "SAMPLE-1",
            "enrichmentKit": "NimagenHEST_hg38_v2",
            "sourceId": "varvis 2.10.0",
            "annotationSources": [],
            "selected": False,
        },
    ]
    return {
        "draft": False,
        "personId": 12345,
        "submitter": "Synthetic Submitter",
        "submitted": "2026-09-01T10:00:00",
        "approver": None,
        "approved": None,
        "title": "Synthetic Report",
        "comment": None,
        "reportState": "SUBMITTED",
        "items": [
            {
                "type": "PERSON",
                "personId": 12345,
                "limsId": "SYNTH-LIMS-001",
                "familyId": None,
                "hpoTerms": [],
                "comment": None,
                "analyses": analyses_raw,
                "active": True,
            },
            {
                "type": "METHODS",
                "analyses": analyses_raw,
                "active": True,
            },
        ],
    }


def test_nested_case_report_parsing_preserves_wire_type():
    raw = _synthetic_case_report_raw()
    report = CaseReport.model_validate(raw)

    person_items = [i for i in report.items if isinstance(i, CaseReportPersonItem)]
    assert len(person_items) == 1
    person_analyses = person_items[0].analyses
    assert len(person_analyses) == 3
    assert [a.analysisType for a in person_analyses] == ["SNV", "CNV", "SNV"]
    assert [a.selected for a in person_analyses] == [True, True, False]

    methods_items = [i for i in report.items if isinstance(i, CaseReportMethodsItem)]
    assert len(methods_items) == 1
    methods_analyses = methods_items[0].analyses
    assert len(methods_analyses) == 3
    assert [a.analysisType for a in methods_analyses] == ["SNV", "CNV", "SNV"]
    assert [a.selected for a in methods_analyses] == [True, True, False]


def test_client_response_parser_preserves_nested_wire_type():
    raw = _synthetic_case_report_raw()

    class _MockResponse:
        text = "dummy"

        def json(self):
            return {"success": True, "response": raw}

    report = _parse_response_for_model(CaseReport, _MockResponse(), data_from_key="response")  # type: ignore[arg-type]
    methods_item = next(i for i in report.items if isinstance(i, CaseReportMethodsItem))
    assert methods_item.analyses[0].analysisType == "SNV"
    assert methods_item.analyses[1].analysisType == "CNV"
    assert methods_item.analyses[2].analysisType == "SNV"
