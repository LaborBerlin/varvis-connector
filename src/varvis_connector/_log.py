"""
Logging utilities.

:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

import logging
import os
import sys
import textwrap
from typing import Any

from ._cli_colors import style


# default log formats for each log level used in CLI
DEFAULT_LOG_FORMATS = {
    logging.DEBUG: style("DEBUG", fg="cyan") + " | " + style("%(message)s", fg="cyan"),
    logging.INFO: "%(message)s",
    logging.WARNING: style("WARN ", fg="yellow")
    + " | "
    + style("%(message)s", fg="yellow"),
    logging.ERROR: style("ERROR", fg="red") + " | " + style("%(message)s", fg="red"),
    logging.CRITICAL: style("FATAL", fg="white", bg="red", bold=True)
    + " | "
    + style("%(message)s", fg="red", bold=True),
}

DEFAULT_LOGGER_NAME = "varvis_connector"

# mapping of log level names to their numeric values
LOG_LEVEL_MAPPING = (
    logging.getLevelNamesMapping()  # pyright: ignore
    if hasattr(
        logging, "getLevelNamesMapping"
    )  # check if this function exists (only Py >= 3.11)
    else {
        "CRITICAL": 50,
        "FATAL": 50,
        "ERROR": 40,
        "WARN": 30,
        "WARNING": 30,
        "INFO": 20,
        "DEBUG": 10,
        "NOTSET": 0,
    }
)


def cli_logger(
    log_level_stdout: int = logging.NOTSET,
    log_level_stderr: int = logging.NOTSET,
    propagate: bool = False,
) -> logging.Logger:
    """
    Create a logger instance for use in the CLI.

    :param log_level_stdout: The logging level for the stdout handler. Special value -1 turns off stdout logging.
    :param log_level_stderr: The logging level for the stderr handler. Special value -1 turns off stderr logging.
    :param propagate: If True, propagate messages to parent loggers. If False, messages are only handled by this logger.
    :return: A logger instance.
    """
    if log_level_stdout == -1:
        log_level_stdout = logging.NOTSET
    elif log_level_stdout == logging.NOTSET:
        log_level_stdout = LOG_LEVEL_MAPPING.get(
            os.getenv("VARVIS_LOG_LEVEL", "INFO").upper(), logging.INFO
        )
    if log_level_stderr == -1:
        log_level_stderr = logging.NOTSET
    elif log_level_stderr == logging.NOTSET:
        log_level_stderr = logging.ERROR

    return get_logger(
        DEFAULT_LOGGER_NAME,
        stdout_level=log_level_stdout,
        stderr_level=log_level_stderr,
        formatter=MultiFormatter(),
        remove_existing_handlers=True,
        propagate=propagate,
    )


def default_logger(
    log_level_stdout: int = logging.NOTSET,
    log_level_stderr: int = logging.NOTSET,
    propagate: bool = False,
) -> logging.Logger:
    """
    Create a default logger instance for use in the package.

    :param log_level_stdout: The logging level for the stdout handler.
    :param log_level_stderr: The logging level for the stderr handler.
    :param propagate: If True, propagate messages to parent loggers. If False, messages are only handled by this logger.
    :return: A logger instance.
    """
    if log_level_stderr == logging.NOTSET:
        log_level_stderr = LOG_LEVEL_MAPPING.get(
            os.getenv("VARVIS_LOG_LEVEL", "INFO").upper(), logging.INFO
        )

    return get_logger(
        DEFAULT_LOGGER_NAME,
        stdout_level=log_level_stdout,
        stderr_level=log_level_stderr,
        remove_existing_handlers=True,
        propagate=propagate,
    )


def get_logger(
    name: str,
    stdout_level: int = logging.INFO,
    stderr_level: int = logging.ERROR,
    formatter: logging.Formatter | None = None,
    remove_existing_handlers: bool = False,
    propagate: bool = True,
) -> logging.Logger:
    """
    Create and configure a logger instance with both console and optional file
    handlers.

    This function initializes a logger by specifying its name, log level, and
    output settings such as console handlers. It configures these
    handlers with a provided formatter and ensures that logging messages conform to
    the specified format.

    :param name: The name of the logger.
    :param stdout_level: The logging level for the stdout handler.
    :param stderr_level: The logging level for the stderr handler.
    :param formatter: The formatter to be applied to log messages.
    :param remove_existing_handlers: If True, remove existing handlers before adding new ones.
    :param propagate: If True, propagate messages to parent loggers. If False, messages are only handled by this logger.

    :return: A configured logger instance.
    """
    # logger instance
    logger = logging.getLogger(name)
    if max(stdout_level, stderr_level) == logging.NOTSET:
        logger.disabled = True
    else:
        logger.disabled = False
        logger.setLevel(min([lvl for lvl in (stdout_level, stderr_level) if lvl > 0]))
    logger.propagate = propagate

    # default formatter
    if formatter is None:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    if remove_existing_handlers:
        # remove existing handlers first
        for h in logger.handlers.copy():
            if isinstance(h, logging.StreamHandler):
                logger.removeHandler(h)

    # add the handlers for stdout and stderr
    for lvl, stream in (stdout_level, sys.__stdout__), (stderr_level, sys.__stderr__):
        if lvl != logging.NOTSET:
            hndl = logging.StreamHandler(stream)
            hndl.set_name(
                f"{name}_stdout" if stream is sys.__stdout__ else f"{name}_stderr"
            )
            hndl.setLevel(lvl)
            hndl.setFormatter(formatter)

            if (
                stream is sys.__stdout__
                and stderr_level != logging.NOTSET
                and stderr_level > stdout_level
            ):
                hndl.addFilter(LogMaxFilter(stderr_level))
            elif (
                stream is sys.__stderr__
                and stdout_level != logging.NOTSET
                and stdout_level >= stderr_level
            ):
                hndl.addFilter(LogMaxFilter(stdout_level - 1))

            logger.addHandler(hndl)

    return logger


class PrettyExceptionFormatter(logging.Formatter):
    """
    Log message formatter that includes traceback information in case of an exception.

    Adapted from https://dev.to/eblocha/logging-in-python-command-line-applications-2gmi
    """

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)

        s = self.formatMessage(record)

        if record.exc_info:
            # Don't assign to exc_text here, since we don't want to inject color all the time
            if s[-1:] != "\n":
                s += "\n"
            # Add indent to indicate the traceback is part of the previous message
            text = textwrap.indent(self.formatException(record.exc_info), " " * 4)
            s += text

        return s


class MultiFormatter(PrettyExceptionFormatter):
    """
    Format log messages differently for each log level.

    Adapted from https://dev.to/eblocha/logging-in-python-command-line-applications-2gmi
    """

    def __init__(self, formats: dict[int, str] | None = None, **kwargs: Any) -> None:
        base_format = kwargs.pop("fmt", None)
        super().__init__(base_format, **kwargs)

        formats = formats or DEFAULT_LOG_FORMATS

        self.formatters = {
            level: PrettyExceptionFormatter(fmt, **kwargs)
            for level, fmt in formats.items()
        }

    def format(self, record: logging.LogRecord) -> str:
        formatter = self.formatters.get(record.levelno)

        if formatter is None:
            return super().format(record)

        return formatter.format(record)


class LogMaxFilter(logging.Filter):
    """Filter out all log messages with level >= max_level"""

    def __init__(self, max_level: int):
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.max_level
