"""Date and time parsing utilities."""

import re
from typing import Optional
from datetime import datetime, timedelta

from dateutil import parser as dateutil_parser

# Regex pattern for extracting time
TIME_PATTERN = re.compile(
    r'\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)?)\b'
)

# Regex pattern for extracting date
DATE_PATTERN = re.compile(
    r'\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b',
    re.IGNORECASE
)

# Common relative date terms
RELATIVE_DATE_TERMS = [
    "today", "tomorrow", "yesterday",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "next week", "this week", "next month",
]

# Day of week mapping
DAYS_OF_WEEK = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6
}

# Month abbreviations
MONTH_ABBREVIATIONS = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec"
]


def parse_relative_date(text: str, reference_date: Optional[datetime] = None) -> Optional[datetime]:
    """Parse a relative date term into an absolute date.

    Args:
        text: Text containing a relative date term.
        reference_date: Reference date for relative calculations (default: now).

    Returns:
        Parsed datetime or None if not recognized.
    """
    text_lower = text.lower().strip()
    ref = reference_date or datetime.now()

    if text_lower == "today":
        return ref.replace(hour=0, minute=0, second=0, microsecond=0)

    if text_lower == "tomorrow":
        return (ref + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    if text_lower == "yesterday":
        return (ref - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Handle day of week
    for day_name, day_num in DAYS_OF_WEEK.items():
        if day_name in text_lower:
            current_day = ref.weekday()
            days_ahead = day_num - current_day
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            if "next" in text_lower:
                days_ahead += 7
            return (ref + timedelta(days=days_ahead)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

    return None


def extract_time_from_text(text: str) -> Optional[str]:
    """Extract time string from natural language text.

    Args:
        text: Text potentially containing a time.

    Returns:
        Extracted time string or None.
    """
    match = TIME_PATTERN.search(text)
    if match:
        return match.group(1)
    return None


def extract_date_from_text(text: str) -> Optional[str]:
    """Extract date string from natural language text.

    Args:
        text: Text potentially containing a date.

    Returns:
        Extracted date string or None.
    """
    # Check for relative dates first
    text_lower = text.lower()
    for term in RELATIVE_DATE_TERMS:
        if term in text_lower:
            return term

    # Check for explicit dates
    match = DATE_PATTERN.search(text)
    if match:
        return match.group(1)

    return None


def format_date_for_display(
    date_str: str,
    reference_date: Optional[datetime] = None
) -> Optional[str]:
    """Format a date string for display in the preview.

    Args:
        date_str: Date string to format.
        reference_date: Reference date for relative calculations.

    Returns:
        Formatted date string (e.g., "Jan 15") or None.
    """
    ref = reference_date or datetime.now()

    # Handle relative dates
    parsed = parse_relative_date(date_str, ref)
    if parsed:
        return parsed.strftime("%b %d")

    # Try to parse with dateutil
    try:
        parsed = dateutil_parser.parse(date_str, fuzzy=True)
        return parsed.strftime("%b %d")
    except (ValueError, TypeError):
        return None
