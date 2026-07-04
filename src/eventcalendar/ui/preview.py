"""Live preview parsing for event text input."""

import re
from datetime import datetime, timedelta
from typing import Dict, Optional

from dateutil import parser as dateutil_parser


# Common words to filter from titles
# Note: "at" is intentionally excluded as it may be part of meaningful title phrases
FILLER_WORDS = {
    "with", "on", "in", "the", "a", "an", "for", "to", "from",
    "next", "this", "today", "tomorrow", "meeting", "appointment",
}

# Day of week mapping
DAYS_OF_WEEK = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_MONTH_TO_NUM = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
_MONTH_ABBR = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_TIME_RE = re.compile(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b")
_LOCATION_RE = re.compile(
    r"\bat\s+([A-Z][A-Za-z\s]+?)(?:\s+(?:on|at|next|this|tomorrow|today)|\s*$)"
)
_MONTH_DAY_RE = re.compile(
    r"\b(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?"
    r"(?:\s*,?\s*(?P<year>\d{4}))?\b"
)
_NUMERIC_DATE_RE = re.compile(r"\b(?P<month>\d{1,2})[/-](?P<day>\d{1,2})(?:[/-](?P<year>\d{2,4}))?\b")

_TITLE_TIME_RE = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", re.IGNORECASE)
_TITLE_DOW_RE = re.compile(
    r"\b(?:next|this)?\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_TITLE_RELATIVE_RE = re.compile(r"\b(?:today|tomorrow)\b", re.IGNORECASE)
_TITLE_MONTH_DAY_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def parse_event_text(text: str, reference_date: Optional[datetime] = None) -> Dict[str, Optional[str]]:
    """Parse natural language event text to extract components.

    Args:
        text: The event description text.
        reference_date: Reference date for relative dates (default: now).

    Returns:
        Dictionary with 'title', 'date', 'time', 'location' keys.
    """
    ref = reference_date or datetime.now()
    text_lower = text.lower()

    result = {
        "title": _extract_title(text),
        "date": _extract_date(text_lower, ref),
        "time": None,
        "location": None,
    }

    time_match = _TIME_RE.search(text_lower)
    if time_match:
        result["time"] = time_match.group(1)

    location_match = _LOCATION_RE.search(text)
    if location_match:
        result["location"] = location_match.group(1).strip()

    return result


def _format_month_day(value: datetime) -> str:
    return f"{_MONTH_ABBR[value.month]} {value.day:02d}"


def _normalize_year(year_str: Optional[str], reference_year: int) -> int:
    if not year_str:
        return reference_year
    year = int(year_str)
    if year < 100:
        return 2000 + year if year <= 68 else 1900 + year
    return year


def _match_month_day(match: re.Match, reference_date: datetime) -> Optional[datetime]:
    month_token = match.group("month").lower()
    month = _MONTH_TO_NUM.get(month_token)
    if month is None:
        return None

    day = int(match.group("day"))
    year = _normalize_year(match.group("year"), reference_date.year)
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _match_numeric_date(match: re.Match, reference_date: datetime) -> Optional[datetime]:
    month = int(match.group("month"))
    day = int(match.group("day"))
    year = _normalize_year(match.group("year"), reference_date.year)
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _extract_explicit_date(text_lower: str, ref: datetime) -> Optional[str]:
    month_match = _MONTH_DAY_RE.search(text_lower)
    if month_match:
        parsed = _match_month_day(month_match, ref)
        if parsed:
            return _format_month_day(parsed)
        try:
            parsed = dateutil_parser.parse(month_match.group(0), fuzzy=True)
            return _format_month_day(parsed)
        except (ValueError, TypeError):
            pass

    numeric_match = _NUMERIC_DATE_RE.search(text_lower)
    if numeric_match:
        parsed = _match_numeric_date(numeric_match, ref)
        if parsed:
            return _format_month_day(parsed)
        try:
            parsed = dateutil_parser.parse(numeric_match.group(0), fuzzy=True)
            return _format_month_day(parsed)
        except (ValueError, TypeError):
            pass

    return None


def _extract_date(text_lower: str, ref: datetime) -> Optional[str]:
    """Extract date from text.

    Args:
        text_lower: Lowercase event text.
        ref: Reference date for relative calculations.

    Returns:
        Formatted date string or None.
    """
    if "today" in text_lower:
        return _format_month_day(ref)

    if "tomorrow" in text_lower:
        return _format_month_day(ref + timedelta(days=1))

    for day_name, day_num in DAYS_OF_WEEK.items():
        if day_name in text_lower:
            current_day = ref.weekday()
            days_ahead = day_num - current_day
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in text_lower:
                days_ahead += 7
            return _format_month_day(ref + timedelta(days=days_ahead))

    return _extract_explicit_date(text_lower, ref)


def _extract_title(text: str) -> str:
    """Extract title from event text.

    Args:
        text: The event description.

    Returns:
        Extracted title string.
    """
    cleaned = _TITLE_TIME_RE.sub("", text)
    cleaned = _TITLE_DOW_RE.sub("", cleaned)
    cleaned = _TITLE_RELATIVE_RE.sub("", cleaned)
    cleaned = _TITLE_MONTH_DAY_RE.sub("", cleaned)

    significant = [w for w in cleaned.split() if w.lower() not in FILLER_WORDS and len(w) > 1]
    if significant:
        return " ".join(significant[:4])  # Limit title length
    return text.strip()


def format_date_display(date_str: str, reference_date: Optional[datetime] = None) -> Optional[str]:
    """Format a date string for display.

    Args:
        date_str: Date string to format.
        reference_date: Reference date for relative dates.

    Returns:
        Formatted date string or None.
    """
    if not date_str:
        return None

    ref = reference_date or datetime.now()
    date_lower = date_str.lower().strip()

    if date_lower == "today":
        return _format_month_day(ref)

    if date_lower == "tomorrow":
        return _format_month_day(ref + timedelta(days=1))

    for day_name, day_num in DAYS_OF_WEEK.items():
        if day_name in date_lower:
            current_day = ref.weekday()
            days_ahead = day_num - current_day
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in date_lower:
                days_ahead += 7
            return _format_month_day(ref + timedelta(days=days_ahead))

    explicit = _extract_explicit_date(date_lower, ref)
    if explicit:
        return explicit

    try:
        parsed = dateutil_parser.parse(date_str, fuzzy=True)
        return _format_month_day(parsed)
    except (ValueError, TypeError):
        return None
