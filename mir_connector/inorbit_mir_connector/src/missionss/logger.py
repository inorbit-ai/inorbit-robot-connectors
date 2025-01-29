"""
logger

Defines a a logger with a custom format to be used across
all the modules.

Class:
    CustomFormatter: Defines a logger formater, with different colors
    and format.
    OnceLogger: defines a logger which reports events only once.

Functions:
    setup_logger: defines a logger, sets it up and return it.
"""

import logging
import platform

# from settings import get_settings


class CustomFormatter(logging.Formatter):

    grey = "\x1b[38;20m"
    green = "\x1b[32m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"

    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: green + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset,
    }

    def format(self, record):
        """
        Override format method to apply color formatting based on the log level.

        Args:
            record (logging.LogRecord): Log record object containing log details.

        Returns:
            str: Formatted log message with color.
        """
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def setup_logger(name: str) -> logging.Logger:
    """
    Set up a logger with the custom formatter.

    Args:
        name (str): The name of the logger.
        log_level (str): Logging level (default: "INFO").

    Returns:
        logging.Logger: Configured logger with the custom formatter.
    """
    # log_level = get_settings().loglevel
    log_level = "DEBUG"
    logger = logging.getLogger(name)
    logger.setLevel(log_level.upper())

    os_name = platform.system()
    if os_name == "Windows":
        log_file_path = "../logs/inorbit_bluebotics_connector.log"
    else:
        log_file_path = "/tmp/inorbit_bluebotics_connector.log"

    if not logger.hasHandlers():
        file_handler = logging.FileHandler(log_file_path)
        logger.addHandler(file_handler)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(CustomFormatter())
        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(console_handler)

    return logger


class OnceLogger:
    def __init__(self, log_handle):
        self._log = log_handle
        self._reported_events = {}

    def warning(self, key: str, msg: str):
        """
        Logs a warn message if it's a new event, and increments occurrence
        number if it's a known issue.
        """
        if self._should_report_event(key):
            self._log.warning(msg + " [reported once]")
            self._reported_events[key] = 1
        else:
            self._reported_events[key] += 1

    def error(self, key: str, msg: str):
        """
        Logs an error message if it's a new event, and increments occurrence
        number if it's a known issue.
        """
        if self._should_report_event(key):
            self._log.error(msg + " [reported once]")
            self._reported_events[key] = 1
        else:
            self._reported_events[key] += 1

    def exception(self, key: str, msg: str):
        """
        Logs an exception message if it's a new event, and increments occurrence
        number if it's a known issue.
        """
        if self._should_report_event(key):
            self._log.exception(msg + " [reported once]")
            self._reported_events[key] = 1
        else:
            self._reported_events[key] += 1

    def reset_one(self, key) -> None:
        """
        Resets event tracking for a particular event
        """
        if self._reported_events.get(key):
            self._reported_events[key] = 0

    def reset_set(self, keys: list[str]) -> None:
        """
        Resets event tracking for a set of events
        """
        map(self.reset_one, keys)

    def reset_all(self) -> None:
        """
        Resets event tracking for the whole module
        """
        self._reported_events = {}

    def _should_report_event(self, key: str) -> None:
        """
        Checks if an event should be reported, based on its number of occurence
        """
        return self._reported_events.get(key, 0) == 0
