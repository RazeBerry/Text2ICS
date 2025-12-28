"""Retry logic and error classification for API calls."""

import logging
from typing import Optional

from eventcalendar.config.constants import (
    NON_RETRYABLE_ERROR_PATTERNS,
    RETRYABLE_ERROR_PATTERNS,
    API_KEY_ERROR_PATTERNS,
)
from eventcalendar.exceptions.errors import CalendarAPIError

logger = logging.getLogger(__name__)


def is_retryable_error(error: Exception) -> bool:
    """Determine if an error should be retried based on error type and message.

    Checks both the current error and its __cause__ chain to handle wrapped exceptions.

    Args:
        error: The exception to check.

    Returns:
        True if the error is retryable (transient), False if permanent.
    """
    # CalendarAPIError is always non-retryable (it's used to wrap permanent failures)
    if isinstance(error, CalendarAPIError):
        return False

    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    # Check for non-retryable patterns first (explicit deny)
    for pattern in NON_RETRYABLE_ERROR_PATTERNS:
        if pattern in error_str or pattern in error_type:
            return False

    # Also check the exception chain (__cause__) for wrapped errors
    if error.__cause__:
        cause_str = str(error.__cause__).lower()
        cause_type = type(error.__cause__).__name__.lower()
        for pattern in NON_RETRYABLE_ERROR_PATTERNS:
            if pattern in cause_str or pattern in cause_type:
                return False

    # Check for retryable patterns (explicit allow)
    for pattern in RETRYABLE_ERROR_PATTERNS:
        if pattern in error_str or pattern in error_type:
            return True

    # Default: retry for unknown errors (safer for transient issues)
    logger.debug(
        "Unknown error type, defaulting to retry: %s - %s",
        type(error).__name__,
        error
    )
    return True


def is_api_key_error(error: Exception) -> bool:
    """Check if error is related to API key issues.

    Args:
        error: The exception to check.

    Returns:
        True if the error is an API key error.
    """
    error_str = str(error).lower()
    for pattern in API_KEY_ERROR_PATTERNS:
        if pattern in error_str:
            return True
    return False


def wrap_api_key_error(error: Exception, masked_key: str) -> CalendarAPIError:
    """Wrap API key errors with user-friendly message.

    Args:
        error: The original exception.
        masked_key: The masked API key for logging.

    Returns:
        A CalendarAPIError with a user-friendly message.
    """
    error_str = str(error).lower()

    if "expired" in error_str:
        msg = "API key has expired. Please renew your Gemini API key."
    else:
        msg = "API key is invalid. Please check your Gemini API key."

    logger.error("API key error (%s): %s", masked_key, error)
    return CalendarAPIError(msg)


# Backward compatibility alias
_is_retryable_error = is_retryable_error
