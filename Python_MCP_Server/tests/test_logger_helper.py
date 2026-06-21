import logging
from src.logger_helper import get_logger

def test_get_logger_creates_logger(tmp_path):
    log_file = tmp_path / "test.log"
    logger = get_logger(log_file=str(log_file), log_name="test_logger")
    assert isinstance(logger, logging.Logger)
    logger.info("Test message")
    # File should exist after logging
    assert log_file.exists()
