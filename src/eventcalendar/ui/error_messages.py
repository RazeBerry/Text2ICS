"""User-friendly error message handling."""

from eventcalendar.exceptions.errors import (
    CalendarAPIError,
    RetryExhaustedError,
    EventValidationError,
)


# Error message mappings for user-friendly display
ERROR_MAPPINGS = {
    "api key": "Your API key appears to be invalid or expired. Please check your settings.",
    "rate limit": "Too many requests. Please wait a moment and try again.",
    "network": "Network error. Please check your internet connection.",
    "timeout": "Request timed out. Please try again.",
    "quota": "API quota exceeded. Please try again later or check your API plan.",
    "invalid json": "The AI returned an unexpected response. Please try rephrasing your event description.",
    "empty response": "No response received from the AI. Please try again.",
}


def get_user_friendly_error(error: Exception) -> str:
    """Convert an exception to a user-friendly error message.

    Args:
        error: The exception to convert.

    Returns:
        A user-friendly error message string.
    """
    error_str = str(error).lower()

    # Check for specific error types first
    if isinstance(error, CalendarAPIError):
        if "api key" in error_str or "expired" in error_str or "invalid" in error_str:
            return ERROR_MAPPINGS["api key"]

    if isinstance(error, RetryExhaustedError):
        return (
            f"Failed after multiple attempts. "
            f"Last error: {get_user_friendly_error(error.last_error) if error.last_error else 'Unknown'}"
        )

    if isinstance(error, EventValidationError):
        return f"Event data is incomplete: missing {', '.join(error.missing_fields)}"

    # Check error message patterns
    for pattern, message in ERROR_MAPPINGS.items():
        if pattern in error_str:
            return message

    # Default message
    return f"An error occurred: {str(error)}"


def format_error_for_status(error: Exception) -> str:
    """Format an error for display in the status bar.

    Args:
        error: The exception to format.

    Returns:
        A short status message.
    """
    friendly = get_user_friendly_error(error)
    # Truncate for status bar
    if len(friendly) > 100:
        return friendly[:97] + "..."
    return friendly
