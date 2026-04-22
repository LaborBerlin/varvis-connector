"""
Tests for the VarvisClient class.
"""

import os
import random
import uuid
from datetime import date
from fnmatch import fnmatchcase
from pathlib import Path

import pytest
from polyfactory.factories.pydantic_factory import ModelFactory
from requests import Response

from ._common import (
    varvis_mockapi_with_login as varvis_mockapi_with_login,
    create_varvis_mockapi_downloads,
)  # "as ..." prevents removal of fixture as "unused" by ruff linter

from varvis_connector import VarvisClient
from varvis_connector.errors import VarvisError
from varvis_connector.models import (
    SnvAnnotationData,
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
    v = VarvisClient(
        url, username, password, https_proxy=https_proxy, ssl_verify=ssl_verify
    )

    if not v.login():  # pragma: no cover
        pytest.fail("Failed to login")

    return v


@pytest.fixture
def varvis_init_data():
    env_vars = [f"VARVIS_TEST_PLAYGROUND_{s}" for s in ("URL", "USER", "PASSWORD")]
    init_data: list[str | bool | None] = [os.getenv(var) for var in env_vars]

    if None in init_data:  # pragma: no cover
        pytest.fail(
            "At least one of the following environment variables is missing for running tests with the "
            "Varvis playground: " + ", ".join(env_vars)
        )

    assert isinstance(init_data[0], str)
    if not init_data[0].endswith("/"):  # pragma: no cover
        pytest.fail(f"{env_vars[0]} must end with a slash")

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

    return monkeypatch


@pytest.mark.parametrize(
    "with_proxy, ssl_verify, connection_timeout, backoff_factor_seconds, backoff_max_tries",
    [
        (True, True, 1, 2, 3),
        (False, True, 0.1, 0.2, 1),
        (True, False, 0.1, 0, 10),
        (False, False, 5, 0, 99),
    ],
)
def test_from_env(
    monkeypatch_clean_env,
    with_proxy,
    ssl_verify,
    connection_timeout,
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
    monkeypatch_clean_env.setenv(
        "VARVIS_BACKOFF_FACTOR_SECONDS", str(backoff_factor_seconds)
    )
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
    assert v.backoff_factor_seconds == backoff_factor_seconds
    assert v.backoff_max_tries == backoff_max_tries
    assert not v.logged_in


def test_post_init(varvis_init_data):
    url, username, password, https_proxy, ssl_verify = varvis_init_data
    url = url.removesuffix("/")
    v = VarvisClient(
        url, username, password, https_proxy=https_proxy, ssl_verify=ssl_verify
    )
    assert v.api_url == url + "/"


def test_login(varvis_init_data):
    url, username, password, https_proxy, ssl_verify = varvis_init_data
    v = VarvisClient(
        url, username, password, https_proxy=https_proxy, ssl_verify=ssl_verify
    )
    assert not v.logged_in
    assert v.login()
    sess = v._session
    assert v.logged_in

    # no second login
    assert v.login()
    assert v.logged_in
    assert v._session is sess


def test_login_mocked(varvis_mockapi_with_login):
    url = "https://playground.varvis.com/"
    username = "mockuser"
    password = "mockpw"

    assert varvis_mockapi_with_login
    v = VarvisClient(url, username, password)
    assert v.login()


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
    varvis = VarvisClient(
        "https://example.com/", username="test-USERNAME", password="test-PASSWORD"
    )
    internal_attrs = [attr for attr in dir(varvis) if attr.startswith("_")]

    for func in (str, repr):
        output = func(varvis)
        assert varvis.password not in output
        assert not any(a in output for a in internal_attrs)


def test_logout(varvis):
    varvis.logout()
    assert not varvis.logged_in

    # second logout is not performed
    varvis.logout()
    assert not varvis.logged_in


def test_not_logged_in(monkeypatch_clean_env):
    var_suffixes = ("URL", "USER", "PASSWORD")
    env_vars = [
        os.getenv(var, "")
        for var in [f"VARVIS_TEST_PLAYGROUND_{s}" for s in var_suffixes]
    ]
    if None in env_vars:  # pragma: no cover
        pytest.fail(
            "At least one of the following environment variables is missing for running tests with the "
            "Varvis playground: " + ", ".join(env_vars)
        )

    for suffix, value in zip(var_suffixes, env_vars):
        monkeypatch_clean_env.setenv("VARVIS_" + suffix, value)

    v = VarvisClient.from_env()

    with pytest.raises(
        VarvisError, match="Session not initialized -- you need to login first"
    ):
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
        with pytest.raises(
            ValueError, match="must be either an integer a non-empty list of integers"
        ):
            varvis.get_cnv_target_results(
                person_lims_id, analysis_ids, virtual_panel_id
            )
    else:
        if expect_error:
            with pytest.raises(VarvisError, match=expect_error):
                varvis.get_cnv_target_results(
                    person_lims_id, analysis_ids, virtual_panel_id
                )
        else:
            res = varvis.get_cnv_target_results(
                person_lims_id, analysis_ids, virtual_panel_id
            )
            assert isinstance(res, CnvTargetResults)
            if not data_can_be_empty:
                assert res.data
            assert res.targetRegionsHeader


@pytest.mark.parametrize(
    "person_lims_id", ["200000000", "OCI3-QK333-Zelllinie-dx-twist", "notexistent"]
)
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
    if (person_id is None and person_lims_id is None) or (
        person_id is not None and person_lims_id is not None
    ):
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
        res = varvis.get_coverage_data(
            person_lims_id, virtual_panel_id=virtual_panel_id
        )
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
                expected_value = "UNKNOWN"  # another Varvis API quirk: passing None leads to storing this data as "UNKNOWN"
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
        with pytest.raises(
            VarvisError, match="Could not create or update person entry"
        ):
            # simulate invalid LIMS ID
            model = PersonUpdateData(id="")
            varvis.create_or_update_person(model)
        return

    # generate a random LIMS ID
    lims_id = "lbrbln-test-" + str(uuid.uuid4())

    # create a model with auto-generated data
    hpo_term_ids = ["HP:0025337", "HP:0001386", "HP:0003037"]
    hpo_term_sample = random.sample(
        hpo_term_ids, k=random.randint(0, len(hpo_term_ids))
    )
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
        update = PersonUpdateData(
            id=lims_id, birthDateYear=1999, birthDateMonth=10, birthDateDay=9
        )
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
    assert (
        res.draft == draft
    )  # requesting a draft always returns a draft, even if a final report already exists

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
            assert all(
                isinstance(analysis, CaseReportAnalysis) for analysis in item.analyses
            )
        else:  # CaseReportPersonItem
            assert item.type == "PERSON"
            assert item.personId == internal_person_id
            assert item.limsId == person_lims_id
            assert len(item.analyses) > 0
            assert all(
                isinstance(analysis, CaseReportAnalysis) for analysis in item.analyses
            )


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
            assert all(
                isinstance(item, FindByInputFileNameAnalysisItem) for item in res
            )


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
def test_create_or_update_virtual_panel(
    varvis, data_as_dict, simulate_validation_error
):
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
            model = VirtualPanelUpdateData(
                name="lbrbln-test-will-fail", active=True, geneIds=[]
            )
            varvis.create_or_update_virtual_panel(model)
        return

    # generate a random VP name
    name = "lbrbln-test-" + str(uuid.uuid4())

    # create a model without ID -> will create a VP
    model = VirtualPanelUpdateData(
        name=name, active=True, geneIds=[24309, 50200], description="An automated test."
    )
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
    varvis,
    analysis_id,
    file_patterns,
    allow_overwrite,
    simulate_file_exists,
    show_progress_bar,
    max_parallel_downloads,
    only_collect_urls,
    expect_error,
):
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
        res = varvis.download_files(**kwargs)
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
                assert any(
                    fnmatchcase(file_name_lwr, pat.lower()) for pat in file_patterns
                )

        if simulate_file_exists and not allow_overwrite:
            assert mocked_files[0] not in res
            assert (tmp_path / mocked_files[0]).read_text() == "already existed"
    else:
        with pytest.raises(VarvisError, match=expect_error):
            varvis.download_files(**kwargs)


def test_download_files_param_errors(varvis, tmp_path):
    with pytest.raises(ValueError, match="Output path does not exist: "):
        varvis.download_files(1, "/foo/bar")
    with pytest.raises(
        ValueError, match="Parameter `max_parallel_downloads` must be at least 1"
    ):
        varvis.download_files(1, tmp_path, max_parallel_downloads=0)


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
        res = varvis.request(
            endpoint, raise_for_status=handle_errors, handle_http_errors=handle_errors
        )

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
