"""
Tests for the command line interface.
"""

import json
import os
import random
import sys
from fnmatch import fnmatchcase
from io import StringIO
from unittest import mock

import pytest
from polyfactory.factories.pydantic_factory import ModelFactory

import varvis_connector
from varvis_connector import VarvisClient
from varvis_connector._cli import VarvisCLI
from varvis_connector.__main__ import main
from varvis_connector.models import (
    SnvAnnotationData,
    CnvTargetResults,
    PendingCnvData,
    QCCaseMetricsData,
    CoverageData,
    AnalysisItem,
    PersonReportItem,
    CaseReport,
    FindByInputFileNameAnalysisItem,
    AnalysisFileDownloadLinks,
    PersonData,
    PersonUpdateData,
    VirtualPanelData,
    VirtualPanelSummary,
    VarvisGene,
    VirtualPanelUpdateData,
)

from ._common import (
    MOCK_URL,
    varvis_mockapi_with_login as varvis_mockapi_with_login,
    create_varvis_mockapi_downloads,
)  # "as ..." prevents removal of fixture as "unused" by ruff linter

POLYFACTORY_RANDOM_SEED = 20260226


class SnvAnnotationDataFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = SnvAnnotationData


class CnvTargetResultsFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = CnvTargetResults


class PendingCnvDataFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = PendingCnvData


class QCCaseMetricsDataFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = QCCaseMetricsData


class CoverageDataFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = CoverageData


class AnalysisItemFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = AnalysisItem


class PersonReportItemFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = PersonReportItem


class CaseReportFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = CaseReport


class PersonDataFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = PersonData


class PersonUpdateDataFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = PersonUpdateData


class FindByInputFileNameAnalysisItemFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = FindByInputFileNameAnalysisItem


class AnalysisFileDownloadLinksFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = AnalysisFileDownloadLinks


class VirtualPanelSummaryFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = VirtualPanelSummary


class VarvisGeneFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = VarvisGene


class VirtualPanelDataFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = VirtualPanelData


class VirtualPanelUpdateDataFactory(ModelFactory):
    __random_seed__ = POLYFACTORY_RANDOM_SEED
    __model__ = VirtualPanelUpdateData


@pytest.fixture()
def monkeypatch_clean_env(monkeypatch):
    envvars = {
        "VARVIS_URL",
        "VARVIS_USER",
        "VARVIS_PASSWORD",
        "HTTPS_PROXY",
        "VARVIS_SSL_VERIFY",
    }
    for var in envvars:
        if os.getenv(var) is not None:
            monkeypatch.delenv(var)

    yield monkeypatch

    monkeypatch.delenv("TEST_DONT_RUN_CMD", raising=False)
    monkeypatch.delenv("TEST_RETURN_CLI", raising=False)


def test_version(capfd, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["varvis_connector", "--version"])

    with pytest.raises(SystemExit):
        # this is normal; argparse calls system exit
        main()

    captured = capfd.readouterr()
    stdout_text = captured.out.strip()
    assert stdout_text == f"varvis_connector v{varvis_connector.__version__}"


def test_help(capfd, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["varvis_connector", "--help"])

    with pytest.raises(SystemExit):
        # this is normal; argparse calls system exit
        main()

    captured = capfd.readouterr()
    assert captured.out.strip().startswith("usage: varvis_connector [-h] ")


@pytest.mark.parametrize(
    "drop_arg, set_envvar, expected_value",
    [
        ("api-url", "VARVIS_URL", "https://example.com/"),
        ("api-url", None, SystemExit),
        ("username", "VARVIS_USER", "foouser"),
        ("username", None, SystemExit),
        ("password", "VARVIS_PASSWORD", "foopw"),
        ("password", None, None),
    ],
)
def test_required_args(
    capfd, monkeypatch_clean_env, drop_arg, set_envvar, expected_value
):
    required_args = [
        "--api-url",
        "https://foo.com/",
        "--username",
        "testuser",
        "--password",
        "testpass",
    ]

    if drop_arg:
        drop_idx = required_args.index(f"--{drop_arg}")
        required_args.pop(drop_idx)  # first pop for arg name
        required_args.pop(drop_idx)  # second pop for arg value

    if set_envvar:
        monkeypatch_clean_env.setenv(set_envvar, expected_value)

    monkeypatch_clean_env.setattr(
        sys, "argv", ["varvis_connector"] + required_args + ["check-login"]
    )

    if expected_value is SystemExit:
        with pytest.raises(SystemExit):
            main()
        captured = capfd.readouterr()
        assert f'Option "{drop_arg}" is required' in captured.err
    else:
        monkeypatch_clean_env.setenv("TEST_DONT_RUN_CMD", "1")
        monkeypatch_clean_env.setenv("TEST_RETURN_CLI", "1")
        if drop_arg == "password" and set_envvar is None and expected_value is None:
            with mock.patch("getpass.getpass", return_value="secret") as mock_getpass:
                cli = main()
                mock_getpass.assert_called_once()
        else:
            cli = main()

        assert isinstance(cli, VarvisCLI)
        assert isinstance(cli._client, VarvisClient)
        assert cli._client.ssl_verify
        assert cli._client.connection_timeout == 10.0
        assert cli._client.backoff_factor_seconds == 0.5
        assert cli._client.backoff_max_tries == 5

        for i in range(0, len(required_args), 2):
            arg, val = required_args[i : i + 2]
            fieldname = arg.removeprefix("--").replace("-", "_")
            assert getattr(cli._client, fieldname) == val

        if set_envvar:
            fieldname = drop_arg.replace("-", "_")
            assert getattr(cli._client, fieldname) == expected_value


@pytest.mark.parametrize(
    "argname, argvalue, set_envvar, envvalue",
    [
        ("https-proxy", "https://proxy.example.com/", None, None),
        ("https-proxy", None, "HTTPS_PROXY", "https://proxy.example.com/"),
        (
            "https-proxy",
            "https://proxy.example.com/",
            "HTTPS_PROXY",
            "https://proxybyenv.example.com/",
        ),
        ("disable-ssl-verify", False, None, None),
        ("disable-ssl-verify", None, "VARVIS_SSL_VERIFY", "0"),
        ("connection-timeout", 1.5, None, None),
        ("connection-timeout", None, "VARVIS_CONNECTION_TIMEOUT", 1.52),
        ("backoff-factor-seconds", 0, None, None),
        ("backoff-factor-seconds", None, "VARVIS_BACKOFF_FACTOR_SECONDS", 1.3),
        ("backoff-max-tries", 2, None, None),
        ("backoff-max-tries", None, "VARVIS_BACKOFF_MAX_TRIES", 3),
    ],
)
def test_optional_args(monkeypatch_clean_env, argname, argvalue, set_envvar, envvalue):
    args = [
        "--api-url",
        "https://foo.com/",
        "--username",
        "testuser",
        "--password",
        "testpass",
    ]

    if argname is not None and argvalue is not None:
        if argname == "disable-ssl-verify":
            args.append("--disable-ssl-verify")
        else:
            args.extend([f"--{argname}", str(argvalue)])

    if set_envvar is not None and envvalue is not None:
        monkeypatch_clean_env.setenv(set_envvar, str(envvalue))

    monkeypatch_clean_env.setattr(
        sys, "argv", ["varvis_connector"] + args + ["check-login"]
    )

    monkeypatch_clean_env.setenv("TEST_DONT_RUN_CMD", "1")
    monkeypatch_clean_env.setenv("TEST_RETURN_CLI", "1")
    cli = main()
    fieldname = (
        "ssl_verify" if argname == "disable-ssl-verify" else argname.replace("-", "_")
    )

    assert isinstance(cli, VarvisCLI)
    client_val = getattr(cli._client, fieldname)
    if set_envvar and not argvalue:
        if set_envvar == "VARVIS_SSL_VERIFY":
            assert client_val is False
        else:
            assert client_val == envvalue
    else:
        if argname == "disable-ssl-verify":
            assert client_val is False
        else:
            assert client_val == argvalue


def test_check_login(capfd, monkeypatch, varvis_mockapi_with_login):
    args = [
        "--api-url",
        MOCK_URL,
        "--username",
        "mockuser",
        "--password",
        "mockpw",
    ]
    monkeypatch.setattr(sys, "argv", ["varvis_connector"] + args + ["check-login"])
    assert varvis_mockapi_with_login

    main()

    captured = capfd.readouterr()
    stdout_text = captured.out
    assert "Login successful" in stdout_text
    assert "Logout successful" in stdout_text


@pytest.mark.parametrize(
    "lims_ids_and_expected_personal_ids, output_to_file, output_indent",
    [
        ({"LIMS-1": 12345}, False, None),
        ({"LIMS-1": 12345, "LIMS-nonexistent": None, "LIMS-3": 6789}, False, None),
        ({"LIMS-1": 12345, "LIMS-nonexistent": None, "LIMS-3": 6789}, False, 2),
        ({"LIMS-nonexistent": None}, False, None),
        ({"LIMS-1": 12345, "LIMS-nonexistent": None, "LIMS-3": 6789}, True, None),
        ({"LIMS-1": 12345, "LIMS-nonexistent": None, "LIMS-3": 6789}, True, 8),
    ],
)
def test_get_internal_person_id(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    lims_ids_and_expected_personal_ids,
    output_to_file,
    output_indent,
):
    further_args = lims_ids_and_expected_personal_ids.keys()
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-internal-person-id",
        output_to_file,
        output_indent,
        further_args,
    )

    expected_output = {}
    for lims_id, expected_personal_id in lims_ids_and_expected_personal_ids.items():
        if expected_personal_id is not None:
            varvis_mockapi_with_login.get(
                MOCK_URL + f"api/person/{lims_id}/id",
                json={"response": expected_personal_id, "success": True},
            )
            expected_output[lims_id] = expected_personal_id

    _run_cmd_and_check_output(
        capfd, output_file, output_indent, expected_output or None
    )


@pytest.mark.parametrize(
    "analysis_ids_and_expected_data, output_to_file, output_indent",
    [
        ({1: True}, False, None),
        ({1: True, 2: True, 3: False}, False, None),
        ({1: True, 2: True, 3: False}, False, 2),
        ({2: False}, False, None),
        ({1: False, 2: True, 3: True}, True, None),
        ({1: False, 2: True, 3: True}, True, 8),
    ],
)
def test_get_snv_annotations(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    analysis_ids_and_expected_data,
    output_to_file,
    output_indent,
):
    further_args = list(map(str, analysis_ids_and_expected_data.keys()))
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-snv-annotations",
        output_to_file,
        output_indent,
        further_args,
    )

    expected_output = {}
    for a_id, expected_data in analysis_ids_and_expected_data.items():
        if expected_data:
            snv_annotation_data = SnvAnnotationDataFactory.build()
            snv_annotation_data_dict = snv_annotation_data.model_dump(mode="json")
            varvis_mockapi_with_login.get(
                MOCK_URL + f"api/analysis/{a_id}/annotations",
                json=snv_annotation_data_dict,
            )
            # keys have to be strings in JSON
            expected_output[str(a_id)] = snv_annotation_data_dict

    _run_cmd_and_check_output(
        capfd, output_file, output_indent, expected_output or None
    )


@pytest.mark.parametrize(
    "lims_id, analysis_ids, virt_panel_id, expect_success, output_to_file, output_indent",
    [
        ("LIMS-1", [1], None, True, False, None),
        ("LIMS-abc", [1, 2], "none", True, False, None),
        ("foobar", [1, 2], 3, True, False, None),
        ("testestest", [1], None, False, False, None),
        ("LIMS-3", [1, 2], "none", True, True, None),
        ("LIMS-99", [1, 2], 3, True, True, 2),
        ("LIMS-99", [1, 2], 3, True, True, 0),
    ],
)
def test_get_cnv_target_results(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    lims_id,
    analysis_ids,
    virt_panel_id,
    expect_success,
    output_to_file,
    output_indent,
):
    further_args = [lims_id] + list(map(str, analysis_ids))
    if virt_panel_id is not None:
        further_args.extend(["--virtual-panel-id", str(virt_panel_id)])

    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-cnv-target-results",
        output_to_file,
        output_indent,
        further_args,
    )

    if expect_success:
        expected_output = CnvTargetResultsFactory.build().model_dump(mode="json")
        expected_err_msg = None

        varvis_mockapi_with_login.get(
            MOCK_URL + f"api/results/{lims_id}/cnv",
            json=expected_output,
        )
    else:
        varvis_mockapi_with_login.get(
            MOCK_URL + f"api/results/{lims_id}/cnv",
            status_code=404,
        )

        expected_output = None
        expected_err_msg = "Could not retrieve CNV target results for LIMS-ID"

    _run_cmd_and_check_output(
        capfd, output_file, output_indent, expected_output, expected_err_msg
    )


@pytest.mark.parametrize(
    "lims_id, internal_person_id, analysis_ids, virt_panel_id, expect_success, output_to_file, output_indent",
    [
        ("LIMS-1", None, [1], None, True, False, None),
        ("LIMS-abc", None, [1, 2], "none", True, False, None),
        (None, 3, [1, 2], 3, True, False, None),
        (None, 999, [1], "none", False, False, None),
        ("LIMS-3", None, [1, 2], None, True, True, None),
        ("LIMS-99", None, [1, 2], 3, True, True, 2),
        (None, 123, [1, 2], 3, True, True, 0),
    ],
)
def test_get_pending_cnv_segments(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    lims_id,
    internal_person_id,
    analysis_ids,
    virt_panel_id,
    expect_success,
    output_to_file,
    output_indent,
):
    if lims_id:
        further_args = ["--lims-id", lims_id]
    else:
        further_args = ["--internal-person-id", str(internal_person_id)]

    further_args += list(map(str, analysis_ids))
    if virt_panel_id is not None:
        further_args.extend(["--virtual-panel-id", str(virt_panel_id)])

    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-pending-cnv-segments",
        output_to_file,
        output_indent,
        further_args,
    )

    if expect_success:
        expected_output = PendingCnvDataFactory.build().model_dump(mode="json")
        expected_err_msg = None

        if lims_id:
            varvis_mockapi_with_login.get(
                MOCK_URL + f"api/person/{lims_id}/id",
                json={"response": 12345, "success": True},
            )
    else:
        expected_output = None
        expected_err_msg = (
            "Could not retrieve pending CNV segments for internal person ID"
        )

    varvis_mockapi_with_login.get(
        MOCK_URL + "pending-cnv",
        json={"response": expected_output, "success": True},
    )

    _run_cmd_and_check_output(
        capfd, output_file, output_indent, expected_output, expected_err_msg
    )


@pytest.mark.parametrize(
    "lims_ids, expect_success, output_to_file, output_indent",
    [
        (["LIMS-1"], True, False, None),
        (["LIMS-abc", "LIMS-1"], True, False, None),
        (["LIMS-99"], True, True, 2),
        (["LIMS-99"], False, True, 2),
    ],
)
def test_get_qc_case_metrics(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    lims_ids,
    expect_success,
    output_to_file,
    output_indent,
):
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-qc-case-metrics",
        output_to_file,
        output_indent,
        lims_ids,
    )

    if expect_success:
        expected_output = {}
        for lims_id in lims_ids:
            data = QCCaseMetricsDataFactory.build().model_dump(mode="json")
            expected_output[lims_id] = data
            mock_data = data.copy()
            metric_results = mock_data.pop("metricResults")
            mock_data["metricResults"] = {lims_id: metric_results}

            varvis_mockapi_with_login.get(
                MOCK_URL + f"api/qualitycontrol/metrics/case/{lims_id}",
                json={"response": mock_data, "success": True},
            )
    else:
        expected_output = None

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "lims_ids, virtual_panel_id, expect_success, output_to_file, output_indent",
    [
        (["LIMS-1"], None, True, False, None),
        (["LIMS-abc", "LIMS-1"], 1, True, False, None),
        (["LIMS-99"], 2, True, True, 2),
        (["LIMS-99"], "none", False, True, 2),
    ],
)
def test_get_coverage_data(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    lims_ids,
    virtual_panel_id,
    expect_success,
    output_to_file,
    output_indent,
):
    further_args = []
    if virtual_panel_id is not None:
        further_args.extend(["--virtual-panel-id", str(virtual_panel_id)])
    further_args.extend(lims_ids)
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-coverage-data",
        output_to_file,
        output_indent,
        further_args,
    )

    if expect_success:
        expected_output = {}
        for lims_id in lims_ids:
            n_items = random.randint(1, 10)
            data = [
                CoverageDataFactory.build().model_dump(mode="json")
                for _ in range(n_items)
            ]
            expected_output[lims_id] = data

            varvis_mockapi_with_login.get(
                MOCK_URL + f"api/{lims_id}/coverage",
                json=data,
            )
    else:
        expected_output = None

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "analysis_ids, output_to_file, output_indent",
    [
        (None, False, None),
        ([2, 3], False, None),
        (None, True, 2),
    ],
)
def test_get_analyses(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    analysis_ids,
    output_to_file,
    output_indent,
):
    further_args = []
    if analysis_ids is not None:
        further_args.extend(["--analysis-ids"] + list(map(str, analysis_ids)))

    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-analyses",
        output_to_file,
        output_indent,
        further_args,
    )

    expected_output = []
    if analysis_ids is None:
        ids = list(range(1, 10))
    else:
        ids = analysis_ids
    mock_data = []
    for id_ in ids:
        model_instance = AnalysisItemFactory.build(id=id_).model_dump(mode="json")
        mock_data.append(model_instance)
        expected_output.append(model_instance)

    varvis_mockapi_with_login.get(
        MOCK_URL + "api/analyses",
        json={"response": mock_data, "success": True},
    )

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "simulate_output_size, output_to_file, output_indent",
    [
        (0, False, None),
        (5, False, None),
        (10, True, 2),
    ],
)
def test_get_report_info_for_persons(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    simulate_output_size,
    output_to_file,
    output_indent,
):
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-report-info-for-persons",
        output_to_file,
        output_indent,
    )

    expected_output = []
    mock_data = []
    for i in range(1, simulate_output_size + 1):
        model_instance = PersonReportItemFactory.build(
            limsId=f"mock-person-{i}"
        ).model_dump(mode="json")
        mock_data.append(model_instance)
        expected_output.append(model_instance)

    varvis_mockapi_with_login.get(
        MOCK_URL + "api/cases/reports/info",
        json={"response": mock_data, "success": True},
    )

    _run_cmd_and_check_output(
        capfd, output_file, output_indent, expected_output or None
    )


@pytest.mark.parametrize(
    "lims_ids, expect_error, output_to_file, output_indent",
    [
        (["NON_EXISTENT"], True, None, None),
        (["P2-NA12878"], False, False, None),
        (["P2-NA12878", "P1-NA12878"], False, False, None),
        (["P2-NA12878", "NON_EXISTENT", "P1-NA12878"], False, True, 2),
    ],
)
def test_get_person_analyses(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    lims_ids,
    expect_error,
    output_to_file,
    output_indent,
):
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-person-analyses",
        output_to_file,
        output_indent,
        lims_ids,
    )

    if expect_error:
        expected_output = None
    else:
        expected_output = {}
        for lims_id in lims_ids:
            if lims_id == "NON_EXISTENT":
                continue

            mock_data = []
            for _ in range(random.randint(0, 4)):
                model_instance = AnalysisItemFactory.build(
                    personLimsId=lims_id
                ).model_dump(mode="json")
                mock_data.append(model_instance)
            expected_output[lims_id] = mock_data

            varvis_mockapi_with_login.get(
                MOCK_URL + f"person/{lims_id}/analyses",
                json=mock_data,
            )

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "lims_ids, draft, inactive, expect_error, output_to_file, output_indent",
    [
        (["NON_EXISTENT"], False, False, True, None, None),
        (["P2-NA12878"], False, False, False, False, None),
        (["P2-NA12878", "P1-NA12878"], False, False, False, False, None),
        (["P2-NA12878", "NON_EXISTENT", "P1-NA12878"], False, False, False, True, 2),
        (["P2-NA12878", "P3-DRAFT", "P1-NA12878"], True, True, False, False, 2),
    ],
)
def test_get_case_report(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    lims_ids,
    draft,
    inactive,
    expect_error,
    output_to_file,
    output_indent,
):
    further_args = lims_ids.copy()
    if draft:
        further_args.append("--draft")
    if inactive:
        further_args.append("--inactive")

    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-case-report",
        output_to_file,
        output_indent,
        further_args,
    )

    if expect_error:
        expected_output = None
    else:
        expected_output = {}
        for lims_id in lims_ids:
            if lims_id == "NON_EXISTENT":
                continue
            mock_data = CaseReportFactory.build(
                draft=lims_id.endswith("DRAFT")
            ).model_dump(mode="json")
            expected_output[lims_id] = mock_data

            varvis_mockapi_with_login.get(
                MOCK_URL + f"api/cases/{lims_id}/report",
                json={"response": mock_data, "success": True},
            )

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "lims_ids, output_to_file, output_indent, expect_error",
    [
        (["P1-NA12878", "200000000"], False, None, False),
        (["OCI3-QK333-Zelllinie-dx-twist", "NON_EXISTENT"], True, 1, False),
        (["NON_EXISTENT"], False, None, True),
    ],
)
def test_get_person(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    lims_ids,
    output_to_file,
    output_indent,
    expect_error,
):
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-person",
        output_to_file,
        output_indent,
        lims_ids,
    )

    if expect_error:
        expected_output = None
    else:
        expected_output = {}
        for lims_id in lims_ids:
            if lims_id == "NON_EXISTENT":
                continue
            mock_data = PersonDataFactory.build().model_dump(mode="json")
            mock_data["personalInformation"]["limsId"] = lims_id
            mock_data["clinicalInformation"]["limsId"] = lims_id
            expected_output[lims_id] = mock_data

            varvis_mockapi_with_login.get(
                MOCK_URL + f"api/person/{lims_id}",
                json={"response": mock_data, "success": True},
            )

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "set_data, input_from_file, expect_error",
    [
        ({}, None, None),
        ({}, "-", None),
        ({}, "test.json", None),
        (
            {"birthDateDay": "123"},
            None,
            "The provided birth date '1234-12-123' is not in the expected format YYYY-MM-DD",
        ),
        (
            {"id": None},
            None,
            "The LIMS ID must be provided when passing person data via CLI arguments",
        ),
        (
            {"id": None},
            "test2.json",
            "The provided JSON data is not valid",
        ),
    ],
)
def test_create_or_update_person(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    set_data,
    input_from_file,
    expect_error,
):
    person_fields_to_args = {
        "id": "lims-id",
        "familyId": "family-id",
        "firstName": "first-name",
        "lastName": "last-name",
        "comment": "comment",
        "sex": "sex",
        "country": "country",
        "birthDate": "birth-date",
        "hpoTermIds": "hpo-term-ids",
    }

    person_data = PersonUpdateDataFactory.build(
        birthDateYear=1234, birthDateMonth=12, birthDateDay=9
    ).model_dump()
    person_data.update(set_data)

    further_args = []
    if input_from_file is None:
        # data provided via args
        for fieldname, argname in person_fields_to_args.items():
            val = None
            if fieldname == "birthDate":
                val = (
                    str(person_data["birthDateYear"])
                    + "-"
                    + str(person_data["birthDateMonth"])
                    + "-"
                    + str(person_data["birthDateDay"])
                )
            elif fieldname == "hpoTermIds":  #  pragma: no cover
                if person_data[fieldname]:
                    val = " ".join(person_data[fieldname])
            else:
                if person_data[fieldname]:
                    val = str(person_data[fieldname])
            if val is not None:
                further_args.extend([f"--{argname}", val])

    _set_up_cmd_args_and_env_with_input(
        monkeypatch,
        tmp_path,
        "create-or-update-person",
        input_from_file,
        further_args,
        person_data,
    )

    def mock_response_callback(_, context):
        context.status_code = 200
        return b"123"

    varvis_mockapi_with_login.put(
        MOCK_URL + "api/person",
        content=mock_response_callback,
    )

    if expect_error:
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code != 0
        captured = capfd.readouterr()
        assert expect_error in captured.err
    else:
        main()
        captured = capfd.readouterr()
        assert captured.out.startswith("Running varvis_connector ")
        assert (
            "Successfully created or updated person with internal person ID 123"
            in captured.out
        )
        assert "Logout successful" in captured.out


@pytest.mark.parametrize(
    "filename, output_to_file, output_indent, expect_error",
    [
        (["string1"], False, None, None),
        (["string1", "string2"], False, 2, None),
        (["string1", "string2"], True, 0, None),
        (["NON_EXISTENT"], False, None, True),
    ],
)
def test_find_analyses_by_filename(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    filename,
    output_to_file,
    output_indent,
    expect_error,
):
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "find-analyses-by-filename",
        output_to_file,
        output_indent,
        filename,
    )

    if expect_error:
        expected_output = None
    else:
        expected_output = []
        for _ in range(random.randint(1, 5)):
            mock_data = FindByInputFileNameAnalysisItemFactory.build(
                matchingCustomerProvidedInputFilePath="/".join(filename)
            ).model_dump(mode="json")
            expected_output.append(mock_data)

    varvis_mockapi_with_login.get(
        MOCK_URL + "analysis-list/find-by-customer-provided-input-file-name",
        json={"response": expected_output or [], "success": True},
    )

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "simulate_n_vp, simulate_n_fail, output_to_file, output_indent",
    [
        (1, 0, False, None),
        (5, 1, True, 2),
        (3, 3, False, 2),
    ],
)
def test_get_virtual_panel(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    simulate_n_vp,
    simulate_n_fail,
    output_to_file,
    output_indent,
):
    expected_output = {}
    vp_ids_args = []
    for i in range(simulate_n_vp):
        vp_id = i + 1
        vp_id_str = str(vp_id)
        vp_ids_args.append(vp_id_str)

        if i < simulate_n_fail:
            varvis_mockapi_with_login.get(
                MOCK_URL + f"virtual-panel/{vp_id}",
                json={
                    "response": None,
                    "success": True,
                },  # this is what the crazy varvis API does
            )
        else:
            vp_data = VirtualPanelDataFactory.build(id=vp_id).model_dump(mode="json")
            expected_output[vp_id_str] = vp_data
            varvis_mockapi_with_login.get(
                MOCK_URL + f"virtual-panel/{vp_id}",
                json={"response": vp_data, "success": True},
            )

    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-virtual-panel",
        output_to_file,
        output_indent,
        vp_ids_args,
    )

    _run_cmd_and_check_output(
        capfd, output_file, output_indent, expected_output or None
    )


@pytest.mark.parametrize(
    "set_data, input_from_file, expect_error",
    [
        ({}, None, None),
        ({}, "-", None),
        ({}, "test.json", None),
        (
            {"geneIds": []},
            None,
            "The provided data is not valid",
        ),
    ],
)
def test_create_virtual_panel(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    set_data,
    input_from_file,
    expect_error,
):
    virtual_panel_fields_to_args = {
        "name": "name",
        "active": "active",
        "geneIds": "gene-ids",
        "description": "description",
        "personId": "person-id",
    }

    vp_data = VirtualPanelUpdateDataFactory.build(
        geneIds=[random.randint(1, 100) for _ in range(random.randint(1, 10))]
    ).model_dump()
    vp_data.update(set_data)
    del vp_data["id"]  # must not be set when creating VP

    further_args = []
    if input_from_file is None:
        # data provided via args
        for fieldname, argname in virtual_panel_fields_to_args.items():
            val = None
            if fieldname == "geneIds":
                if vp_data[fieldname]:
                    val = list(map(str, vp_data[fieldname]))
            else:
                if vp_data[fieldname]:
                    val = str(vp_data[fieldname])
            if val is not None:
                if fieldname == "active":
                    further_args.append(f"--{argname}")
                elif isinstance(val, list):
                    further_args.extend([f"--{argname}"] + val)
                else:
                    further_args.extend([f"--{argname}", val])

    _set_up_cmd_args_and_env_with_input(
        monkeypatch,
        tmp_path,
        "create-virtual-panel",
        input_from_file,
        further_args,
        vp_data,
    )

    def mock_response_callback(_, context):
        context.status_code = 200
        return {"response": 123, "success": True}

    varvis_mockapi_with_login.post(
        MOCK_URL + "api/virtual-panel",
        json=mock_response_callback,
    )

    if expect_error:
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code != 0
        captured = capfd.readouterr()
        assert expect_error in captured.err
    else:
        main()
        captured = capfd.readouterr()
        assert captured.out.startswith("Running varvis_connector ")
        assert "Successfully created virtual panel with ID 123" in captured.out
        assert "Logout successful" in captured.out


@pytest.mark.parametrize(
    "set_data, input_from_file, expect_error",
    [
        ({}, None, None),
        ({}, "-", None),
        ({}, "test.json", None),
        (
            {"id": None},
            None,
            "When updating a virtual panel, an ID must be given",
        ),
        (
            {"id": 999},
            None,
            "Could not retrieve existing virtual panel data for ID 999",
        ),
    ],
)
def test_update_virtual_panel(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    set_data,
    input_from_file,
    expect_error,
):
    virtual_panel_fields_to_args = {
        "id": "id",
        "name": "name",
        "active": "active",
        "geneIds": "gene-ids",
        "description": "description",
        "personId": "person-id",
    }

    vp_data = VirtualPanelUpdateDataFactory.build(
        id=123, geneIds=[random.randint(1, 100) for _ in range(random.randint(1, 10))]
    ).model_dump()
    vp_data.update(set_data)

    further_args = []
    if input_from_file is None:
        # data provided via args
        for fieldname, argname in virtual_panel_fields_to_args.items():
            val = None
            if fieldname == "geneIds":
                if vp_data[fieldname]:
                    val = list(map(str, vp_data[fieldname]))
            elif fieldname == "active":  # pragma: no cover
                if vp_data[fieldname]:
                    further_args.append("--active")
                else:
                    further_args.append("--inactive")
            else:
                if vp_data[fieldname]:
                    val = str(vp_data[fieldname])

            if val is not None and fieldname != "active":
                if isinstance(val, list):
                    further_args.extend([f"--{argname}"] + val)
                else:
                    further_args.extend([f"--{argname}", val])

    _set_up_cmd_args_and_env_with_input(
        monkeypatch,
        tmp_path,
        "update-virtual-panel",
        input_from_file,
        further_args,
        vp_data,
    )

    def mock_response_callback(_, context):
        context.status_code = 200
        return {"response": 123, "success": True}

    existing_vp_data = VirtualPanelDataFactory.build(id=123).model_dump(mode="json")
    varvis_mockapi_with_login.get(
        MOCK_URL + "virtual-panel/123",
        json={"response": existing_vp_data, "success": True},
    )
    varvis_mockapi_with_login.get(
        MOCK_URL + "virtual-panel/999",
        json={
            "response": None,
            "success": True,
        },  # crazy, but this is actually what the Varvis API does
    )

    varvis_mockapi_with_login.post(
        MOCK_URL + "api/virtual-panel",
        json=mock_response_callback,
    )

    if expect_error:
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code != 0
        captured = capfd.readouterr()
        assert expect_error in captured.err
    else:
        main()
        captured = capfd.readouterr()
        assert captured.out.startswith("Running varvis_connector ")
        assert "Successfully updated virtual panel with ID 123" in captured.out
        assert "Logout successful" in captured.out


@pytest.mark.parametrize(
    "simulate_n_summaries, output_to_file, output_indent",
    [
        (1, False, None),
        (5, False, None),
        (3, True, 2),
        (0, True, 2),
    ],
)
def test_get_virtual_panel_summaries(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    simulate_n_summaries,
    output_to_file,
    output_indent,
):
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-virtual-panel-summaries",
        output_to_file,
        output_indent,
    )

    expected_output = []
    for _ in range(simulate_n_summaries):
        model_instance = VirtualPanelSummaryFactory.build().model_dump(mode="json")
        expected_output.append(model_instance)

    varvis_mockapi_with_login.get(
        MOCK_URL + "virtual-panels",
        json={"response": expected_output, "success": True},
    )

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "simulate_n_genes, output_to_file, output_indent",
    [
        (1, False, None),
        (5, False, None),
        (3, True, 2),
        (0, True, 2),
    ],
)
def test_get_all_genes(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    simulate_n_genes,
    output_to_file,
    output_indent,
):
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-all-genes",
        output_to_file,
        output_indent,
    )

    expected_output = []
    for _ in range(simulate_n_genes):
        model_instance = VarvisGeneFactory.build().model_dump(mode="json")
        expected_output.append(model_instance)

    varvis_mockapi_with_login.get(
        MOCK_URL + "virtual-panel-genes",
        json={"response": expected_output, "success": True},
    )

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "analysis_ids, expect_success, output_to_file, output_indent",
    [
        ([1], True, False, None),
        ([1, 0, 2], True, False, 2),
        ([1, 2, 2], True, True, 2),
        ([0], False, False, None),
    ],
)
def test_get_file_download_links(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    analysis_ids,
    expect_success,
    output_to_file,
    output_indent,
):
    _, output_file = _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "get-file-download-links",
        output_to_file,
        output_indent,
        list(map(str, analysis_ids)),
    )

    if expect_success:
        expected_output = {}
        for id_ in analysis_ids:
            if id_ <= 0:
                continue

            model_instance = AnalysisFileDownloadLinksFactory.build(id=id_).model_dump(
                mode="json"
            )
            expected_output[str(id_)] = model_instance
            varvis_mockapi_with_login.get(
                MOCK_URL + f"api/analysis/{id_}/get-file-download-links",
                json={"response": model_instance, "success": True},
            )
    else:
        expected_output = None

    _run_cmd_and_check_output(capfd, output_file, output_indent, expected_output)


@pytest.mark.parametrize(
    "analysis_ids, output_dir_given, create_folder_per_id, file_pattern, overwrite, simulate_file_exists, no_progress, parallel_downloads",
    [
        ([1], False, False, None, False, False, False, None),
        ([0, 1], False, False, None, False, False, False, None),
        ([0, 1, 2], True, False, None, False, False, False, None),
        ([0, 1, 2], True, True, None, False, False, False, None),
        ([0, 1, 2], False, True, None, False, False, False, None),
        ([0, 1, 2], True, "an_%ID", None, False, False, False, None),
        ([1], False, False, ["*.gz"], False, False, False, None),
        ([1], False, False, ["*.gz", "*.bai"], False, False, False, None),
        ([1], False, False, None, False, True, False, None),
        ([1], False, False, None, True, True, False, None),
        ([1], False, False, None, False, False, True, None),
        ([0, 1, 2], True, "an_%ID", None, False, False, False, 2),
        ([0, 1, 2], True, "ana", None, False, False, True, 10),
    ],
)
def test_download_files(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    analysis_ids,
    output_dir_given,
    create_folder_per_id,
    file_pattern,
    overwrite,
    simulate_file_exists,
    no_progress,
    parallel_downloads,
):
    if output_dir_given:
        output_dir = tmp_path / "downloads"
        output_dir.mkdir()
    else:
        monkeypatch.chdir(tmp_path)
        output_dir = tmp_path

    mocked_files_per_id = {}
    for a_id in analysis_ids:
        mocked_files = create_varvis_mockapi_downloads(
            varvis_mockapi_with_login,
            a_id,
            a_id < 1,
            simulate_file_exists,
            output_dir,
            fname_prepend=f"{a_id}_",
        )
        mocked_files_per_id[a_id] = mocked_files

    further_args = list(map(str, analysis_ids))
    if output_dir_given:
        further_args.extend(["--output-dir", str(output_dir)])
    if create_folder_per_id:
        if create_folder_per_id is True:
            further_args.append("--create-folder-per-id")
        else:
            further_args.extend(["--create-folder-per-id", create_folder_per_id])
    if file_pattern:
        for pat in file_pattern:
            further_args.extend(["--file-pattern", pat])
    if overwrite:
        further_args.append("--overwrite")
    if no_progress:
        further_args.append("--no-progress")
    if parallel_downloads:
        further_args.extend(["--parallel-downloads", str(parallel_downloads)])

    _set_up_cmd_args_and_env_with_output(
        tmp_path,
        monkeypatch,
        "download-files",
        False,
        None,
        further_args,
    )
    monkeypatch.setenv("TEST_WRITES_TO_STDOUT", "0")

    main()

    captured = capfd.readouterr()
    assert captured.out.startswith("Running varvis_connector ")

    dl_index = 1
    for a_id, mocked_files in mocked_files_per_id.items():
        if create_folder_per_id is True:
            target_folder = output_dir / str(a_id)
        elif isinstance(create_folder_per_id, str):
            if "%ID" in create_folder_per_id:
                target_folder = output_dir / create_folder_per_id.replace(
                    "%ID", str(a_id)
                )
            else:
                target_folder = output_dir / (create_folder_per_id + str(a_id))
        else:
            target_folder = output_dir

        assert target_folder.exists()

        for f in mocked_files:
            if f == ".":
                continue

            f_path = target_folder / f
            f_exists = f_path.exists()
            if a_id == 0:
                assert not f_exists
            else:
                if f.endswith(".archive") or f == " ":
                    assert not f_exists
                else:
                    if file_pattern:
                        f_lwr = f.lower()
                        assert f_exists == any(
                            fnmatchcase(f_lwr, pat.lower()) for pat in file_pattern
                        )
                    else:
                        assert f_exists

            if f_exists:
                overwritten = False
                if simulate_file_exists and f == mocked_files[0] and not overwrite:
                    assert f_path.read_text() == "already existed"
                else:
                    assert f_path.read_text() == "testdata"
                    overwritten = (
                        simulate_file_exists and (f == mocked_files[0]) and overwrite
                    )

                assert f"Download #{dl_index}: " in captured.out
                assert (f"Download #{dl_index}: 0.00B" in captured.out) == (
                    no_progress is False or overwritten is True
                )

                if not (simulate_file_exists or overwrite or f != mocked_files[0]):
                    dl_index += 1


@pytest.mark.parametrize(
    "method, endpoint, raw_input, input_data, input_from_file, output_to_file, output_indent, simulate_error",
    [
        (None, "mockapi/test1", False, None, None, False, None, False),
        ("get", "/mockapi/test2", False, None, None, False, None, False),
        ("get", "/mockapi/test2", False, None, None, False, None, True),
        ("post", "api/mockapi/test3", False, {"x": 1}, "-", False, None, False),
        ("put", "mockapi/test4", True, {"x": 1}, "test.json", False, 2, False),
        ("head", "mockapi/test5", True, None, None, True, 1, False),
        ("patch", "mockapi/test6", False, None, None, False, None, False),
        ("delete", "mockapi/test7", False, None, None, False, None, False),
    ],
)
def test_request(
    capfd,
    monkeypatch,
    tmp_path,
    varvis_mockapi_with_login,
    method,
    endpoint,
    raw_input,
    input_data,
    input_from_file,
    output_to_file,
    output_indent,
    simulate_error,
):
    further_args = [endpoint]
    if method:
        further_args.append(f"--{method}")
    if raw_input:
        further_args.append("--raw-input")

    if output_to_file:
        output_file = tmp_path / "output.json"
        further_args.extend(["--output", str(output_file)])
        monkeypatch.setenv("TEST_WRITES_TO_STDOUT", "0")
    else:
        output_file = None
        monkeypatch.setenv("TEST_WRITES_TO_STDOUT", "1")

    if output_indent:
        further_args.extend(["--output-indent", str(output_indent)])

    _set_up_cmd_args_and_env_with_input(
        monkeypatch,
        tmp_path,
        "request",
        input_from_file,
        further_args,
        input_data,
        input_optional=True,
    )

    expected_output = {"response": 123, "success": not simulate_error}

    def mock_response_callback(_, context):
        context.status_code = 400 if simulate_error else 200
        return expected_output

    requests_mock_method = (
        getattr(varvis_mockapi_with_login, method)
        if method
        else varvis_mockapi_with_login.get
    )
    requests_mock_method(
        MOCK_URL + endpoint.removeprefix("/"),
        json=mock_response_callback,
    )

    if simulate_error:
        with pytest.raises(SystemExit) as e:
            main()
        assert e.value.code != 0

        out, err = capfd.readouterr()

        if not output_to_file:
            err, out = out, err

        assert "Varvis API returned HTTP status code 400" in out
    else:
        main()
        out, err = capfd.readouterr()

        if not output_to_file:
            err, out = out, err

        assert out.startswith("Running varvis_connector ")

        if input_data is not None:
            if raw_input:
                assert "Sending raw input data" in out
            else:
                assert "Sending JSON input data" in out

        if output_file:
            output_text = output_file.read_text()
        else:
            output_text = err.strip()

        assert json.loads(output_text) == expected_output
        assert output_text == json.dumps(expected_output, indent=output_indent or None)

    assert "Logout successful" in out


def _set_up_cmd_args_and_env_with_output(
    tmp_path, monkeypatch, cmd, output_to_file, output_indent, further_args=None
):
    connection_args = [
        "--api-url",
        MOCK_URL,
        "--username",
        "mockuser",
        "--password",
        "mockpw",
    ]

    cmd_args = []

    if output_to_file:
        output_file = tmp_path / "output.json"
        cmd_args.extend(["--output", str(output_file)])
        monkeypatch.setenv("TEST_WRITES_TO_STDOUT", "0")
    else:
        output_file = None
        monkeypatch.setenv("TEST_WRITES_TO_STDOUT", "1")

    if output_indent:
        cmd_args.extend(["--output-indent", str(output_indent)])

    if further_args:
        cmd_args.extend(further_args)

    monkeypatch.setattr(
        sys,
        "argv",
        ["varvis_connector"] + connection_args + [cmd] + cmd_args,
    )

    return cmd_args, output_file


def _set_up_cmd_args_and_env_with_input(
    monkeypatch,
    tmp_path,
    cmd,
    input_from_file,
    further_args,
    data,
    input_optional=False,
):
    if input_from_file is not None:
        # data provided via stdin
        if input_from_file == "-":
            monkeypatch.setattr("sys.stdin", StringIO(json.dumps(data)))
        else:
            # data provided via file
            input_from_file = tmp_path / input_from_file
            with input_from_file.open("w") as f:
                json.dump(data, f)

    connection_args = [
        "--api-url",
        MOCK_URL,
        "--username",
        "mockuser",
        "--password",
        "mockpw",
    ]

    cmd_args = []

    if input_from_file and (input_optional or input_from_file != "-"):
        cmd_args.extend(["--input", str(input_from_file)])

    if further_args:
        cmd_args.extend(further_args)

    monkeypatch.setattr(
        sys,
        "argv",
        ["varvis_connector"] + connection_args + [cmd] + cmd_args,
    )

    return cmd_args


def _run_cmd_and_check_output(
    capfd, output_file, output_indent, expected_output, expected_err_msg=None
):
    if expected_output is None:
        with pytest.raises(SystemExit):
            main()

        captured = capfd.readouterr()
        expected_err_msg = (
            expected_err_msg
            or "Data retrieval failed for all requests. No data to write."
        )
        assert expected_err_msg in captured.err
    else:
        main()

        captured = capfd.readouterr()

        if output_file:
            assert captured.out.startswith("Running varvis_connector ")
            output_text = output_file.read_text()
        else:
            assert captured.err.startswith("Running varvis_connector ")
            output_text = captured.out.strip()

        assert json.loads(output_text) == expected_output
        assert output_text == json.dumps(expected_output, indent=output_indent or None)
