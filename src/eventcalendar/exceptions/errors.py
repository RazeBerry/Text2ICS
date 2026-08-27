"""Custom exceptions for the EventCalendarGenerator application."""


class CalendarAPIError(Exception):
    """Base exception for API-related errors."""
    pass


class TimezoneResolutionError(CalendarAPIError):
    """A timezone could not be resolved without guessing."""

    def __init__(self, tz_name: str, reason: str = "unknown timezone"):
        self.tz_name = tz_name
        self.reason = reason
        super().__init__(f"Cannot resolve timezone '{tz_name}': {reason}")


class EventValidationError(CalendarAPIError):
    """Event data failed validation."""

    def __init__(
        self,
        missing_fields: set | None = None,
        event_title: str = "Unknown",
        reason: str | None = None,
    ):
        self.missing_fields = missing_fields or set()
        self.event_title = event_title
        if reason is None:
            reason = f"missing required fields: {self.missing_fields}"
        self.reason = reason
        super().__init__(f"Event '{event_title}' is invalid: {reason}")


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


class RequestDeadlineExceeded(CalendarAPIError):
    """The submission exhausted its end-to-end latency budget."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        super().__init__(
            f"Request timed out after {seconds:.0f} seconds. "
            "Try fewer attachments or check your connection."
        )
