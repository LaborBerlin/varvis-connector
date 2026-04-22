"""
varvis_connector VarvisClient class implementation module

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

import concurrent.futures
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from json import JSONDecodeError
from pathlib import Path
from fnmatch import fnmatchcase
from typing import Type, TypeVar, Callable, Any, overload, Literal

import requests
from pydantic import BaseModel, ValidationError
from requests import Response
from tqdm import tqdm

from ._log import default_logger
from .errors import VarvisError
from .models import (
    SnvAnnotationData,
    CnvTargetResults,
    PendingCnvData,
    QCCaseMetricsData,
    CoverageData,
    AnalysisItem,
    CaseReport,
    PersonReportItem,
    FindByInputFileNameAnalysisItem,
    AnalysisFileDownloadLinks,
    PersonUpdateData,
    PersonData,
    VirtualPanelSummary,
    VarvisGene,
    VirtualPanelUpdateData,
    VirtualPanelData,
)

DEFAULT_HTTP_ERROR_MESSAGES = {
    400: "Bad request.",
    404: "Not found.",
    405: "Method not allowed.",
    406: "Not acceptable.",
    422: "Unprocessable entity.",
}

TModel = TypeVar("TModel", bound=BaseModel)


def _jsondata_from_response(
    resp: Response, data_from_key: str
) -> list | dict | str | float | int | bool | None:
    """Convert API response to JSON and extract data from the specified key. Handle reported errors."""
    jsondata = resp.json()
    if not jsondata.get("success", False):
        _raise_varvis_error(jsondata, "Varvis API request did not succeed.")
    try:
        extracted = jsondata[data_from_key]
        assert isinstance(extracted, list | dict | str | float | int | bool | None)
        return extracted
    except KeyError as e:
        raise VarvisError(
            f"Response does not contain expected data key '{data_from_key}'"
        ) from e


def _parse_response_for_model(
    model_class: Type[TModel], resp: Response, data_from_key: str | None = None
) -> TModel:
    """Parse response data using the specified model class. Handle data validation errors."""
    data: str | dict
    if data_from_key:
        # some endpoints return the actual payload in a separate "response" key ...
        result = _jsondata_from_response(resp, data_from_key)
        if result is None:
            raise VarvisError("Response data is None")
        assert isinstance(result, dict)
        cls_validation_method = getattr(model_class, "model_validate")
        data = result
    else:
        # ... while others return the payload directly in the response body
        data = resp.text
        cls_validation_method = getattr(model_class, "model_validate_json")

    try:
        validated_model = cls_validation_method(data)
        assert isinstance(validated_model, model_class)
        return validated_model
    except ValidationError as e:
        raise VarvisError(f"Response validation failed: {e}") from e


def _parse_response_for_model_list(
    model_class: Type[TModel], resp: Response, data_from_key: str | None = None
) -> list[TModel]:
    if data_from_key:
        # some endpoints return the actual payload in a separate "response" key ...
        data = _jsondata_from_response(resp, data_from_key)
    else:
        # ... while others return the payload directly in the response body
        data = resp.json()
    cls_validation_method = getattr(model_class, "model_validate")
    return_data = []
    assert isinstance(data, list)
    for i, item in enumerate(data):
        try:
            return_data.append(cls_validation_method(item))
        except ValidationError as e:
            raise VarvisError(
                f"Response validation failed for data item #{i}: {e}"
            ) from e
    return return_data


def _parse_response_for_primitive(
    resp: Response, data_from_key: str, convert_result: Callable | None = None
) -> None | bool | int | float | str:
    """Parse response data as a primitive type (e.g. int, str, float). Handle data conversion errors."""
    data = _jsondata_from_response(resp, data_from_key)

    if convert_result:
        try:
            data = convert_result(data)
        except ValueError as e:
            raise VarvisError(f"Response conversion failed: {e}") from e

    assert isinstance(data, None | bool | int | float | str)
    return data


def _raise_varvis_error(
    error_data: dict[str, str | None], custom_error_msg: str = ""
) -> None:
    """
    Helper function to raise a VarvisError with am optional custom error message and all information provided by
    the API.

    :param error_data: A dictionary containing the error data.
    :param custom_error_msg: An optional custom error message.
    """
    custom_error_msg = custom_error_msg + "\n" if custom_error_msg else ""
    error_msg_id = error_data.get("errorMessageId", "<NOT GIVEN>")
    error_expected = str(error_data.get("errorExpected", "<NOT GIVEN>"))
    error_id = error_data.get("errorId", "<NOT GIVEN>")
    additional_info = error_data.get("additionalInformation", "<NOT GIVEN>")
    raise VarvisError(
        f"{custom_error_msg}"
        f"Error message ID: {error_msg_id}\n"
        f"Error expected: {error_expected}\n"
        f"Error ID: {error_id}\n"
        f"Additional information: {additional_info}"
    )


@dataclass
class VarvisClient:
    """
    Handles interactions with the Varvis API, including authentication and request
    management.

    The Varvis class facilitates login and logout operations as well as handling
    authenticated communication with the API, using methods to manage session
    state and API requests.

    :ivar api_url: The base URL for the Varvis API.
    :ivar username: The username used for Varvis authentication.
    :ivar password: The password used for Varvis authentication.
    :ivar https_proxy: Optional HTTPS proxy URL to use for API requests.
    :ivar ssl_verify: Whether to verify SSL certificates for API requests.
    :ivar connection_timeout: Timeout in seconds for API requests.
    :ivar backoff_factor_seconds: Base factor for exponential backoff between retries.
    :ivar backoff_max_tries: Maximum number of retry attempts for failed requests.
    :ivar logger: Logger instance for recording operations and errors.
    :ivar _session: The HTTP session used for Varvis API communication,
        initialized during login and cleared during logout.
    :ivar _loggedin_csrf: The CSRF token used for API requests after login.
    """

    api_url: str = field(metadata={"help": "Varvis API URL", "envvar": "VARVIS_URL"})
    username: str = field(
        metadata={"help": "Varvis credentials username", "envvar": "VARVIS_USER"}
    )
    password: str = field(metadata={"help": "Varvis credentials password"})
    https_proxy: str | None = field(
        default=None,
        metadata={"help": "Optional HTTPS proxy URL", "envvar": "HTTPS_PROXY"},
    )
    ssl_verify: bool = field(
        default=True,
        metadata={
            "help": "Disable SSL certificate verification for API requests",
            "argname": "disable-ssl-verify",
        },
    )
    connection_timeout: float = field(
        default=10.0, metadata={"help": "Timeout in seconds for API requests"}
    )
    backoff_factor_seconds: float = field(
        default=0.5,
        metadata={"help": "Base factor for exponential backoff between retries"},
    )
    backoff_max_tries: int = field(
        default=5,
        metadata={"help": "Maximum number of API request attempts. Must be at least 1"},
    )
    download_chunk_size: int = field(
        default=5 * 1024 * 1024,
        metadata={"help": "Chunk size in bytes for file downloads. Default is 5MB"},
    )
    logger: logging.Logger = logging.Logger("not_initialized", -1)
    _session: requests.Session | None = None
    _loggedin_csrf: str | None = None

    def __post_init__(self) -> None:
        """Additional setup steps."""

        if not self.api_url:
            raise ValueError("API URL must be provided")
        if not self.username:
            raise ValueError("Username must be provided")
        if not self.password:
            raise ValueError("Password must be provided")

        if self.logger.level == -1:
            self.logger = default_logger()

        if not self.api_url.endswith("/"):
            self.api_url += "/"
        self.logger.info('VarvisClient initialized for API URL "%s"', self.api_url)

        if self.https_proxy:
            self.logger.info('Using HTTPS proxy "%s"', self.https_proxy)

        if not self.ssl_verify:
            import urllib3.exceptions

            urllib3.disable_warnings(category=urllib3.exceptions.InsecureRequestWarning)
            self.logger.warning("SSL verification disabled")

        if self.backoff_factor_seconds < 0:
            raise ValueError("backoff_factor_seconds must be a non-negative number")
        if self.backoff_max_tries < 1:
            raise ValueError("backoff_max_tries must be a strictly positive integer")

    def __repr__(self) -> str:
        return (
            f"VarvisClient(api_url={self.api_url}, "
            f"username={self.username}, "
            f"password=***, "
            f"https_proxy={self.https_proxy}, "
            f"ssl_verify={self.ssl_verify}, "
            f"connection_timeout={self.connection_timeout}, "
            f"backoff_factor_seconds={self.backoff_factor_seconds}, "
            f"backoff_max_tries={self.backoff_max_tries})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    @classmethod
    def from_env(cls) -> "VarvisClient":
        url, username, password = [
            os.getenv("VARVIS_" + s, "") for s in ("URL", "USER", "PASSWORD")
        ]

        kwargs = {}
        for key in {
            "https_proxy",
            "ssl_verify",
            "connection_timeout",
            "backoff_factor_seconds",
            "backoff_max_tries",
        }:
            prefix = "VARVIS_" if key != "https_proxy" else ""
            value: Any = os.getenv(prefix + key.upper())
            if value is not None:
                if key in {"connection_timeout", "backoff_factor_seconds"}:
                    value = float(value)
                elif key == "backoff_max_tries":
                    value = int(value)
                elif key == "ssl_verify":
                    value = value.lower() in {"true", "1"} if value else True
                kwargs[key] = value

        return cls(url, username, password, **kwargs)

    @property
    def logged_in(self) -> bool:
        """Check if the user is logged in."""
        return self._session is not None and self._loggedin_csrf is not None

    def login(self, raise_for_status: bool = True) -> bool:
        """
        Performs the login operation for the user if not already logged in. It initializes
        a session, retrieves the necessary cookies and CSRF token, and submits the user's
        credentials to authenticate. After a successful login, the session is updated
        with the new cookies and CSRF token required for subsequent authenticated requests.

        This method raises an error if the CSRF token is not found in the initial response
        or if the login fails due to missing CSRF token in the login response.

        :param raise_for_status: If true, raise an error if the login fails due to HTTP errors.
        :raises VarvisError: If the login failed.
        :raises HTTPError: Indicates a failure during the HTTP communication with the varvis API.
        :return: True if the login was successful, False otherwise.
        """
        if self.logged_in:
            self.logger.info("Already logged in -- not performing a new login")
            return True

        self.logger.info("Logging in")

        # set initial session
        self._session = requests.Session()
        self._session.verify = self.ssl_verify

        if self.https_proxy:
            self._session.proxies = {"https": self.https_proxy}

        # get initial session cookie and CSRF code
        self.logger.debug("Acquiring initial session")
        initial_resp = self._session.head(self.api_url, stream=True)
        if raise_for_status:
            initial_resp.raise_for_status()
        elif not initial_resp.ok:
            self.logger.error("Could not acquire initial session -- aborting login")
            self._reset_state_on_logout()
            return False

        initial_cookies = initial_resp.cookies
        initial_csrf = initial_resp.headers.get("X-CSRF-TOKEN", None)
        if not initial_csrf:
            if raise_for_status:
                raise VarvisError("CSRF token not found in initial response")
            else:
                self.logger.error("CSRF token not found in initial response")
                self._reset_state_on_logout()
                return False
        self.logger.debug("Initial session OK")

        # log in using the provided credentials, CSRF code and initial cookie
        login_data = {
            "username": self.username,
            "password": self.password,
            "_csrf": initial_csrf,
        }

        self.logger.debug("Acquiring login session")
        login_resp = self._send_request(
            "POST",
            "login",
            allow_retries=False,
            raise_for_status=raise_for_status,
            cookies=initial_cookies,
            data=login_data,
        )

        # get the session cookie and CSRF code that can be used for the rest of the session
        loggedin_cookies = login_resp.cookies
        loggedin_csrf = login_resp.headers.get("X-CSRF-TOKEN", None)
        if not loggedin_csrf:
            # it seems the varvis API responds with HTTP 200 OK in case the login fails, but doesn't return a CSRF in that case
            if raise_for_status:
                raise VarvisError(
                    "Login failed (CSRF token not found in login response)"
                )
            else:
                self.logger.error(
                    "Login failed (CSRF token not found in login response)"
                )
                self._reset_state_on_logout()
                return False

        self.logger.debug("Login session OK")

        if api_build_version := login_resp.headers.get("BUILD-VERSION", None):
            self.logger.debug("Varvis API build version: %s", api_build_version)

        # set cookies and CSRF for further requests
        self._session.cookies.update(loggedin_cookies)
        self._session.headers.update({"X-CSRF-TOKEN": loggedin_csrf})
        self._loggedin_csrf = loggedin_csrf

        self.logger.info("Login successful")

        return True

    def logout(self) -> None:
        """
        Logs out the user by ending the current session and resetting authentication credentials.

        This method ensures that the user is logged out by sending a logout request to the
        appropriate endpoint. It clears the session data and invalidates the CSRF token upon
        successful logout. If the user is not logged in, the method will not perform any
        action and logs a corresponding message.

        :raises HTTPError: Indicates a failure during the logout HTTP request.
        """
        if not self.logged_in:
            self.logger.info("Not logged in -- not performing a logout")
            return

        # log out
        self.logger.info("Logging out")

        logout_data = {"_csrf": self._loggedin_csrf}
        self._send_request("POST", "logout", allow_retries=False, data=logout_data)

        self._reset_state_on_logout()
        self.logger.info("Logout successful")

    def get_snv_annotations(self, analysis_id: int) -> SnvAnnotationData:
        """
        Retrieves the SNV (Single Nucleotide Variant) annotations for a given analysis
        based on the specified analysis ID. This method sends an HTTP GET request
        to the appropriate endpoint of the API to fetch the annotation data associated
        with the analysis.

        :param analysis_id: The unique identifier of the analysis for which SNV
            annotations are being retrieved.
        :return: An object of `SnvAnnotationData` containing the SNV annotations
            for the specified analysis.
        """
        self.logger.info("Getting SNV annotations for analysis %d", analysis_id)
        resp = self._send_request(
            "GET",
            f"analysis/{analysis_id}/annotations",
            handle_http_errors={400: "Analysis not found for the given ID."},
        )

        return _parse_response_for_model(SnvAnnotationData, resp)

    def get_cnv_target_results(
        self,
        person_lims_id: str,
        analysis_ids: int | list[int],
        virtual_panel_id: int | None = 1,
    ) -> CnvTargetResults:
        """
        Retrieves the Copy Number Variant (CNV) target results for a specified person LIMS-ID and associated analyses.
        A virtual panel can also optionally be specified to filter the results.

        This method communicates with an external API to request and retrieve the CNV target results. The analysis IDs
        can be provided either as a single integer or a list of integers. Results are validated to ensure they align
        with the expected data structure, and an appropriate model is used for parsing.

        :param person_lims_id: The LIMS ID of the person for whom the CNV target results are being queried.
        :param analysis_ids: A single analysis ID or a list of analysis IDs to query CNV results for.
        :param virtual_panel_id: (Optional) The ID of the virtual panel to apply in filtering the CNV target data.
            If 1 (the default), the "all genes" panel is used (i.e. no filtering). If None, the Varvis documentation
            states that "the lastly selected virtual panel for the given person is used or 'All Genes' if no virtual
            panel was selected yet.", i.e. if None the behavior depends on the selection stored in the current user's
            session.
        :return: An instance of CnvTargetResults containing the parsed CNV target results data.
        :raises ValueError: If `analysis_ids` is neither an integer nor a non-empty list of integers.
        :raises requests.HTTPError: For errors occurring during the API request if they are unrelated to 422 status codes.
        :raises VarvisError: If the API response indicates an invalid analysis ID.
        """
        analysis_ids = [analysis_ids] if isinstance(analysis_ids, int) else analysis_ids

        if not analysis_ids:
            raise ValueError(
                "Parameter `analysis_ids` must be either an integer a non-empty list of integers"
            )

        self.logger.info(
            "Getting CNV target results for person LIMS-ID %s, analysis IDs %s%s",
            person_lims_id,
            ", ".join(map(str, analysis_ids)),
            ", " + str(virtual_panel_id) if virtual_panel_id else "",
        )
        query_params = "&".join(f"analysisIds={a_id}" for a_id in analysis_ids)
        if virtual_panel_id:
            query_params += f"&virtualPanelId={virtual_panel_id}"

        resp = self._send_request(
            "GET",
            f"results/{person_lims_id}/cnv?{query_params}",
            handle_http_errors={
                404: "Person with given LIMS-ID was not found.",
                422: "Analysis ID is not associated with a CNV analysis or is not valid for the specified person LIMS-ID.",
            },
        )

        return _parse_response_for_model(CnvTargetResults, resp)

    def get_internal_person_id(self, person_lims_id: str) -> int:
        """
        Retrieve the internal Varvis ID associated with a given person's LIMS-ID by sending a
        request to the Varvis API. This method fetches the internal ID required for
        further operations on the person record.

        :param person_lims_id: The LIMS-ID of the person whose internal ID is to
            be retrieved.
        :return: The internal ID of the person associated with the given LIMS-ID.
        :raises VarvisError: If the Varvis API responds with an error, fails to provide
            the expected data, or returns invalid or missing internal IDs.
        :raises requests.HTTPError: For HTTP errors other than 404.
        """
        self.logger.info('Getting internal ID for person LIMS-ID "%s"', person_lims_id)

        resp = self._send_request(
            "GET",
            f"person/{person_lims_id}/id",
            handle_http_errors={404: "Person not found for the given LIMS-ID."},
        )

        pers_id = _parse_response_for_primitive(resp, "response", convert_result=int)
        assert isinstance(pers_id, int)
        return pers_id

    def get_pending_cnv_segments(
        self,
        *,
        person_id: int | None = None,
        person_lims_id: str | None = None,
        analysis_ids: int | list[int] | None,
        virtual_panel_id: int | None = 1,
    ) -> PendingCnvData:
        """
        Retrieves pending CNV segments based for a given person (identified either by internal ID or LIMS ID) and
        associated analysis IDs.

        :param person_id: Internal ID of the person. Must be an integer or None and must be given if ``person_lims_id`` is None.
        :param person_lims_id: LIMS ID of the person. Must be a string or None and must be given if ``person_id`` is None.
        :param analysis_ids: Analysis IDs associated with the person. Can be an integer or a list of integers.
        :param virtual_panel_id: Optional virtual panel ID, if applicable, for filtering the CNV segments.
            If 1 (the default), the "all genes" panel is used (i.e. no filtering). If None, the Varvis documentation
            states that "the lastly selected virtual panel for the given person is used or 'All Genes' if no virtual
            panel was selected yet.", i.e. if None the behavior depends on the selection stored in the current user's
            session.
        :return: An instance of `PendingCnvData` containing the pending CNV segment
            information.
        :raises ValueError: Raised if both `person_id` and `person_lims_id` are missing
            or if both are provided. Also raised when `analysis_ids` is improperly formatted
            or empty.
        :raises VarvisError: Raised if the response from the Varvis API does not contain
            the expected data.
        """
        if person_id is None and person_lims_id is None:
            raise ValueError("Either `person_id` or `person_lims_id` must be provided")
        if person_id is not None and person_lims_id is not None:
            raise ValueError(
                "Only one of `person_id` or `person_lims_id` can be provided"
            )

        if person_lims_id is not None:
            self.logger.info("LIMS-ID is given; will retrieve internal person ID first")
            person_id = self.get_internal_person_id(person_lims_id)

        analysis_ids = [analysis_ids] if isinstance(analysis_ids, int) else analysis_ids

        if not analysis_ids:
            raise ValueError(
                "Parameter `analysis_ids` must be either an integer a non-empty list of integers"
            )

        self.logger.info(
            "Getting pending CNV segments for person internal ID %d, analysis IDs %s%s",
            person_id,
            ", ".join(map(str, analysis_ids)),
            ", " + str(virtual_panel_id) if virtual_panel_id else "",
        )

        # note: the CNV target results endpoint uses analysisIds (with "i") as the parameter name, this endpoint uses
        # analysesIds (with "e") -- crazy varvis API!
        query_params = f"personId={person_id}&" + "&".join(
            f"analysesIds={a_id}" for a_id in analysis_ids
        )
        if virtual_panel_id:
            query_params += f"&virtualPanelId={virtual_panel_id}"

        resp = self._send_request(
            "GET",
            f"pending-cnv?{query_params}",
            handle_http_errors={400: "Person or analysis ID not found."},
        )
        return _parse_response_for_model(PendingCnvData, resp, "response")

    def get_qc_case_metrics(self, person_lims_id: str) -> QCCaseMetricsData:
        """
        Fetches quality control (QC) case metrics for a given person based on their LIMS ID.
        This method interacts with a remote API to retrieve and process QC data, ensuring
        that it is structured into a usable format. If no metric results match the provided
        LIMS ID, an error will be raised.

        :param person_lims_id: The LIMS ID of the person whose QC case metrics are to
            be retrieved.
        :return: An instance of QCCaseMetricsData containing parsed and validated QC case
            metrics.
        :raises VarvisError: If no metric results data for the provided LIMS ID is found
            or if the response validation fails.
        """
        self.logger.info(
            'Getting QC case metrics for person LIMS ID "%s"', person_lims_id
        )

        resp = self._send_request(
            "GET",
            f"qualitycontrol/metrics/case/{person_lims_id}",
            handle_http_errors={400: "Person with given LIMS-ID was not found."},
        )
        data = _jsondata_from_response(resp, "response")
        assert isinstance(data, dict)

        try:
            metric_results = data["metricResults"].pop(person_lims_id)
        except KeyError:
            raise VarvisError(
                f"No metric results data for person with LIMS ID {person_lims_id} found in response"
            )

        data["metricResults"] = metric_results

        try:
            return QCCaseMetricsData.model_validate(data)
        except ValidationError as e:
            raise VarvisError(f"Response validation failed: {e}") from e

    def get_coverage_data(
        self, person_lims_id: str, virtual_panel_id: int | None = 1
    ) -> list[CoverageData]:
        """
        Retrieves coverage data for a specified person LIMS ID and optional virtual panel ID.

        This function fetches coverage data based on the provided person LIMS ID. If a
        virtual panel ID is specified, it filters the coverage data accordingly. The
        response is further validated and processed into a list of `CoverageData`
        objects.

        :param person_lims_id: A string representing the person LIMS ID for whom the
            coverage data is to be retrieved.
        :param virtual_panel_id: An optional integer representing the virtual panel
            ID to filter the coverage data, if applicable.
            If 1 (the default), the "all genes" panel is used (i.e. no filtering). If None, the Varvis documentation
            states that "the lastly selected virtual panel for the given person is used or 'All Genes' if no virtual
            panel was selected yet.", i.e. if None the behavior depends on the selection stored in the current user's
            session.
        :return: A list of `CoverageData` objects containing validated coverage
            information.
        :raises VarvisError: If the validation of any coverage data item fails.
        """
        self.logger.info(
            'Getting coverage data for person LIMS ID "%s"%s',
            person_lims_id,
            f" (virtual panel ID {virtual_panel_id})" if virtual_panel_id else "",
        )

        if virtual_panel_id:
            query_params = f"?virtualPanelId={virtual_panel_id}"
        else:
            query_params = ""

        resp = self._send_request(
            "GET",
            f"{person_lims_id}/coverage{query_params}",
            handle_http_errors={400: "Person with given LIMS-ID was not found."},
        )
        return _parse_response_for_model_list(CoverageData, resp)

    def get_analyses(
        self, analysis_ids: int | list[int] | None = None
    ) -> list[AnalysisItem]:
        """
        Retrieves a list of analysis items from the varvis API. Optionally allows to filter by analysis IDs.

        This method sends a GET request to the "analyses" endpoint of the
        server and parses the response into a list of `AnalysisItem` objects.

        Raises exceptions on request failure or if the response format
        is invalid.

        :param analysis_ids: Optional list of analysis IDs to filter the results by. If provided,
            only analyses with matching IDs will be returned.
        :return: A list of `AnalysisItem` objects retrieved from the varvis API.
        """
        self.logger.info("Getting analyses")

        if isinstance(analysis_ids, int):
            analysis_ids = [analysis_ids]

        if analysis_ids:
            query_params = f"?analysisIds={','.join(map(str, analysis_ids))}"
        else:
            query_params = ""

        resp = self._send_request("GET", f"analyses{query_params}")
        return _parse_response_for_model_list(AnalysisItem, resp, "response")

    def get_person(self, person_lims_id: str) -> PersonData:
        """
        Fetches person data for the given LIMS-ID.

        This method retrieves information associated with a person identified via
        their specified LIMS-ID. It sends a GET request to fetch the relevant data,
        and returns a structured person data model upon a successful response.

        :param person_lims_id: The unique LIMS-ID identifying the person for whom
            data is to be fetched.
        :return: The detailed person data represented as a PersonData object.
        """
        self.logger.info('Getting person data for LIMS-ID "%s"', person_lims_id)

        resp = self._send_request(
            "GET",
            f"person/{person_lims_id}",
            handle_http_errors={404: "Person with given LIMS-ID was not found."},
        )
        return _parse_response_for_model(PersonData, resp, data_from_key="response")

    def create_or_update_person(
        self, person_data: PersonUpdateData | dict[str, Any]
    ) -> int:
        """
        Allows to create a new person entry, or updates an existing one. Only the id field is required.
        Fields that are null will not override existing values on update.

        Updates or creates a person record in Varvis. If a dictionary is provided
        for `person_data`, it will be validated against the `PersonUpdateData` schema. If validation
        fails, an error will be raised to ensure proper input format.

        :param person_data: The data required to create or update a person record. Can be
            either an instance of `PersonUpdateData` or a dictionary that adheres to the
            `PersonUpdateData` schema.
        :raises ValueError: If the provided `person_data` is not valid based on the
            `PersonUpdateData` schema.
        :return: Internal person ID of the created or updated person.
        """
        if isinstance(person_data, dict):
            try:
                person_data = PersonUpdateData.model_validate(person_data)
            except ValidationError as e:
                raise ValueError(
                    "Parameter `person_data` must be a PersonUpdateData object or a dictionary that can be "
                    "validated against the PersonUpdateData schema"
                ) from e

        self.logger.info(
            'Creating or updating person record with LIMS-ID "%s"', person_data.id
        )

        resp = self._send_modeldata(
            "person",
            person_data,
            method="PUT",
            handle_http_errors={400: "Could not create or update person entry."},
        )

        try:
            return int(resp.content)
        except ValueError:
            raise VarvisError(
                "Response could not be parsed. Expected internal person ID as integer."
            )

    def get_case_report(
        self, person_lims_id: str, draft: bool = False, inactive: bool = False
    ) -> CaseReport:
        """
        Retrieve a case report for a given person LIMS-ID.

        The method communicates with the server using a GET request to fetch the case
        report of a person identified by the provided LIMS-ID. It allows for additional
        filters like draft and inactive status.

        :param person_lims_id: The unique identifier for a person in the LIMS system.
        :param draft: Set to true if a draft report with pending changes is explicitly requested instead of
            the final report (submitted report).
        :param inactive: Flag indicating whether inactive report items should be also returned (by default
            inactive report items are not returned).
        :return: A case report object fetched from the server.
        """
        enabled_flags = []
        if draft or inactive:
            if draft:
                enabled_flags.append("draft")
            if inactive:
                enabled_flags.append("inactive")
            query_params = "?" + "&".join(map(lambda x: f"{x}=true", enabled_flags))
        else:
            query_params = ""

        self.logger.info(
            'Getting case report for person LIMS-ID "%s"%s',
            person_lims_id,
            f" ({', '.join(enabled_flags)})" if enabled_flags else "",
        )

        resp = self._send_request(
            "GET",
            f"cases/{person_lims_id}/report{query_params}",
            handle_http_errors={
                404: "Person with given LIMS-ID was not found or no report exists for the given criteria."
            },
        )
        return _parse_response_for_model(CaseReport, resp, data_from_key="response")

    def get_report_info_for_persons(self) -> list[PersonReportItem]:
        """
        Fetches the report information for all persons.

        This method sends a "GET" request to the "cases/reports/info" endpoint to
        retrieve detailed report information for persons. The response is parsed
        into a list of `PersonReportItem` objects for further use within the
        application.

        :return: A list of `PersonReportItem` objects containing the report
            information for all persons.
        """
        self.logger.info("Getting report information for persons")

        resp = self._send_request("GET", "cases/reports/info")
        return _parse_response_for_model_list(PersonReportItem, resp, "response")

    def get_person_analyses(self, person_lims_id: str) -> list[AnalysisItem]:
        """
        Gets the list of analyses associated with a person based on the provided LIMS ID.
        The analyses are returned as a list of `AnalysisItem` objects.

        This method is very similar to ``get_analyses()``, but it retrieves analyses for a
        specific person. In contrast to ``get_analyses()``, this API endpoint doesn't allow
        for filtering by analysis ID.

        :param person_lims_id: The unique LIMS ID representing the person whose analyses
            are being retrieved.
        :return: A list of AnalysisItem objects containing information about the analyses
            associated with the provided person LIMS ID.
        """
        self.logger.info('Getting analyses for person LIMS ID "%s"', person_lims_id)
        resp = self._send_request(
            "GET",
            f"person/{person_lims_id}/analyses",
            handle_http_errors={400: "Person with given LIMS-ID was not found."},
        )
        return _parse_response_for_model_list(AnalysisItem, resp)

    def find_analyses_by_filename(
        self, filename: str | list[str]
    ) -> list[FindByInputFileNameAnalysisItem]:
        """
        Find analyses by searching for the given filename components within customer-provided input file names.

        :param filename: A single filename or a list of filenames as substrings to search for in the analyses.
            If a list of strings is provided, *all* of the provided strings must be found in a customer input file
            name for the corresponding analysis to be included in the result (AND operator). Provided strings must be
            non-empty.
        :return: A list of `FindByInputFileNameAnalysisItem` objects resulting from the search.
        """
        if isinstance(filename, str):
            filename = [filename]

        filename = [f for f in (f.strip() for f in filename) if f]

        if len(filename) == 0:
            raise ValueError(
                "Parameter `filename` must be a non-empty string or a non-empty list of strings"
            )

        self.logger.info(
            "Getting analyses by searching for filename component(s) %s",
            " AND ".join(f'"{f}"' for f in filename),
        )
        query_param = "&".join(f"customerProvidedInputFileName={f}" for f in filename)
        resp = self._send_request(
            "GET",
            "analysis-list/find-by-customer-provided-input-file-name?" + query_param,
        )
        return _parse_response_for_model_list(
            FindByInputFileNameAnalysisItem, resp, data_from_key="response"
        )

    def get_virtual_panel_summaries(self) -> list[VirtualPanelSummary]:
        """
        Retrieves the summaries for all virtual panels, except for the virtual panel containing all genes.

        This method sends a GET request to the "virtual-panels" endpoint to fetch a
        list of virtual panel summaries. The response is parsed to return
        a structured list of `VirtualPanelSummary` objects.

        :return: A list of `VirtualPanelSummary` instances representing the
                 parsed virtual panel summaries.
        """
        self.logger.info("Getting virtual panel summaries")

        resp = self._send_request("GET", "virtual-panels")
        return _parse_response_for_model_list(
            VirtualPanelSummary, resp, data_from_key="response"
        )

    def get_virtual_panel(self, virtual_panel_id: int) -> VirtualPanelData:
        """
        Retrieves the information of a virtual panel based on the given ID. This method
        sends a GET request to fetch the virtual panel data and parses the response
        into a VirtualPanelData model. If the virtual panel ID is not found, a
        VarvisError is raised.

        :param virtual_panel_id: The ID of the virtual panel to retrieve
        :return: An instance of VirtualPanelData containing the information of the virtual panel
        :raises VarvisError: If the virtual panel with the specified ID is not found
        """
        self.logger.info(f"Getting virtual panel {virtual_panel_id}")

        resp = self._send_request("GET", f"virtual-panel/{virtual_panel_id}")
        try:
            return _parse_response_for_model(
                VirtualPanelData, resp, data_from_key="response"
            )
        except VarvisError as exc:
            raise VarvisError(
                f"Virtual panel with ID {virtual_panel_id} not found"
            ) from exc

    def get_all_genes(self) -> list[VarvisGene]:
        """
        Retrieves a list of all genes and their details. The details are reduced to information
        important for virtual panels.

        This method sends a GET request to the "virtual-panel-genes" endpoint
        to fetch a list of available genes. The response is parsed into a list
        of VarvisGene models and returned.

        :return: A list containing instances of VarvisGene parsed from the response.
        """
        self.logger.info("Getting all genes")

        resp = self._send_request("GET", "virtual-panel-genes")
        return _parse_response_for_model_list(
            VarvisGene, resp, data_from_key="response"
        )

    def get_file_download_links(self, analysis_id: int) -> AnalysisFileDownloadLinks:
        """
        Retrieves the file download links associated with the provided analysis ID.

        :param analysis_id: The unique identifier of the analysis for which
            the file download links are to be retrieved.
        :return: An instance of AnalysisFileDownloadLinks containing the
            download links for the specified analysis.
        """
        self.logger.info("Getting file download links for analysis ID %d", analysis_id)

        resp = self._send_request(
            "GET",
            f"analysis/{analysis_id}/get-file-download-links",
            handle_http_errors={400: "Analysis with given ID was not found."},
        )
        return _parse_response_for_model(
            AnalysisFileDownloadLinks, resp, data_from_key="response"
        )

    def create_or_update_virtual_panel(
        self, virtual_panel_data: VirtualPanelUpdateData | dict[str, Any]
    ) -> int:
        """
        Creates or updates a virtual panel entry based on the provided data. If the
        provided data doesn't include an ID, a new virtual panel will be created. If
        an ID is specified in the data, an existing virtual panel with that ID will
        be updated accordingly. Validates the input data against the
        VirtualPanelUpdateData schema before processing.

        :param virtual_panel_data: Data for the virtual panel. Must be either an
            instance of VirtualPanelUpdateData or a dictionary conforming to the
            VirtualPanelUpdateData schema.
        :return: ID of the created or updated virtual panel.
        """
        if isinstance(virtual_panel_data, dict):
            try:
                virtual_panel_data = VirtualPanelUpdateData.model_validate(
                    virtual_panel_data
                )
            except ValidationError as e:
                raise ValueError(
                    "Parameter `virtual_panel_data` must be a VirtualPanelUpdateData instance or a dictionary that "
                    "can be validated against the VirtualPanelUpdateData schema."
                ) from e

        if virtual_panel_data.id is None:
            self.logger.info("Creating a new virtual panel")
        else:
            self.logger.info("Updating virtual panel with ID %d", virtual_panel_data.id)

        resp = self._send_modeldata("virtual-panel", virtual_panel_data)
        vp_id = _parse_response_for_primitive(resp, "response")
        assert isinstance(vp_id, int)
        return vp_id

    def download_files(
        self,
        analysis_id: int,
        output_path: str | os.PathLike,
        file_patterns: str | list[str] | None = None,
        allow_overwrite: bool = False,
        show_progress_bar: bool = False,
        max_parallel_downloads: int = 1,
        only_collect_urls: bool = False,
    ) -> dict[str, Path]:
        """
        Downloads files for a given analysis ID while supporting filtering by file patterns, parallel downloads,
        progress display, and overwrite control.

        The function fetches download links and attempts to download the files concurrently
        up to the maximum number of parallel downloads. Files can be filtered using
        specific patterns and duplicate downloads or invalid files are skipped.
        Logs provide information about failed downloads, skipped files, and completion status.

        :param analysis_id: Integer representing the unique ID for the analysis data to be downloaded.
        :param output_path: Path where the downloaded files will be stored. Accepts path-like objects.
        :param file_patterns: File name pattern(s) used to include files for download. Can be a single string
                              or a list of strings. If None, all files are included.
        :param allow_overwrite: Boolean flag determining whether to overwrite existing files in the output path.
        :param show_progress_bar: Boolean flag indicating whether to display progress bars for each download.
        :param max_parallel_downloads: Maximum number of files to download concurrently. Must be at least 1.
        :param only_collect_urls: Boolean flag indicating whether to only collect download URLs without actually
                                  downloading files. Useful when collecting file download URLs for multiple analyses
                                  and then submitting them to
                                  :meth:`_varvis_client.VarvisClient.download_files_from_urls_parallel`.
        :return: If ``only_collect_urls`` is False: A dictionary mapping the downloaded file names to their download
            location as Path objects. Otherwise: A dictionary that maps download URLs to the corresponding target file
            Path objects.
        """
        output_path = Path(output_path)
        if not output_path.exists():
            raise ValueError(f"Output path does not exist: {output_path}")

        if max_parallel_downloads < 1:
            raise ValueError("Parameter `max_parallel_downloads` must be at least 1")

        download_links = self.get_file_download_links(analysis_id)

        if not only_collect_urls:
            self.logger.info("Downloading files for analysis ID %d", analysis_id)

        if isinstance(file_patterns, str):
            file_patterns = [file_patterns]

        if file_patterns and not only_collect_urls:
            self.logger.info(
                "> Using file pattern(s) %s",
                ", ".join(f'"{pat}"' for pat in file_patterns),
            )

        # first only collect the valid download links
        valid_download_links: dict[
            str, Path
        ] = {}  # maps link to output file path string
        for link_object in download_links.apiFileLinks:
            if link_object.fileName is None or link_object.downloadLink is None:
                continue

            output_file_name = link_object.fileName.strip()

            if (
                output_file_name in {"", ".", ".."}
                or "\0" in output_file_name
                or "/" in output_file_name
            ):
                self.logger.error(
                    '> Skipping file "%s" because it has an invalid name',
                    output_file_name,
                )
                continue

            if file_patterns:
                output_file_name_lwr = output_file_name.lower()
                if not any(
                    fnmatchcase(output_file_name_lwr, pat.lower())
                    for pat in file_patterns
                ):
                    self.logger.info(
                        '> Skipping file "%s" because it does not match any of the provided patterns',
                        output_file_name,
                    )
                    continue

            if link_object.currentlyArchived:
                self.logger.error(
                    '> Skipping file "%s" because it is marked as currently archived with '
                    "estimated restore time %s",
                    output_file_name,
                    link_object.estimatedRestoreTime,
                )
                continue

            output_file_path = output_path / output_file_name

            if output_file_path.exists():
                if allow_overwrite:
                    self.logger.warning(
                        '> Will overwrite existing file "%s"', output_file_path
                    )
                else:
                    self.logger.error(
                        '> Skipping file "%s" because it already exists at "%s"',
                        output_file_name,
                        output_file_path,
                    )
                    continue

            if link_object.downloadLink in valid_download_links:
                self.logger.error(
                    '> Skipping file "%s" because its download link was already collected',
                    output_file_name,
                )
                continue

            valid_download_links[link_object.downloadLink] = output_file_path
        if only_collect_urls:
            return valid_download_links
        res: dict[str, Path] = self.download_files_from_urls_parallel(
            valid_download_links,
            max_parallel_downloads,
            show_progress_bar,
            return_messages=False,
        )
        return res

    @overload
    def download_files_from_urls_parallel(
        self,
        urls_and_targets: dict[str, Path],
        max_parallel_downloads: int,
        show_progress_bar: bool,
        return_messages: Literal[False],
    ) -> dict[str, Path]: ...

    @overload
    def download_files_from_urls_parallel(
        self,
        urls_and_targets: dict[str, Path],
        max_parallel_downloads: int,
        show_progress_bar: bool,
        return_messages: Literal[True],
    ) -> tuple[dict[str, Path], list[tuple[int, str]]]: ...

    @overload
    def download_files_from_urls_parallel(
        self,
        urls_and_targets: dict[str, Path],
        max_parallel_downloads: int,
        show_progress_bar: bool,
        return_messages: bool,
    ) -> dict[str, Path] | tuple[dict[str, Path], list[tuple[int, str]]]: ...

    def download_files_from_urls_parallel(
        self,
        urls_and_targets: dict[str, Path],
        max_parallel_downloads: int,
        show_progress_bar: bool,
        return_messages: bool,
    ) -> dict[str, Path] | tuple[dict[str, Path], list[tuple[int, str]]]:
        """
        Downloads multiple files from given URLs to specified target locations concurrently.

        This function utilizes a thread pool executor to download multiple files in parallel. Each file
        is downloaded to a specified target location provided in the dictionary. The function keeps
        track of progress and logs success or failure for each file download. Optionally, a progress
        bar can be shown for each download to visualize the current progress.

        :param urls_and_targets: A dictionary where keys are URLs pointing to files to download and
            values are their respective output file paths where the downloaded files should be stored.
        :param max_parallel_downloads: The maximum number of downloads that can run concurrently.
        :param show_progress_bar: A boolean flag to indicate whether the progress bar should be
            displayed for file downloads.
        :param return_messages: A boolean flag to indicate whether to additionally return a list of
            log messages.
        :return: A dictionary mapping filenames to their respective output paths for successfully
            downloaded files. If ``return_messages`` is True, additionally returns a list of log
            messages.
        """

        def download_single_file(
            url: str,
            output_file_path: Path,
            download_num: int,
            logger: logging.Logger,
            ssl_verify: bool,
            connection_timeout: float,
            show_progress_bar: bool,
            download_chunk_size: int,
        ) -> bool:
            def human_readable_size(size_bytes: int) -> str:
                units = ["B", "KB", "MB", "GB", "TB", "PB"]
                size = float(size_bytes)
                for unit in units:
                    if size < 1024.0:
                        return f"{size:.2f} {unit}"
                    size /= 1024.0
                return f"{size:.2f} PB"

            resp = requests.get(
                url, stream=True, verify=ssl_verify, timeout=connection_timeout
            )

            if not resp.ok:
                logger.error(
                    f"Download #{download_num + 1}: HTTP error {resp.status_code} while downloading the file: {resp.reason}"
                )
                return False

            nbytes = int(resp.headers.get("content-length", 0))
            nbytes_readable = human_readable_size(nbytes)

            progress_bar_output_stream = None
            if show_progress_bar:
                for hndlr in logger.handlers:
                    if isinstance(hndlr, logging.StreamHandler):
                        progress_bar_output_stream = hndlr.stream
                        break
            else:
                logger.info(
                    f'Download #{download_num + 1}: Downloading file of size {nbytes_readable} to output file "{output_file_path}"...'
                )
                logger.debug(f"Download #{download_num + 1}: URL: {url}")

            with tqdm(
                desc=f"Download #{download_num + 1}",
                file=progress_bar_output_stream,
                total=nbytes,
                unit="B",
                unit_scale=True,
                miniters=1,
                disable=not show_progress_bar,
            ) as progress_bar:
                try:
                    with open(output_file_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=download_chunk_size):
                            if show_progress_bar:
                                progress_bar.update(len(chunk))
                            f.write(chunk)
                except (requests.HTTPError, requests.ConnectionError, OSError) as e:
                    logging.error(
                        f"Download #{download_num + 1}: Error while downloading the file: {e}"
                    )
                    return False

            return True

        with ThreadPoolExecutor(max_workers=max_parallel_downloads) as executor:
            # submit tasks ("futures") to threads
            futures = {}  # maps Future objects to URLs
            for i, (url, target_path) in enumerate(urls_and_targets.items()):
                fut = executor.submit(
                    download_single_file,
                    url,
                    target_path,
                    download_num=i,
                    logger=self.logger,
                    ssl_verify=self.ssl_verify,
                    connection_timeout=self.connection_timeout,
                    show_progress_bar=show_progress_bar,
                    download_chunk_size=self.download_chunk_size,
                )
                futures[fut] = (url, i)

            # iterate through completed tasks (order is random)
            collected_messages = []  # for deferring messages when using progress bars
            downloaded_files = {}
            for fut in concurrent.futures.as_completed(futures):
                url, download_num = futures[fut]
                downloaded_target_path = Path(urls_and_targets[url])
                file_name = downloaded_target_path.name
                try:
                    success = fut.result()
                except Exception as exc:
                    msg = f'Download #{download_num + 1}: Error while downloading file "{file_name}": {exc}'
                    if show_progress_bar:
                        collected_messages.append((logging.ERROR, msg))
                    else:
                        self.logger.error(msg)
                else:
                    if success:
                        downloaded_files[file_name] = downloaded_target_path

                        msg = f'Download #{download_num + 1}: Successfully downloaded file "{file_name}"'
                        if show_progress_bar:
                            collected_messages.append((logging.INFO, msg))
                        else:
                            self.logger.info(msg)
                    else:
                        msg = f'Download #{download_num + 1}: Could not download file "{file_name}"'
                        if show_progress_bar:
                            collected_messages.append((logging.ERROR, msg))
                        else:
                            self.logger.error(msg)

            if show_progress_bar and not return_messages:
                # log the collected messages after all downloads completed
                for lvl, msg in collected_messages:
                    self.logger.log(lvl, msg)
        if return_messages:
            return downloaded_files, collected_messages
        else:
            return downloaded_files

    def request(
        self,
        endpoint: str,
        method: str = "GET",
        stream: bool = True,
        raise_for_status: bool = True,
        handle_http_errors: dict[int, str] | bool = True,
        allow_retries: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Sends an authenticated HTTP request to the specified Varvis endpoint.

        :param endpoint: The endpoint to which the request will be sent.
        :param method: The HTTP method to use for the request. Defaults to "GET".
        :param stream: Whether to stream the response. Defaults to True.
        :param raise_for_status: Whether to raise an exception for HTTP error responses.
            Defaults to True.
        :param handle_http_errors: Specifies custom error handling behavior. If True,
            default error messages are used. If False, no custom handling is applied.
            A dictionary mapping status codes to custom messages can also be provided.
            Defaults to True.
        :param allow_retries: Whether to allow retries for failed requests. Defaults to True.
        :param kwargs: Additional arguments to be passed to the request.
        :return: The HTTP response object returned by the request.
        """
        if handle_http_errors is True:
            handle_http_errors_arg = DEFAULT_HTTP_ERROR_MESSAGES
        elif handle_http_errors is False:
            handle_http_errors_arg = None
        else:
            handle_http_errors_arg = handle_http_errors

        return self._send_request(
            method=method,
            endpoint=endpoint,
            auto_fix_endpoint=False,
            stream=stream,
            raise_for_status=raise_for_status,
            handle_http_errors=handle_http_errors_arg,
            allow_retries=allow_retries,
            **kwargs,
        )

    def _send_modeldata(
        self,
        endpoint: str,
        model: BaseModel,
        method: str = "POST",
        handle_http_errors: dict[int, str] | None = None,
    ) -> requests.Response:
        """
        Sends serialized model data to the specified endpoint using the given HTTP method.

        This function serializes the provided model instance to a dictionary and sends
        it as a JSON payload to a specified URL endpoint. The request method used for
        this operation can be customized, defaulting to "POST". This function assumes
        proper formatting and validation of the `model` before its invocation.

        :param endpoint: The specific part of the URL to append to the base endpoint.
        :param model: An instance of a class inheriting from BaseModel, representing
                      the model data to send.
        :param method: The HTTP method to use for the request, defaulting to "POST".
        :param handle_http_errors: Optional dict of HTTP error codes to handle explicitly. The dict maps HTTP
            error codes to custom error messages. If None, the default error messages are used.
            If one of the supplied HTTP errors occurs, a ``VarvisError`` will be raised. Defaults to None.
        :return: The response from the HTTP request.
        """
        data = model.model_dump()
        return self._send_request(
            method, endpoint, handle_http_errors=handle_http_errors, json=data
        )

    def _send_request(
        self,
        method: str,
        endpoint: str,
        auto_fix_endpoint: bool = True,
        stream: bool = True,
        raise_for_status: bool = True,
        handle_http_errors: dict[int, str] | None = None,
        allow_retries: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        """
        Sends an HTTP request to the specified endpoint and handles retries with optional
        re-login in cases of failed requests or invalid session scenarios.

        This method constructs the full API URL dynamically depending on the endpoint and
        manages session-based retries when needed. Certain API quirks, such as session
        invalidations, are taken into account and handled appropriately.

        :param method: HTTP method to use for the request (e.g., "GET", "POST"). Type should match a valid HTTP method string.
        :param endpoint: Partial URL to append to the API base URL. Determines the specific endpoint being addressed.
        :param auto_fix_endpoint: If True, automatically prepend "api/" to the endpoint in the cases where it is necessary.
        :param stream: Whether to stream the HTTP response content. Defaults to True.
        :param raise_for_status: If True, raises an HTTP error for non-successful status codes. Defaults to True.
        :param handle_http_errors: Optional dict of HTTP error codes to handle explicitly. The dict maps HTTP
            error codes to custom error messages. If None, the default error messages are used.
            If one of the supplied HTTP errors occurs, a ``VarvisError`` will be raised. Defaults to None.
        :param allow_retries: Whether to allow retrying the request in case of failure. Defaults to True.
        :param kwargs: Additional request options passed to `requests.Session.request()`.
        :return: HTTP response object from the `requests` library containing the server's response.
        """

        if self._session is None:
            raise VarvisError("Session not initialized -- you need to login first")

        endpoint = endpoint.removeprefix("/")

        if auto_fix_endpoint:
            urlpart_components = endpoint.split("?")[0].split("/")
            # strangely, some endpoints are prefixed with "api/" and others don't, so we need to handle these cases:
            # - endpoint starting with "login", "logout", "pending-cnv", "analysis-list", etc.: NO prefix
            # - endpoint with the pattern "person/.../analyses": NO prefix (e.g. "/person/{personLimsId}/analyses", etc.)
            # - endpoint starting with "virtual-panel" and method is not GET: prefix
            # - all other endpoints will also get an "/api" prefix (e.g. "/api/analyses/{analysisId}")
            if not (
                urlpart_components[0]
                in {
                    "login",
                    "logout",
                    "pending-cnv",
                    "analysis-list",
                    "virtual-panels",
                    "virtual-panel",
                    "virtual-panel-genes",
                }
                or (
                    urlpart_components[0] == "person"
                    and urlpart_components[-1] == "analyses"
                )
            ) or (urlpart_components[0] == "virtual-panel" and method != "GET"):
                endpoint = "api/" + endpoint

        # construct final URL and send request
        request_url = self.api_url + endpoint

        resp = None
        n_tries = 1
        max_retries = self.backoff_max_tries if allow_retries else 1
        while True:
            self.logger.debug(
                "Try #%d/%d. Sending %s request to %s",
                n_tries,
                max_retries,
                method,
                request_url,
            )

            retry = False  # reset on each try
            send_request = True

            if not self._session:  # re-login was requested on previous try
                self.logger.debug("Attempting re-login after failed request")

                # try to login again; it uses`allow_retries=False`, as this would cause recursive retry loops
                if self.login(raise_for_status=False):
                    # successfully logged in -- we can continue with the actual request
                    self.logger.debug("Re-login successful")
                else:
                    # we will have to try logging in again -- we will not send the actual request now
                    self.logger.debug("Re-login failed")
                    retry = True
                    send_request = False

            if send_request:
                try:
                    resp = self._session.request(
                        method,
                        request_url,
                        stream=stream,
                        allow_redirects=False,
                        timeout=self.connection_timeout,
                        **kwargs,
                    )
                    self.logger.debug(
                        "Response received with status code %d", resp.status_code
                    )

                    if resp.status_code == 302 and resp.headers.get(
                        "Location", ""
                    ).removesuffix("/") == self.api_url.removesuffix("/"):
                        # Varvis API quirk: in case there are too many concurrent requests for the same session, the session
                        # seems to be invalidated and the response is a redirect to the base URL; we need to login again after
                        # waiting a bit
                        self.logger.debug(
                            "Possible forced logout from API detected -- will try to login again"
                        )
                        retry = True
                        self._reset_state_on_logout()
                        resp = None
                except requests.ConnectionError:
                    self.logger.debug("Connection error")
                    retry = True
                except requests.Timeout:
                    self.logger.debug("Timeout error")
                    retry = True

            if retry and n_tries < max_retries:
                wait_sec = 2 ** (n_tries - 1) * self.backoff_factor_seconds
                n_tries += 1
                self.logger.debug("Retrying in %.1f seconds", wait_sec)
                time.sleep(wait_sec)
            else:
                break

        if resp is None:
            raise VarvisError(
                f"Failed to send request to Varvis API after {self.backoff_max_tries} tries"
            )

        if handle_http_errors and resp.status_code in handle_http_errors:
            custom_error_msg = handle_http_errors[resp.status_code]
            if custom_error_msg:
                custom_error_msg = " " + custom_error_msg
            try:
                error_data = resp.json()
            except JSONDecodeError:
                error_data = {}
            _raise_varvis_error(
                error_data,
                f"Varvis API returned HTTP status code {resp.status_code}.{custom_error_msg}",
            )
        elif raise_for_status:
            resp.raise_for_status()

        return resp

    def _reset_state_on_logout(self) -> None:
        self._session = None
        self._loggedin_csrf = None
