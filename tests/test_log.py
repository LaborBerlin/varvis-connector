"""
Tests for varvis_connector CLI tool.

Copyright (C) 2026 Labor Berlin – Charité Vivantes GmbH

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

import logging
from datetime import date
from functools import partial

from varvis_connector._log import cli_logger, default_logger, get_logger


# usage of pytest caplog fixture requires to set remove_existing_handlers to False
cli_logger_for_test = partial(cli_logger, propagate=True)
default_logger_for_test = partial(default_logger, propagate=True)


def test_cli_logger_default_log_levels(caplog):
    # caplog.set_level(logging.INFO, logger="varvis_connector")
    logger = cli_logger_for_test()
    assert not logger.disabled
    assert logger.level == logging.INFO
    assert len(logger.handlers) == 2
    assert logger.handlers[0].level == logging.INFO
    assert logger.handlers[0].name == "varvis_connector_stdout"
    assert logger.handlers[1].level == logging.ERROR
    assert logger.handlers[1].name == "varvis_connector_stderr"
    logger.info("This is an info message")
    logger.error("This is an error message")

    assert caplog.record_tuples == [
        ("varvis_connector", logging.INFO, "This is an info message"),
        ("varvis_connector", logging.ERROR, "This is an error message"),
    ]


def test_cli_logger_custom_stdout_level(caplog):
    logger = cli_logger_for_test(log_level_stdout=logging.ERROR)
    logger.info("This should not appear in stdout logs")
    logger.error("This should appear in stdout logs")

    assert "This should not appear in stdout logs" not in caplog.text
    assert "This should appear in stdout logs" in caplog.text


def test_cli_logger_disable_stdout_logs(caplog):
    logger = cli_logger_for_test(log_level_stdout=-1)
    logger.info("This should not appear in stdout logs")
    logger.error("This should appear in stderr logs")

    assert "This should not appear in stdout logs" not in caplog.text
    assert "This should appear in stderr logs" in caplog.text


def test_cli_logger_disable_stderr_logs(caplog):
    logger = cli_logger_for_test(log_level_stderr=-1)
    assert len(logger.handlers) == 1
    assert logger.handlers[0].level == logging.INFO
    assert logger.handlers[0].name == "varvis_connector_stdout"
    logger.info("This is an info message")
    logger.error("This should not appear in stderr logs")

    assert "This is an info message" in caplog.text
    assert "This should not appear in stderr logs" in caplog.text  # still appears in stdout


def test_cli_logger_disable_all_logs(caplog):
    logger = cli_logger_for_test(log_level_stdout=-1, log_level_stderr=-1)
    assert logger.disabled
    logger.info("info")
    logger.error("err")

    assert caplog.text == ""


def test_default_logger_default_levels(caplog):
    logger = default_logger_for_test()
    assert not logger.disabled
    assert len(logger.handlers) == 1
    assert logger.handlers[0].level == logging.INFO
    assert logger.handlers[0].name == "varvis_connector_stderr"

    logger.info("Default logger info message")
    logger.error("Default logger error message")

    # caplog.text doesn't contain the formatted records, so we do it here manually
    text = "\n".join(logger.handlers[0].formatter.format(r) for r in caplog.records)  # pyright: ignore
    assert text.startswith(date.today().strftime("%Y-%m-%d "))
    assert " - varvis_connector - " in text
    assert "Default logger info message" in text
    assert "Default logger error message" in text


def test_get_logger_custom_formatter(caplog):
    formatter = logging.Formatter("%(levelname)s ||| %(message)s")
    logger = get_logger("custom_logger", formatter=formatter, propagate=True)
    logger.info("Info custom format")
    logger.error("Error custom format")

    # caplog.text doesn't contain the formatted records, so we do it here manually
    text = "\n".join(logger.handlers[0].formatter.format(r) for r in caplog.records)  # pyright: ignore
    assert "INFO ||| Info custom format" in text
    assert "ERROR ||| Error custom format" in text
