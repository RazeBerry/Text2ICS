"""Custom exceptions for the EventCalendarGenerator application."""


class CalendarAPIError(Exception):
    """Base exception for API-related errors."""
    pass


class TimezoneResolutionError(CalendarAPIError):
    """Failed to resolve timezone - using fallback."""

    def __init__(self, tz_name: str, fallback: str = "UTC"):
        self.tz_name = tz_name
        self.fallback = fallback
        super().__init__(
            f"Failed to resolve timezone '{tz_name}', using {fallback}"
        )


class EventValidationError(CalendarAPIError):
    """Event data failed validation - missing required fields."""

    def __init__(self, missing_fields: set, event_title: str = "Unknown"):
        self.missing_fields = missing_fields
        self.event_title = event_title
        super().__init__(
            f"Event '{event_title}' is missing required fields: {missing_fields}"
        )


class ImageProcessingError(CalendarAPIError):
    """Failed to process image for upload."""

    def __init__(self, file_path: str, reason: str):
        self.file_path = file_path
        self.reason = reason
        super().__init__(f"Failed to process image '{file_path}': {reason}")


class APIResponseError(CalendarAPIError):
    """API returned an unexpected or invalid response."""

    def __init__(self, message: str, raw_response: str = None):
        self.raw_response = raw_response
        super().__init__(message)


class RetryExhaustedError(CalendarAPIError):
    """All retry attempts have been exhausted."""

    def __init__(self, attempts: int, last_error: Exception = None):
        self.attempts = attempts
        self.last_error = last_error
        message = f"Failed after {attempts} attempts"
        if last_error:
            message += f": {last_error}"
        super().__init__(message)
