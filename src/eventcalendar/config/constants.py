"""Centralized constants for EventCalendarGenerator.

This module consolidates all hardcoded constants that were previously
scattered across Calender.py and api_client.py.
"""

# Key storage constants
KEYRING_SERVICE_NAME = "EventCalendarGenerator"
KEYRING_ACCOUNT_NAME = "gemini_api_key"

# Environment variable names (prefer free tier if provided)
PREFERRED_ENV_VAR = "GEMINI_API_KEY_FREE"
PRIMARY_ENV_VAR = "GEMINI_API_KEY"

# Supported image formats.  Extensions are only a file-picker hint; image
# contents are verified with Pillow before they enter the application.
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
SUPPORTED_PIL_FORMATS = {"PNG", "JPEG", "GIF", "WEBP", "BMP"}
IMAGE_FORMAT_MIME_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
}
MAX_IMAGE_ATTACHMENTS = 8
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000

# ICS calendar constants
ICS_PRODID = "-//NL Calendar Creator//EN"
ICS_VERSION = "2.0"
ICS_CALSCALE = "GREGORIAN"
DEFAULT_REMINDER_MINUTES = -30  # 30 minutes before event

# Status callback messages
STATUS_ATTEMPTING = "Extracting event details... (attempt {attempt} of {max_retries})"
STATUS_SUCCESS = "Successfully extracted {count} event(s)."
STATUS_MAX_RETRIES = "Error: Max retries reached. Failed to create event."

# Error classification patterns for smart retry logic
# These errors should NOT be retried (permanent failures)
NON_RETRYABLE_ERROR_PATTERNS = [
    "invalid api key",
    "api_key_invalid",
    "api key expired",
    "permission denied",
    "quota exceeded",
    "invalid argument",
    "authentication",
    "unauthorized",
]

# These errors SHOULD be retried (transient failures)
RETRYABLE_ERROR_PATTERNS = [
    "timeout",
    "deadline exceeded",
    "service unavailable",
    "resource exhausted",
    "connection",
    "network",
    "temporarily unavailable",
]

# API key error patterns for centralized detection
API_KEY_ERROR_PATTERNS = [
    "api key expired",
    "api_key_invalid",
    "invalid api key",
]

# Generic region abbreviations intentionally map to DST-aware IANA zones.
# Explicit standard/daylight abbreviations are fixed offsets below: "EST" means
# UTC-05:00 even in July, while "ET" follows New York's seasonal rules.
ABBR_TO_TZ = {
    "ET": "America/New_York",
    "CT": "America/Chicago",
    "MT": "America/Denver",
    "PT": "America/Los_Angeles",
}

# Unambiguous explicit abbreviations preserve the offset the user wrote.
FIXED_TZ_ABBREVIATIONS = {
    "EST": -5 * 3600,
    "EDT": -4 * 3600,
    "CDT": -5 * 3600,
    "MST": -7 * 3600,
    "MDT": -6 * 3600,
    "PST": -8 * 3600,
    "PDT": -7 * 3600,
    "GMT": 0,
    "CET": 1 * 3600,
    "CEST": 2 * 3600,
    "EET": 2 * 3600,
    "EEST": 3 * 3600,
    "AEST": 10 * 3600,
    "AEDT": 11 * 3600,
}

# These tokens have several common meanings worldwide.  Silently selecting one
# creates events at the wrong instant, so callers must request an IANA zone or
# numeric UTC offset instead.
AMBIGUOUS_TZ_ABBREVIATIONS = {"CST", "BST", "IST"}

# Date/time parsing patterns
DATE_INDICATORS = [
    "today", "tomorrow", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "next", "this",
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]

TIME_INDICATORS = ["am", "pm", ":", "noon", "midnight", "morning", "afternoon", "evening"]

EVENT_INDICATORS = ["meeting", "appointment", "dinner", "lunch", "call", "event"]
