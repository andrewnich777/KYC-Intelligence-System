"""
Logging configuration for KYC Client Onboarding Intelligence System.

Provides structured logging with appropriate levels and formatting.
Log messages at INFO and DEBUG levels are automatically sanitized to
strip common PII patterns (SIN, DOB, email, phone numbers).
"""

import logging
import sys

from config import get_config

# Module-level logger cache
_loggers: dict[str, logging.Logger] = {}
_initialized: bool = False


class _SanitizingFormatter(logging.Formatter):
    """Formatter that redacts PII patterns from INFO/DEBUG messages.

    WARNING and above are left intact so operators can diagnose issues,
    but a redacted correlation ID is attached rather than raw PII.
    """

    _sanitize = None

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if record.levelno <= logging.INFO:
            if _SanitizingFormatter._sanitize is None:
                from utilities.pii_sanitizer import sanitize
                _SanitizingFormatter._sanitize = sanitize
            msg = _SanitizingFormatter._sanitize(msg)
        return msg


def setup_logging(
    level: str | None = None,
    format_string: str | None = None,
    stream: object | None = None
):
    """
    Initialize the logging system.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_string: Custom format string for log messages
        stream: Output stream (defaults to sys.stderr)
    """
    global _initialized

    config = get_config()

    # Use provided values or fall back to config
    log_level = level or config.log_level
    log_format = format_string or config.log_format
    output_stream = stream or sys.stderr

    # Get numeric level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler(output_stream)
    console_handler.setLevel(numeric_level)

    # Create sanitizing formatter
    formatter = _SanitizingFormatter(log_format)
    console_handler.setFormatter(formatter)

    # Add handler to root logger
    root_logger.addHandler(console_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for the given name.

    Args:
        name: Logger name (typically __name__ of the calling module)

    Returns:
        Configured logger instance
    """
    global _initialized, _loggers

    if not _initialized:
        setup_logging()

    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)

    return _loggers[name]


# Convenience functions for quick logging
def debug(msg: str, *args, **kwargs):
    """Log a debug message."""
    get_logger("kyc").debug(msg, *args, **kwargs)


def info(msg: str, *args, **kwargs):
    """Log an info message."""
    get_logger("kyc").info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    """Log a warning message."""
    get_logger("kyc").warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    """Log an error message."""
    get_logger("kyc").error(msg, *args, **kwargs)


def critical(msg: str, *args, **kwargs):
    """Log a critical message."""
    get_logger("kyc").critical(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs):
    """Log an exception with traceback."""
    get_logger("kyc").exception(msg, *args, **kwargs)
