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

# Supported image file extensions
SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# ICS calendar constants
ICS_PRODID = "-//NL Calendar Creator//EN"
ICS_VERSION = "2.0"
ICS_CALSCALE = "GREGORIAN"
DEFAULT_REMINDER_MINUTES = -30  # 30 minutes before event

# Default event title when none provided
DEFAULT_EVENT_TITLE = "No Title"

# Status callback messages
STATUS_ATTEMPTING = "Attempting to get event details... (Try {attempt}/{max_retries})"
STATUS_SUCCESS = "Successfully extracted {count} event(s)."
STATUS_ERROR_EXPIRED = "Error: Your API key has expired. Please renew it."
STATUS_ERROR_INVALID = "Error: Your API key is invalid."
STATUS_ERROR_NON_RETRYABLE = "Error: {error_type} - this error cannot be retried."
STATUS_RETRYING = "Error occurred ({error_type}), retrying in {delay:.0f} seconds..."
STATUS_MAX_RETRIES = "Error: Max retries reached. Failed to create event."
STATUS_FAILED = "Error: Failed to create event after retries."

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

# Timezone abbreviation to IANA zone mapping
# Maps common (and DST) abbreviations to canonical IANA zones that understand DST
ABBR_TO_TZ = {
    # North America
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    # United Kingdom / Europe
    "GMT": "Europe/London",
    "BST": "Europe/London",
    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",
    "EET": "Europe/Athens",
    "EEST": "Europe/Athens",
    # Australia
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    # Asia
    "IST": "Asia/Kolkata",  # India (UTC+5:30 – no DST)
}

# Date/time parsing patterns
DATE_INDICATORS = [
    "today", "tomorrow", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "next", "this",
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]

TIME_INDICATORS = ["am", "pm", ":", "noon", "midnight", "morning", "afternoon", "evening"]

EVENT_INDICATORS = ["meeting", "appointment", "dinner", "lunch", "call", "event"]
