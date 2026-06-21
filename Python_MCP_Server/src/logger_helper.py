"""Helper module for logging."""

import logging
from logging.handlers import RotatingFileHandler
import sys

# A pretty default logging format
DEFAULT_FORMAT = "%(asctime)s|%(levelname)s|%(name)s|%(funcName)s|%(message)s"


def get_logger(log_file="out.log", log_level=logging.INFO, console_level=logging.INFO, log_format=DEFAULT_FORMAT, log_name=None):
    """
    Create a new root logger and sets its formatting and handlers.

    Parameters:
    log_file (str): full path to file logger will write to
    log_level (int): file logging level. defaults to logging.INFO
    console_level (int): console logging level. defaults to logging.INFO
    log_format (str): log message format. defaults to "%(asctime)s|%(levelname)-5s|%(name)s|%(funcName)s|%(message)s"

    Returns: New root logger

    """
    # Set up new root logger
    new_logger = logging.getLogger(log_name)
    new_logger.setLevel(log_level)

    # Set the time format
    log_format = logging.Formatter(log_format, "%Y-%m-%d %H:%M:%S")

    # Set up file handler
    file_handler = RotatingFileHandler(log_file, maxBytes=1000 * 1000)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(log_format)
    new_logger.addHandler(file_handler)

    # Set up stream handler
    #stream_handler = logging.StreamHandler(sys.stdout)
    # stream_handler = logging.StreamHandler(sys.stderr)
    # stream_handler.setLevel(console_level)
    # stream_handler.setFormatter(log_format)
    # new_logger.addHandler(stream_handler)

    return new_logger