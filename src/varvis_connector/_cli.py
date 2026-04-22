"""
varvis_connector CLI implementation module

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

import argparse
import logging
import os
import sys
import traceback
from abc import ABC
from dataclasses import dataclass, fields, MISSING
import getpass
from datetime import datetime
from pathlib import Path
from types import UnionType
from typing import Any, ClassVar, Type, Callable
import json

from pydantic import BaseModel, ValidationError

from varvis_connector.models import (
    SnvAnnotationData,
    QCCaseMetricsData,
    CoverageData,
    AnalysisItem,
    CaseReport,
    AnalysisFileDownloadLinks,
    PersonData,
    PersonUpdateData,
    VirtualPanelData,
    VirtualPanelUpdateData,
)
from ._log import cli_logger, LOG_LEVEL_MAPPING
from . import __version__, VarvisClient
from .errors import VarvisError


@dataclass(frozen=True)
class _CmdBase(ABC):
    """Base class for CLI commands."""

    logger: logging.Logger
    client: VarvisClient
    parsed_args: argparse.Namespace

    command: ClassVar[str] = ""
    help: ClassVar[str] = ""

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        pass  # default: no further arguments required

    @classmethod
    def _set_arguments_for_lims_ids(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "lims_ids",
            metavar="lims-ids",
            nargs="+",
            help="Person LIMS-ID(s). Repeat argument for multiple persons.",
        )

    @classmethod
    def _set_arguments_for_fileoutput(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "--output",
            type=argparse.FileType("w"),
            default="-",
            help="Output JSON file. If not given, output will be printed to stdout.",
        )
        argparser.add_argument(
            "--output-indent", type=int, default=None, help="Output JSON indentation."
        )

    @classmethod
    def _set_arguments_for_fileinput(
        cls,
        argparser: argparse.ArgumentParser,
        input_description: str,
        default: str | None = "-",
    ) -> None:
        argparser.add_argument(
            "--input",
            type=argparse.FileType("r"),
            default=default,
            help=f"{input_description}. If not given, input will be read from stdin.",
        )

    def _parse_virtual_panel_id(self) -> int | None:
        if (
            isinstance(self.parsed_args.virtual_panel_id, str)
            and self.parsed_args.virtual_panel_id.lower() == "none"
        ):
            return None

        try:
            return int(self.parsed_args.virtual_panel_id)
        except ValueError:
            self.logger.error('Provided virtual panel ID must be an integer or "none".')
            exit(1)

    def _write_file_output(
        self,
        data: Any,
        allow_empty_data: bool = False,
        serialize_modeldata: bool = True,
        stdout_info_message: str | None = None,
    ) -> None:
        def recursive_model_to_json(
            d: BaseModel | dict[str, Any] | list | str | float | int | None,
        ) -> BaseModel | dict[str, Any] | list | str | float | int | None:
            if isinstance(d, BaseModel):
                return d.model_dump(mode="json")
            elif isinstance(d, list):
                return [recursive_model_to_json(v) for v in d]
            elif isinstance(d, dict):
                # keys have to be strings in JSON
                return {str(k): recursive_model_to_json(v) for k, v in d.items()}
            else:
                return d

        serializable_data: Any

        if serialize_modeldata:
            if isinstance(data, BaseModel):
                serializable_data = data.model_dump(mode="json")
            else:
                if not allow_empty_data and len(data) == 0:
                    self.logger.error(
                        "Data retrieval failed for all requests. No data to write."
                    )
                    exit(1)

                serializable_data = recursive_model_to_json(data)
        else:
            serializable_data = data

        if self.parsed_args.output.name == "<stdout>" and stdout_info_message:
            self.logger.info(stdout_info_message)
        elif self.parsed_args.output.name != "<stdout>":
            self.logger.info(f'Writing output to file "{self.parsed_args.output.name}"')

        json.dump(
            serializable_data,
            self.parsed_args.output,
            indent=self.parsed_args.output_indent or None,
        )

    def run(self) -> None:
        raise NotImplementedError("Subclasses must implement the run() method.")

    def cleanup(self) -> None:
        pass


@dataclass(frozen=True)
class _CheckLoginCmd(_CmdBase):
    command: ClassVar[str] = "check-login"
    help: ClassVar[str] = "Check if logging in succeeds with the provided credentials."

    def run(self) -> None:
        self.client.login(raise_for_status=False)

    def cleanup(self) -> None:
        self.client.logout()


@dataclass(frozen=True)
class _AutoLoginCmdBase(_CmdBase):
    """Base class for CLI commands that automatically login and logout."""

    def run(self) -> None:
        self.client.login()

    def cleanup(self) -> None:
        self.client.logout()


@dataclass(frozen=True)
class _ArbitraryRequestCmd(_AutoLoginCmdBase):
    command: ClassVar[str] = "request"
    help: ClassVar[str] = (
        "Perform an arbitrary authenticated request to a Varvis API endpoint."
    )
    _http_methods: ClassVar[tuple[str, ...]] = (
        "get",
        "post",
        "put",
        "head",
        "patch",
        "delete",
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "endpoint",
            help="Varvis API endpoint to perform the request against. Note that some endpoints start with "
            '"api/", others don\'t. A slash at the beginning is not required.',
        )
        method_arg_grp = argparser.add_mutually_exclusive_group()
        for method in cls._http_methods:
            method_arg_grp.add_argument(
                f"--{method}",
                action="store_true",
                help=f"Use {method.upper()} method",
            )

        argparser.add_argument(
            "--raw-input",
            action="store_true",
            help="Send raw text input data instead of JSON.",
        )

        cls._set_arguments_for_fileinput(
            argparser,
            input_description="Optional input data in if sending data to an endpoint. "
            'Set to "-" in order to pass data from stdin',
            default=None,
        )
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        method = "GET"  # default method
        for m in self._http_methods:
            if getattr(self.parsed_args, m):
                method = m.upper()
                break

        # check if we have input to process
        kwargs = {}
        if self.parsed_args.input is not None:
            input_data = self.parsed_args.input.read()
            if self.parsed_args.raw_input:
                self.logger.info("Sending raw input data")
                self.logger.debug(f"Raw input data:\n{input_data}")
                kwargs = {"data": input_data}
            else:
                self.logger.info("Sending JSON input data")
                input_json = json.loads(input_data)
                self.logger.debug(
                    f"JSON input data:\n{json.dumps(input_json, indent=2)}"
                )
                kwargs = {"json": input_json}

        # send request and catch some common API error codes
        resp = self.client.request(
            self.parsed_args.endpoint,
            method,
            **kwargs,
        )

        # parse and write the output
        output_data = resp.json()
        self._write_file_output(
            output_data,
            serialize_modeldata=False,
            stdout_info_message="Response data written to stderr",
        )


@dataclass(frozen=True)
class _GetInternalPersonIdCmd(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-internal-person-id"
    help: ClassVar[str] = (
        "Retrieve the internal Varvis ID associated with given persons' LIMS-IDs. Generates JSON that maps LIMS IDs "
        "to internal person IDs. If an error occurs while retrieving data for a specific LIMS-ID, this ID will be "
        "skipped, but data retrieval for the other IDs will continue. If retrieving data fails for all LIMS IDs, the "
        "program will exit with an error description."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        cls._set_arguments_for_lims_ids(argparser)
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data: dict[str, int] = {}
        for lims_id in self.parsed_args.lims_ids:
            try:
                output_data[lims_id] = self.client.get_internal_person_id(lims_id)
            except Exception as exc:
                self.logger.warning(
                    f"Could not retrieve internal person ID for LIMS-ID {lims_id}: {exc}"
                )

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetSnvAnnotations(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-snv-annotations"
    help: ClassVar[str] = (
        "Retrieves the SNV annotations for given analysis IDs. Generates JSON that maps analysis IDs to SNV "
        "annotation data. If an error occurs while retrieving data for a specific analysis ID, this analysis will "
        "be skipped, but data retrieval for the other IDs will continue. If retrieving data fails for all analysis "
        "IDs, the program will exit with an error description."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "analysis_ids",
            metavar="analysis-ids",
            nargs="+",
            help="One or more analysis IDs (integers).",
        )
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data: dict[int, SnvAnnotationData] = {}
        for a_id in self.parsed_args.analysis_ids:
            try:
                a_id = int(a_id)
                output_data[a_id] = self.client.get_snv_annotations(a_id)
            except ValueError:
                self.logger.warning(f'Provided analysis ID "{a_id}" is not an integer.')
            except Exception as exc:
                self.logger.warning(
                    f"Could not retrieve SNV annotations for analysis ID {a_id}: {exc}"
                )

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetCnvTargetResults(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-cnv-target-results"
    help: ClassVar[str] = (
        "Retrieves the CNV target results for a specified person LIMS-ID and associated analyses. A virtual panel "
        "can optionally be specified to filter the results. Generates JSON with the CNV target results. If an error "
        "occurs while retrieving data, the program will exit with an error description."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "lims_id",
            metavar="lims-id",
            help="A person LIMS-ID for which to retrieve results.",
        )
        argparser.add_argument(
            "analysis_ids",
            metavar="analysis-ids",
            nargs="+",
            help="One or more analysis IDs (integers).",
        )
        argparser.add_argument(
            "--virtual-panel-id",
            default=1,
            help="Optional ID of the virtual panel to apply in filtering the CNV target data. By default, the "
            'virtual panel ID 1, i.e. the "all genes" panel is used. If set to the string "none", the virtual '
            'panel ID will be omitted. In that case, the Varvis documentation states that "the lastly selected '
            "virtual panel for the given person is used or 'All Genes' if no virtual panel was selected yet.\" "
            'This means, if set to "none" the behavior depends on the selection stored in the current user\'s session.',
        )
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        try:
            analysis_ids = list(map(int, self.parsed_args.analysis_ids))
        except ValueError:
            self.logger.error("Provided analysis IDs must all be integers.")
            exit(1)

        virtual_panel_id = self._parse_virtual_panel_id()

        try:
            output_data = self.client.get_cnv_target_results(
                self.parsed_args.lims_id,
                analysis_ids=analysis_ids,
                virtual_panel_id=virtual_panel_id,
            )
        except Exception as exc:
            self.logger.error(
                f'Could not retrieve CNV target results for LIMS-ID "{self.parsed_args.lims_id}": {exc}'
            )
            exit(1)

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetPendingCnvSegments(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-pending-cnv-segments"
    help: ClassVar[str] = (
        "Retrieves pending CNV segments based for a given person (identified either by internal ID or LIMS ID) and "
        "associated analysis IDs. A virtual panel can optionally be specified to filter the results. "
        "Generates JSON with the pending CNV segments. If an error occurs while retrieving data, the program will "
        "exit with an error description."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        lims_or_internal_id = argparser.add_mutually_exclusive_group(required=True)
        lims_or_internal_id.add_argument(
            "--lims-id",
            help="A person LIMS-ID for which to retrieve results. Either this or "
            "--internal-person-id must be provided.",
        )
        lims_or_internal_id.add_argument(
            "--internal-person-id",
            help="Internal varvis person ID for which to retrieve results. Either "
            "this or --lims-id must be provided.",
        )

        argparser.add_argument(
            "analysis_ids",
            metavar="analysis-ids",
            nargs="+",
            help="One or more analysis IDs (integers).",
        )
        argparser.add_argument(
            "--virtual-panel-id",
            default=1,
            help="Optional ID of the virtual panel to apply in filtering the CNV segments. By default, the "
            'virtual panel ID 1, i.e. the "all genes" panel is used. If set to the string "none", the virtual '
            'panel ID will be omitted. In that case, the Varvis documentation states that "the lastly selected '
            "virtual panel for the given person is used or 'All Genes' if no virtual panel was selected yet.\" "
            'This means, if set to "none" the behavior depends on the selection stored in the current user\'s session.',
        )
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        kwargs = {}
        if self.parsed_args.lims_id is not None:
            kwargs["person_lims_id"] = self.parsed_args.lims_id
        else:
            try:
                kwargs["person_id"] = int(self.parsed_args.internal_person_id)
            except ValueError:
                self.logger.error("Provided internal person ID must be an integer.")
                exit(1)

        try:
            kwargs["analysis_ids"] = list(map(int, self.parsed_args.analysis_ids))
        except ValueError:
            self.logger.error("Provided analysis IDs must all be integers.")
            exit(1)

        kwargs["virtual_panel_id"] = self._parse_virtual_panel_id()

        try:
            output_data = self.client.get_pending_cnv_segments(**kwargs)
        except Exception as exc:
            id_info = (
                f'LIMS-ID "{self.parsed_args.lims_id}"'
                if self.parsed_args.lims_id
                else f"internal person ID {self.parsed_args.internal_person_id}"
            )
            self.logger.error(
                f"Could not retrieve pending CNV segments for {id_info}: {exc}"
            )
            exit(1)

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetQcCaseMetricsCmd(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-qc-case-metrics"
    help: ClassVar[str] = "Retrieves QC case metrics for given person LIMS-ID(s)."

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        cls._set_arguments_for_lims_ids(argparser)
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data: dict[str, QCCaseMetricsData] = {}
        for lims_id in self.parsed_args.lims_ids:
            try:
                output_data[lims_id] = self.client.get_qc_case_metrics(lims_id)
            except Exception as exc:
                self.logger.warning(
                    f"Could not retrieve QC case metrics for person LIMS-ID {lims_id}: {exc}"
                )

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetCoverageData(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-coverage-data"
    help: ClassVar[str] = (
        "Retrieves coverage data for given person LIMS-ID(s), optionally filtered by virtual panel ID."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        cls._set_arguments_for_lims_ids(argparser)
        argparser.add_argument(
            "--virtual-panel-id",
            default=1,
            help="Optional ID of the virtual panel to apply in filtering the coverage data. By default, the "
            'virtual panel ID 1, i.e. the "all genes" panel is used. If set to the string "none", the virtual '
            'panel ID will be omitted. In that case, the Varvis documentation states that "the lastly selected '
            "virtual panel for the given person is used or 'All Genes' if no virtual panel was selected yet.\" "
            'This means, if set to "none" the behavior depends on the selection stored in the current user\'s session.',
        )
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        virtual_panel_id = self._parse_virtual_panel_id()

        output_data: dict[str, list[CoverageData]] = {}
        for lims_id in self.parsed_args.lims_ids:
            try:
                output_data[lims_id] = self.client.get_coverage_data(
                    lims_id, virtual_panel_id
                )
            except Exception as exc:
                self.logger.warning(
                    f"Could not retrieve coverage data for person LIMS-ID {lims_id}: {exc}"
                )

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetAnalyses(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-analyses"
    help: ClassVar[str] = (
        "Get basic information about analyses including the timestamps of first and last annotation. Optionally, the "
        "analyses can be filtered by analysis IDs."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "--analysis-ids",
            nargs="*",
            help="Optional analysis IDs to filter the results by.",
        )
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()
        output_data = self.client.get_analyses(self.parsed_args.analysis_ids)
        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetReportInfoForPersons(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-report-info-for-persons"
    help: ClassVar[str] = "Retrieves case report information all persons."

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()
        output_data = self.client.get_report_info_for_persons()
        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetPersonAnalyses(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-person-analyses"
    help: ClassVar[str] = (
        "Get basic information about analyses for given person LIMS-ID(s)."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        cls._set_arguments_for_lims_ids(argparser)
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data: dict[str, list[AnalysisItem]] = {}
        for lims_id in self.parsed_args.lims_ids:
            try:
                output_data[lims_id] = self.client.get_person_analyses(lims_id)
            except Exception as exc:
                self.logger.warning(
                    f"Could not retrieve analyses for person LIMS-ID {lims_id}: {exc}"
                )

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetCaseReport(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-case-report"
    help: ClassVar[str] = (
        "Retrieves case report information for given person LIMS-ID(s)."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        cls._set_arguments_for_lims_ids(argparser)
        argparser.add_argument(
            "--draft",
            action="store_true",
            help="Set this if a draft report with pending changes is explicitly requested instead of the final report (submitted report).",
        )
        argparser.add_argument(
            "--inactive",
            action="store_true",
            help="Set this if inactive report items should be also returned (by default inactive report items are not returned).",
        )
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data: dict[str, CaseReport] = {}
        for lims_id in self.parsed_args.lims_ids:
            try:
                output_data[lims_id] = self.client.get_case_report(
                    lims_id,
                    draft=self.parsed_args.draft,
                    inactive=self.parsed_args.inactive,
                )
            except Exception as exc:
                self.logger.warning(
                    f"Could not retrieve analyses for person LIMS-ID {lims_id}: {exc}"
                )

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetPerson(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-person"
    help: ClassVar[str] = (
        "Retrieves person data including clinical information for given person LIMS-ID(s)."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        cls._set_arguments_for_lims_ids(argparser)
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data: dict[str, PersonData] = {}
        for lims_id in self.parsed_args.lims_ids:
            try:
                output_data[lims_id] = self.client.get_person(lims_id)
            except Exception as exc:
                self.logger.warning(
                    f"Could not retrieve person information for person LIMS-ID {lims_id}: {exc}"
                )

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _CreateOrUpdatePerson(_AutoLoginCmdBase):
    """
    Class for creating or updating a person entry.

    Note that unlike the endpoint to create or update a virtual panel, you can't directly control whether a person entry
    is created or updated since the LIMS ID must always be given. Hence we can't separate this into two commands like
    ``create-person`` and ``update-person`` as it is done with the virtual panel commands in the
    ``_CreateOrUpdateVirtualPanelBase`` class.
    """

    command: ClassVar[str] = "create-or-update-person"
    help: ClassVar[str] = (
        "Allows to create a new person entry, or updates an existing one. Person data can be passed either via "
        "arguments like --lims-id or as JSON data that follows the PersonUpdateData schema (see documentation). "
        "The JSON data can be passed via stdin (default) or loaded from file using the --input argument. If any "
        "person data CLI argument is given, any JSON input will be ignored. The command reports the internal ID of the "
        "person entry that was created or updated."
    )
    person_fields_to_args: ClassVar[dict[str, str]] = {
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

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        for fieldname, argname in cls.person_fields_to_args.items():
            if fieldname == "birthDate":
                description = "The person's birthdate given in YYYY-MM-DD format."
            elif fieldname == "hpoTermIds":
                description = 'A list of HPO term IDs (in the form of "HP:0123456") that are associated with the person.'
            else:
                description = PersonUpdateData.model_fields[fieldname].description or ""

            argparser.add_argument(
                f"--{argname}",
                help=description,
                default=None,
                nargs="+" if fieldname == "hpoTermIds" else None,
            )

        cls._set_arguments_for_fileinput(
            argparser,
            input_description="Optional input JSON file that follows that PersonUpdateData schema. Can be used as "
            "alternative to providing the data via the above arguments",
        )

    def run(self) -> None:
        super().run()

        # first check if data was provided via CLI arguments
        data_from_args = {}
        for fieldname, argname in self.person_fields_to_args.items():
            attrname = argname.replace("-", "_")
            argval = getattr(self.parsed_args, attrname)
            if argval is not None:
                if fieldname == "birthDate":
                    try:
                        birth_date = datetime.strptime(argval, "%Y-%m-%d").date()
                    except ValueError:
                        self.logger.error(
                            f"The provided birth date '{argval}' is not in the expected format YYYY-MM-DD."
                        )
                        exit(1)
                    data_from_args["birthDateYear"] = birth_date.year
                    data_from_args["birthDateMonth"] = birth_date.month
                    data_from_args["birthDateDay"] = birth_date.day
                else:
                    data_from_args[fieldname] = argval
        if data_from_args:
            # if CLI arguments were given, check for validity
            self.logger.debug("Data provided via CLI arguments")
            lims_id = data_from_args.get("id")
            if lims_id is None:
                self.logger.error(
                    "The LIMS ID must be provided when passing person data via CLI arguments."
                )
                exit(1)
            try:
                person_data = PersonUpdateData.model_validate(data_from_args)
            except ValidationError as exc:
                self.logger.error(
                    f"The provided data passed as CLI arguments is not valid:\n{exc}"
                )
                exit(1)
        else:
            # if no CLI arguments were given, check if data was provided via stdin or file
            self.logger.debug("Data provided as file or via stdin")
            json_data = self.parsed_args.input.read()
            try:
                person_data = PersonUpdateData.model_validate_json(json_data)
            except ValidationError as exc:
                self.logger.error(f"The provided JSON data is not valid:\n{exc}")
                exit(1)

        self.logger.debug(
            "Will send the following person data to the Varvis API:\n%s",
            person_data.model_dump_json(indent=2),
        )
        internal_pers_id = self.client.create_or_update_person(person_data)
        self.logger.info(
            f"Successfully created or updated person with internal person ID {internal_pers_id}"
        )


@dataclass(frozen=True)
class _FindAnalysesByFilename(_AutoLoginCmdBase):
    command: ClassVar[str] = "find-analyses-by-filename"
    help: ClassVar[str] = (
        "Find analyses by searching for the given filename components within customer-provided input file names."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "filename",
            nargs="+",
            help="One or more filename components to search for. Each component is treated as a substring search where "
            "all of the provided components must be found in a customer input filename for the corresponding "
            "analysis to be included in the result (AND operator).",
        )

        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data = None
        try:
            output_data = self.client.find_analyses_by_filename(
                self.parsed_args.filename
            )
        except Exception as exc:
            self.logger.error(f"Error while searching for analyses by filename: {exc}")

        if output_data is not None:
            self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetVirtualPanel(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-virtual-panel"
    help: ClassVar[str] = (
        "Retrieves virtual panel data for given virtual panel IDs. Returned data includes name, active status, and "
        "details of the genes that are associated with the virtual panel."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "ids",
            nargs="+",
            help="List of virtual panel IDs to retrieve data for.",
        )

        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data: dict[int, VirtualPanelData] = {}
        for vp_id in self.parsed_args.ids:
            try:
                output_data[vp_id] = self.client.get_virtual_panel(vp_id)
            except Exception as exc:
                self.logger.warning(
                    f"Error while retrieving virtual panel {vp_id}: {exc}"
                )

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _GetVirtualPanelSummaries(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-virtual-panel-summaries"
    help: ClassVar[str] = (
        "Retrieves the summaries for all virtual panels, except for the virtual panel "
        "containing all genes."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data = None
        try:
            output_data = self.client.get_virtual_panel_summaries()
        except Exception as exc:
            self.logger.error(f"Error while retrieving virtual panel summaries: {exc}")

        if output_data is not None:
            self._write_file_output(output_data, allow_empty_data=True)


@dataclass(frozen=True)
class _GetAllGenes(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-all-genes"
    help: ClassVar[str] = (
        "Retrieves a list of all genes and their details. The details are reduced to information important for "
        "virtual panels."
    )

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        output_data = None
        try:
            output_data = self.client.get_all_genes()
        except Exception as exc:
            self.logger.error(f"Error while retrieving all genes: {exc}")

        if output_data is not None:
            self._write_file_output(output_data, allow_empty_data=True)


@dataclass(frozen=True)
class _CreateOrUpdateVirtualPanelBase(_AutoLoginCmdBase):
    """
    Base class for creating or updating a virtual panel defined in ``_CreateVirtualPanel`` and ``_CreateVirtualPanel``
    respectively.
    """

    create: ClassVar[bool]
    virtual_panel_fields_to_args: ClassVar[dict[str, str]] = {
        "id": "id",
        "name": "name",
        "active": "active",
        "inactive": "inactive",
        "geneIds": "gene-ids",
        "description": "description",
        "personId": "person-id",
    }

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        for fieldname, argname in cls.virtual_panel_fields_to_args.items():
            if cls.create and fieldname in {"id", "inactive"}:
                continue

            if fieldname != "inactive":
                fieldinfo = VirtualPanelUpdateData.model_fields[fieldname]

                if fieldname == "id":
                    description = "The virtual panel id for the panel to be updated."
                elif fieldname == "active":
                    description = "Set this flag in order to activate the virtual panel (has precedence over --inactive)."
                else:
                    description = fieldinfo.description or ""
            else:
                description = "Set this flag in order to deactivate the virtual panel."

            arg_kwarg: dict[str, Any] = {}
            if argname in {"active", "inactive"}:
                arg_kwarg["action"] = "store_true"
            else:
                arg_kwarg["type"] = (
                    int if argname in {"id", "gene-ids", "person-id"} else str
                )
                arg_kwarg["nargs"] = "+" if argname == "gene-ids" else None

            argparser.add_argument(
                f"--{argname}", default=None, help=description, **arg_kwarg
            )

        cls._set_arguments_for_fileinput(
            argparser,
            input_description="Optional input JSON file that follows that VirtualPanelUpdateData schema. Can be used "
            "as alternative to providing the data via the above arguments",
        )

    def run(self) -> None:
        super().run()

        # first check if data was provided via CLI arguments
        data_from_args = {}
        for fieldname, argname in self.virtual_panel_fields_to_args.items():
            if self.create and fieldname in {"id", "inactive"}:
                continue
            attrname = argname.replace("-", "_")
            argval = getattr(self.parsed_args, attrname)
            if argval is not None:
                data_from_args[fieldname] = argval

        if data_from_args:
            # CLI arguments were given
            data_from_args["active"] = self.parsed_args.active or False

            # apply inactive flag
            if (
                not self.create
                and "inactive" in data_from_args
                and "active" not in data_from_args
            ):
                data_from_args["active"] = False
                del data_from_args["inactive"]

            self.logger.debug("Data provided via CLI arguments")
            model_data = data_from_args
        else:
            # no CLI arguments were given
            self.logger.debug("Data provided as file or via stdin")
            try:
                model_data = json.loads(self.parsed_args.input.read())
            except json.JSONDecodeError as exc:
                self.logger.error(f"Error while parsing JSON: {exc}")
                exit(1)

        vp_id = model_data.get("id")
        if self.create:
            if vp_id is not None:
                self.logger.error(
                    "When creating a new virtual panel, no ID must be given."
                )
                exit(1)
        else:
            if vp_id is None:
                self.logger.error("When updating a virtual panel, an ID must be given.")
                exit(1)

            if set(model_data.keys()) == {"id"}:
                self.logger.error(
                    "When updating an existing virtual panel, at least one field must be provided other than ID."
                )
                exit(1)

            # fetch existing VP data so that we only update what was given and leave other fields unchanged
            try:
                existing_vp_data = self.client.get_virtual_panel(vp_id).model_dump()
            except VarvisError:
                self.logger.error(
                    "Could not retrieve existing virtual panel data for ID %d", vp_id
                )
                exit(1)

            for fieldname in self.virtual_panel_fields_to_args.keys():
                if fieldname in {"id", "inactive"}:
                    continue
                if fieldname not in model_data:
                    if fieldname == "geneIds":
                        existing_val = [g["id"] for g in existing_vp_data["genes"]]
                    else:
                        existing_val = existing_vp_data[fieldname]
                    model_data[fieldname] = existing_val

        try:
            vp_data = VirtualPanelUpdateData.model_validate(model_data)
        except ValidationError as exc:
            self.logger.error(f"The provided data is not valid:\n{exc}")
            exit(1)

        self.logger.debug(
            "Will send the following virtual panel data to the Varvis API:\n%s",
            vp_data.model_dump_json(indent=2),
        )
        internal_vp_id = self.client.create_or_update_virtual_panel(vp_data)
        if vp_data.id is None:
            self.logger.info(
                f"Successfully created virtual panel with ID {internal_vp_id}"
            )
        else:
            self.logger.info(
                f"Successfully updated virtual panel with ID {internal_vp_id}"
            )


@dataclass(frozen=True)
class _CreateVirtualPanel(_CreateOrUpdateVirtualPanelBase):
    command: ClassVar[str] = "create-virtual-panel"
    help: ClassVar[str] = (
        "Allows to create a new virtual panel entry. Data can be passed either via arguments like --name or as JSON "
        "data that follows the VirtualPanelUpdateData schema (see documentation). The JSON data can be passed via "
        "stdin (default) or loaded from file using the --input argument. If any virtual panel data CLI argument is "
        "given, any JSON input will be ignored. The command reports the ID of the virtual panel that was created."
    )
    create: ClassVar[bool] = True


@dataclass(frozen=True)
class _UpdateVirtualPanel(_CreateOrUpdateVirtualPanelBase):
    command: ClassVar[str] = "update-virtual-panel"
    help: ClassVar[str] = (
        "Allows to update an existing virtual panel entry identified by an ID. Data can be passed either via arguments "
        "like --name or as JSON data that follows the VirtualPanelUpdateData schema (see documentation). The JSON data "
        "can be passed via stdin (default) or loaded from file using the --input argument. If any virtual panel data "
        "CLI argument is given, any JSON input will be ignored.  The command reports the ID of the virtual panel that "
        "was updated."
    )
    create: ClassVar[bool] = False


@dataclass(frozen=True)
class _GetFileDownloadLinks(_AutoLoginCmdBase):
    command: ClassVar[str] = "get-file-download-links"
    help: ClassVar[str] = "Retrieve file download links for given analysis IDs."

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "analysis_ids",
            metavar="analysis-ids",
            nargs="+",
            help="One or more analysis IDs (integers).",
        )

        cls._set_arguments_for_fileoutput(argparser)

    def run(self) -> None:
        super().run()

        # JSON doesn't allow integer keys, so we use the analysis ID as string here
        output_data: dict[str, AnalysisFileDownloadLinks] = {}
        for analysis_id in self.parsed_args.analysis_ids:
            try:
                analysis_id = int(analysis_id)
                output_data[str(analysis_id)] = self.client.get_file_download_links(
                    analysis_id
                )
            except Exception as exc:
                self.logger.warning(
                    f"Could not retrieve file download links for analysis ID {analysis_id}: {exc}"
                )

        self._write_file_output(output_data)


@dataclass(frozen=True)
class _DownloadFiles(_AutoLoginCmdBase):
    command: ClassVar[str] = "download-files"
    help: ClassVar[str] = "Downloads files for given analysis IDs."

    @classmethod
    def set_up_arguments(cls, argparser: argparse.ArgumentParser) -> None:
        argparser.add_argument(
            "analysis_ids",
            metavar="analysis-ids",
            nargs="+",
            help="One or more analysis IDs (integers).",
        )
        argparser.add_argument(
            "--output-dir",
            default=os.getcwd(),
            help="Optional output directory for downloaded files. Defaults to the current working directory.",
        )
        argparser.add_argument(
            "--create-folder-per-id",
            nargs="?",
            const=True,
            default=False,
            help="If set, create a separate folder for each analysis ID using this folder name template. The template "
            'can contain the placeholder "%%ID" which will be replaced by the analysis ID. If this placeholder is '
            "not given, the analysis ID will be simply appended. By default, no folders will be created and all "
            'files will be written to the directory specified by the "--output-dir" option.',
        )
        argparser.add_argument(
            "--file-pattern",
            action="append",
            nargs="*",
            default=[],
            help="Optional file pattern(s) to filter the files to download. Pass glob-style patterns as arguments "
            "like '*.gz' and always use quotes to prevent shell expansion. Argument can be repeated.",
        )
        argparser.add_argument(
            "--overwrite",
            action="store_true",
            help="Set this if existing files should be overwritten.",
        )
        argparser.add_argument(
            "--no-progress",
            action="store_true",
            help="Set this if no progress bar should be shown during the download.",
        )
        argparser.add_argument(
            "--parallel-downloads",
            default=1,
            help="Maximum number of parallel downloads. Defaults to 1 (no parallel downloads).",
        )

    def run(self) -> None:
        super().run()

        output_dir = Path(self.parsed_args.output_dir)

        if not output_dir.is_dir():
            self.logger.error(
                f"Output directory does not exist: {output_dir.absolute()}"
            )
            return

        try:
            max_parallel_downloads = int(self.parsed_args.parallel_downloads)
        except ValueError:
            self.logger.error("Argument --parallel-downloads must be an integer.")
            return

        urls_and_target_paths: dict[str, Path] = {}
        for analysis_id in self.parsed_args.analysis_ids:
            try:
                analysis_id = int(analysis_id)
            except ValueError:
                self.logger.warning(
                    f"Invalid analysis ID (must be an integer): {analysis_id}"
                )

            if analysis_foldername_template := self.parsed_args.create_folder_per_id:
                if isinstance(
                    analysis_foldername_template, str
                ):  # used as string value
                    if "%ID" not in analysis_foldername_template:
                        analysis_foldername_template += "%ID"
                    analysis_foldername = analysis_foldername_template.replace(
                        "%ID", str(analysis_id)
                    )
                else:  # used as flag and set to True
                    analysis_foldername = str(analysis_id)

                analysis_target_folder = output_dir / analysis_foldername
                analysis_target_folder.mkdir(exist_ok=True)
            else:
                analysis_target_folder = output_dir

            # flatten this list
            file_patterns = []
            for pat in self.parsed_args.file_pattern:
                file_patterns.extend(pat)

            # collect the download URLS
            try:
                urls_and_paths_for_analysis = self.client.download_files(
                    analysis_id,
                    analysis_target_folder,
                    file_patterns=file_patterns,
                    allow_overwrite=self.parsed_args.overwrite,
                    only_collect_urls=True,
                )
            except Exception as exc:
                self.logger.warning(
                    f"Could not retrieve file download links for analysis ID {analysis_id}: {exc}"
                )
                continue

            for url in urls_and_paths_for_analysis:
                if url in urls_and_target_paths:
                    self.logger.warning(
                        "Download URL for analysis ID %d already collected from a previous "
                        "analysis ID. Target path will be overwritten.",
                        analysis_id,
                    )

            urls_and_target_paths.update(urls_and_paths_for_analysis)

        if not urls_and_target_paths:
            self.logger.info("No files to download")
            return

        self.logger.info("Starting the following downloads:")
        for i, (url, target_path) in enumerate(urls_and_target_paths.items(), 1):
            self.logger.info(
                f'Download #{i}: "{target_path.name}" -> "{target_path.parent}"'
            )

        # actually download the files
        show_progress = not self.parsed_args.no_progress
        downloads_result = self.client.download_files_from_urls_parallel(
            urls_and_target_paths,
            max_parallel_downloads=max_parallel_downloads,
            show_progress_bar=show_progress,
            return_messages=show_progress,
        )
        if show_progress:
            assert isinstance(downloads_result, tuple) and len(downloads_result) == 2
            _, messages = downloads_result
            for lvl, msg in messages:
                self.logger.log(lvl, msg)


@dataclass
class VarvisCLI:
    """
    Represents the command-line interface for the Varvis application.

    Handles initialization, argument parsing, and logging setup necessary for running
    the Varvis command-line functionality. The purpose of this class is to provide a
    interface for users to interact with the application through commands and options in
    a terminal environment.

    :ivar logger: Logger instance used for application logging throughout the CLI.
    :ivar _argparser: Argument parser for handling command-line arguments and options.
    :ivar _parsed_args: Parsed arguments from the command-line input.
    """

    logger: logging.Logger | None = None
    _argparser: argparse.ArgumentParser | None = None
    _parsed_args: argparse.Namespace | None = None
    _client: VarvisClient | None = None

    # register all available commands
    _commands: ClassVar[dict[str, Type[_CmdBase]]] = {
        _CheckLoginCmd.command: _CheckLoginCmd,
        _GetInternalPersonIdCmd.command: _GetInternalPersonIdCmd,
        _GetSnvAnnotations.command: _GetSnvAnnotations,
        _GetCnvTargetResults.command: _GetCnvTargetResults,
        _GetPendingCnvSegments.command: _GetPendingCnvSegments,
        _GetQcCaseMetricsCmd.command: _GetQcCaseMetricsCmd,
        _GetCoverageData.command: _GetCoverageData,
        _GetAnalyses.command: _GetAnalyses,
        _GetReportInfoForPersons.command: _GetReportInfoForPersons,
        _GetPersonAnalyses.command: _GetPersonAnalyses,
        _GetCaseReport.command: _GetCaseReport,
        _GetPerson.command: _GetPerson,
        _CreateOrUpdatePerson.command: _CreateOrUpdatePerson,
        _GetVirtualPanel.command: _GetVirtualPanel,
        _GetVirtualPanelSummaries.command: _GetVirtualPanelSummaries,
        _GetAllGenes.command: _GetAllGenes,
        _CreateVirtualPanel.command: _CreateVirtualPanel,
        _UpdateVirtualPanel.command: _UpdateVirtualPanel,
        _FindAnalysesByFilename.command: _FindAnalysesByFilename,
        _GetFileDownloadLinks.command: _GetFileDownloadLinks,
        _DownloadFiles.command: _DownloadFiles,
        _ArbitraryRequestCmd.command: _ArbitraryRequestCmd,
    }

    def run(self) -> None:
        # set up arguments; logging is not available yet, so we capture errors during setup and log them later
        failed_setup_msg = None
        client_config = {}
        try:
            client_config = self._setup_argparser()
        except RuntimeError as exc:
            failed_setup_msg = str(exc)

        assert self._argparser is not None
        assert self._parsed_args is not None

        # set up logging
        self._setup_logging()
        assert self.logger is not None

        if failed_setup_msg:
            self.logger.critical(failed_setup_msg)
            exit(2)

        self.logger.info("Running varvis_connector v%s", __version__)

        # initialize the Varvis client
        self._client = VarvisClient(**client_config, logger=self.logger)

        # set up the specified command and run it
        cmd_class = self._commands[self._parsed_args.command]
        cmd_instance = cmd_class(self.logger, self._client, self._parsed_args)

        if not int(
            os.getenv("TEST_DONT_RUN_CMD", "0")
        ):  # running the actual command can be disabled for testing purposes
            try:
                cmd_instance.run()
                cmd_instance.cleanup()
            except Exception as exc:
                self.logger.error(exc)
                self.logger.error(traceback.format_exc())
                try:
                    self._client.logout()
                except Exception as exc:
                    self.logger.error("Another error occurred during logout:")
                    self.logger.error(exc)
                exit(1)

    def _setup_argparser(self) -> dict[str, Any]:
        # first set up up the standard CLI arguments like API URL, username, etc.
        self._argparser = argparse.ArgumentParser(prog="varvis_connector")

        # maps varvis client config options argument name to tuple of
        # (config option name, environment variable name, type, is_required)
        config_args_defaults: dict[str, tuple[str, str, Callable, bool]] = {}
        for field in fields(VarvisClient):
            if not field.name.startswith("_") and field.name != "logger":
                argname = field.metadata.get("argname", field.name.replace("_", "-"))
                kwargs = {
                    "dest": field.name,
                    "help": field.metadata["help"] + "."
                    if "help" in field.metadata
                    else "",
                    "default": None,
                }
                if field.type is bool:
                    kwargs["action"] = "store_false" if field.default else "store_true"
                else:
                    if isinstance(field.type, UnionType):
                        types_not_none = [
                            t for t in field.type.__args__ if t is not None
                        ]
                        if len(types_not_none) == 1:
                            kwargs["type"] = types_not_none[0]
                    else:
                        kwargs["type"] = field.type

                config_envvar_name: str = field.metadata.get(
                    "envvar", f"VARVIS_{field.name.upper()}"
                )

                type_func: Callable = kwargs.get(  # type: ignore
                    "type",
                    (lambda x: x.lower() in {"1", "true", "yes"})
                    if kwargs.get("action") in {"store_true", "store_false"}
                    else str,
                )

                config_args_defaults[argname] = (
                    field.name,
                    config_envvar_name,
                    type_func,
                    field.default is MISSING,
                )
                self._argparser.add_argument(f"--{argname}", **kwargs)  # type: ignore

        # set up version argument
        self._argparser.add_argument(
            "--version", action="version", version=f"varvis_connector v{__version__}"
        )

        # set up log level
        lvls = [
            lvl.lower() for lvl in LOG_LEVEL_MAPPING if lvl not in {"NOTSET", "WARN"}
        ] + ["off"]
        self._argparser.add_argument(
            "--loglevel",
            choices=lvls,
            default="info",
            help=f"Set the log level. Possible values are: {', '.join(lvls)}. Default is 'info'.",
        )

        # set up sub-command arguments
        subargs = self._argparser.add_subparsers(dest="command", required=True)
        for cmd in self._commands.values():
            cmd_arg_parser = subargs.add_parser(cmd.command, help=cmd.help)
            cmd.set_up_arguments(cmd_arg_parser)

        # parse the arguments
        self._parsed_args = self._argparser.parse_args()

        # process the standard CLI arguments which will be used as options for the VarvisClient instance
        client_config: dict[str, Any] = {}
        for opt_argname, (
            opt_fieldname,
            envvar,
            type_func,
            is_required,
        ) in config_args_defaults.items():
            opt_val = getattr(self._parsed_args, opt_fieldname, None)

            if opt_val is None:
                opt_val = os.getenv(envvar, None)
                if opt_val is not None:
                    try:
                        opt_val = type_func(opt_val)
                    except ValueError:
                        raise RuntimeError(
                            f'The provided value for option "{opt_argname}" could not be parsed.'
                        )

            if opt_val is not None:
                client_config[opt_fieldname] = opt_val
            elif opt_val is None and is_required:
                if opt_argname == "password":
                    client_config[opt_fieldname] = getpass.getpass(
                        f'Password not provided via environment variable or program argument. Please enter the password for user "{client_config["username"]}": '
                    )
                else:
                    raise RuntimeError(
                        f'Option "{opt_argname}" is required but not provided. Either pass it as a command-line argument or set the environment variable "{envvar}".'
                    )

        return client_config

    def _setup_logging(self) -> None:
        assert self._parsed_args is not None
        log_level_label = self._parsed_args.loglevel.upper()
        log_level_value = LOG_LEVEL_MAPPING.get(log_level_label, -1)

        level_stdout = log_level_value
        level_stderr = (
            -1
            if log_level_value == -1
            else (logging.ERROR if log_level_value < logging.ERROR else logging.NOTSET)
        )

        if getattr(self._parsed_args, "output", None) is sys.__stdout__ or int(
            os.getenv("TEST_WRITES_TO_STDOUT", "0")
        ):
            # in case file output is printed to stdout, we want to log to stderr only
            level_stderr = level_stdout
            level_stdout = -1

        self.logger = self.logger or cli_logger(
            log_level_stdout=level_stdout,
            log_level_stderr=level_stderr,
        )
