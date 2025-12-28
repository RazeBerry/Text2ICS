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
    "friday": 4, "saturday": 5, "sunday": 6
}


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
        "title": None,
        "date": None,
        "time": None,
        "location": None,
    }

    # Extract time
    time_match = re.search(
        r'\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b',
        text_lower
    )
    if time_match:
        result["time"] = time_match.group(1)

    # Extract date
    result["date"] = _extract_date(text_lower, ref)

    # Extract title (remaining significant words)
    result["title"] = _extract_title(text)

    # Extract location (after "at" that's not a time)
    location_match = re.search(r'\bat\s+([A-Z][A-Za-z\s]+?)(?:\s+(?:on|at|next|this|tomorrow|today)|\s*$)', text)
    if location_match:
        result["location"] = location_match.group(1).strip()

    return result


def _extract_date(text_lower: str, ref: datetime) -> Optional[str]:
    """Extract date from text.

    Args:
        text_lower: Lowercase event text.
        ref: Reference date for relative calculations.

    Returns:
        Formatted date string or None.
    """
    # Check for relative dates
    if "today" in text_lower:
        return ref.strftime("%b %d")

    if "tomorrow" in text_lower:
        return (ref + timedelta(days=1)).strftime("%b %d")

    # Check for day of week
    for day_name, day_num in DAYS_OF_WEEK.items():
        if day_name in text_lower:
            current_day = ref.weekday()
            days_ahead = day_num - current_day
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in text_lower:
                days_ahead += 7
            target_date = ref + timedelta(days=days_ahead)
            return target_date.strftime("%b %d")

    # Try to parse explicit dates
    date_patterns = [
        r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}',
        r'\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?',
    ]

    for pattern in date_patterns:
        match = re.search(pattern, text_lower)
        if match:
            try:
                parsed = dateutil_parser.parse(match.group(), fuzzy=True)
                return parsed.strftime("%b %d")
            except (ValueError, TypeError):
                continue

    return None


def _extract_title(text: str) -> str:
    """Extract title from event text.

    Args:
        text: The event description.

    Returns:
        Extracted title string.
    """
    # Remove time patterns
    cleaned = re.sub(r'\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b', '', text, flags=re.IGNORECASE)

    # Remove date patterns
    cleaned = re.sub(
        r'\b(?:next|this)?\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
        '', cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r'\b(?:today|tomorrow)\b', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?\b',
        '', cleaned, flags=re.IGNORECASE
    )

    # Get significant words
    words = cleaned.split()
    significant = [w for w in words if w.lower() not in FILLER_WORDS and len(w) > 1]

    if significant:
        return ' '.join(significant[:4])  # Limit title length
    return text.strip()


def format_date_display(date_str: str, reference_date: Optional[datetime] = None) -> Optional[str]:
    """Format a date string for display.

    Args:
        date_str: Date string to format.
        reference_date: Reference date for relative dates.

    Returns:
        Formatted date string or None.
    """
    ref = reference_date or datetime.now()
    date_lower = date_str.lower().strip()

    # Handle relative dates
    if date_lower == "today":
        return ref.strftime("%b %d")

    if date_lower == "tomorrow":
        return (ref + timedelta(days=1)).strftime("%b %d")

    # Handle day of week
    for day_name, day_num in DAYS_OF_WEEK.items():
        if day_name in date_lower:
            current_day = ref.weekday()
            days_ahead = day_num - current_day
            if days_ahead <= 0:
                days_ahead += 7
            if "next" in date_lower:
                days_ahead += 7
            target_date = ref + timedelta(days=days_ahead)
            return target_date.strftime("%b %d")

    # Try to parse as date
    try:
        parsed = dateutil_parser.parse(date_str, fuzzy=True)
        return parsed.strftime("%b %d")
    except (ValueError, TypeError):
        return None
