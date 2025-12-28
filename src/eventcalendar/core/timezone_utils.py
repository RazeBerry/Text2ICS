"""Timezone resolution and time normalization utilities."""

import logging
import re
from datetime import datetime
from typing import Optional, Tuple

import pytz
import tzlocal
from dateutil import tz as du_tz

from eventcalendar.config.constants import ABBR_TO_TZ

logger = logging.getLogger(__name__)


def normalize_time_string(time_str: str) -> str:
    """Handle common human formats like '20:00h' or '20h15' before parsing.

    Args:
        time_str: The time string to normalize.

    Returns:
        A normalized time string that dateutil can parse.
    """
    if not isinstance(time_str, str):
        return str(time_str)

    s = time_str.strip()

    # Convert European "20.00" to "20:00" for dateutil
    if re.match(r"^\d{1,2}\.\d{2}$", s):
        s = s.replace(".", ":")

    # Handle "20:00h", "20h", "20h15", "20h15m" styles
    match = re.match(r"^\s*(\d{1,2})(?:[:\.]?(\d{2}))?\s*h(?:rs?)?\.?\s*$", s, re.IGNORECASE)
    if match:
        hour = int(match.group(1))
        minute = match.group(2) or "00"
        return f"{hour:02d}:{minute}"

    match = re.match(r"^\s*(\d{1,2})h(\d{2})\s*$", s, re.IGNORECASE)
    if match:
        hour = int(match.group(1))
        minute = match.group(2)
        return f"{hour:02d}:{minute}"

    # Fallback: return cleaned string
    return s


def resolve_timezone(tz_str: str, event_title: Optional[str] = None) -> Tuple[object, Optional[str]]:
    """Resolve a timezone string to a timezone object.

    Args:
        tz_str: The timezone string (e.g., "EST", "America/New_York", "local").
        event_title: Optional event title for warning messages.

    Returns:
        Tuple of (timezone_object, warning_message or None).
    """
    tz_str_raw = tz_str or "local"
    tz_upper = tz_str_raw.upper()
    warning = None

    if tz_upper == "LOCAL":
        # User's system zone (DST aware)
        local_tz_obj = tzlocal.get_localzone()
        tz_name = getattr(local_tz_obj, "zone", str(local_tz_obj))
    else:
        tz_name = ABBR_TO_TZ.get(tz_upper, tz_str_raw)

    try:
        local_tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        # Last-ditch attempt with dateutil (may return fixed offset)
        local_tz = du_tz.gettz(tz_name)
        if local_tz is None:
            local_tz = pytz.utc
            event_desc = f"'{event_title}'" if event_title else "event"
            warning = (
                f"Couldn't resolve timezone '{tz_str_raw}' for {event_desc} - "
                "using UTC. Please verify the time in your calendar."
            )
            logger.warning(warning)

    return local_tz, warning


def attach_timezone(tzobj, naive_dt: datetime) -> datetime:
    """Return timezone-aware datetime, using proper DST rules where possible.

    Args:
        tzobj: The timezone object (pytz or dateutil).
        naive_dt: A naive datetime to attach the timezone to.

    Returns:
        A timezone-aware datetime.
    """
    if hasattr(tzobj, "localize"):
        # pytz – honour DST rules automatically; let pytz raise on ambiguous times
        try:
            return tzobj.localize(naive_dt, is_dst=None)
        except Exception:
            # Fall back to is_dst=True on ambiguity (earlier) – still better than wrong offset
            return tzobj.localize(naive_dt, is_dst=True)
    else:
        # zoneinfo/dateutil – just set tzinfo; these implement DST via utcoffset()
        return naive_dt.replace(tzinfo=tzobj)


# Backward compatibility aliases
_normalize_time_string = normalize_time_string
_attach_tz = attach_timezone
