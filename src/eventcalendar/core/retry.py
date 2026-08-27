"""Typed retry policy for Gemini and transport failures."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Optional

from eventcalendar.config.constants import (
    API_KEY_ERROR_PATTERNS,
    NON_RETRYABLE_ERROR_PATTERNS,
    RETRYABLE_ERROR_PATTERNS,
)
from eventcalendar.exceptions.errors import CalendarAPIError

logger = logging.getLogger(__name__)


class RetryCategory(str, Enum):
    """Stable failure categories used by retry and user-error boundaries."""

    APPLICATION = "application"
    CREDENTIALS = "credentials"
    PERMISSION = "permission"
    QUOTA = "quota"
    INVALID_REQUEST = "invalid_request"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    SERVER = "server"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RetryDecision:
    """A retry verdict with a machine-readable category and audit reason."""

    retryable: bool
    category: RetryCategory
    reason: str
    retry_after_seconds: Optional[float] = None


_RETRYABLE_API_STATUSES = {
    "ABORTED",
    "DEADLINE_EXCEEDED",
    "INTERNAL",
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
}
_CREDENTIAL_STATUSES = {"UNAUTHENTICATED"}
_PERMISSION_STATUSES = {"PERMISSION_DENIED"}
_DAILY_QUOTA_PATTERNS = (
    "per day",
    "daily quota",
    "daily limit",
    "requests_per_day",
    "requests per day",
)


def _retry_after_seconds(error: Exception) -> Optional[float]:
    """Read a server-provided retry delay without depending on one SDK shape."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        value = headers.get("retry-after") or headers.get("Retry-After")
        try:
            if value is not None:
                return max(0.0, float(value))
        except (TypeError, ValueError):
            pass

    # Google RetryInfo details commonly serialize as ``retryDelay: '1.5s'``.
    details = getattr(error, "details", None)
    match = re.search(r"retry[_ ]?delay[^0-9]*(\d+(?:\.\d+)?)s", str(details), re.I)
    return float(match.group(1)) if match else None


def _exception_chain(error: Exception) -> Iterator[Exception]:
    """Yield a cycle-safe cause/context chain, outermost first."""
    current: Optional[BaseException] = error
    seen: set[int] = set()
    while isinstance(current, Exception) and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _is_genai_api_error(error: Exception) -> bool:
    """Recognize SDK errors without loading the Google SDK on every app import."""
    if not type(error).__module__.startswith("google.genai"):
        return False
    try:
        from google.genai.errors import APIError as GenAIAPIError
    except ImportError:
        return False
    return isinstance(error, GenAIAPIError)


def _api_error_decision(error: Exception) -> Optional[RetryDecision]:
    code = getattr(error, "code", None)
    status = str(getattr(error, "status", "") or "").upper()
    reason = f"Gemini API {code or 'unknown'} {status or 'status'}"

    if code == 401 or status in _CREDENTIAL_STATUSES:
        return RetryDecision(False, RetryCategory.CREDENTIALS, reason)
    if code == 403 or status in _PERMISSION_STATUSES:
        return RetryDecision(False, RetryCategory.PERMISSION, reason)
    if code == 408 or status == "DEADLINE_EXCEEDED":
        return RetryDecision(True, RetryCategory.TIMEOUT, reason)
    if code == 429 or status == "RESOURCE_EXHAUSTED":
        error_text = f"{error} {getattr(error, 'details', '')}".lower()
        if any(pattern in error_text for pattern in _DAILY_QUOTA_PATTERNS):
            return RetryDecision(False, RetryCategory.QUOTA, f"{reason}; daily quota exhausted")
        return RetryDecision(
            True,
            RetryCategory.RATE_LIMIT,
            reason,
            _retry_after_seconds(error),
        )
    if isinstance(code, int) and 500 <= code < 600:
        return RetryDecision(True, RetryCategory.SERVER, reason)
    if status in _RETRYABLE_API_STATUSES:
        return RetryDecision(True, RetryCategory.SERVER, reason)
    if isinstance(code, int) and 400 <= code < 500:
        return RetryDecision(False, RetryCategory.INVALID_REQUEST, reason)
    return None


def _typed_decision(error: Exception) -> Optional[RetryDecision]:
    if isinstance(error, CalendarAPIError):
        return RetryDecision(
            False,
            RetryCategory.APPLICATION,
            f"application error {type(error).__name__}",
        )
    if _is_genai_api_error(error):
        return _api_error_decision(error)
    if isinstance(error, TimeoutError):
        return RetryDecision(True, RetryCategory.TIMEOUT, type(error).__name__)
    if isinstance(error, ConnectionError):
        return RetryDecision(True, RetryCategory.CONNECTION, type(error).__name__)
    module = type(error).__module__
    name = type(error).__name__.lower()
    if module.startswith(("httpx", "httpcore")):
        if "timeout" in name:
            return RetryDecision(True, RetryCategory.TIMEOUT, type(error).__name__)
        if "transport" in name or "connect" in name or "network" in name:
            return RetryDecision(True, RetryCategory.CONNECTION, type(error).__name__)
    return None


def _fallback_decision(errors: list[Exception]) -> RetryDecision:
    """Preserve the legacy message classifier for otherwise unknown errors."""
    searchable = [f"{type(error).__name__} {error}".lower() for error in errors]

    for text in searchable:
        if any(pattern in text for pattern in API_KEY_ERROR_PATTERNS):
            return RetryDecision(False, RetryCategory.CREDENTIALS, "legacy credential pattern")

    for text in searchable:
        for pattern in NON_RETRYABLE_ERROR_PATTERNS:
            if pattern not in text:
                continue
            category = RetryCategory.QUOTA if "quota" in pattern else RetryCategory.INVALID_REQUEST
            return RetryDecision(False, category, f"legacy non-retryable pattern: {pattern}")

    for text in searchable:
        for pattern in RETRYABLE_ERROR_PATTERNS:
            if pattern not in text:
                continue
            if "timeout" in pattern or "deadline" in pattern:
                category = RetryCategory.TIMEOUT
            elif "connection" in pattern or "network" in pattern:
                category = RetryCategory.CONNECTION
            elif "resource exhausted" in pattern:
                category = RetryCategory.RATE_LIMIT
            else:
                category = RetryCategory.SERVER
            return RetryDecision(True, category, f"legacy retryable pattern: {pattern}")

    logger.debug(
        "Unknown error type, failing fast: %s - %s",
        type(errors[0]).__name__,
        errors[0],
    )
    return RetryDecision(False, RetryCategory.UNKNOWN, "unclassified error; fail-fast")


def classify_retry(error: Exception) -> RetryDecision:
    """Classify an error using stable types/statuses, then legacy text fallback."""
    errors = list(_exception_chain(error))

    # Preserve the old invariant that application-owned errors never retry,
    # even when they wrap a lower-level transient cause.
    application_error = next(
        (item for item in errors if isinstance(item, CalendarAPIError)),
        None,
    )
    if application_error is not None:
        return RetryDecision(
            False,
            RetryCategory.APPLICATION,
            f"application error {type(application_error).__name__}",
        )

    typed = [decision for item in errors if (decision := _typed_decision(item)) is not None]
    permanent = next((decision for decision in typed if not decision.retryable), None)
    if permanent is not None:
        return permanent
    if typed:
        return typed[0]
    return _fallback_decision(errors)


def is_retryable_error(error: Exception) -> bool:
    """Backward-compatible boolean retry predicate."""
    return classify_retry(error).retryable


def is_api_key_error(error: Exception) -> bool:
    """Backward-compatible credential-error predicate."""
    return classify_retry(error).category == RetryCategory.CREDENTIALS


def wrap_api_key_error(error: Exception, masked_key: str) -> CalendarAPIError:
    """Wrap credential failures with a user-friendly message."""
    error_text = " ".join(str(item).lower() for item in _exception_chain(error))
    if "expired" in error_text:
        msg = "API key has expired. Please renew your Gemini API key."
    else:
        msg = "API key is invalid. Please check your Gemini API key."

    logger.error("API key error (%s): %s", masked_key, error)
    return CalendarAPIError(msg)
